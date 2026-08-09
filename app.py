import time
from threading import Thread, Lock
import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="Crypto Scanner & Advanced Signal Bot", layout="wide"
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

# Thread'ler arası güvenli veri paylaşımı (Optimizasyonlar eklendi)
GLOBAL_CONFIG = {
    "active": False,
    "token": DEFAULT_TOKEN,
    "chat_id": DEFAULT_CHAT_ID,
    "min_volume": 10.0,
    "min_change": 2.0,
    "rsi_min": 40,            # Optimal Momentum Giriş Sınırı
    "rsi_max": 62,            # Tepede Şişmeyi Önleme Sınırı
    "use_ema_filter": True,   # Yükselen Trend Zorunlu
    "interval": 60,
}
config_lock = Lock()


# --- TEKNİK HESAPLAMALAR ---
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calculate_atr(df, period=14):
    """ATR (Average True Range) volatilite hesaplaması"""
    high_low = df["h"] - df["l"]
    high_close = (df["h"] - df["c"].shift()).abs()
    low_close = (df["l"] - df["c"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return atr.iloc[-1]


# --- SIDEBAR & FILTERS ---
st.sidebar.header("⚙️ Bot & Genel Ayarlar")

TELEGRAM_BOT_TOKEN = st.sidebar.text_input("Telegram Bot Token", value=DEFAULT_TOKEN, type="password")
TELEGRAM_CHAT_ID = st.sidebar.text_input("Telegram Kanal/Chat ID", value=DEFAULT_CHAT_ID)

scan_interval = st.sidebar.slider("Tarama Sıklığı (Saniye)", min_value=10, max_value=300, value=60)
bot_active = st.sidebar.checkbox("🤖 Telegram Bildirimlerini Aktif Et")

st.sidebar.markdown("---")
st.sidebar.header("🔍 Temel & Hacim Filtreleri")

min_volume_m = st.sidebar.number_input("Minimum 24h Hacim (Milyon $)", value=10.0, step=5.0)
min_change_pct = st.sidebar.number_input("Minimum Değişim (%)", value=2.0, step=0.5)

st.sidebar.markdown("---")
st.sidebar.header("📈 Optimal Teknik Filtreler")

# Varsayılan strateji değerleri: RSI 40-62 ve EMA Trend Aktif
rsi_range = st.sidebar.slider("RSI (14) Aralığı (Önerilen: 40-62)", 0, 100, (40, 62))
use_ema_filter = st.sidebar.checkbox("Sadece Yükselen Trenddekileri Göster (EMA20 > EMA50)", value=True)

with config_lock:
    GLOBAL_CONFIG["active"] = bot_active
    GLOBAL_CONFIG["token"] = TELEGRAM_BOT_TOKEN
    GLOBAL_CONFIG["chat_id"] = TELEGRAM_CHAT_ID
    GLOBAL_CONFIG["min_volume"] = float(min_volume_m)
    GLOBAL_CONFIG["min_change"] = float(min_change_pct)
    GLOBAL_CONFIG["rsi_min"] = rsi_range[0]
    GLOBAL_CONFIG["rsi_max"] = rsi_range[1]
    GLOBAL_CONFIG["use_ema_filter"] = use_ema_filter
    GLOBAL_CONFIG["interval"] = int(scan_interval)


# --- TELEGRAM MESAJ GÖNDERİMİ ---
def send_telegram_signal(token, chat_id, row):
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    
    symbol = row['symbol']
    price = row['lastPrice']
    change = row['priceChangePercent']
    volume = row['quoteVolume']
    rsi = row.get('rsi', 0)
    ema_status = row.get('ema_status', 'N/A')
    sl = row.get('sl_price', 0)
    tp1 = row.get('tp1_price', 0)
    tp2 = row.get('tp2_price', 0)
    
    # Akıllı Momentum Notu
    if rsi < 45:
        rsi_note = "🟢 Dip Katlama Potansiyeli"
    elif rsi <= 58:
        rsi_note = "🚀 Güçlü Momentum Kırılımı"
    else:
        rsi_note = "⚠️ Dirence Yakın / Dikkat"
        
    message = (
        f"🚨 *YÜKSEK OLASILIKLI KRİPTO SİNYALİ* 🚨\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🪙 *Sembol:* #{symbol}\n"
        f"💵 *Giriş (Entry):* `${price:.4f}`\n"
        f"📈 *24h Değişim:* `%{change:+.2f}`\n"
        f"💰 *24h Hacim:* `${volume:.2f}M`\n"
        f"📊 *RSI (14):* `{rsi:.1f}` ({rsi_note})\n"
        f"📐 *Trend Durumu:* `{ema_status}`\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎯 *RİSK & HEDEF SEVİYELERİ (ATR)*\n"
        f"🛑 *Stop-Loss (SL):* `${sl:.4f}` (`-%{((price-sl)/price)*100:.2f}`)\n"
        f"🎯 *Hedef 1 (TP1 - 1:1.5):* `${tp1:.4f}` (`+%{((tp1-price)/price)*100:.2f}`)\n"
        f"🚀 *Hedef 2 (TP2 - 1:2.0):* `${tp2:.4f}` (`+%{((tp2-price)/price)*100:.2f}`)\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💡 *İşlem Öncesi:* Lütfen aşağıdaki butonla grafiği açıp **üst majör direnci** kontrol ediniz.\n"
        f"⏰ *Zaman:* `{time.strftime('%H:%M:%S')}`\n"
    )
    
    clean_sym = symbol.replace("USDT", "-USDT")
    tradingview_url = f"https://www.tradingview.com/chart/?symbol=OKX:{symbol}"
    okx_url = f"https://www.okx.com/trade-swap/{clean_sym.lower()}-swap"
    
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "📈 TradingView Grafiği (Direnç Kontrolü)", "url": tradingview_url},
                {"text": "🔗 OKX'te İncele", "url": okx_url}
            ]
        ]
    }

    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "reply_markup": reply_markup
    }
    
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Telegram Hatası: {e}")


