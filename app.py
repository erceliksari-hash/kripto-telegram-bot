import datetime
import threading
import time
import pandas as pd
import requests
import streamlit as st
import ccxt
import ta

# ==========================================
# 1. PAGE CONFIG
# ==========================================
st.set_page_config(
    page_title="Krypto Piyasası Taraması & Risk/Ödül Analiz Paneli",
    page_icon="📊",
    layout="wide",
)

# ==========================================
# 2. SECRETS'TEN TELEGRAM BİLGİLERİNİ OKU
# ==========================================
TELEGRAM_TOKEN = ""
TELEGRAM_CHAT_ID = ""

if "telegram" in st.secrets:
    TELEGRAM_TOKEN = st.secrets["telegram"].get("bot_token", "")
    TELEGRAM_CHAT_ID = st.secrets["telegram"].get("chat_id", "")
else:
    TELEGRAM_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", st.secrets.get("bot_token", ""))
    TELEGRAM_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", st.secrets.get("chat_id", ""))

# CCXT Binance Borsa Bağlantısı
exchange = ccxt.binance({'enableRateLimit': True})

# ==========================================
# 3. SIDEBAR (SOL PANEL) AYARLARI
# ==========================================
st.sidebar.title("⚙️ Panel ve Otomasyon Ayarları")

enable_auto_telegram = st.sidebar.checkbox("Otomatik Telegram Bildirimleri (Aktif)", value=True)

st.sidebar.markdown("---")

# --- MANUEL GENEL TARAMA LİSTESİ ---
st.sidebar.subheader("📝 Genel Taranacak Semboller")
default_symbols = "BTCUSDT, ETHUSDT, SOLUSDT, AVAXUSDT, NEARUSDT, LINKUSDT"
symbol_input = st.sidebar.text_area(
    "Semboller (Virgülle ayırın)",
    value=default_symbols,
    height=80,
)
custom_symbol_list = [s.strip().upper() for s in symbol_input.replace("\n", ",").split(",") if s.strip()]

st.sidebar.markdown("---")

# --- QUNTRY FRY ÖZEL TAKİP LİSTESİ ---
st.sidebar.subheader("🍟 Quntry Fry Özel Listesi")
quntry_default = "BEATUSDT, BICOUSDT, RECALLUSDT, ZDTUSDT"
quntry_input = st.sidebar.text_area(
    "Quntry Fry Coinleri (Virgülle ayırın)",
    value=quntry_default,
    height=80,
)
quntry_symbol_list = [s.strip().upper() for s in quntry_input.replace("\n", ",").split(",") if s.strip()]

quntry_timeframe = st.sidebar.selectbox("Zaman Dilimi", ["15m", "1h", "4h"], index=1)

st.sidebar.markdown("---")

# --- TEKNİK & HACİM FİLTRELERİ ---
st.sidebar.subheader("📌 Teknik Filtre Ayarları")
min_volume = st.sidebar.number_input("Minimum 24h Hacim (Milyon $)", value=10.00, step=1.00)
min_change = st.sidebar.number_input("Minimum Değişim (%)", value=1.00, step=0.50)
rsi_min, rsi_max = st.sidebar.slider("RSI (14) Aralığı", min_value=0, max_value=100, value=(35, 70))

# ==========================================
# 4. CANLI VERİ ÇEKME & TEKNİK ANALİZ
# ==========================================

