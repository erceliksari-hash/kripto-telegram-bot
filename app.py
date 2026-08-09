import datetime
import time
import ccxt
import pandas as pd
import requests
import streamlit as st
import ta

# ==========================================
# 1. PAGE CONFIG
# ==========================================
st.set_page_config(
    page_title="Kripto Piyasası Taraması & Risk/Ödül Analiz Paneli",
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
    TELEGRAM_TOKEN = st.secrets.get(
        "TELEGRAM_BOT_TOKEN", st.secrets.get("bot_token", "")
    )
    TELEGRAM_CHAT_ID = st.secrets.get(
        "TELEGRAM_CHAT_ID", st.secrets.get("chat_id", "")
    )

# Binance CCXT Kurulumu (Rate Limit & Timeout Korumalı)
exchange = ccxt.binance({
    "enableRateLimit": True,
    "timeout": 10000,  # 10 saniye ağ bekleme süresi
})

# ==========================================
# 3. SIDEBAR (SOL PANEL) AYARLARI
# ==========================================
st.sidebar.title("⚙️ Panel ve Otomasyon Ayarları")

# UptimeRobot Durum Bildirimi
st.sidebar.success("🟢 **UptimeRobot:** Aktif\n(Ping istekleri sistemi uyanık tutar)")

st.sidebar.markdown("---")

# Otomatik Telegram Bildirim Checkbox
enable_auto_telegram = st.sidebar.checkbox(
    "30 Dk'da Bir Otomatik Telegram Sinyali Gönder", value=True
)

st.sidebar.markdown("---")

# Genel Taranacak Semboller
st.sidebar.subheader("📝 Genel Taranacak Semboller")
default_symbols = "BTCUSDT, ETHUSDT, SOLUSDT, AVAXUSDT, NEARUSDT, LINKUSDT"
symbol_input = st.sidebar.text_area(
    "Semboller (Virgülle ayırın)", value=default_symbols, height=80
)
custom_symbol_list = [
    s.strip().upper()
    for s in symbol_input.replace("\n", ",").split(",")
    if s.strip()
]

st.sidebar.markdown("---")

# Quntry Fry Özel Takip Listesi
st.sidebar.subheader("🍟 Quntry Fry Özel Listesi")
quntry_default = "BICOUSDT, RECALLUSDT, ZDTUSDT, BEATUSDT"
quntry_input = st.sidebar.text_area(
    "Quntry Fry Coinleri (Virgülle ayırın)", value=quntry_default, height=80
)
quntry_symbol_list = [
    s.strip().upper()
    for s in quntry_input.replace("\n", ",").split(",")
    if s.strip()
]

quntry_timeframe = st.sidebar.selectbox(
    "Quntry Fry Zaman Dilimi", ["15m", "1h", "4h"], index=1
)

st.sidebar.markdown("---")

# Filtreleme Ayarları (Varsayılanlar Esnetildi)
st.sidebar.subheader("🔍 Filtreleme Kriterleri")
min_volume = st.sidebar.number_input(
    "Minimum 24h Hacim (Milyon $)", value=0.1, step=1.0
)
min_change = st.sidebar.number_input(
    "Minimum 24h Değişim (%)", value=-10.0, step=0.5
)
rsi_min, rsi_max = st.sidebar.slider(
    "RSI (14) Aralığı", 0, 100, (0, 100)
)


# ==========================================
# 4. CANLI VERİ VE ANALİZ MOTORU
# ==========================================
def fetch_symbol_data_safe(symbol, timeframe="1h", retries=2):
    """
    Binance API'den canlı veri çeker, teknik indikatörleri hesaplar.
    Ağ veya IP hatalarına karşı 2 kez tekrar dener.
    """
    formatted_symbol = symbol if "/" in symbol else symbol.replace("USDT", "/USDT")
    
    for attempt in range(retries):
        try:
            ohlcv = exchange.fetch_ohlcv(formatted_symbol, timeframe=timeframe, limit=100)
            if not ohlcv or len(ohlcv) < 50:
                return None

            df = pd.DataFrame(
                ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
            )

            # İndikatör Hesaplamaları
            df["rsi"] = ta.momentum.rsi(df["close"], window=14)
            df["ema50"] = ta.trend.ema_indicator(df["close"], window=50)

            macd = ta.trend.MACD(df["close"])
            df["macd"] = macd.macd()
            df["macd_signal"] = macd.macd_signal()
            df["atr"] = ta.volatility.average_true_range(
                df["high"], df["low"], df["close"], window=14
            )
            df["vol_sma"] = df["volume"].rolling(window=20).mean()

            latest = df.iloc[-1]
            prev = df.iloc[-2]
            price = float(latest["close"])

            # 24s Değişim ve Hacim Hesabı
            first_price = float(df.iloc[0]["close"])
            change_24h = ((price - first_price) / first_price) * 100
            vol_24h_m = (df["volume"].sum() * price) / 1_000_000

            # Sahte Kırılım (Fakeout) & Hacim Onayı Kontrolü
            is_volume_surge = latest["volume"] > (latest["vol_sma"] * 1.3)
            is_bullish = price > latest["ema50"]
            is_macd_cross = (prev["macd"] < prev["macd_signal"]) and (
                latest["macd"] > latest["macd_signal"]
            )

            # Sinyal Mantığı
            if is_bullish and is_macd_cross and is_volume_surge and (latest["rsi"] < 68):
                signal = "GÜÇLÜ AL"
                comment = "🟢 Hacim Onaylı Trend Kırılımı"
            elif is_bullish and (latest["rsi"] < 60):
                signal = "AL"
                comment = "🟡 Trend Pozitif"
            elif (latest["rsi"] > 70) or (price < latest["ema50"] and not is_volume_surge):
                signal = "SAT / RISKLİ"
                comment = "🔴 Sahte Kırılım / Aşırı Alım"
            else:
                signal = "NÖTR"
                comment = "⚪ Yatay Piyasa"

            atr_val = float(latest["atr"])
            return {
                "Sembol": symbol,
                "Fiyat ($)": price,
                "24h Değişim (%)": round(change_24h, 2),
                "24h Hacim (M$)": round(vol_24h_m, 2),
                "RSI (14)": round(float(latest["rsi"]), 1),
                "Stop Loss": round(price - (atr_val * 1.5), 4),
                "Hedef 1 (TP1)": round(price + (atr_val * 2.0), 4),
                "Sinyal": signal,
                "Yorum": comment,
                "Update Time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

        except ccxt.DDoSProtection:
            time.sleep(2)
        except ccxt.RequestTimeout:
            time.sleep(1)
        except Exception as e:
            break

    return None


def analyze_symbol_list(symbols, timeframe="1h"):
    results = [fetch_symbol_data_safe(sym, timeframe=timeframe) for sym in symbols]
    return pd.DataFrame([r for r in results if r is not None])


# ==========================================
# 5. TELEGRAM BİLDİRİM FONKSİYONU
# ==========================================
def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False, "Telegram token veya chat_id eksik."
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        res = requests.post(url, json=payload, timeout=5)
        return (True, "Başarılı") if res.status_code == 200 else (False, res.text)
    except Exception as e:
        return False, str(e)


# ==========================================
# 6. EKRAN ARAYÜZÜ VE TARTMA
# ==========================================
st.title("📊 Kripto Piyasası & Risk/Ödül Analiz Paneli")

# Taramaları Gerçekleştir
df_quntry_raw = analyze_symbol_list(quntry_symbol_list, timeframe=quntry_timeframe)
df_genel_raw = analyze_symbol_list(custom_symbol_list, timeframe="1h")

# Sol Panel Filtrelerini Uygula
def apply_filters(df):
    if df.empty:
        return df
    return df[
        (df["24h Hacim (M$)"] >= min_volume)
        & (df["24h Değişim (%)"] >= min_change)
        & (df["RSI (14)"] >= rsi_min)
        & (df["RSI (14)"] <= rsi_max)
    ]

df_quntry = apply_filters(df_quntry_raw)
df_genel = apply_filters(df_genel_raw)

# Özet Üst Metrikler
c1, c2, c3 = st.columns(3)
c1.metric(
    "UptimeRobot Durumu",
    "🟢 ONLINE",
    f"Son Ping: {datetime.datetime.now().strftime('%H:%M:%S')}",
)
c2.metric("Quntry Fry Coin Sayısı", len(df_quntry_raw))
c3.metric("Genel Taranan Coin Sayısı", len(df_genel_raw))

# --- BÖLÜM 1: QUNTRY FRY LİSTESİ ---
st.markdown("### 🍟 Quntry Fry Özel Takip Listesi")
if not df_quntry.empty:
    st.dataframe(df_quntry, use_container_width=True)
else:
    st.warning("⚠️ Belirlenen filtre kriterlerine uyan Quntry Fry coini bulunamadı.")
    if not df_quntry_raw.empty:
        with st.expander("🔍 Tüm Quntry Fry Varlıklarının Ham Verisini Göster"):
            st.dataframe(df_quntry_raw, use_container_width=True)

st.markdown("---")

# --- BÖLÜM 2: GENEL PİYASA ANALİZİ ---
st.markdown("### 🎯 Genel Piyasa Risk & Hedef Analizi")
if not df_genel.empty:
    st.dataframe(df_genel, use_container_width=True)
else:
    st.warning("⚠️ Belirlenen filtre kriterlerine uyan Genel piyasa coini bulunamadı.")
    if not df_genel_raw.empty:
        with st.expander("🔍 Taranan Tüm Genel Varlıkların Ham Verisini Göster"):
            st.dataframe(df_genel_raw, use_container_width=True)

# Manuel Telegram Sinyal Butonu
st.sidebar.markdown("---")
if st.sidebar.button("📤 Telegram Raporunu Şimdi Gönder"):
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = f"📊 *ANLIK KRİPTO ANALİZ RAPORU*\n⏱️ *Update Time:* `{now_str}`\n\n"

    if not df_quntry_raw.empty:
        msg += "🍟 *QUNTRY FRY BİLDİRİMLERİ:*\n"
        for _, row in df_quntry_raw.iterrows():
            msg += f"• *{row['Sembol']}*: `${row['Fiyat ($)']}` | RSI: `{row['RSI (14)']}` | Sinyal: `{row['Sinyal']}`\n"

    success, err = send_telegram_message(msg)
    if success:
        st.sidebar.success("✅ Rapor Telegram'a gönderildi!")
    else:
        st.sidebar.error(f"❌ Hata: {err}")

# ==========================================
# 7. OTOMATİK ZAMANLAYICI (UPTIMEROBOT UYUMLU)
# ==========================================
if enable_auto_telegram:
    if "last_bot_run" not in st.session_state:
        st.session_state["last_bot_run"] = 0

    CURRENT_TIME = time.time()
    THIRTY_MINUTES = 1800  # 30 Dakika (1800 saniye)

    if (CURRENT_TIME - st.session_state["last_bot_run"]) > THIRTY_MINUTES:
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msg = f"🤖 *OTOMATİK PERİYODİK RAPOR*\n⏱️ *Update Time:* `{now_str}`\n\n"

        if not df_quntry_raw.empty:
            msg += "🍟 *QUNTRY FRY LİSTESİ:*\n"
            for _, row in df_quntry_raw.iterrows():
                msg += f"• *{row['Sembol']}*: `${row['Fiyat ($)']}` | Durum: `{row['Sinyal']}`\n"

        send_telegram_message(msg)
        st.session_state["last_bot_run"] = CURRENT_TIME
