import streamlit as st
import pandas as pd
import requests
import time

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
    """Telegram API üzerinden mesaj gönderir."""
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

# Session State Initializations (Tekrarlayan bildirimleri önlemek için)
if "sent_alerts" not in st.session_state:
    st.session_state.sent_alerts = set()

# ==========================================
# SIDEBAR / GENEL AYARLAR
# ==========================================
st.sidebar.title("⚙️ Bot & Genel Ayarlar")

telegram_token = st.sidebar.text_input("Telegram Bot Token", type="password")
telegram_chat_id = st.sidebar.text_input("Telegram Kanal/Chat ID")
refresh_interval = st.sidebar.slider("Tarama Sıklığı (Saniye)", min_value=10, max_value=300, value=60)
auto_telegram = st.sidebar.checkbox("Ötotomatik Telegram Bildirimlerini Aktif Et", value=True)

# Oturum hafızasını sıfırlama butonu
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
st.sidebar.title("🔍 Temel & Hacim Filtreleri")
min_volume = st.sidebar.number_input("Minimum 24h Hacim (Milyon $)", value=10.0)

# ==========================================
# SAHTE/ÖRNEK VERİ MOTORU (Sizin veri çekme fonksiyonunuz buraya gelir)
# ==========================================
def fetch_okx_data():
    """
    Burada OKX veya CCXT kütüphanesi ile piyasadan veri çektiğinizi varsayıyoruz.
    Demo amaçlı kilit ekran görüntünüzdeki fırsatları döndürür.
    """
    # Gerçek projenizde burası OKX API'sine istek atıp teknik analiz yapar.
    all_opportunities = [
        {"symbol": "CAPUSDT", "price": 0.0383, "change": 3.68, "volume_m": 711.70, "rsi": 58.8, "stop_loss": 0.0362, "tp1": 0.0414, "r1": 0.0389, "r2": 0.0394},
        {"symbol": "IRYSUSDT", "price": 0.0163, "change": 2.58, "volume_m": 52.74, "rsi": 46.5, "stop_loss": 0.0160, "tp1": 0.0168, "r1": 0.0164, "r2": 0.0165},
        {"symbol": "0GUSDT", "price": 0.1541, "change": 2.32, "volume_m": 20.75, "rsi": 44.3, "stop_loss": 0.1504, "tp1": 0.1596, "r1": 0.1554, "r2": 0.1565},
    ]
    total_symbols = 423
    return all_opportunities, total_symbols

# ==========================================
# ANA SAYFA VE ARAYÜZ
# ==========================================
st.title("📊 Crypto Scanner & Quantfury Analiz Paneli")

if st.button("🔄 Verileri Şimdi Yenile"):
    st.rerun()

all_opportunities, total_symbols = fetch_okx_data()

# Quantfury listesi eşleşmelerini filtrele
quantfury_opportunities = [item for item in all_opportunities if item["symbol"] in quantfury_list]

# Metrik Kartları
col1, col2, col3, col4 = st.columns(4)
col1.metric("Piyasadaki Toplam Sembol", total_symbols)
col2.metric("Quantfury Uygun Fırsat", len(quantfury_opportunities))
col3.metric("Tüm Piyasa Uygun Fırsat", len(all_opportunities))
col4.metric("Bot Durumu", "Aktif" if auto_telegram else "Pasif")

# ==========================================
# TELEGRAM BİLDİRİM MANTIĞI (GÜNCELLENEN KISIM)
# ==========================================
if auto_telegram and telegram_token and telegram_chat_id:
    # 🟢 DEĞİŞİKLİK: Artık sadece quantfury_opportunities değil, all_opportunities döngüye alınıyor.
    for coin in all_opportunities:
        symbol = coin["symbol"]
        
        # Eğer bu coin daha önce bildirildiyse tekrar atma
        if symbol not in st.session_state.sent_alerts:
            # Rozet/Etiket belirleme
            is_qf = symbol in quantfury_list
            tag = "⚡ [Quantfury Listesi]" if is_qf else "🌐 [Genel OKX Fırsatı]"
            
            # Telegram Mesaj Taslağı
            msg = (
                f"🚨 **Yeni Fırsat Sinyali!** {tag}\n\n"
                f"📌 **Sembol:** `{symbol}`\n"
                f"💵 **Giriş Fiyatı:** `${coin['price']}`\n"
                f"📈 **24s Değişim:** `%{coin['change']}`\n"
                f"📊 **RSI (14):** `{coin['rsi']}`\n"
                f"🛑 **Stop-Loss:** `${coin['stop_loss']}`\n"
                f"🎯 **Target (TP1):** `${coin['tp1']}`\n"
            )
            
            # Mesajı Gönder
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
        st.info("Quantfury izleme listenizde şu an uygun fırsat bulunamadı.")

with tab2:
    st.subheader("🌍 OKX Üzerindeki Tüm Uygun Fırsatlar")
    if all_opportunities:
        df_all = pd.DataFrame(all_opportunities)
        st.dataframe(df_all, use_container_width=True)
    else:
        st.info("Piyasada kriterlere uygun fırsat bulunamadı.")
