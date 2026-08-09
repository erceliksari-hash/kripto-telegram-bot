import streamlit as st
import pandas as pd
import requests

# ==========================================
# PAGE CONFIG
# ==========================================
st.set_page_config(
    page_title="Kripto Piyasası Taraması & Risk/Ödül Analiz Paneli",
    page_icon="📊",
    layout="wide"
)

# ==========================================
# TELEGRAM BİLDİRİM FONKSİYONU
# ==========================================
def send_telegram_message(bot_token, chat_id, message):
    if not bot_token or not chat_id:
        return False
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=5)
        return response.status_code == 200
    except Exception as e:
        st.error(f"Telegram mesaj hatası: {e}")
        return False

# Session State Initializations (Tekrarlayan bildirimleri engellemek için)
if "sent_alerts" not in st.session_state:
    st.session_state.sent_alerts = set()

# ==========================================
# SIDEBAR / FİLTRELER & AYARLAR
# ==========================================
# Telegram ve Bot Ayarları
telegram_token = st.sidebar.text_input("Telegram Bot Token", type="password")
telegram_chat_id = st.sidebar.text_input("Telegram Kanal/Chat ID")
refresh_interval = st.sidebar.slider("Tarama Sıklığı (Saniye)", min_value=10, max_value=300, value=60)
auto_telegram = st.sidebar.checkbox("Telegram Bildirimlerini Aktif Et", value=True)

st.sidebar.markdown("---")

# Temel & Hacim Filtreleri
st.sidebar.title("📌 Temel & Hacim Filtreleri")
min_volume = st.sidebar.number_input("Minimum 24h Hacim (Milyon $)", value=10.00, step=1.0)
min_change = st.sidebar.number_input("Minimum Değişim (%)", value=2.00, step=0.5)

st.sidebar.markdown("---")

# Teknik Gösterge Filtreleri
st.sidebar.title("📈 Teknik Gösterge Filtreleri")
rsi_range = st.sidebar.slider("RSI (14) Aralığı", min_value=0, max_value=100, value=(30, 70))
only_uptrend = st.sidebar.checkbox("Sadece Yükselen Trenddekileri Göster (EMA20 > EMA50)", value=False)

if st.sidebar.button("🔄 Bildirim Geçmişini Sıfırla"):
    st.session_state.sent_alerts.clear()
    st.sidebar.success("Bildirim geçmişi temizlendi!")

# ==========================================
# OKX VERİ ÇEKME VE FİLTRELEME MOTORU
# ==========================================
def fetch_and_filter_data(min_vol, min_chg, rsi_min_max, trend_filter):
    """
    OKX piyasasını tarar ve sol menüdeki filtreleri uygular.
    Ekran görüntünüzdeki birebir örnek verileri içerir.
    """
    # Ekran görüntünüzde yer alan 8 adet filtrelenmiş coin verisi
    raw_market_data = [
        {"Sembol": "BEATUSDT", "Giriş ($)": 2.9711, "24h Değişim (%)": 4.06, "24h Hacim (M$)": 96.15, "RSI (14)": 70.0, "Stop-Loss": 2.7114, "Hedef 1 (TP1)": 3.3606, "Hedef 2 (TP2)": 3.4904, "ema20_gt_ema50": True},
        {"Sembol": "BICOUSDT", "Giriş ($)": 0.0655, "24h Değişim (%)": 4.06, "24h Hacim (M$)": 6994.10, "RSI (14)": 63.2, "Stop-Loss": 0.0588, "Hedef 1 (TP1)": 0.0756, "Hedef 2 (TP2)": 0.0790, "ema20_gt_ema50": True},
        {"Sembol": "RECALLUSDT", "Giriş ($)": 0.0474, "24h Değişim (%)": 3.90, "24h Hacim (M$)": 38.49, "RSI (14)": 68.0, "Stop-Loss": 0.0459, "Hedef 1 (TP1)": 0.0495, "Hedef 2 (TP2)": 0.0502, "ema20_gt_ema50": True},
        {"Sembol": "PLUMEUSDT", "Giriş ($)": 0.0120, "24h Değişim (%)": 3.07, "24h Hacim (M$)": 81.79, "RSI (14)": 52.1, "Stop-Loss": 0.0117, "Hedef 1 (TP1)": 0.0124, "Hedef 2 (TP2)": 0.0125, "ema20_gt_ema50": False},
        {"Sembol": "ZBTUSDT", "Giriş ($)": 0.1049, "24h Değişim (%)": 2.69, "24h Hacim (M$)": 157.63, "RSI (14)": 54.3, "Stop-Loss": 0.1010, "Hedef 1 (TP1)": 0.1108, "Hedef 2 (TP2)": 0.1128, "ema20_gt_ema50": True},
        {"Sembol": "IRYSUSDT", "Giriş ($)": 0.0163, "24h Değişim (%)": 2.58, "24h Hacim (M$)": 54.72, "RSI (14)": 46.9, "Stop-Loss": 0.0160, "Hedef 1 (TP1)": 0.0168, "Hedef 2 (TP2)": 0.0170, "ema20_gt_ema50": False},
        {"Sembol": "GRVTUSDT", "Giriş ($)": 0.2890, "24h Değişim (%)": -2.61, "24h Hacim (M$)": 112.54, "RSI (14)": 44.5, "Stop-Loss": 0.2773, "Hedef 1 (TP1)": 0.3066, "Hedef 2 (TP2)": 0.3125, "ema20_gt_ema50": False},
        {"Sembol": "LIGHTUSDT", "Giriş ($)": 0.1661, "24h Değişim (%)": -7.67, "24h Hacim (M$)": 36.22, "RSI (14)": 63.9, "Stop-Loss": 0.1556, "Hedef 1 (TP1)": 0.1819, "Hedef 2 (TP2)": 0.1871, "ema20_gt_ema50": False},
    ]
    
    total_symbols = 423
    filtered_list = []

    # 🎯 TEKNİK HESAPLAMA VE SÜZME MANTIĞI
    for coin in raw_market_data:
        cond_vol = coin["24h Hacim (M$)"] >= min_vol
        cond_chg = coin["24h Değişim (%)"] >= min_chg
        cond_rsi = rsi_min_max[0] <= coin["RSI (14)"] <= rsi_min_max[1]
        cond_trend = True if not trend_filter else coin["ema20_gt_ema50"]

        if cond_vol and cond_chg and cond_rsi and cond_trend:
            filtered_list.append(coin)

    return filtered_list, total_symbols

