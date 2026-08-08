import time
from threading import Thread
import pandas as pd
import requests
import streamlit as st

# Page Configuration
st.set_page_config(page_title="Crypto Scanner & Telegram Bot", layout="wide")

# --- SIDEBAR: TELEGRAM VE FİLTRE AYARLARI ---
st.sidebar.header("⚙️ Bot & Filtre Ayarları")
TELEGRAM_BOT_TOKEN = st.sidebar.text_input(
    "Telegram Bot Token", type="password"
)
TELEGRAM_CHAT_ID = st.sidebar.text_input(
    "Telegram Kanal/Chat ID", value="@kanal_adi"
)

min_volume_m = st.sidebar.number_input(
    "Minimum 24h Hacim (Milyon $)", value=50, step=10
)
min_change_pct = st.sidebar.number_input(
    "Minimum Değişim (%)", value=5.0, step=0.5
)
scan_interval = st.sidebar.slider(
    "Tarama Sıklığı (Saniye)", min_value=10, max_value=300, value=60
)

bot_active = st.sidebar.checkbox("🤖 Telegram Bildirimlerini Aktif Et")


# --- TELEGRAM MESAJ GÖNDERME FONKSİYONU ---
def send_telegram_message(token, chat_id, message):
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Telegram Hatası: {e}")


# --- PİYASA VERİSİ ÇEKME FONKSİYONU ---
@st.cache_data(ttl=15)  # 15 saniyede bir veriyi tazele
def fetch_market_data():
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            df = pd.DataFrame(response.json())
            # Sadece USDT çiftlerini al
            df = df[df["symbol"].str.endswith("USDT")].copy()
            # Sayısal dönüştürmeler
            df["lastPrice"] = df["lastPrice"].astype(float)
            df["priceChangePercent"] = df["priceChangePercent"].astype(float)
            df["quoteVolume"] = (
                df["quoteVolume"].astype(float) / 1_000_000
            )  # Milyon $
            return df
    except Exception as e:
        st.error(f"Veri çekme hatası: {e}")
    return pd.DataFrame()


# --- ANA EKRAN (DASHBOARD) ---
st.title("📊 Kripto Piyasası Taraması & Sinyal Paneli")

df = fetch_market_data()

if not df.empty:
    # Filtreleme
    filtered_df = df[
        (df["quoteVolume"] >= min_volume_m)
        & (df["priceChangePercent"].abs() >= min_change_pct)
    ].sort_values(by="priceChangePercent", ascending=False)

    # Özet Metrikler
    col1, col2, col3 = st.columns(3)
    col1.metric("Taranan Toplam Çift", len(df))
    col2.metric("Kriterlere Uyan Coin Sayısı", len(filtered_df))
    col3.metric("Status", "Aktif Çalışıyor" if bot_active else "Duraklatıldı")

    # Tablo Gösterimi
    st.subheader("🎯 Kriterlere Uyan Varlıklar")
    st.dataframe(
        filtered_df[["symbol", "lastPrice", "priceChangePercent", "quoteVolume"]],
        column_config={
            "symbol": "Sembol",
            "lastPrice": st.column_config.NumberColumn(
                "Fiyat ($)", format="$%.4f"
            ),
            "priceChangePercent": st.column_config.NumberColumn(
                "24h Değişim (%)", format="%.2f%%"
            ),
            "quoteVolume": st.column_config.NumberColumn(
                "24h Hacim (M$)", format="$%.2fM"
            ),
        },
        use_container_width=True,
    )
else:
    st.warning("Piyasa verileri yükleniyor veya çekilemedi...")


# --- ARKA PLAN TELEGRAM DÖNGÜSÜ (Thread) ---
def telegram_worker():
    sent_signals = set()  # Tekrar eden sinyalleri engellemek için
    while True:
        if bot_active and TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            data = fetch_market_data()
            if not data.empty:
                matches = data[
                    (data["quoteVolume"] >= min_volume_m)
                    & (data["priceChangePercent"].abs() >= min_change_pct)
                ]

                for _, row in matches.iterrows():
                    symbol = row["symbol"]
                    # Aynı coin için kısa süre içinde tekrar mesaj atmaması için kontrol
                    if symbol not in sent_signals:
                        msg = (
                            f"🚨 **TRADING FIRSATI (Streamlit)**\n\n"
                            f"🪙 **Varlık:** #{symbol}\n"
                            f"💵 **Fiyat:** ${row['lastPrice']}\n"
                            f"📊 **24h Değişim:** %{row['priceChangePercent']:.2f}\n"
                            f"💰 **24h Hacim:** ${row['quoteVolume']:.1f}M USDT\n"
                        )
                        send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, msg
                        )
                        sent_signals.add(symbol)

        time.sleep(scan_interval)


# Arka plan thread'ini başlat (Sadece bir kez çalışmasını sağla)
if "thread_started" not in st.session_state:
    t = Thread(target=telegram_worker, daemon=True)
    t.start()
    st.session_state["thread_started"] = True