def fetch_symbol_data(symbol, timeframe="1h"):
    """Binance API'den canlı mum verisi çeker ve çoklu indikatörleri hesaplar."""
    try:
        # USDT formatını düzenle
        formatted_symbol = symbol if "/" in symbol else symbol.replace("USDT", "/USDT")
        ohlcv = exchange.fetch_ohlcv(formatted_symbol, timeframe=timeframe, limit=100)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # İndikatör Hesaplamaları
        df['rsi'] = ta.momentum.rsi(df['close'], window=14)
        df['ema50'] = ta.trend.ema_indicator(df['close'], window=50)
        
        # MACD
        macd = ta.trend.MACD(df['close'])
        df['macd'] = macd.macd()
        df['macd_signal'] = macd.macd_signal()
        
        # ATR (Dinamik Stop/TP için)
        df['atr'] = ta.volatility.average_true_range(df['high'], df['low'], df['close'], window=14)
        
        # Hacim Ortalaması (Sahte Kırılım Tespiti İçin)
        df['vol_sma'] = df['volume'].rolling(window=20).mean()

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        price = float(latest['close'])
        change_pct = ((price - df.iloc[-24]['close']) / df.iloc[-24]['close']) * 100 if len(df) >= 24 else 0.0
        volume_m = (latest['volume'] * price) / 1_000_000

        # Dinamik Stop-Loss ve Take-Profit (ATR Bazlı)
        atr_val = latest['atr']
        stop_loss = round(price - (atr_val * 1.5), 4)
        tp1 = round(price + (atr_val * 2.0), 4)
        tp2 = round(price + (atr_val * 3.5), 4)

        # Sahte Yükseliş / Düşüş (Fakeout) & Sinyal Analizi
        is_volume_surge = latest['volume'] > (latest['vol_sma'] * 1.3)
        is_bullish_trend = price > latest['ema50']
        is_macd_cross = (prev['macd'] < prev['macd_signal']) and (latest['macd'] > latest['macd_signal'])

        # Karar Mekanizması (Al/Sat/Nötr)
        if is_bullish_trend and is_macd_cross and is_volume_surge and (latest['rsi'] < 68):
            signal = "GUCLU_AL"
            comment = "🟢 Güçlü Trend & Hacim Onaylı AL"
        elif is_bullish_trend and (latest['rsi'] < 60):
            signal = "AL"
            comment = "🟡 Trend Pozitif, Alım Düşünülebilir"
        elif (latest['rsi'] > 70) or (price < latest['ema50'] and not is_volume_surge):
            signal = "SAT"
            comment = "🔴 Sahte Kırılım / Aşırı Alım Riski (SAT/Uzak Dur)"
        else:
            signal = "NOTR"
            comment = "⚪ Yatay Piyasa / Beklemede Kal"

        return {
            "Sembol": symbol,
            "Giriş ($)": price,
            "24h Değişim (%)": round(change_pct, 2),
            "24h Hacim (M$)": round(volume_m, 2),
            "RSI (14)": round(latest['rsi'], 1),
            "Stop Loss": stop_loss,
            "Hedef 1 (TP1)": tp1,
            "Hedef 2 (TP2)": tp2,
            "Sinyal": signal,
            "Yorum": comment,
            "Güncelleme": datetime.datetime.now().strftime("%H:%M:%S")
        }
    except Exception as e:
        return None

def analyze_symbol_list(symbols, timeframe="1h"):
    """Verilen sembol listesini canlı olarak tarar ve DataFrame döndürür."""
    results = []
    for sym in symbols:
        data = fetch_symbol_data(sym, timeframe=timeframe)
        if data:
            results.append(data)
    return pd.DataFrame(results)

# ==========================================
# 5. TELEGRAM RAPORU OLUŞTURMA & GÖNDERME
# ==========================================

def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False, "Secrets içinde Telegram bilgileri eksik."

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
    }
    try:
        response = requests.post(url, json=payload, timeout=5)
        return (True, "Başarılı") if response.status_code == 200 else (False, response.text)
    except Exception as e:
        return False, str(e)

