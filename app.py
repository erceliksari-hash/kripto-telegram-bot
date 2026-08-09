import time
from threading import Thread, Lock
import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="Crypto Scanner & Telegram Bot", layout="wide"
)

# Secrets veya Varsayılan Tanımlamalar
def get_secret(section, key, default=""):
    try:
        return st.secrets[section][key]
    except Exception:
        try:
            return st.secrets.get(key, default)
        except Exception:
            return default

DEFAULT_TOKEN = get_secret("telegram", "bot_token", "8736398780:AAFWxPurStPIts--TYjHZccPpjVNnIk02Sg")
DEFAULT_CHAT_ID = get_secret("telegram", "chat_id", "-1004436877206")

# Thread'ler arası güvenli veri paylaşımı için Global Konfigürasyon
GLOBAL_CONFIG = {
    "active": False,
    "token": DEFAULT_TOKEN,
    "chat_id": DEFAULT_CHAT_ID,
    "min_volume": 10.0,
    "min_change": 2.0,
    "interval": 60,
}
config_lock = Lock()


# --- SIDEBAR & FILTERS ---
st.sidebar.header("⚙️ Bot & Filtre Ayarları")

TELEGRAM_BOT_TOKEN = st.sidebar.text_input(
    "Telegram Bot Token", value=DEFAULT_TOKEN, type="password"
)
TELEGRAM_CHAT_ID = st.sidebar.text_input(
    "Telegram Kanal/Chat ID", value=DEFAULT_CHAT_ID
)

min_volume_m = st.sidebar.number_input(
    "Minimum 24h Hacim (Milyon $)", value=10, step=5
)
min_change_pct = st.sidebar.number_input(
    "Minimum Değişim (%)", value=2.0, step=0.5
)
scan_interval = st.sidebar.slider(
    "Tarama Sıklığı (Saniye)", min_value=10, max_value=300, value=60
)

bot_active = st.sidebar.checkbox("🤖 Telegram Bildirimlerini Aktif Et")

with config_lock:
    GLOBAL_CONFIG["active"] = bot_active
    GLOBAL_CONFIG["token"] = TELEGRAM_BOT_TOKEN
    GLOBAL_CONFIG["chat_id"] = TELEGRAM_CHAT_ID
    GLOBAL_CONFIG["min_volume"] = float(min_volume_m)
    GLOBAL_CONFIG["min_change"] = float(min_change_pct)
    GLOBAL_CONFIG["interval"] = int(scan_interval)


# --- TELEGRAM MESAJ ---
def send_telegram_message(token, chat_id, message):
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Telegram Hatası: {e}")


# --- KESİNTİSİZ VERİ ÇEKME FONKSİYONU ---
def _raw_fetch_bybit_data():
    endpoints = [
        "https://api.bybit.com/v5/market/tickers?category=linear",
        "https://api.bytick.com/v5/market/tickers?category=linear",
        "https://api-testnet.bybit.com/v5/market/tickers?category=linear"
    ]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    }

    res = None
    last_error = ""

    # Katman 1: Standart requests + Custom Headers
    for url in endpoints:
        try:
            r = requests.get(url, headers=headers, timeout=6)
            if r.status_code == 200:
                res = r
                break
        except Exception as e:
            last_error = str(e)

    # Katman 2: curl_cffi (TLS Impersonation)
    if res is None:
        try:
            from curl_cffi import requests as curl_requests
            for url in endpoints:
                r = curl_requests.get(url, impersonate="chrome120", timeout=8)
                if r.status_code == 200:
                    res = r
                    break
        except Exception as e:
            last_error = str(e)

    # Katman 3: cloudscraper
    if res is None:
        try:
            import cloudscraper
            scraper = cloudscraper.create_scraper()
            for url in endpoints:
                r = scraper.get(url, timeout=8)
                if r.status_code == 200:
                    res = r
                    break
        except Exception as e:
            last_error = str(e)

    if res is None:
        return pd.DataFrame(), f"Tüm API kanalları başarısız oldu. Son Hata: {last_error}"

    try:
        data = res.json()
        if data.get("retCode") != 0:
            return pd.DataFrame(), f"Bybit Hata Kodu: {data.get('retCode')} - {data.get('retMsg')}"

        ticker_list = data.get("result", {}).get("list", [])
        if not ticker_list:
            return pd.DataFrame(), "API başarılı yanıt verdi ancak sembol listesi boş."

        df = pd.DataFrame(ticker_list)
        
        # Sadece USDT perpetual (Vadeli) çiftleri al
        df = df[df["symbol"].str.endswith("USDT")].copy()

        # Sayısal dönüşümler
        df["lastPrice"] = pd.to_numeric(df["lastPrice"], errors="coerce")
        df["priceChangePercent"] = pd.to_numeric(df["price24hPcnt"], errors="coerce") * 100
        df["quoteVolume"] = pd.to_numeric(df["turnover24h"], errors="coerce") / 1_000_000

        df = df.dropna(subset=["lastPrice", "priceChangePercent", "quoteVolume"])
        return df[["symbol", "lastPrice", "priceChangePercent", "quoteVolume"]], None

    except Exception as e:
        return pd.DataFrame(), f"JSON Format/Veri İşleme Hatası: {str(e)}"


