import datetime
import threading
import time
import pandas as pd
import requests
import streamlit as st

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
    TELEGRAM_TOKEN = st.secrets.get(
        "TELEGRAM_BOT_TOKEN", st.secrets.get("bot_token", "")
    )
    TELEGRAM_CHAT_ID = st.secrets.get(
        "TELEGRAM_CHAT_ID", st.secrets.get("chat_id", "")
    )

# ==========================================
# 3. SIDEBAR (SOL PANEL) AYARLARI
# ==========================================
st.sidebar.title("⚙️ Panel ve Otomasyon Ayarları")

enable_auto_telegram = st.sidebar.checkbox(
    "30 Dk'da Bir Otomatik Telegram Mesajı Gönder", value=True
)

st.sidebar.markdown("---")

# --- MANUEL SEMBOL / COİN LİSTESİ ---
st.sidebar.subheader("📝 Manuel Coin / Sembol Listesi")
default_symbols = "BEATUSDT, BICOUSDT, RECALLUSDT, ZDTUSDT, BTCUSDT, ETHUSDT"
symbol_input = st.sidebar.text_area(
    "Taranacak Semboller (Virgülle ayırın)",
    value=default_symbols,
    height=100,
)

custom_symbol_list = [
    s.strip().upper()
    for s in symbol_input.replace("\n", ",").split(",")
    if s.strip()
]

st.sidebar.markdown("---")

# --- QUNTRY FRY (QUANTIFY) ÖZEL SEGMENTİ ---
st.sidebar.subheader("🍟 Quntry Fry (Quantify) Ayarları")
quntry_mode = st.sidebar.selectbox(
    "Tarama Modu",
    ["Trend Takibi", "Aşırı Alım/Satım (Mean Reversion)", "Hacim Patlaması"],
)
quntry_sensitivity = st.sidebar.slider(
    "Sinyal Duyarlılığı (Threshold)",
    min_value=1.0,
    max_value=5.0,
    value=2.5,
    step=0.1,
)
quntry_period = st.sidebar.selectbox(
    "Zaman Dilimi (Timeframe)", ["15m", "1h", "4h", "1d"], index=1
)

st.sidebar.markdown("---")

# --- TEKNİK & HACİM FİLTRELERİ ---
st.sidebar.subheader("📌 Temel & Hacim Filtreleri")
min_volume = st.sidebar.number_input(
    "Minimum 24h Hacim (Milyon $)", value=10.00, step=1.00
)
min_change = st.sidebar.number_input(
    "Minimum Değişim (%)", value=2.00, step=0.50
)
rsi_min, rsi_max = st.sidebar.slider(
    "RSI (14) Aralığı", min_value=0, max_value=100, value=(30, 72)
)

# ==========================================
# 4. YARDIMCI VE ANALİZ FONKSİYONLARI
# ==========================================


def send_telegram_message(message):
    """Telegram API üzerinden mesaj gönderir."""
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
        if response.status_code == 200:
            return True, "Başarılı"
        else:
            return False, f"Telegram API Hatası: {response.text}"
    except Exception as e:
        return False, f"Bağlantı Hatası: {str(e)}"


def generate_market_analysis(filtered_df):
    """Listelenen varlıkların risk/ödül analizini ve Quntry Fry yorumunu hazırlar."""
    if filtered_df.empty:
        return "⚠️ *Krypto Tarama Raporu*\n\nŞu anda kriterlere uyan uygun bir varlık bulunamadı."

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    msg = f"📊 *QUNTRY FRY & RİSK ANALİZ RAPORU*\n📅 `{now_str}`\n"
    msg += f"⚙️ *Mod:* `{quntry_mode}` | *Periyot:* `{quntry_period}`\n"
    msg += f"🎯 *Filtreye Uyan Varlık Sayısı:* {len(filtered_df)}\n"
    msg += "-----------------------------------\n\n"

    for idx, row in filtered_df.iterrows():
        symbol = row["Sembol"]
        price = row["Giriş ($)"]
        change = row["24h Değişim (%)"]
        rsi = row["RSI (14)"]
        stop = row["Stop Loss"]
        tp1 = row["Hedef 1 (TP1)"]
        tp2 = row["Hedef 2 (TP2)"]

        # Risk / Ödül Hesaplaması (R:R)
        risk = price - stop
        reward_tp1 = tp1 - price
        rr_ratio = reward_tp1 / risk if risk > 0 else 0

        # Otomatik Yorum Üretimi
        if rsi > 65:
            rsi_comment = "Güçlü momentum"
        elif rsi < 40:
            rsi_comment = "Aşırı satıştan tepki"
        else:
            rsi_comment = "Dengeli bölge"

        msg += f"🔹 *{symbol}*\n"
        msg += f"• Giriş Fiyatı: `${price}` (+%{change})\n"
        msg += f"• RSI (14): `{rsi}` ({rsi_comment})\n"
        msg += f"• Stop Loss: `${stop}` | TP1: `${tp1}` | TP2: `${tp2}`\n"
        msg += f"• Risk/Ödül Oranı (TP1): `1:{rr_ratio:.2f}`\n"

        if rr_ratio >= 1.5:
            msg += "💡 *Yorum:* Quntry Fry filtresine uygun, R:R oranı yüksek, takip edilebilir.\n\n"
        else:
            msg += "⚠️ *Yorum:* R:R oranı dar, stop seviyesine sadık kalınmalı.\n\n"

    return msg


