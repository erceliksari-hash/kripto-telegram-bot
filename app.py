import streamlit as st
import pandas as pd
import requests

# ==========================================
# PAGE CONFIG
# ==========================================
st.set_page_config(
    page_title="Crypto Scanner & Quantfury Analiz Paneli",
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

# Session State Initializations
if "sent_alerts" not in st.session_state:
    st.session_state.sent_alerts = set()

# ==========================================
# SIDEBAR / FILTRELER & AYARLAR
# ==========================================
st.sidebar.title("⚙️ Bot & Genel Ayarlar")

telegram_token = st.sidebar.text_input("Telegram Bot Token", type="password")
telegram_chat_id = st.sidebar.text_input("Telegram Kanal/Chat ID")
refresh_interval = st.sidebar.slider("Tarama Sıklığı (Saniye)", min_value=10, max_value=300, value=60)
auto_telegram = st.sidebar.checkbox("Otomatik Telegram Bildirimlerini Aktif Et", value=True)

if st.sidebar.button("🔄 Bildirim Geçmişini Sıfırla"):
    st.session_state.sent_alerts.clear()
    st.sidebar.success("Bildirim geçmişi temizlendi!")

st.sidebar.markdown("---")
st.sidebar.title("🚀 Quantfury / Özel İzleme Listesi")
quantfury_raw = st.sidebar.text_area(
    "Quantfury Coin Listesi (Virgülle Ayırın):",
    value="BTCUSDT, ETHUSDT, SOLUSDT, AVAXUSDT, XRPUSDT, LINKUSDT, ADAUSDT, DOTUSDT, NEARUSDT, LTCUSDT, DOGEUSDT, SHIBUSDT"
)
quantfury_list = [c.strip().upper() for c in quantfury_raw.split(",") if c.strip()]

st.sidebar.markdown("---")
st.sidebar.title("🔍 Temel & Gösterge Filtreleri")

# TEKNİK GÖSTERGE VE TEMEL FİLTRELER
min_volume = st.sidebar.number_input("Minimum 24h Hacim (Milyon $)", value=10.0)
max_rsi = st.sidebar.slider("Maksimum RSI (14)", min_value=10, max_value=100, value=60)
min_change = st.sidebar.number_input("Minimum 24s Değişim (%)", value=0.0)

# ==========================================
# VERİ VERİ ÇEKME & TEKNİK FİLTRE HESAPLAMA
# ==========================================
def fetch_and_filter_okx_data(min_vol, rsi_limit, min_chg):
    """
    OKX piyasa verilerini çeker ve sol panellerdeki TEKNİK GÖSTERGE filtrelerine göre süzer.
    """
    # Örnek/Ham piyasa verileri (Gerçek projede OKX API / CCXT verisi)
    raw_market_data = [
        {"symbol": "CAPUSDT", "price": 0.0383, "change": 3.68, "volume_m": 711.70, "rsi": 58.8, "stop_loss": 0.0362, "tp1": 0.0414, "r1": 0.0389, "r2": 0.0394},
        {"symbol": "IRYSUSDT", "price": 0.0163, "change": 2.58, "volume_m": 52.74, "rsi": 46.5, "stop_loss": 0.0160, "tp1": 0.0168, "r1": 0.0164, "r2": 0.0165},
        {"symbol": "0GUSDT", "price": 0.1541, "change": 2.32, "volume_m": 20.75, "rsi": 44.3, "stop_loss": 0.1504, "tp1": 0.1596, "r1": 0.1554, "r2": 0.1565},
        {"symbol": "BTCUSDT", "price": 65000.0, "change": -1.2, "volume_m": 1200.0, "rsi": 65.0, "stop_loss": 64000.0, "tp1": 67000.0, "r1": 66000.0, "r2": 66500.0}, # RSI > 60 elenecek
    ]
    
    total_symbols = 423
    filtered_opportunities = []

    # 🎯 TEKNİK FİLTRE HESAPLAMASI
    for coin in raw_market_data:
        # Filtre Şartları: Hacim >= Min Hacim AND RSI <= RSI Limit AND Değişim >= Min Değişim
        if (coin["volume_m"] >= min_vol) and (coin["rsi"] <= rsi_limit) and (coin["change"] >= min_chg):
            filtered_opportunities.append(coin)

    return filtered_opportunities, total_symbols

# ==========================================
# ANA SAYFA VE ARAYÜZ
# ==========================================
st.title("📊 Crypto Scanner & Quantfury Analiz Paneli")

if st.button("🔄 Verileri Şimdi Yenile"):
    st.rerun()

# Teknik Gösterge Filtrelerini Veri Motoruna Gönderiyoruz
all_opportunities, total_symbols = fetch_and_filter_okx_data(min_volume, max_rsi, min_change)

# Quantfury listesi eşleşmeleri
quantfury_opportunities = [item for item in all_opportunities if item["symbol"] in quantfury_list]

# Metrik Kartları
col1, col2, col3, col4 = st.columns(4)
col1.metric("Piyasadaki Toplam Sembol", total_symbols)
col2.metric("Quantfury Uygun Fırsat", len(quantfury_opportunities))
col3.metric("Tüm Piyasa Uygun Fırsat", len(all_opportunities))
col4.metric("Bot Durumu", "Aktif" if auto_telegram else "Pasif")

# ==========================================
# TELEGRAM BİLDİRİM MANTIĞI
# ==========================================
if auto_telegram and telegram_token and telegram_chat_id:
    # Filtreden geçen TÜM fırsatları döngüye alıyoruz
    for coin in all_opportunities:
        symbol = coin["symbol"]
        
        if symbol not in st.session_state.sent_alerts:
            is_qf = symbol in quantfury_list
            tag = "⚡ [Quantfury Listesi]" if is_qf else "🌐 [Genel OKX Fırsatı]"
            
            msg = (
                f"🚨 **Yeni Fırsat Sinyali!** {tag}\n\n"
                f"📌 **Sembol:** `{symbol}`\n"
                f"💵 **Giriş Fiyatı:** `${coin['price']}`\n"
                f"📈 **24s Değişim:** `%{coin['change']}`\n"
                f"📊 **RSI (14):** `{coin['rsi']}`\n"
                f"🛑 **Stop-Loss:** `${coin['stop_loss']}`\n"
                f"🎯 **Target (TP1):** `${coin['tp1']}`\n"
            )
            
            sent_success = send_telegram_message(telegram_token, telegram_chat_id, msg)
            if sent_success:
                st.session_state.sent_alerts.add(symbol)

# ==========================================
# SEKMELER VE TABLOLAR
# ==========================================
tab1, tab2 = st.tabs(["⚡ Quantfury / İzleme Listesi Fırsatları", "🌐 Tüm OKX Piyasası Fırsatları"])

with tab1:
    if quantfury_opportunities:
        df_qf = pd.DataFrame(quantfury_opportunities)
        st.dataframe(df_qf, use_container_width=True)
    else:
        st.info("Quantfury izleme listenizde filtrelere uyan fırsat bulunamadı.")

with tab2:
    st.subheader("🌍 OKX Üzerindeki Tüm Uygun Fırsatlar")
    if all_opportunities:
        df_all = pd.DataFrame(all_opportunities)
        st.dataframe(df_all, use_container_width=True)
    else:
        st.info("Piyasada belirlenen teknik filtrelere uygun fırsat bulunamadı.")
