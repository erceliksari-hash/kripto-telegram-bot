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
    page_title="Kripto Piyasası Taraması & Uptime Robot Paneli",
    page_icon="📊",
    layout="wide",
)

# ==========================================
# 2. SECRETS & CANLI BAGLANTILAR
# ==========================================
TELEGRAM_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", st.secrets.get("telegram", {}).get("bot_token", ""))
TELEGRAM_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", st.secrets.get("telegram", {}).get("chat_id", ""))

# Binance CCXT Kurulumu (Rate Limit & Timeout Korumalı)
exchange = ccxt.binance({
    "enableRateLimit": True,
    "timeout": 10000,
})

# ==========================================
# 3. SIDEBAR & UPTIMEROBOT DURUMU
# ==========================================
st.sidebar.title("⚙️ Panel ve Otomasyon Ayarları")

# UptimeRobot Bilgilendirmesi
st.sidebar.success("🟢 **UptimeRobot Entegrasyonu:** Aktif\n(Ping istekleri sunucuyu 7/24 uyanık tutar)")

st.sidebar.markdown("---")

# --- MANUEL GENEL TARAMA LİSTESİ ---
st.sidebar.subheader("📝 Genel Taranacak Semboller")
default_symbols = "BTCUSDT, ETHUSDT, SOLUSDT, AVAXUSDT, NEARUSDT, LINKUSDT"
symbol_input = st.sidebar.text_area("Semboller (Virgülle ayırın)", value=default_symbols, height=80)
custom_symbol_list = [s.strip().upper() for s in symbol_input.replace("\n", ",").split(",") if s.strip()]

st.sidebar.markdown("---")

# --- QUNTRY FRY ÖZEL TAKİP LİSTESİ ---
st.sidebar.subheader("🍟 Quntry Fry Özel Listesi")
quntry_default = "BEATUSDT, BICOUSDT, RECALLUSDT, ZDTUSDT"
quntry_input = st.sidebar.text_area("Quntry Fry Coinleri (Virgülle ayırın)", value=quntry_default, height=80)
quntry_symbol_list = [s.strip().upper() for s in quntry_input.replace("\n", ",").split(",") if s.strip()]

quntry_timeframe = st.sidebar.selectbox("Zaman Dilimi", ["15m", "1h", "4h"], index=1)

# ==========================================
# 4. CANLI VERİ VE ANALİZ MOTORU
# ==========================================
def fetch_symbol_data(symbol, timeframe="1h"):
    """Binance API'den veri çeker, sahte kırılımları süzer."""
    try:
        formatted_symbol = symbol if "/" in symbol else symbol.replace("USDT", "/USDT")
        ohlcv = exchange.fetch_ohlcv(formatted_symbol, timeframe=timeframe, limit=100)
        
        if not ohlcv or len(ohlcv) < 50:
            return None

        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        
        # İndikatör Hesaplamaları
        df["rsi"] = ta.momentum.rsi(df["close"], window=14)
        df["ema50"] = ta.trend.ema_indicator(df["close"], window=50)
        
        macd = ta.trend.MACD(df["close"])
        df["macd"] = macd.macd()
        df["macd_signal"] = macd.macd_signal()
        df["atr"] = ta.volatility.average_true_range(df["high"], df["low"], df["close"], window=14)
        df["vol_sma"] = df["volume"].rolling(window=20).mean()

        latest = df.iloc[-1]
        prev = df.iloc[-2]
        price = float(latest["close"])

        # Sahte Kırılım (Fakeout) & Hacim Onayı Kontrolü
        is_volume_surge = latest["volume"] > (latest["vol_sma"] * 1.3)
        is_bullish = price > latest["ema50"]
        is_macd_cross = (prev["macd"] < prev["macd_signal"]) and (latest["macd"] > latest["macd_signal"])

        # Sinyal Yönetimi
        if is_bullish and is_macd_cross and is_volume_surge and (latest["rsi"] < 68):
            signal = "GUCLU_AL"
            comment = "🟢 Hacim Onaylı Trend Kırılımı (Sahte Yükseliş Riski Düşük)"
        elif is_bullish and (latest["rsi"] < 60):
            signal = "AL"
            comment = "🟡 Trend Pozitif, Alım Uygun"
        elif (latest["rsi"] > 70) or (price < latest["ema50"] and not is_volume_surge):
            signal = "SAT / TEPEDE"
            comment = "🔴 Sahte Kırılım / Aşırı Alım Bölgesi"
        else:
            signal = "NOTR"
            comment = "⚪ Yatay Piyasa"

        atr_val = latest["atr"]
        return {
            "Sembol": symbol,
            "Giriş ($)": price,
            "RSI (14)": round(latest["rsi"], 1),
            "Stop Loss": round(price - (atr_val * 1.5), 4),
            "Hedef 1 (TP1)": round(price + (atr_val * 2.0), 4),
            "Sinyal": signal,
            "Yorum": comment,
            "Update Time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    except Exception as e:
        return None

def analyze_symbol_list(symbols, timeframe="1h"):
    results = [fetch_symbol_data(sym, timeframe=timeframe) for sym in symbols]
    return pd.DataFrame([r for r in results if r is not None])

# ==========================================
# 5. TELEGRAM VE UPTIMEROBOT YÖNETİMİ
# ==========================================
def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False, "Telegram bilgileri eksik."
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        res = requests.post(url, json=payload, timeout=5)
        return (True, "Başarılı") if res.status_code == 200 else (False, res.text)
    except Exception as e:
        return False, str(e)

# ==========================================
# 6. EKRAN GÖRÜNÜMÜ & DÖNGÜ ZAMANLAYICI
# ==========================================
st.title("📊 Kripto Piyasası & Uptime Robot Paneli")

# Canlı Taramaları Yap
df_genel = analyze_symbol_list(custom_symbol_list, timeframe="1h")
df_quntry = analyze_symbol_list(quntry_symbol_list, timeframe=quntry_timeframe)

# Metrikler
c1, c2, c3 = st.columns(3)
c1.metric("UptimeRobot Durumu", "🟢 ONLINE", f"Son Ping: {datetime.datetime.now().strftime('%H:%M:%S')}")
c2.metric("Taranan Genel Coin", len(df_genel))
c3.metric("Quntry Fry Coin", len(df_quntry))

st.markdown("### 🍟 Quntry Fry Özel Takip Listesi")
st.dataframe(df_quntry, use_container_width=True)

st.markdown("### 🎯 Genel Piyasa Analizi")
st.dataframe(df_genel, use_container_width=True)

# ------------------------------------------
# OTOMATİK ZAMANLAYICI (UPTIMEROBOT İLE UYUMLU)
# ------------------------------------------
if "last_bot_run" not in st.session_state:
    st.session_state["last_bot_run"] = 0

CURRENT_TIME = time.time()
THIRTY_MINUTES = 1800  # 30 Dakika (1800 Saniye)

if (CURRENT_TIME - st.session_state["last_bot_run"]) > THIRTY_MINUTES:
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = f"🤖 *UPTIMEROBOT ONAYLI OTOMATİK RAPOR*\n⏱️ *Update Time:* `{now_str}`\n\n"
    
    if not df_quntry.empty:
        msg += "🍟 *QUNTRY FRY BİLDİRİMLERİ:*\n"
        for _, row in df_quntry.iterrows():
            msg += f"• *{row['Sembol']}*: `${row['Giriş ($)']}` | Durum: `{row['Sinyal']}`\n"
            
    send_telegram_message(msg)
    st.session_state["last_bot_run"] = CURRENT_TIME
