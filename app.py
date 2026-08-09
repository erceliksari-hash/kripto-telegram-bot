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
# 2. SECRETS'TEN TELEGRAM BİLGİLERİNİ OKU
# ==========================================
TELEGRAM_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "")

# ==========================================
# 3. SIDEBAR (SOL PANEL) AYARLARI
# ==========================================
st.sidebar.title("⚙️ Panel ve Bot Ayarları")

# Tarama Sıklığı ve Bildirim Aktiflik Durumu
scan_interval = st.sidebar.slider(
    "Tarama Sıklığı (Saniye)", min_value=10, max_value=300, value=60
)
enable_telegram = st.sidebar.checkbox(
    "Telegram Bildirimlerini Aktif Et", value=True
)

st.sidebar.markdown("---")

# --- MANUEL SEMBOL / COİN LİSTESİ (QUNTRYFRY / QUANTIFY İÇİN) ---
st.sidebar.subheader("📝 Manuel Coin / Sembol Listesi")
default_symbols = "BEATUSDT, BICOUSDT, RECALLUSDT, ZDTUSDT, BTCUSDT, ETHUSDT"
symbol_input = st.sidebar.text_area(
    "Taranacak Semboller (Virgülle veya alt alta yazın)",
    value=default_symbols,
    height=100,
    help="Quantify / Quntryfry taramasında kullanılacak özel sembol listeniz.",
)

# Girilen metni temiz bir listeye dönüştürme
custom_symbol_list = [
    s.strip().upper()
    for s in symbol_input.replace("\n", ",").split(",")
    if s.strip()
]

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


# ==========================================
# 4. TELEGRAM BİLDİRİM FONKSİYONU
# ==========================================
def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return (
            False,
            "Streamlit Secrets içinde TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID bulunamadı.",
        )

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


# ==========================================
# 5. ANA EKRAN VE TARAMA VERİLERİ
# ==========================================
st.title("📊 Krypto Piyasası Taraması & Risk/Ödül Analiz Paneli")

if st.button("🔄 Verileri Şimdi Yenile"):
    st.rerun()

# Örnek Veri Havuzu (Gerçek Quntryfry / Quantify API çağrısını buraya bağlayabilirsiniz)
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

# Sadece kullanıcının manuel listede belirttiği sembolleri filtrele
scanned_data = [
    mock_database[sym]
    for sym in custom_symbol_list
    if sym in mock_database
]

df = pd.DataFrame(scanned_data)

if not df.empty:
    # Teknik & Hacim Filtrelerinin Uygulanması
    filtered_df = df[
        (df["24h Hacim (M$)"] >= min_volume)
        & (df["24h Değişim (%)"] >= min_change)
        & (df["RSI (14)"] >= rsi_min)
        & (df["RSI (14)"] <= rsi_max)
    ]
else:
    filtered_df = pd.DataFrame()

# Özet Metrikler
col1, col2, col3 = st.columns(3)
col1.metric("Taranan Toplam Sembol", len(custom_symbol_list))
col2.metric("Filtreye Uyan Semboller", len(filtered_df))

bot_status = (
    "Aktif"
    if (enable_telegram and TELEGRAM_TOKEN and TELEGRAM_CHAT_ID)
    else "Beklemede / Secrets Eksik"
)
col3.metric("Bot Durumu", bot_status)

st.markdown("### 🎯 Otomatik Risk & Hedef Analizli Varlıklar")

# Tablo Görünümü
if not filtered_df.empty:
    st.dataframe(filtered_df, use_container_width=True)
else:
    st.info(
        "Girdiğiniz manuel liste ve filtrelere uygun varlık bulunamadı."
    )

# ==========================================
# 6. TELEGRAM KONTROLÜ
# ==========================================
st.markdown("---")
if enable_telegram:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        st.warning(
            "⚠️ Telegram bildirimleri aktif fakat secrets.toml içinde TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID eksik."
        )
    else:
        if st.button("📲 Test Telegram Bildirimi Gönder"):
            sample_msg = f"🚀 *Krypto Tarama Test Sinyali*\nFiltreye uyan varlık sayısı: {len(filtered_df)}"
            success, err_msg = send_telegram_message(sample_msg)
            if success:
                st.success(
                    "✅ Telegram bildirimi secrets üzerinden başarıyla gönderildi!"
                )
            else:
                st.error(f"❌ Telegram gönderimi başarısız oldu: {err_msg}")
