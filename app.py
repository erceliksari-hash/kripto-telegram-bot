import time
from threading import Thread, Lock
import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="Crypto Scanner & Position Calculator", layout="wide"
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

QUANTFURY_DEFAULT_LIST = (
    "BTCUSDT, ETHUSDT, SOLUSDT, AVAXUSDT, XRPUSDT, LINKUSDT, ADAUSDT, DOTUSDT, "
    "NEARUSDT, LTCUSDT, DOGEUSDT, SHIBUSDT, MATICUSDT, ATOMUSDT, APTUSDT, "
    "SUIUSDT, ARBUSDT, OPUSDT, INJUSDT, TIAUSDT, FETUSDT, RENDERUSDT, PEPEUSDT"
)

GLOBAL_CONFIG = {
    "active": False,
    "token": DEFAULT_TOKEN,
    "chat_id": DEFAULT_CHAT_ID,
    "min_volume": 10.0,
    "min_change": 2.0,
    "rsi_min": 40,
    "rsi_max": 62,
    "use_ema_filter": True,
    "interval": 60,
    "watchlist": [s.strip() for s in QUANTFURY_DEFAULT_LIST.split(",") if s.strip()]
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
    high_low = df["h"] - df["l"]
    high_close = (df["h"] - df["c"].shift()).abs()
    low_close = (df["l"] - df["c"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return atr.iloc[-1]

def calculate_pivot_points(df):
    high = df["h"].iloc[-1]
    low = df["l"].iloc[-1]
    close = df["c"].iloc[-1]
    
    pivot = (high + low + close) / 3.0
    r1 = (2 * pivot) - low
    s1 = (2 * pivot) - high
    r2 = pivot + (high - low)
    s2 = pivot - (high - low)
    
    return round(pivot, 4), round(r1, 4), round(r2, 4), round(s1, 4), round(s2, 4)


# --- QUANTFURY POZİSYON VE KALDIRAÇ HESAPLAYICI ---
def calculate_quantfury_position(account_balance, risk_percentage, entry_price, stop_loss_price, take_profit_price=None, leverage=1.0):
    if entry_price <= 0 or stop_loss_price <= 0:
        raise ValueError("Giriş ve Stop-Loss fiyatları 0'dan büyük olmalıdır.")
    
    is_long = entry_price > stop_loss_price
    direction = "LONG 🟢" if is_long else "SHORT 🔴"
    
    risk_amount_usd = account_balance * (risk_percentage / 100.0)
    
    if is_long:
        price_risk_pct = (entry_price - stop_loss_price) / entry_price
    else:
        price_risk_pct = (stop_loss_price - entry_price) / entry_price

    if price_risk_pct <= 0:
        raise ValueError("Long işlemde Stop-Loss girişten küçük, Short işlemde büyük olmalıdır.")

    max_position_size_usd = risk_amount_usd / price_risk_pct
    max_allowed_by_leverage = account_balance * leverage
    actual_position_size_usd = min(max_position_size_usd, max_allowed_by_leverage)
    
    units = actual_position_size_usd / entry_price
    required_margin = actual_position_size_usd / leverage
    
    pnl_tp_usd = None
    risk_reward_ratio = None
    if take_profit_price and take_profit_price > 0:
        if is_long:
            tp_pct = (take_profit_price - entry_price) / entry_price
        else:
            tp_pct = (entry_price - take_profit_price) / entry_price
            
        pnl_tp_usd = actual_position_size_usd * tp_pct
        risk_reward_ratio = pnl_tp_usd / risk_amount_usd if risk_amount_usd > 0 else 0.0

    return {
        "direction": direction,
        "risk_amount_usd": round(risk_amount_usd, 2),
        "position_size_usd": round(actual_position_size_usd, 2),
        "units": round(units, 4),
        "required_margin": round(required_margin, 2),
        "effective_leverage": round(actual_position_size_usd / account_balance, 2),
        "price_risk_pct": round(price_risk_pct * 100, 2),
        "tp_pnl_usd": round(pnl_tp_usd, 2) if pnl_tp_usd is not None else None,
        "risk_reward_ratio": round(risk_reward_ratio, 2) if risk_reward_ratio is not None else None
    }


# --- SIDEBAR AYARLARI ---
st.sidebar.header("⚙️ Bot & Genel Ayarlar")

TELEGRAM_BOT_TOKEN = st.sidebar.text_input("Telegram Bot Token", value=DEFAULT_TOKEN, type="password")
TELEGRAM_CHAT_ID = st.sidebar.text_input("Telegram Kanal/Chat ID", value=DEFAULT_CHAT_ID)

scan_interval = st.sidebar.slider("Tarama Sıklığı (Saniye)", min_value=10, max_value=300, value=60)
bot_active = st.sidebar.checkbox("🤖 Otomatik Telegram Bildirimlerini Aktif Et", value=True)

st.sidebar.markdown("---")
st.sidebar.header("🎯 Quantfury / Özel İzleme Listesi")

watchlist_raw = st.sidebar.text_area(
    "Quantfury Coin Listesi (Virgülle Ayırın)",
    value=QUANTFURY_DEFAULT_LIST,
    height=120,
    help="Quantfury sekmende görünmesini istediğin coinler."
)

parsed_watchlist = [s.strip().upper() for s in watchlist_raw.split(",") if s.strip()]

st.sidebar.markdown("---")
st.sidebar.header("🔍 Temel & Hacim Filtreleri")

min_volume_m = st.sidebar.number_input("Minimum 24h Hacim (Milyon $)", value=10.0, step=5.0)
min_change_pct = st.sidebar.number_input("Minimum Değişim (%)", value=2.0, step=0.5)

st.sidebar.markdown("---")
st.sidebar.header("📈 Optimal Teknik Filtreler")

rsi_range = st.sidebar.slider("RSI (14) Aralığı", 0, 100, (40, 62))
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
    GLOBAL_CONFIG["watchlist"] = parsed_watchlist


# --- TELEGRAM GÖNDERİMİ ---
def send_telegram_signal(token, chat_id, row, is_quantfury=False):
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
    
    pivot = row.get('pivot', 0)
    r1 = row.get('r1', 0)
    r2 = row.get('r2', 0)
    s1 = row.get('s1', 0)
    
    tag_header = "⚡ *QUANTFURY SİNYALİ*" if is_quantfury else "🌐 *GENEL PİYASA SİNYALİ (OKX)*"

    message = (
        f"🚨 {tag_header} 🚨\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🪙 *Sembol:* #{symbol}\n"
        f"💵 *Giriş (Entry):* `${price:.4f}`\n"
        f"📈 *24h Değişim:* `%{change:+.2f}`\n"
        f"💰 *24h Hacim:* `${volume:.2f}M`\n"
        f"📊 *RSI (14):* `{rsi:.1f}` | *Trend:* `{ema_status}`\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎯 *ATR RİSK & HEDEF SEVİYELERİ*\n"
        f"🛑 *Stop-Loss (SL):* `${sl:.4f}` (`-%{((price-sl)/price)*100:.2f}`)\n"
        f"🎯 *Hedef 1 (TP1):* `${tp1:.4f}` (`+%{((tp1-price)/price)*100:.2f}`)\n"
        f"🚀 *Hedef 2 (TP2):* `${tp2:.4f}` (`+%{((tp2-price)/price)*100:.2f}`)\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📐 *PIVOT DESTEK / DİRENÇ*\n"
        f"🔴 *Direnç 1 (R1):* `${r1:.4f}` | *R2:* `${r2:.4f}`\n"
        f"⚪ *Pivot (P):* `${pivot:.4f}` | *S1:* `${s1:.4f}`\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⏰ *Zaman:* `{time.strftime('%H:%M:%S')}`\n"
    )
    
    clean_sym = symbol.replace("USDT", "-USDT")
    tradingview_url = f"https://www.tradingview.com/chart/?symbol=OKX:{symbol}"
    okx_url = f"https://www.okx.com/trade-swap/{clean_sym.lower()}-swap"
    
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "📈 TradingView Grafiği", "url": tradingview_url},
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


# --- VERİ ÇEKME FONKSİYONLARI ---
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
                
                pivot, r1, r2, s1, s2 = calculate_pivot_points(df_kline)
                
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
                    round(tp2_price, 4),
                    pivot, r1, r2, s1, s2
                )
    except Exception:
        pass
    
    sl = current_price * 0.97
    tp1 = current_price * 1.045
    tp2 = current_price * 1.06
    return 50.0, "N/A", False, round(sl, 4), round(tp1, 4), round(tp2, 4), 0, 0, 0, 0, 0


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


# --- ANA EKRAN VE SEKMELER ---
st.title("📊 Crypto Scanner & Quantfury Analiz Paneli")

col_b1, _ = st.columns([1, 4])
with col_b1:
    if st.button("🔄 Verileri Şimdi Yenile"):
        st.cache_data.clear()

df_raw, err_msg = fetch_market_data_cached()

if err_msg:
    st.error(f"❌ Veri Çekme Hatası: {err_msg}")

if not df_raw.empty:
    base_filtered = df_raw[
        (df_raw["quoteVolume"] >= min_volume_m) &
        (df_raw["priceChangePercent"] >= min_change_pct)
    ].copy()

    rsi_list, ema_status_list, is_bullish_list = [], [], []
    sl_list, tp1_list, tp2_list = [], [], []
    pivot_list, r1_list, r2_list = [], [], []

    for _, row in base_filtered.iterrows():
        rsi_val, ema_stat, is_bull, sl, tp1, tp2, p, r1, r2, s1, s2 = fetch_kline_indicators(row["instId"], row["lastPrice"])
        rsi_list.append(rsi_val)
        ema_status_list.append(ema_stat)
        is_bullish_list.append(is_bull)
        sl_list.append(sl)
        tp1_list.append(tp1)
        tp2_list.append(tp2)
        pivot_list.append(p)
        r1_list.append(r1)
        r2_list.append(r2)

    base_filtered["rsi"] = rsi_list
    base_filtered["ema_status"] = ema_status_list
    base_filtered["is_bullish"] = is_bullish_list
    base_filtered["sl_price"] = sl_list
    base_filtered["tp1_price"] = tp1_list
    base_filtered["tp2_price"] = tp2_list
    base_filtered["pivot"] = pivot_list
    base_filtered["r1"] = r1_list
    base_filtered["r2"] = r2_list

    final_df = base_filtered[
        (base_filtered["rsi"] >= rsi_range[0]) &
        (base_filtered["rsi"] <= rsi_range[1])
    ]
    if use_ema_filter:
        final_df = final_df[final_df["is_bullish"] == True]

    final_df = final_df.sort_values(by="priceChangePercent", ascending=False)

    df_quantfury = final_df[final_df["symbol"].isin(parsed_watchlist)].copy()
    df_all_market = final_df.copy()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Piyasadaki Toplam Sembol", len(df_raw))
    col2.metric("Quantfury Uygun Fırsat", len(df_quantfury))
    col3.metric("Tüm Piyasa Uygun Fırsat", len(df_all_market))
    col4.metric("Bot Durumu", "Aktif" if bot_active else "Pasif")

    st.markdown("---")

    tab1, tab2, tab3 = st.tabs([
        "⚡ Quantfury / İzleme Listesi Fırsatları", 
        "🌐 Tüm OKX Piyasası Fırsatları", 
        "🧮 Quantfury Kaldıraç Hesaplayıcı"
    ])

    def display_crypto_table(df_to_show):
        if df_to_show.empty:
            st.info("Kriterlere uyan hiçbir kripto varlık bulunamadı.")
        else:
            st.dataframe(
                df_to_show[["symbol", "lastPrice", "priceChangePercent", "quoteVolume", "rsi", "sl_price", "tp1_price", "r1", "r2"]],
                column_config={
                    "symbol": "Sembol",
                    "lastPrice": st.column_config.NumberColumn("Giriş ($)", format="$%.4f"),
                    "priceChangePercent": st.column_config.NumberColumn("24h Değişim (%)", format="%.2f%%"),
                    "quoteVolume": st.column_config.NumberColumn("24h Hacim (M$)", format="$%.2fM"),
                    "rsi": st.column_config.NumberColumn("RSI (14)", format="%.1f"),
                    "sl_price": st.column_config.NumberColumn("🛑 Stop-Loss", format="$%.4f"),
                    "tp1_price": st.column_config.NumberColumn("🎯 TP1 (1:1.5)", format="$%.4f"),
                    "r1": st.column_config.NumberColumn("🔴 Direnç 1 (R1)", format="$%.4f"),
                    "r2": st.column_config.NumberColumn("🔴 Direnç 2 (R2)", format="$%.4f"),
                },
                use_container_width=True,
            )

    with tab1:
        st.subheader("📌 Quantfury'de Mevcut Olan Fırsatlar")
        display_crypto_table(df_quantfury)

    with tab2:
        st.subheader("🌍 OKX Üzerindeki Tüm Uygun Fırsatlar")
        display_crypto_table(df_all_market)

    with tab3:
        st.subheader("🧮 Quantfury Risk & Kaldıraç Hesaplayıcı")
        st.caption("Girmek istediğiniz pozisyon için risk bakiyenizi aşmayacak ideal pozisyon büyüklüğünü hesaplayın.")

        col_calc1, col_calc2 = st.columns(2)

        with col_calc1:
            acc_balance = st.number_input("Toplam Hesap Bakiyesi ($)", min_value=10.0, value=1000.0, step=50.0)
            risk_pct = st.slider("İşlem Başı Riske Edilecek Bakiye (%)", min_value=0.5, max_value=10.0, value=2.0, step=0.5)
            selected_lev = st.selectbox("Seçilen Kaldıraç Oranı", options=[1, 2, 3, 5, 10, 20], index=4)

        with col_calc2:
            entry_p = st.number_input("Giriş Fiyatı ($)", min_value=0.0001, value=50000.0, step=10.0, format="%.4f")
            sl_p = st.number_input("Stop-Loss Fiyatı ($)", min_value=0.0001, value=49000.0, step=10.0, format="%.4f")
            tp_p = st.number_input("Take-Profit / Kar Al Fiyatı ($)", min_value=0.0, value=52000.0, step=10.0, format="%.4f")

        if st.button("🧮 Pozisyon Büyüklüğünü Hesapla", type="primary"):
            try:
                calc_res = calculate_quantfury_position(
                    account_balance=acc_balance,
                    risk_percentage=risk_pct,
                    entry_price=entry_p,
                    stop_loss_price=sl_p,
                    take_profit_price=tp_p,
                    leverage=selected_lev
                )

                st.markdown("---")
                st.markdown(f"### **İşlem Yönü:** {calc_res['direction']}")

                m_col1, m_col2, m_col3 = st.columns(3)
                m_col1.metric("Önerilen Pozisyon Büyüklüğü", f"${calc_res['position_size_usd']:,}")
                m_col2.metric("Maksimum Risk Tutarı", f"${calc_res['risk_amount_usd']:,}")
                m_col3.metric("Gerekli Teminat (Margin)", f"${calc_res['required_margin']:,}")

                st.markdown(f"""
                - **Pozisyon Adedi:** `{calc_res['units']}` Lot / Birim
                - **Stop-Loss Uzaklığı:** `%{calc_res['price_risk_pct']}`
                - **Etkili Kaldıraç Kullanımı:** `{calc_res['effective_leverage']}x`
                """)

                if calc_res['tp_pnl_usd'] is not None:
                    st.success(f"🎯 **Hedef Kar (TP):** ${calc_res['tp_pnl_usd']:,} (Risk/Ödül Oranı = **1 : {calc_res['risk_reward_ratio']}**)")

            except Exception as ex:
                st.error(f"Hesaplama Hatası: {str(ex)}")


# --- ARKA PLAN BOT WORKER ---
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
                    is_qf = sym in cfg["watchlist"]

                    if sym not in sent_signals or (current_time - sent_signals[sym]) > cooldown_seconds:
                        rsi_val, ema_stat, is_bull, sl, tp1, tp2, p, r1, r2, s1, s2 = fetch_kline_indicators(row["instId"], row["lastPrice"])
                        
                        rsi_pass = (cfg["rsi_min"] <= rsi_val <= cfg["rsi_max"])
                        ema_pass = (not cfg["use_ema_filter"]) or is_bull
                        
                        if rsi_pass and ema_pass:
                            row_dict = row.to_dict()
                            row_dict["rsi"] = rsi_val
                            row_dict["ema_status"] = ema_stat
                            row_dict["sl_price"] = sl
                            row_dict["tp1_price"] = tp1
                            row_dict["tp2_price"] = tp2
                            row_dict["pivot"] = p
                            row_dict["r1"] = r1
                            row_dict["r2"] = r2
                            row_dict["s1"] = s1
                            row_dict["s2"] = s2
                            
                            send_telegram_signal(cfg["token"], cfg["chat_id"], row_dict, is_quantfury=is_qf)
                            sent_signals[sym] = current_time

        time.sleep(cfg.get("interval", 60))


@st.cache_resource
def start_background_worker():
    t = Thread(target=telegram_worker, daemon=True)
    t.start()
    return True


start_background_worker()