# --- OKX TEKNİK & ATR VERİ ÇEKME ---
def fetch_kline_indicators(inst_id, current_price):
    url = f"https://www.okx.com/api/v5/market/candles?instId={inst_id}&bar=1H&limit=60"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            data = r.json().get("data", [])
            if len(data) >= 50:
                df_kline = pd.DataFrame(data, columns=["ts", "o", "h", "l", "c", "vol", "volCcy", "volCcyQuote", "confirm"])
                df_kline["c"] = df_kline["c"].astype(float)
                df_kline["h"] = df_kline["h"].astype(float)
                df_kline["l"] = df_kline["l"].astype(float)
                df_kline = df_kline.iloc[::-1].reset_index(drop=True)
                
                rsi_series = calculate_rsi(df_kline["c"], 14)
                ema20_series = calculate_ema(df_kline["c"], 20)
                ema50_series = calculate_ema(df_kline["c"], 50)
                atr_val = calculate_atr(df_kline, 14)
                
                latest_rsi = rsi_series.iloc[-1]
                latest_ema20 = ema20_series.iloc[-1]
                latest_ema50 = ema50_series.iloc[-1]
                
                ema_status = "EMA20 > EMA50 (Boğa)" if latest_ema20 > latest_ema50 else "EMA20 < EMA50 (Ayı)"
                is_bullish = latest_ema20 > latest_ema50
                
                sl_price = max(0.0001, current_price - (1.5 * atr_val))
                risk_amount = current_price - sl_price
                tp1_price = current_price + (1.5 * risk_amount)
                tp2_price = current_price + (2.0 * risk_amount)
                
                return (
                    round(latest_rsi, 2),
                    ema_status,
                    is_bullish,
                    round(sl_price, 4),
                    round(tp1_price, 4),
                    round(tp2_price, 4)
                )
    except Exception:
        pass
    
    sl = current_price * 0.97
    tp1 = current_price * 1.045
    tp2 = current_price * 1.06
    return 50.0, "N/A", False, round(sl, 4), round(tp1, 4), round(tp2, 4)


def _raw_fetch_okx_data():
    url = "https://www.okx.com/api/v5/market/tickers?instType=SWAP"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            res = r.json()
            if res.get("code") != "0":
                return pd.DataFrame(), f"OKX API Yanıt Hatası: {res.get('msg')}"

            raw_list = res.get("data", [])
            parsed_data = []

            for item in raw_list:
                inst_id = item.get("instId", "")
                if inst_id.endswith("-USDT-SWAP"):
                    symbol = inst_id.replace("-USDT-SWAP", "USDT")
                    last_price = float(item.get("last", 0))
                    sod_utc0 = float(item.get("sodUtc0", last_price))
                    
                    change_pct = ((last_price - sod_utc0) / sod_utc0) * 100 if sod_utc0 > 0 else 0.0
                    quote_vol = float(item.get("volCcy24h", 0)) / 1_000_000

                    parsed_data.append({
                        "instId": inst_id,
                        "symbol": symbol,
                        "lastPrice": last_price,
                        "priceChangePercent": change_pct,
                        "quoteVolume": quote_vol
                    })

            if parsed_data:
                return pd.DataFrame(parsed_data), None
            return pd.DataFrame(), "OKX verisi boş döndü."
        return pd.DataFrame(), f"OKX HTTP Hatası: Kod {r.status_code}"
    except Exception as e:
        return pd.DataFrame(), f"OKX Bağlantı Hatası: {str(e)}"


@st.cache_data(ttl=15, show_spinner=False)
def fetch_market_data_cached():
    return _raw_fetch_okx_data()


# --- DASHBOARD ---
st.title("📊 Kripto Piyasası Taraması & Risk/Ödül Analiz Paneli")

