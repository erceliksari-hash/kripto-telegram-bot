import time
from threading import Thread, Lock
from datetime import datetime, timezone

import pandas as pd
import requests
import streamlit as st

# ───────────────────────────────────────────────
# PAGE CONFIG
# ───────────────────────────────────────────────
st.set_page_config(
    page_title="Crypto Scanner & Telegram Bot",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ───────────────────────────────────────────────
# GLOBAL CONFIG (Thread-safe)
# ───────────────────────────────────────────────
GLOBAL_CONFIG = {
    "active": False,
    "token": "",
    "chat_id": "",
    "min_volume": 10.0,
    "min_change": 2.0,
    "interval": 60,
}
config_lock = Lock()

# Worker thread singleton kontrolu
_worker_started = False
_worker_lock = Lock()


# ───────────────────────────────────────────────
# HELPERS
# ───────────────────────────────────────────────
def escape_telegram_markdown(text):
    """Telegram Markdown parse_mode icin ozel karakterleri escape eder."""
    escape_chars = r"\_*[]()~`>#+-=|{}.!"
    for ch in escape_chars:
        text = text.replace(ch, "\\" + ch)
    return text


def fetch_bybit_tickers():
    """Bybit V5 API'den USDT perpetual ticker verilerini ceker."""
    url = "https://api.bybit.com/v5/market/tickers"
    params = {"category": "linear", "limit": 1000}
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        return pd.DataFrame(), "Bybit API zaman asimina ugradi."
    except requests.exceptions.ConnectionError:
        return pd.DataFrame(), "Bybit API'ye baglanilamadi."
    except requests.exceptions.HTTPError as e:
        return pd.DataFrame(), f"Bybit API HTTP Hatasi: {e.response.status_code}"
    except requests.exceptions.RequestException as e:
        return pd.DataFrame(), f"Istek Hatasi: {str(e)}"

    try:
        data = resp.json()
    except ValueError:
        return pd.DataFrame(), "API yaniti JSON formatinda degil."

    ret_code = data.get("retCode")
    if ret_code not in (0, None):
        ret_msg = data.get("retMsg", "Bilinmeyen hata")
        return pd.DataFrame(), f"Bybit API Hatasi [{ret_code}]: {ret_msg}"

    ticker_list = data.get("result", {}).get("list", [])
    if not ticker_list:
        return pd.DataFrame(), "API yanit verdi fakat liste bos dondu."

    df = pd.DataFrame(ticker_list)
    df = df[df["symbol"].astype(str).str.endswith("USDT")].copy()

    if df.empty:
        return pd.DataFrame(), "USDT cifti bulunamadi."

    numeric_cols = {
        "lastPrice": "lastPrice",
        "price24hPcnt": "priceChangePercent",
        "turnover24h": "quoteVolume",
    }

    for src, dst in numeric_cols.items():
        if src in df.columns:
            df[dst] = pd.to_numeric(df[src], errors="coerce")
        else:
            df[dst] = pd.NA

    df = df.dropna(subset=["lastPrice", "priceChangePercent", "quoteVolume"])
    df["priceChangePercent"] = df["priceChangePercent"] * 100
    df["quoteVolume"] = df["quoteVolume"] / 1_000_000

    return df[["symbol", "lastPrice", "priceChangePercent", "quoteVolume"]].copy(), None


# ───────────────────────────────────────────────
# TELEGRAM
# ───────────────────────────────────────────────
def send_telegram_message(token, chat_id, message):
    """Telegram bot uzerinden mesaj gonderir."""
    if not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    try:
        resp = requests.post(url, json=payload, timeout=8)
        resp.raise_for_status()
        return True
    except requests.exceptions.RequestException:
        return False


# ───────────────────────────────────────────────
# BACKGROUND WORKER
# ───────────────────────────────────────────────
def telegram_worker():
    """Arka plan thread'i - Streamlit API'si kullanmaz!"""
    sent_signals = {}
    cooldown_seconds = 1800  # 30 dakika
    cleanup_counter = 0

    while True:
        with config_lock:
            cfg = dict(GLOBAL_CONFIG)

        interval = cfg.get("interval", 60)

        if not (cfg["active"] and cfg["token"] and cfg["chat_id"]):
            time.sleep(interval)
            continue

        df, err = fetch_bybit_tickers()

        if err or df.empty:
            time.sleep(interval)
            continue

        min_vol = cfg["min_volume"]
        min_chg = cfg["min_change"]

        matches = df[
            (df["quoteVolume"] >= min_vol)
            & (df["priceChangePercent"].abs() >= min_chg)
        ]

        now = time.time()

        for _, row in matches.iterrows():
            sym = str(row["symbol"])

            last_sent = sent_signals.get(sym, 0)
            if (now - last_sent) <= cooldown_seconds:
                continue

            safe_sym = escape_telegram_markdown(sym)
            direction = "YUKARI" if row["priceChangePercent"] >= 0 else "ASAGI"
            price = float(row["lastPrice"])
            change = float(row["priceChangePercent"])
            volume = float(row["quoteVolume"])
            time_str = datetime.now(timezone.utc).strftime("%H:%M UTC")

            msg = (
                "🚨 *KRIPTO SINYALI* " + direction + "\n\n"
                "🪙 *Sembol:* `#" + safe_sym + "`\n"
                "💵 *Fiyat:* `$" + f"{price:.4f}" + "`\n"
                "📊 *Degisim:* `%" + f"{change:.2f}" + "`\n"
                "💰 *Hacim:* `$" + f"{volume:.1f}M" + "`\n"
                "⏰ *Zaman:* `" + time_str + "`"
            )

            if send_telegram_message(cfg["token"], cfg["chat_id"], msg):
                sent_signals[sym] = now

        # Bellek temizligi (her 10 dongude bir)
        cleanup_counter += 1
        if cleanup_counter >= 10:
            cutoff = now - cooldown_seconds
            expired = [s for s, ts in sent_signals.items() if ts < cutoff]
            for s in expired:
                del sent_signals[s]
            # Hard limit: 5000 kayit
            if len(sent_signals) > 5000:
                sorted_items = sorted(sent_signals.items(), key=lambda x: x[1])
                to_remove = len(sorted_items) - 5000
                for s, _ in sorted_items[:to_remove]:
                    del sent_signals[s]
            cleanup_counter = 0

        time.sleep(interval)


def start_worker_once():
    """Worker thread'ini sadece bir kez baslatir."""
    global _worker_started
    with _worker_lock:
        if not _worker_started:
            t = Thread(target=telegram_worker, daemon=True, name="TelegramWorker")
            t.start()
            _worker_started = True


# ───────────────────────────────────────────────
# STREAMLIT UI
# ───────────────────────────────────────────────
def get_secret(key, default=""):
    """Secrets'ten guvenli sekilde deger okur."""
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


# Sidebar
st.sidebar.header("⚙️ Bot & Filtre Ayarlari")

default_token = get_secret("TELEGRAM_BOT_TOKEN", "")
default_chat_id = get_secret("TELEGRAM_CHAT_ID", "")

TELEGRAM_BOT_TOKEN = st.sidebar.text_input(
    "Telegram Bot Token", value=default_token, type="password"
)
TELEGRAM_CHAT_ID = st.sidebar.text_input(
    "Telegram Kanal/Chat ID", value=default_chat_id
)

min_volume_m = st.sidebar.number_input(
    "Minimum 24h Hacim (Milyon $)", value=10, step=5
)
min_change_pct = st.sidebar.number_input(
    "Minimum Degisim (%)", value=2.0, step=0.5
)
scan_interval = st.sidebar.slider(
    "Tarama Sikligi (Saniye)", min_value=10, max_value=300, value=60
)

bot_active = st.sidebar.checkbox("🤖 Telegram Bildirimlerini Aktif Et")

# Global config'i guncelle
with config_lock:
    GLOBAL_CONFIG["active"] = bot_active
    GLOBAL_CONFIG["token"] = TELEGRAM_BOT_TOKEN
    GLOBAL_CONFIG["chat_id"] = TELEGRAM_CHAT_ID
    GLOBAL_CONFIG["min_volume"] = float(min_volume_m)
    GLOBAL_CONFIG["min_change"] = float(min_change_pct)
    GLOBAL_CONFIG["interval"] = int(scan_interval)

# Worker'i baslat (sadece bir kez)
start_worker_once()


# ───────────────────────────────────────────────
# DASHBOARD
# ───────────────────────────────────────────────
st.title("📊 Kripto Piyasasi Taramasi & Sinyal Paneli")

col_b1, col_b2 = st.columns([1, 4])
with col_b1:
    if st.button("🔄 Verileri Simdi Yenile"):
        st.cache_data.clear()


@st.cache_data(ttl=15, show_spinner=False)
def fetch_market_data_cached():
    return fetch_bybit_tickers()


df, err_msg = fetch_market_data_cached()

if err_msg:
    st.error("❌ " + err_msg)

if not df.empty:
    filtered_df = df[
        (df["quoteVolume"] >= min_volume_m)
        & (df["priceChangePercent"].abs() >= min_change_pct)
    ].sort_values(by="priceChangePercent", ascending=False)

    col1, col2, col3 = st.columns(3)
    col1.metric("Taranan Sembol Sayisi", len(df))
    col2.metric("Filtreye Uyan Semboller", len(filtered_df))
    col3.metric("Bot Durumu", "Aktif" if bot_active else "Pasif")

    st.subheader("🎯 Filtreye Uyan Varliklar")
    st.dataframe(
        filtered_df[["symbol", "lastPrice", "priceChangePercent", "quoteVolume"]],
        column_config={
            "symbol": "Sembol",
            "lastPrice": st.column_config.NumberColumn(
                "Fiyat ($)", format="$%.4f"
            ),
            "priceChangePercent": st.column_config.NumberColumn(
                "24h Degisim (%)", format="%.2f%%"
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
            "⚠️ API verisi alindi fakat belirlenen filtre kriterlerine uyan coin bulunamadi."
        )
