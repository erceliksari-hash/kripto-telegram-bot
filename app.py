import time
from threading import Thread
import pandas as pd
import requests
import streamlit as st

# Page Configuration
st.set_page_config(page_title="Crypto Scanner & Telegram Bot", layout="wide")

# --- SECRETS & SIDEBAR ---
st.sidebar.header("⚙️ Bot & Filtre Ayarları")

# Streamlit Secrets'tan oku, yoksa boş string al
default_token = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
default_chat_id = st.secrets.get("TELEGRAM_CHAT_ID", "")

TELEGRAM_BOT_TOKEN = st.sidebar.text_input(
    "Telegram Bot Token", value=default_token, type="password"
)
TELEGRAM_CHAT_ID = st.sidebar.text_input(
    "Telegram Kanal/Chat ID", value=default_chat_id
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


# --- KESİNTİSİZ PİYASA VERİSİ ÇEKME FONKSİYONU (BYBIT V5 API) ---
@st.cache_data(ttl=15)
def fetch_market_data():
    # Bybit Futures API - AWS/Streamlit Cloud IP kısıtlamasına takılmaz
    url = "https://api.bybit.com/v5/market/tickers?category=linear"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
    }

    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            result = res.json().get("result", {}).get("list", [])
            if not result:
                return pd.DataFrame()

            df = pd.DataFrame(result)

            # Sadece USDT çiftlerini filtrele
            df = df[df["symbol"].str.endswith("USDT")].copy()

            # Sayısal veri dönüşümleri ve oranlamalar
            df["lastPrice"] = pd.to_numeric(df["lastPrice"], errors="coerce")

            # Bybit 24h yüzde değişimi ondalık verir (örn: 0.05 = %5)
            df["priceChangePercent"] = (
                pd.to_numeric(df["price24hPcnt"], errors="coerce") * 100
            )

            # turnover24h = 24 Saatlik Toplam Hacim (USD cinsinden) -> Milyon $'a çevrilir
            df["quoteVolume"] = (
                pd.to_numeric(df["turnover24h"], errors="coerce") / 1_000_000
            )

            # Eksik / Hatalı verileri temizle
            df = df.dropna(
                subset=["lastPrice", "priceChangePercent", "quoteVolume"]
            )

            return df[
                ["symbol", "lastPrice", "priceChangePercent", "quoteVolume"]
            ]
    except Exception as e:
        print(f"Piyasa verisi çekme hatası: {e}")

    return pd.DataFrame()


# --- ANA EKRAN (DASHBOARD) ---
st.title("📊 Kripto Piyasası Taraması & Sinyal Paneli")

# Sayfayı Manuel Yenileme Butonu
if st.button("🔄 Verileri Şimdi Yenile"):
    st.cache_data.clear()

df = fetch_market_data()

if not df.empty:
    filtered_df = df[
        (df["quoteVolume"] >= min_volume_m)
        & (df["priceChangePercent"].abs() >= min_change_pct)
    ].sort_values(by="priceChangePercent", ascending=False)

    col1, col2, col3 = st.columns(3)
    col1.metric("Taranan Toplam Çift", len(df))
    col2.metric("Kriterlere Uyan Coin Sayısı", len(filtered_df))
    col3.metric("Status", "Aktif Çalışıyor" if bot_active else "Duraklatıldı")

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
    st.error(
        "❌ Piyasa verileri çekilemedi! Bağlantı zaman aşımına uğramış olabilir."
    )
    st.info(
        "💡 Çözüm: Sayfadaki 'Verileri Şimdi Yenile' butonuna basabilir veya birkaç saniye bekleyebilirsiniz."
    )


# --- ARKA PLAN WORKER (THREAD - TELEGRAM GÖNDERİCİSİ) ---
def telegram_worker():
    sent_signals = set()
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
                    if symbol not in sent_signals:
                        msg = (
                            f"🚨 **TRADING FIRSATI (Streamlit)**\n\n"
                            f"🪙 **Varlık:** #{symbol}\n"
                            f"💵 **Fiyat:** ${row['lastPrice']:.4f}\n"
                            f"📊 **24h Değişim:** %{row['priceChangePercent']:.2f}\n"
                            f"💰 **24h Hacim:** ${row['quoteVolume']:.1f}M USDT\n"
                        )
                        send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, msg
                        )
                        sent_signals.add(symbol)

        time.sleep(scan_interval)


# Background thread'i tek bir sefer başlatma kontrolü
if "thread_started" not in st.session_state:
    t = Thread(target=telegram_worker, daemon=True)
    t.start()
    st.session_state["thread_started"] = True