# Streamlit arayüzü için önbellekli versiyon
@st.cache_data(ttl=15, show_spinner=False)
def fetch_market_data_cached():
    return _raw_fetch_bybit_data()


# --- DASHBOARD ---
st.title("📊 Kripto Piyasası Taraması & Sinyal Paneli")

col_b1, col_b2 = st.columns([1, 4])
with col_b1:
    if st.button("🔄 Verileri Şimdi Yenile"):
        st.cache_data.clear()

df, err_msg = fetch_market_data_cached()

if err_msg:
    st.error(f"❌ Veri Çekme Hatası: {err_msg}")

if not df.empty:
    filtered_df = df[
        (df["quoteVolume"] >= min_volume_m)
        & (df["priceChangePercent"].abs() >= min_change_pct)
    ].sort_values(by="priceChangePercent", ascending=False)

    col1, col2, col3 = st.columns(3)
    col1.metric("Taranan Sembol Sayısı", len(df))
    col2.metric("Filtreye Uyan Semboller", len(filtered_df))
    col3.metric("Bot Durumu", "Aktif" if bot_active else "Pasif")

    st.subheader("🎯 Filtreye Uyan Varlıklar")
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
    if not err_msg:
        st.warning(
            "⚠️ API verisi başarıyla çekildi ancak filtre kriterlerine (Hacim / Değişim %) uyan coin bulunamadı."
        )


# --- BACKGROUND WORKER ---
def telegram_worker():
    sent_signals = {}
    cooldown_seconds = 1800

    while True:
        with config_lock:
            cfg = GLOBAL_CONFIG.copy()

        if cfg["active"] and cfg["token"] and cfg["chat_id"]:
            data, _ = _raw_fetch_bybit_data()

            if not data.empty:
                matches = data[
                    (data["quoteVolume"] >= cfg["min_volume"])
                    & (data["priceChangePercent"].abs() >= cfg["min_change"])
                ]

                current_time = time.time()
                for _, row in matches.iterrows():
                    sym = row["symbol"]

                    if (
                        sym not in sent_signals
                        or (current_time - sent_signals[sym]) > cooldown_seconds
                    ):
                        safe_sym = sym.replace("_", "\\_")
                        msg = (
                            f"🚨 *KRİPTO SİNYALİ*\n\n"
                            f"🪙 *Sembol:* #{safe_sym}\n"
                            f"💵 *Fiyat:* ${row['lastPrice']:.4f}\n"
                            f"📊 *Değişim:* %{row['priceChangePercent']:.2f}\n"
                            f"💰 *Hacim:* ${row['quoteVolume']:.1f}M\n"
                        )
                        send_telegram_message(cfg["token"], cfg["chat_id"], msg)
                        sent_signals[sym] = current_time

        time.sleep(cfg.get("interval", 60))


@st.cache_resource
def start_background_worker():
    t = Thread(target=telegram_worker, daemon=True)
    t.start()
    return True


start_background_worker()