col_b1, col_b2 = st.columns([1, 4])
with col_b1:
    if st.button("🔄 Verileri Şimdi Yenile"):
        st.cache_data.clear()

df_raw, err_msg = fetch_market_data_cached()

if err_msg:
    st.error(f"❌ Veri Çekme Hatası: {err_msg}")

if not df_raw.empty:
    # Sadece pozitif değişim gösteren (yükselen) coinleri tara
    base_filtered = df_raw[
        (df_raw["quoteVolume"] >= min_volume_m) &
        (df_raw["priceChangePercent"] >= min_change_pct)
    ].copy()

    rsi_list = []
    ema_status_list = []
    is_bullish_list = []
    sl_list = []
    tp1_list = []
    tp2_list = []

    for _, row in base_filtered.iterrows():
        rsi_val, ema_stat, is_bull, sl, tp1, tp2 = fetch_kline_indicators(row["instId"], row["lastPrice"])
        rsi_list.append(rsi_val)
        ema_status_list.append(ema_stat)
        is_bullish_list.append(is_bull)
        sl_list.append(sl)
        tp1_list.append(tp1)
        tp2_list.append(tp2)

    base_filtered["rsi"] = rsi_list
    base_filtered["ema_status"] = ema_status_list
    base_filtered["is_bullish"] = is_bullish_list
    base_filtered["sl_price"] = sl_list
    base_filtered["tp1_price"] = tp1_list
    base_filtered["tp2_price"] = tp2_list

    final_df = base_filtered[
        (base_filtered["rsi"] >= rsi_range[0]) &
        (base_filtered["rsi"] <= rsi_range[1])
    ]
    if use_ema_filter:
        final_df = final_df[final_df["is_bullish"] == True]

    final_df = final_df.sort_values(by="priceChangePercent", ascending=False)

    col1, col2, col3 = st.columns(3)
    col1.metric("Taranan Toplam Sembol", len(df_raw))
    col2.metric("Filtreye Uyan Semboller", len(final_df))
    col3.metric("Bot Durumu", "Aktif" if bot_active else "Pasif")

    st.subheader("🎯 Otomatik Risk & Hedef Analizli Varlıklar")
    st.dataframe(
        final_df[["symbol", "lastPrice", "priceChangePercent", "quoteVolume", "rsi", "sl_price", "tp1_price", "tp2_price"]],
        column_config={
            "symbol": "Sembol",
            "lastPrice": st.column_config.NumberColumn("Giriş ($)", format="$%.4f"),
            "priceChangePercent": st.column_config.NumberColumn("24h Değişim (%)", format="%.2f%%"),
            "quoteVolume": st.column_config.NumberColumn("24h Hacim (M$)", format="$%.2fM"),
            "rsi": st.column_config.NumberColumn("RSI (14)", format="%.1f"),
            "sl_price": st.column_config.NumberColumn("🛑 Stop-Loss", format="$%.4f"),
            "tp1_price": st.column_config.NumberColumn("🎯 Hedef 1 (TP1)", format="$%.4f"),
            "tp2_price": st.column_config.NumberColumn("🚀 Hedef 2 (TP2)", format="$%.4f"),
        },
        use_container_width=True,
    )


# --- BACKGROUND WORKER ---
def telegram_worker():
    sent_signals = {}
    cooldown_seconds = 1800

    while True:
        with config_lock:
            cfg = GLOBAL_CONFIG.copy()

        if cfg["active"] and cfg["token"] and cfg["chat_id"]:
            data, _ = _raw_fetch_okx_data()

            if not data.empty:
                matches = data[
                    (data["quoteVolume"] >= cfg["min_volume"]) &
                    (data["priceChangePercent"] >= cfg["min_change"])
                ].copy()

                current_time = time.time()
                for _, row in matches.iterrows():
                    sym = row["symbol"]
                    
                    if sym not in sent_signals or (current_time - sent_signals[sym]) > cooldown_seconds:
                        rsi_val, ema_stat, is_bull, sl, tp1, tp2 = fetch_kline_indicators(row["instId"], row["lastPrice"])
                        
                        rsi_pass = (cfg["rsi_min"] <= rsi_val <= cfg["rsi_max"])
                        ema_pass = (not cfg["use_ema_filter"]) or is_bull
                        
                        if rsi_pass and ema_pass:
                            row_dict = row.to_dict()
                            row_dict["rsi"] = rsi_val
                            row_dict["ema_status"] = ema_stat
                            row_dict["sl_price"] = sl
                            row_dict["tp1_price"] = tp1
                            row_dict["tp2_price"] = tp2
                            
                            send_telegram_signal(cfg["token"], cfg["chat_id"], row_dict)
                            sent_signals[sym] = current_time

        time.sleep(cfg.get("interval", 60))


@st.cache_resource
def start_background_worker():
    t = Thread(target=telegram_worker, daemon=True)
    t.start()
    return True


start_background_worker()