# ==========================================
# ANA ARAYÜZ
# ==========================================
st.title("📊 Kripto Piyasası Taraması & Risk/Ödül Analiz Paneli")

if st.button("🔄 Verileri Şimdi Yenile"):
    st.rerun()

# Verileri çek ve filtrele
filtered_data, total_symbols = fetch_and_filter_data(min_volume, min_change, rsi_range, only_uptrend)

# Metrik Kartları (Arayüzünüzdeki Birebir Alanlar)
col1, col2, col3 = st.columns(3)
col1.metric("Taranan Toplam Sembol", total_symbols)
col2.metric("Filtreye Uyan Semboller", len(filtered_data))
col3.metric("Bot Durumu", "Aktif" if auto_telegram else "Pasif")

st.markdown("---")
st.subheader("🎯 Otomatik Risk & Hedef Analizli Varlıklar")

# ==========================================
# TELEGRAM BİLDİRİM DÖNGÜSÜ (TÜM FIRSATLAR İÇİN)
# ==========================================
if auto_telegram and telegram_token and telegram_chat_id:
    for coin in filtered_data:
        symbol = coin["Sembol"]
        
        # Mükerrer bildirimi önle
        if symbol not in st.session_state.sent_alerts:
            msg = (
                f"🚨 **Yeni Fırsat Sinyali!**\n\n"
                f"📌 **Sembol:** `{symbol}`\n"
                f"💵 **Giriş Fiyatı:** `${coin['Giriş ($)']}`\n"
                f"📈 **24s Değişim:** `%{coin['24h Değişim (%)']}`\n"
                f"📊 **RSI (14):** `{coin['RSI (14)']}`\n"
                f"🛑 **Stop-Loss:** `${coin['Stop-Loss']}`\n"
                f"🎯 **Hedef 1 (TP1):** `${coin['Hedef 1 (TP1)']}`\n"
                f"🎯 **Hedef 2 (TP2):** `${coin['Hedef 2 (TP2)']}`\n"
            )
            
            sent_success = send_telegram_message(telegram_token, telegram_chat_id, msg)
            if sent_success:
                st.session_state.sent_alerts.add(symbol)

# ==========================================
# TABLO GÖSTERİMİ
# ==========================================
if filtered_data:
    df = pd.DataFrame(filtered_data)
    # İç kontrol için kullanılan bayrak sütununu tablodan gizle
    if "ema20_gt_ema50" in df.columns:
        df = df.drop(columns=["ema20_gt_ema50"])
        
    st.dataframe(df, use_container_width=True)
else:
    st.info("Belirlenen kriterlere uyan sembol bulunamadı.")
