import datetime
import pandas as pd
import requests
import streamlit as st

# ==========================================
# 1. PAGE CONFIG & TITLE
# ==========================================
st.set_page_config(
    page_title="Krypto Piyasası Taraması & Risk/Ödül Analiz Paneli",
    page_icon="📊",
    layout="wide",
)

# ==========================================
# 2. SECRETS VE DEFAULT DEĞERLERİ ÇEK
# ==========================================
# Streamlit secrets ( secrets.toml ) üzerinden bilgileri alıyoruz.
# Eğer secrets dosyasında yoksa boş string dönerek hatayı engeller.
default_token = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
default_chat_id = st.secrets.get("TELEGRAM_CHAT_ID", "")

# ==========================================
# 3. SIDEBAR (SOL PANEL) AYARLARI
# ==========================================
st.sidebar.title("⚙️ Panel ve Bot Ayarları")

# Telegram Bot Ayarları (Secrets entegrasyonlu)
telegram_token = st.sidebar.text_input(
    "Telegram Bot Token",
    value=default_token,
    type="password",
    help="BotFather'dan alınan token bilgisi.",
)

telegram_chat_id = st.sidebar.text_input(
    "Telegram Kanal/Chat ID",
    value=default_chat_id,
    help="Bildirim gönderilecek Telegram Chat/Kanal ID.",
)

scan_interval = st.sidebar.slider(
    "Tarama Sıklığı (Saniye)", min_value=10, max_value=300, value=60
)
enable_telegram = st.sidebar.checkbox(
    "Telegram Bildirimlerini Aktif Et", value=True
)

st.sidebar.markdown("---")

# --- TEMEL & HACİM FİLTRELERİ ---
st.sidebar.subheader("📌 Temel & Hacim Filtreleri")
min_volume = st.sidebar.number_input(
    "Minimum 24h Hacim (Milyon $)", value=10.00, step=1.00
)
min_change = st.sidebar.number_input(
    "Minimum Değişim (%)", value=2.00, step=0.50
)

st.sidebar.markdown("---")

# --- TEKNİK GÖSTERGE FİLTRELERİ ---
st.sidebar.subheader("📊 Teknik Gösterge Filtreleri")
rsi_min, rsi_max = st.sidebar.slider(
    "RSI (14) Aralığı", min_value=0, max_value=100, value=(30, 72)
)

st.sidebar.markdown("---")

# --- QUNTRY / QUANTIFY FİLTRELERİ ---
st.sidebar.subheader("🌐 Quntry / Quantify Filtreleri")
quntry_filter_active = st.sidebar.checkbox(
    "Quntry/Quantify Sinyal Taramasını Etkinleştir", value=True
)
quntry_threshold = st.sidebar.number_input(
    "Quntry Hassasiyet Eşiği", value=1.5, step=0.1
)


# ==========================================
# 4. TELEGRAM BİLDİRİM FONKSİYONU
# ==========================================
def send_telegram_message(token, chat_id, message):
    if not token or not chat_id:
        return False, "Token veya Chat ID eksik."

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}

    try:
        response = requests.post(url, json=payload, timeout=5)
        if response.status_code == 200:
            return True, "Başarılı"
        else:
            return False, f"Telegram API Hatası: {response.text}"
    except Exception as e:
        return False, f"Bağlantı Hatası: {str(e)}"


# ==========================================
# 5. ANA EKRAN VE BAŞLIK
# ==========================================
st.title("📊 Krypto Piyasası Taraması & Risk/Ödül Analiz Paneli")

# Yenileme Butonu
if st.button("🔄 Verileri Şimdi Yenile"):
    st.rerun()

# Örnek Sembol Taraması (Sanal/Simüle Veriler)
# Gerçek API entegrasyonunuz varsa bu kısmı borsa borsa bağlayabilirsiniz.
mock_data = [
    {
        "Sembol": "BEATUSDT",
        "Giriş ($)": 2.9711,
        "24h Değişim (%)": 4.06,
        "24h Hacim (M$)": 96.15,
        "RSI (14)": 70.0,
        "Stop Loss": 2.7114,
        "Hedef 1 (TP1)": 3.3606,
        "Hedef 2 (TP2)": 3.4904,
    },
    {
        "Sembol": "BICOUSDT",
        "Giriş ($)": 0.0655,
        "24h Değişim (%)": 4.06,
        "24h Hacim (M$)": 6994.10,
        "RSI (14)": 63.2,
        "Stop Loss": 0.0588,
        "Hedef 1 (TP1)": 0.0756,
        "Hedef 2 (TP2)": 0.0790,
    },
    {
        "Sembol": "RECALLUSDT",
        "Giriş ($)": 0.0474,
        "24h Değişim (%)": 3.90,
        "24h Hacim (M$)": 38.49,
        "RSI (14)": 69.0,
        "Stop Loss": 0.0459,
        "Hedef 1 (TP1)": 0.0495,
        "Hedef 2 (TP2)": 0.0502,
    },
    {
        "Sembol": "ZDTUSDT",
        "Giriş ($)": 0.1049,
        "24h Değişim (%)": 2.69,
        "24h Hacim (M$)": 157.63,
        "RSI (14)": 54.3,
        "Stop Loss": 0.1010,
        "Hedef 1 (TP1)": 0.1108,
        "Hedef 2 (TP2)": 0.1128,
    },
]

df = pd.DataFrame(mock_data)

# Filtrelerin Uygulanması
filtered_df = df[
    (df["24h Hacim (M$)"] >= min_volume)
    & (df["24h Değişim (%)"] >= min_change)
    & (df["RSI (14)"] >= rsi_min)
    & (df["RSI (14)"] <= rsi_max)
]

# Özet Metrikler
col1, col2, col3 = st.columns(3)
col1.metric("Taranan Toplam Sembol", len(df))
col2.metric("Filtreye Uyan Semboller", len(filtered_df))

bot_status = (
    "Aktif" if (enable_telegram and telegram_token and telegram_chat_id) else "Beklemede / Eksik Bilgi"
)
col3.metric("Bot Durumu", bot_status)

st.markdown("### 🎯 Otomatik Risk & Hedef Analizli Varlıklar")

# Tablo Görünümü
st.dataframe(filtered_df, use_container_width=True)

# ==========================================
# 6. TELEGRAM BİLDİRİM KONTROLÜ VE TETİKLEME
# ==========================================
st.markdown("---")
if enable_telegram:
    if not telegram_token or not telegram_chat_id:
        st.warning(
            "⚠️ Telegram bildirimleri aktif fakat Bot Token veya Chat ID girilmemiş/Secrets'ten okunamadı."
        )
    else:
        if st.button("📲 Test Telegram Bildirimi Gönder"):
            sample_msg = f"🚀 *Krypto Tarama Test Sinyali*\nFiltreye uyan varlık sayısı: {len(filtered_df)}"
            success, err_msg = send_telegram_message(
                telegram_token, telegram_chat_id, sample_msg
            )
            if success:
                st.success("✅ Telegram bildirimi başarıyla gönderildi!")
            else:
                st.error(f"❌ Telegram gönderimi başarısız oldu: {err_msg}")
