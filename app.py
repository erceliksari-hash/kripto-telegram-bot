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
# HELPERS
# ───────────────────────────────────────────────
def escape_telegram_markdown(text: str) -> str:
    """
    Telegram 'Markdown' parse_mode icin ozel karakterleri escape eder.
    """
    escape_chars = r"\_*[]()~`>#+-=|{}.!"
    for ch in escape_chars:
        text = text.replace(ch, "\\" + ch)
    return text


def fetch_bybit_tickers():
    """
    Bybit V5 API'den USDT perpetual ticker verilerini ceker.
    Returns: (DataFrame, error_message or None)
    """
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
        return pd.DataFrame(), "Bybit API zaman asimina ugradi. Lutfen tekrar deneyin."
    except requests.exceptions.ConnectionError:
        return pd.DataFrame(), "Bybit API'ye baglanilamadi. Internet baglantinizi kontrol edin."
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

    # Sadece USDT ciftleri
    df = df[df["symbol"].astype(str).str.endswith("USDT")].copy()

    if df.empty:
        return pd.DataFrame(), "USDT cifti bulunamadi."

    # Sayisal donusumler
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

    # Yuzde formatina cevir
    df["priceChangePercent"] = df["priceChangePercent"] * 100

    # Hacmi milyon $'a cevir
    df["quoteVolume"] = df["quoteVolume"] / 1_000_000

    return df[["symbol", "lastPrice", "priceChangePercent", "quoteVolume"]].copy(), None


# ───────────────────────────────────────────────
# TELEGRAM
# ───────────────────────────────────────────────
def send_telegram_message(token, chat_id, message):
    """Telegram bot uzerinden mesaj gonderir. Basari durumunu dondurur."""
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
class TelegramWorker:
    """
    Arka plan thread'i olarak calisan sinyal gonderici.
    Streamlit session_state uzerinden konfigurasyonu okur.
    """

    COOLDOWN_SECONDS = 1800  # 30 dakika
    SENT_SIGNALS_MAX_SIZE = 5000

    def __init__(self):
        self._thread = None
        self._lock = Lock()
        self._sent_signals = {}
        self._running = False

    def start(self):
        """Worker thread'ini baslatir (idempotent)."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._running = True
            self._thread = Thread(target=self._run, daemon=True, name="TelegramWorker")
            self._thread.start()

    def _cleanup_old_signals(self):
        """Bellek sizintisini onlemek icin eski sinyalleri temizler."""
        now = time.time()
        cutoff = now - self.COOLDOWN_SECONDS
        expired = [sym for sym, ts in self._sent_signals.items() if ts < cutoff]
        for sym in expired:
            del self._sent_signals[sym]

        # Hard limit
        if len(self._sent_signals) > self.SENT_SIGNALS_MAX_SIZE:
            sorted_items = sorted(self._sent_signals.items(), key=lambda x: x[1])
            to_remove = len(sorted_items) - self.SENT_SIGNALS_MAX_SIZE
            for sym, _ in sorted_items[:to_remove]:
                del self._sent_signals[sym]

    def _run(self):
        """Ana dongu."""
        while True:
            # Streamlit session_state'den config oku
            cfg = st.session_state.get("bot_config", {})
            active = cfg.get("active", False)
            token = cfg.get("token", "")
            chat_id = cfg.get("chat_id", "")
            interval = cfg.get("interval", 60)

            if not (active and token and chat_id):
                time.sleep(interval)
                continue

            df, err = fetch_bybit_tickers()

            if err or df.empty:
                time.sleep(interval)
                continue

            min_vol = cfg.get("min_volume", 10.0)
            min_chg = cfg.get("min_change", 2.0)

            matches = df[
                (df["quoteVolume"] >= min_vol)
                & (df["priceChangePercent"].abs() >= min_chg)
            ]

            now = time.time()

            for _, row in matches.iterrows():
                sym = str(row["symbol"])

                last_sent = self._sent_signals.get(sym, 0)
                if (now - last_sent) <= self.COOLDOWN_SECONDS:
                    continue

                safe_sym = escape_telegram_markdown(sym)
                direction = "🟢 YUKARI" if row["priceChangePercent"] >= 0 else "🔴 ASAGI"
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

                if send_telegram_message(token, chat_id, msg):
                    self._sent_signals[sym] = now

            self._cleanup_old_signals()
            time.sleep(interval)


# ───────────────────────────────────────────────
# STREAMLIT UI
# ───────────────────────────────────────────────
def init_session_state():
    """Session state degiskenlerini baslatir."""
    defaults = {
        "bot_config": {
            "active": False,
            "token": "",
            "chat_id": "",
            "min_volume": 10.0,
            "min_change": 2.0,
            "interval": 60,
        },
        "last_scan_time": None,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def render_sidebar():
    """Sidebar'i render eder ve config sozlugunu dondurur."""
    st.sidebar.header("⚙️ Bot & Filtre Ayarlari")

    # Secrets'ten varsayilan degerler
    default_token = ""
    default_chat_id = ""
    try:
        default_token = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
        default_chat_id = st.secrets.get("TELEGRAM_CHAT_ID", "")
    except Exception:
        pass

    # Onceki degerleri session_state'ten al
    prev_cfg = st.session_state.get("bot_config", {})

    token = st.sidebar.text_input(
        "Telegram Bot Token",
        value=prev_cfg.get("token") or default_token,
        type="password",
        key="input_token",
    )
    chat_id = st.sidebar.text_input(
        "Telegram Kanal/Chat ID",
        value=prev_cfg.get("chat_id") or default_chat_id,
        key="input_chat_id",
    )

    min_vol = st.sidebar.number_input(
        "Minimum 24h Hacim (Milyon $)",
        min_value=0.0,
        value=float(prev_cfg.get("min_volume", 10.0)),
        step=5.0,
        key="input_min_vol",
    )

    min_chg = st.sidebar.number_input(
        "Minimum Degisim (%)",
        min_value=0.0,
        value=float(prev_cfg.get("min_change", 2.0)),
        step=0.5,
        key="input_min_chg",
    )

    interval = st.sidebar.slider(
        "Tarama Sikligi (Saniye)",
        min_value=10,
        max_value=300,
        value=int(prev_cfg.get("interval", 60)),
        step=10,
        key="input_interval",
    )

    bot_active = st.sidebar.checkbox(
        "🤖 Telegram Bildirimlerini Aktif Et",
        value=bool(prev_cfg.get("active", False)),
        key="input_active",
    )

    return {
        "active": bot_active,
        "token": token.strip(),
        "chat_id": chat_id.strip(),
        "min_volume": float(min_vol),
        "min_change": float(min_chg),
        "interval": int(interval),
    }