# ==========================================
# 5. VERİ İŞLEME VE FİLTRELEME
# ==========================================
mock_database = {
    "BEATUSDT": {
        "Sembol": "BEATUSDT",
        "Giriş ($)": 2.9711,
        "24h Değişim (%)": 4.06,
        "24h Hacim (M$)": 96.15,
        "RSI (14)": 70.0,
        "Stop Loss": 2.7114,
        "Hedef 1 (TP1)": 3.3606,
        "Hedef 2 (TP2)": 3.4904,
    },
    "BICOUSDT": {
        "Sembol": "BICOUSDT",
        "Giriş ($)": 0.0655,
        "24h Değişim (%)": 4.06,
        "24h Hacim (M$)": 6994.10,
        "RSI (14)": 63.2,
        "Stop Loss": 0.0588,
        "Hedef 1 (TP1)": 0.0756,
        "Hedef 2 (TP2)": 0.0790,
    },
    "RECALLUSDT": {
        "Sembol": "RECALLUSDT",
        "Giriş ($)": 0.0474,
        "24h Değişim (%)": 3.90,
        "24h Hacim (M$)": 38.49,
        "RSI (14)": 69.0,
        "Stop Loss": 0.0459,
        "Hedef 1 (TP1)": 0.0495,
        "Hedef 2 (TP2)": 0.0502,
    },
    "ZDTUSDT": {
        "Sembol": "ZDTUSDT",
        "Giriş ($)": 0.1049,
        "24h Değişim (%)": 2.69,
        "24h Hacim (M$)": 157.63,
        "RSI (14)": 54.3,
        "Stop Loss": 0.1010,
        "Hedef 1 (TP1)": 0.1108,
        "Hedef 2 (TP2)": 0.1128,
    },
    "BTCUSDT": {
        "Sembol": "BTCUSDT",
        "Giriş ($)": 64200.00,
        "24h Değişim (%)": 1.20,
        "24h Hacim (M$)": 15200.00,
        "RSI (14)": 58.1,
        "Stop Loss": 62500.00,
        "Hedef 1 (TP1)": 66800.00,
        "Hedef 2 (TP2)": 68500.00,
    },
    "ETHUSDT": {
        "Sembol": "ETHUSDT",
        "Giriş ($)": 3450.00,
        "24h Değişim (%)": 0.85,
        "24h Hacim (M$)": 8400.00,
        "RSI (14)": 49.5,
        "Stop Loss": 3320.00,
        "Hedef 1 (TP1)": 3620.00,
        "Hedef 2 (TP2)": 3750.00,
    },
}

scanned_data = [
    mock_database[sym]
    for sym in custom_symbol_list
    if sym in mock_database
]
df = pd.DataFrame(scanned_data)

if not df.empty:
    filtered_df = df[
        (df["24h Hacim (M$)"] >= min_volume)
        & (df["24h Değişim (%)"] >= min_change)
        & (df["RSI (14)"] >= rsi_min)
        & (df["RSI (14)"] <= rsi_max)
    ]
else:
    filtered_df = pd.DataFrame()

# ==========================================
# 6. EKRAN GÖRÜNÜMÜ
# ==========================================
st.title("📊 Krypto Piyasası Taraması & Risk/Ödül Analiz Paneli")

col1, col2, col3 = st.columns(3)
col1.metric("Taranan Toplam Sembol", len(custom_symbol_list))
col2.metric("Filtreye Uyan Semboller", len(filtered_df))

bot_status = (
    "30 Dk Otomatik Aktif"
    if (enable_auto_telegram and TELEGRAM_TOKEN and TELEGRAM_CHAT_ID)
    else "Beklemede / Devre Dışı"
)
col3.metric("Bot Durumu", bot_status)

st.markdown("### 🎯 Quntry Fry Filtreli Risk & Hedef Analizli Varlıklar")

if not filtered_df.empty:
    st.dataframe(filtered_df, use_container_width=True)
else:
    st.info("Filtrelere uygun varlık bulunamadı.")

# Manuel Gönderim Butonu
if st.button("📲 Analiz Raporunu Şimdi Telegram'a Gönder"):
    report_msg = generate_market_analysis(filtered_df)
    success, err_msg = send_telegram_message(report_msg)
    if success:
        st.success("✅ Quntry Fry Analiz Raporu Telegram'a iletildi!")
    else:
        st.error(f"❌ Gönderim başarısız: {err_msg}")

# ==========================================
# 7. 30 DAKİKALIK OTOMATİK ZAMANLAYICI
# ==========================================
if "last_sent_time" not in st.session_state:
    st.session_state["last_sent_time"] = 0

THIRTY_MINUTES = 1800
current_time = time.time()

if enable_auto_telegram:
    if (current_time - st.session_state["last_sent_time"]) > THIRTY_MINUTES:
        report_msg = generate_market_analysis(filtered_df)
        success, _ = send_telegram_message(report_msg)
        if success:
            st.session_state["last_sent_time"] = current_time