def build_telegram_report(df_genel, df_quntry):
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    msg = f"🤖 *UZMAN KRİPTO ANALİZ RAPORU*\n📅 `{now_str}`\n"
    msg += "-----------------------------------\n\n"

    # 1. GENEL PİYASA ANALİZİ BÖLÜMÜ
    msg += "📊 *GENEL PİYASA TARAMA SONUÇLARI*\n"
    if not df_genel.empty:
        for _, row in df_genel.iterrows():
            msg += f"🔹 *{row['Sembol']}* -> `{row['Sinyal']}`\n"
            msg += f"• Fiyat: `${row['Giriş ($)']}` (%{row['24h Değişim (%)']})\n"
            msg += f"• RSI: `{row['RSI (14)']}` | Hacim: `${row['24h Hacim (M$)']}M`\n"
            msg += f"• 🛑 Stop: `${row['Stop Loss']}` | 🎯 TP1: `${row['Hedef 1 (TP1)']}` | TP2: `${row['Hedef 2 (TP2)']}`\n"
            msg += f"💡 *Analiz:* {row['Yorum']}\n\n"
    else:
        msg += "⚠️ Genel listede filtrelere uyan uygun fırsat bulunamadı.\n\n"

    msg += "-----------------------------------\n\n"

    # 2. QUNTRY FRY ÖZEL BÖLÜMÜ
    msg += "🍟 *QUNTRY FRY ÖZEL ANALİZ LİSTESİ*\n"
    if not df_quntry.empty:
        for _, row in df_quntry.iterrows():
            msg += f"⭐ *{row['Sembol']}*\n"
            msg += f"• Giriş: `${row['Giriş ($)']}` | RSI: `{row['RSI (14)']}`\n"
            msg += f"• Stop: `${row['Stop Loss']}` | TP1: `${row['Hedef 1 (TP1)']}`\n"
            msg += f"💡 *Karar:* {row['Yorum']}\n\n"
    else:
        msg += "⚠️ Quntry Fry listesinden veri alınamadı.\n"

    return msg

# ==========================================
# 6. EKRAN GÖRÜNÜMÜ (STREAMLIT UI)
# ==========================================
st.title("📊 Krypto Piyasası Taraması & Risk/Ödül Analiz Paneli")

# Taramayı Gerçekleştir
df_all_genel = analyze_symbol_list(custom_symbol_list, timeframe="1h")
df_all_quntry = analyze_symbol_list(quntry_symbol_list, timeframe=quntry_timeframe)

# Genel Filtreleme
if not df_all_genel.empty:
    filtered_genel = df_all_genel[
        (df_all_genel["24h Hacim (M$)"] >= min_volume) &
        (df_all_genel["24h Değişim (%)"] >= min_change) &
        (df_all_genel["RSI (14)"] >= rsi_min) &
        (df_all_genel["RSI (14)"] <= rsi_max)
    ]
else:
    filtered_genel = pd.DataFrame()

col1, col2, col3 = st.columns(3)
col1.metric("Taranan Genel Semboller", len(custom_symbol_list))
col2.metric("Filtreye Uyan Fırsatlar", len(filtered_genel))
col3.metric("Quntry Fry Coin Sayısı", len(quntry_symbol_list))

st.markdown("### 🎯 Genel Piyasa Analiz Taraması")
if not filtered_genel.empty:
    st.dataframe(filtered_genel, use_container_width=True)
else:
    st.info("Genel filtre kriterlerine uyan coin bulunamadı.")

st.markdown("### 🍟 Quntry Fry Özel Takip & Analiz Listesi")
if not df_all_quntry.empty:
    st.dataframe(df_all_quntry, use_container_width=True)
else:
    st.info("Quntry Fry listesi yüklenemedi.")

# Manuel Gönderim Butonu
if st.button("📲 Analiz Raporunu Şimdi Telegram'a Gönder"):
    report_msg = build_telegram_report(filtered_genel, df_all_quntry)
    success, err_msg = send_telegram_message(report_msg)
    if success:
        st.success("✅ Piyasa ve Quntry Fry Analiz Raporu Telegram'a iletildi!")
    else:
        st.error(f"❌ Gönderim başarısız: {err_msg}")