# ───────────────────────────────────────────────
# MAIN
# ───────────────────────────────────────────────
def main():
    init_session_state()

    # Sidebar render et ve config'i session_state'e kaydet
    cfg = render_sidebar()
    st.session_state["bot_config"] = cfg

    # Background worker'i baslat (idempotent)
    worker = TelegramWorker()
    worker.start()

    # ── DASHBOARD ──
    st.title("📊 Kripto Piyasasi Taramasi & Sinyal Paneli")

    col_btn, col_info = st.columns([1, 4])
    with col_btn:
        if st.button("🔄 Verileri Simdi Yenile", use_container_width=True):
            st.cache_data.clear()
            st.session_state["last_scan_time"] = datetime.now(timezone.utc)

    # Verileri cek
    @st.cache_data(ttl=15, show_spinner="Veriler yukleniyor...")
    def _cached_fetch():
        return fetch_bybit_tickers()

    df, err_msg = _cached_fetch()

    if err_msg:
        st.error("❌ " + err_msg)
        st.stop()

    if df.empty:
        st.warning("⚠️ API verisi alindi fakat islenecek USDT cifti bulunamadi.")
        st.stop()

    # Filtrele
    filtered = df[
        (df["quoteVolume"] >= cfg["min_volume"])
        & (df["priceChangePercent"].abs() >= cfg["min_change"])
    ].sort_values(by="priceChangePercent", ascending=False)

    # Metrikler
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Taranan Sembol", len(df))
    c2.metric("Filtreye Uyan", len(filtered))
    c3.metric("Bot Durumu", "🟢 Aktif" if cfg["active"] else "🔴 Pasif")
    last_scan = st.session_state.get("last_scan_time")
    c4.metric(
        "Son Tarama",
        last_scan.strftime("%H:%M:%S") if last_scan else "—",
    )

    st.divider()

    # Tablo
    st.subheader("🎯 Filtreye Uyan Varliklar")

    if not filtered.empty:
        st.dataframe(
            filtered,
            column_config={
                "symbol": st.column_config.TextColumn("Sembol", width="small"),
                "lastPrice": st.column_config.NumberColumn(
                    "Fiyat ($)", format="$%.4f", width="medium"
                ),
                "priceChangePercent": st.column_config.NumberColumn(
                    "24h Degisim (%)",
                    format="%.2f%%",
                    width="medium",
                ),
                "quoteVolume": st.column_config.NumberColumn(
                    "24h Hacim (M$)", format="$%.2fM", width="medium"
                ),
            },
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info(
            "ℹ️ Belirlenen filtre kriterlerine uyan coin bulunamadi. "
            "Filtre degerlerini dusurmeyi deneyin."
        )


if __name__ == "__main__":
    main()
