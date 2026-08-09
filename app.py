import datetime
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import ccxt
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import streamlit as st
import ta

# ==========================================
# 1. PAGE CONFIG
# ==========================================
st.set_page_config(
    page_title="Akıllı Kripto Analiz & Risk Yönetim Botu",
    page_icon="🛡️",
    layout="wide",
)

# ==========================================
# 2. SECRETS'TEN TELEGRAM BİLGİLERİNİ OKU
# ==========================================
TELEGRAM_TOKEN = ""
TELEGRAM_CHAT_ID = ""

if "telegram" in st.secrets:
    TELEGRAM_TOKEN = st.secrets["telegram"].get("bot_token", "")
    TELEGRAM_CHAT_ID = st.secrets["telegram"].get("chat_id", "")
else:
    TELEGRAM_TOKEN = st.secrets.get(
        "TELEGRAM_BOT_TOKEN", st.secrets.get("bot_token", "")
    )
    TELEGRAM_CHAT_ID = st.secrets.get(
        "TELEGRAM_CHAT_ID", st.secrets.get("chat_id", "")
    )

@st.cache_resource
def init_exchanges():
    exchanges = {
        "Binance": ccxt.binance({"enableRateLimit": True, "timeout": 8000}),
        "OKX": ccxt.okx({"enableRateLimit": True, "timeout": 8000}),
        "Bybit": ccxt.bybit({"enableRateLimit": True, "timeout": 8000}),
        "KuCoin": ccxt.kucoin({"enableRateLimit": True, "timeout": 8000}),
        "Coinbase": ccxt.coinbase({"enableRateLimit": True, "timeout": 8000}),
    }
    return exchanges

EXCHANGES = init_exchanges()

# ==========================================
# 3. SIDEBAR (SOL PANEL) AYARLARI
# ==========================================
st.sidebar.title("⚙️ Panel & Risk Yönetim Ayarları")

st.sidebar.success("🟢 **UptimeRobot:** Aktif\n(5 Borsa Otomatik Taranır)")
st.sidebar.markdown("---")

# Kasa ve Risk Yönetimi Parametreleri
st.sidebar.subheader("💰 Kasa & Pozisyon Büyüklüğü")
user_balance = st.sidebar.number_input("Toplam Bakiye ($)", value=1000.0, step=100.0)
user_risk_pct = st.sidebar.number_input("İşlem Başı Risk (%)", value=2.0, step=0.5)

st.sidebar.markdown("---")

enable_auto_telegram = st.sidebar.checkbox(
    "30 Dk'da Bir Otomatik Telegram Sinyali Gönder", value=True
)

only_signals_telegram = st.sidebar.checkbox(
    "🔔 Telegram'a Sadece AL/GÜÇLÜ AL Sinyallerini Gönder", value=True
)

st.sidebar.markdown("---")

st.sidebar.subheader("📝 Genel Taranacak Semboller")
default_symbols = (
    "BTCUSDT, ETHUSDT, SOLUSDT, AVAXUSDT, NEARUSDT, LINKUSDT, DOGEUSDT, XRPUSDT, "
    "ADAUSDT, DOTUSDT, SHIBUSDT, MATICUSDT, LTCUSDT, TRONUSDT, UNIUSDT, ATOMUSDT, "
    "APTUSDT, ARBUSDT, OPUSDT, INJUSDT, SUIUSDT, FETUSDT, RENDERUSDT, PEPEUSDT, "
    "FLOKIUSDT, BONKUSDT, TIAUSDT, SEIUSDT, FILUSDT, ICPUSDT"
)
symbol_input = st.sidebar.text_area(
    "Semboller (Virgülle ayırın)", value=default_symbols, height=100
)
custom_symbol_list = [
    s.strip().upper()
    for s in symbol_input.replace("\n", ",").split(",")
    if s.strip()
]

st.sidebar.markdown("---")

st.sidebar.subheader("🍟 Quntry Fry Özel Listesi")
quntry_default = "BICOUSDT, RECALLUSDT, ZDTUSDT, BEATUSDT"
quntry_input = st.sidebar.text_area(
    "Quntry Fry Coinleri (Virgülle ayırın)", value=quntry_default, height=60
)
quntry_symbol_list = [
    s.strip().upper()
    for s in quntry_input.replace("\n", ",").split(",")
    if s.strip()
]

quntry_timeframe = st.sidebar.selectbox(
    "Quntry Fry Zaman Dilimi", ["15m", "1h", "4h"], index=1
)

st.sidebar.markdown("---")

st.sidebar.subheader("🔍 Filtreleme Kriterleri")
min_volume = st.sidebar.number_input("Minimum 24h Hacim (Milyon $)", value=0.1, step=1.0)
min_change = st.sidebar.number_input("Minimum 24h Değişim (%)", value=-10.0, step=0.5)
rsi_min, rsi_max = st.sidebar.slider("RSI (14) Aralığı", 0, 100, (0, 100))


# ==========================================
# 4. AKILLI ANALİZ MOTORU & YARDIMCI FİLTRELER
# ==========================================

# 1. AKILLI FİLTRE: BTC Piyasa Trend Kontrolü
def get_btc_market_status():
    """BTC 4 saatlik EMA50 üzerinde mi kontrol eder."""
    for ex_instance in EXCHANGES.values():
        try:
            ohlcv = ex_instance.fetch_ohlcv("BTC/USDT", timeframe="4h", limit=60)
            if ohlcv and len(ohlcv) >= 50:
                df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "vol"])
                ema50 = ta.trend.ema_indicator(df["close"], window=50).iloc[-1]
                btc_price = df["close"].iloc[-1]
                if btc_price > ema50:
                    return "BULLISH", btc_price
                else:
                    return "BEARISH", btc_price
        except Exception:
            continue
    return "UNKNOWN", 0.0

# 2. AKILLI FİLTRE: 4 Saatlik Ana Trend Kontrolü
def check_4h_trend(ex_instance, symbol):
    """Coin'in 4h ana trendinin pozitif olup olmadığını kontrol eder."""
    try:
        ohlcv = ex_instance.fetch_ohlcv(symbol, timeframe="4h", limit=60)
        if ohlcv and len(ohlcv) >= 50:
            df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "vol"])
            ema50 = ta.trend.ema_indicator(df["close"], window=50).iloc[-1]
            return df["close"].iloc[-1] > ema50
    except Exception:
        pass
    return True # Veri çekilemezse varsayılan engelleme yapmaz

def fetch_symbol_from_all_exchanges(symbol, timeframe="1h", return_df=False, btc_status="BULLISH"):
    raw_sym = symbol.replace("/", "").replace("-", "")
    formatted_symbol = f"{raw_sym[:-4]}/USDT" if raw_sym.endswith("USDT") else symbol

    for ex_name, ex_instance in EXCHANGES.items():
        try:
            ohlcv = ex_instance.fetch_ohlcv(formatted_symbol, timeframe=timeframe, limit=100)
            if not ohlcv or len(ohlcv) < 50:
                continue

            df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")

            # İndikatör Hesaplamaları
            df["rsi"] = ta.momentum.rsi(df["close"], window=14)
            df["ema50"] = ta.trend.ema_indicator(df["close"], window=50)

            macd = ta.trend.MACD(df["close"])
            df["macd"] = macd.macd()
            df["macd_signal"] = macd.macd_signal()
            df["atr"] = ta.volatility.average_true_range(df["high"], df["low"], df["close"], window=14)
            df["vol_sma"] = df["volume"].rolling(window=20).mean()

            if return_df:
                return df, ex_name

            latest = df.iloc[-1]
            prev = df.iloc[-2]
            price = float(latest["close"])

            # En yakın Direnç (Son 20 mumun en yükseği)
            recent_resistance = float(df["high"].tail(20).max())

            # 24s Değişim ve Hacim Hesabı
            first_price = float(df.iloc[0]["close"])
            change_24h = ((price - first_price) / first_price) * 100
            vol_24h_m = (df["volume"].sum() * price) / 1_000_000

            # Kırılım & Hacim Onayı Kontrolü
            is_volume_surge = latest["volume"] > (latest["vol_sma"] * 1.3)
            is_bullish_1h = price > latest["ema50"]
            is_macd_cross = (prev["macd"] < prev["macd_signal"]) and (latest["macd"] > latest["macd_signal"])

            # 4 Saatlik Ana Trend Onayı
            is_bullish_4h = check_4h_trend(ex_instance, formatted_symbol)

            # Sinyal Sınıflandırma
            if is_bullish_1h and is_macd_cross and is_volume_surge and (latest["rsi"] < 68):
                if btc_status == "BEARISH":
                    signal = "⚠️ RISK (BTC DÜŞÜŞTE)"
                    comment = "🟡 Sinyal var fakat BTC trendi olumsuz!"
                elif not is_bullish_4h:
                    signal = "AL (KISA VADELİ TEPKİ)"
                    comment = "🟠 1H Pozitif ama 4H Ana Trend Düşüşte!"
                else:
                    signal = "GÜÇLÜ AL"
                    comment = "🟢 Hacim + 4H Trend + MACD Onaylı"
            elif is_bullish_1h and (latest["rsi"] < 60):
                signal = "AL"
                comment = "🟡 Trend Pozitif"
            elif (latest["rsi"] > 70) or (price < latest["ema50"] and not is_volume_surge):
                signal = "SAT / RISKLİ"
                comment = "🔴 Sahte Kırılım / Aşırı Alım"
            else:
                signal = "NÖTR"
                comment = "⚪ Yatay Piyasa"

            # 3. AKILLI FİLTRE: Stop Loss, Risk/Ödül & Pozisyon Büyüklüğü Hesaplama
            atr_val = float(latest["atr"])
            stop_loss = round(price - (atr_val * 1.5), 4)
            target_tp1 = round(price + (atr_val * 2.0), 4)

            # Risk / Ödül Hesaplama
            risk_per_coin = price - stop_loss
            reward_per_coin = target_tp1 - price
            rr_ratio = round(reward_per_coin / risk_per_coin, 2) if risk_per_coin > 0 else 0

            # Dirence Uzaklık
            dist_to_resistance_pct = round(((recent_resistance - price) / price) * 100, 2)

            # Önerilen Pozisyon Büyüklüğü ($) = (Bakiye * Risk%) / SL Mesafesi (%)
            sl_pct = (risk_per_coin / price)
            max_risk_amount = user_balance * (user_risk_pct / 100)
            rec_position_size = round(max_risk_amount / sl_pct, 2) if sl_pct > 0 else 0
            # Kasadan fazla pozisyon açılmasını engelle
            rec_position_size = min(rec_position_size, user_balance)

            return {
                "Sembol": symbol,
                "Kaynak Borsa": ex_name,
                "Fiyat ($)": price,
                "24h Değişim (%)": round(change_24h, 2),
                "24h Hacim (M$)": round(vol_24h_m, 2),
                "RSI (14)": round(float(latest["rsi"]), 1),
                "Stop Loss": stop_loss,
                "Hedef (TP1)": target_tp1,
                "R:R Oranı": rr_ratio,
                "Direnç Mesafesi (%)": dist_to_resistance_pct,
                "Önerilen Pozisyon ($)": rec_position_size,
                "Sinyal": signal,
                "Yorum": comment,
                "Update Time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

        except Exception:
            continue

    return None if not return_df else (None, None)


def analyze_symbol_list_fast(symbols, timeframe="1h", btc_status="BULLISH"):
    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fetch_symbol_from_all_exchanges, sym, timeframe, False, btc_status) for sym in symbols]
        for future in as_completed(futures):
            res = future.result()
            if res is not None:
                results.append(res)
    return pd.DataFrame(results)


# ==========================================
# 5. TELEGRAM BİLDİRİM FONKSİYONU
# ==========================================
def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False, "Telegram token veya chat_id eksik."
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        res = requests.post(url, json=payload, timeout=5)
        return (True, "Başarılı") if res.status_code == 200 else (False, res.text)
    except Exception as e:
        return False, str(e)


# ==========================================
# 6. EKRAN ARAYÜZÜ VE TARAMA
# ==========================================
st.title("🛡️ Akıllı Kripto Analiz & Risk Yönetim Paneli")

# BTC Trendini Başta Kontrol Et
btc_status, btc_price = get_btc_market_status()

# BTC Piyasa Durum Kartı
if btc_status == "BULLISH":
    st.success(f"🟢 **Piyasa Durumu:** Bitcoin (BTC) `${btc_price}` ile **YÜKSELİŞ TRENDİNDE**. Altcoin sinyalleri güvenli.")
elif btc_status == "BEARISH":
    st.error(f"🔴 **Piyasa Durumu:** Bitcoin (BTC) `${btc_price}` ile **DÜŞÜŞ TRENDİNDE**. Altcoin 'AL' sinyallerinde DİKKATLİ olun!")
else:
    st.warning("⚠️ BTC piyasa trendi alınamadı, genel tarama yapılıyor.")

# Paralel Tarama
start_time = time.time()
df_quntry_raw = analyze_symbol_list_fast(quntry_symbol_list, timeframe=quntry_timeframe, btc_status=btc_status)
df_genel_raw = analyze_symbol_list_fast(custom_symbol_list, timeframe="1h", btc_status=btc_status)
scan_duration = round(time.time() - start_time, 2)

def apply_filters(df):
    if df.empty:
        return df
    return df[
        (df["24h Hacim (M$)"] >= min_volume)
        & (df["24h Değişim (%)"] >= min_change)
        & (df["RSI (14)"] >= rsi_min)
        & (df["RSI (14)"] <= rsi_max)
    ]

df_quntry = apply_filters(df_quntry_raw)
df_genel = apply_filters(df_genel_raw)

# Özet Üst Metrikler
c1, c2, c3, c4 = st.columns(4)
c1.metric("Tarama Süresi", f"{scan_duration} sn")
c2.metric("Quntry Fry Bulunan", len(df_quntry_raw))
c3.metric("Genel Bulunan Coin", len(df_genel_raw))
c4.metric("Kasa / İşlem Riski", f"${user_balance} / %{user_risk_pct}")

# --- BÖLÜM 1: QUNTRY FRY LİSTESİ ---
st.markdown("### 🍟 Quntry Fry Özel Takip Listesi")
if not df_quntry.empty:
    st.dataframe(df_quntry, use_container_width=True)
else:
    st.warning("⚠️ Belirlenen filtrelere uyan Quntry Fry coini bulunamadı.")

st.markdown("---")

# --- BÖLÜM 2: GENEL PİYASA ANALİZİ ---
st.markdown("### 🎯 Genel Piyasa Risk & Hedef Analizi")
if not df_genel.empty:
    st.dataframe(df_genel, use_container_width=True)
else:
    st.warning("⚠️ Belirlenen filtrelere uyan Genel piyasa coini bulunamadı.")

st.markdown("---")

# --- BÖLÜM 3: İNTERAKTİF GRAFİK EKRANI ---
st.markdown("### 📈 Canlı Grafik İnceleme Paneli")
all_available_symbols = list(set(custom_symbol_list + quntry_symbol_list))
selected_chart_symbol = st.selectbox("Grafiğini Görmek İstediğiniz Coini Seçin:", all_available_symbols)

if selected_chart_symbol:
    df_chart, chart_ex_name = fetch_symbol_from_all_exchanges(selected_chart_symbol, timeframe="1h", return_df=True)
    if df_chart is not None:
        st.info(f"📍 **{selected_chart_symbol}** verisi **{chart_ex_name}** borsasından çekildi.")
        
        fig = make_subplots(
            rows=2, cols=1, shared_xaxes=True, 
            vertical_spacing=0.08, subplot_titles=(f"{selected_chart_symbol} Fiyat Grafik & EMA50", "RSI (14) Göstergesi"),
            row_heights=[0.7, 0.3]
        )

        fig.add_trace(go.Candlestick(
            x=df_chart['datetime'],
            open=df_chart['open'], high=df_chart['high'],
            low=df_chart['low'], close=df_chart['close'],
            name="Fiyat"
        ), row=1, col=1)

        fig.add_trace(go.Scatter(
            x=df_chart['datetime'], y=df_chart['ema50'],
            mode='lines', name='EMA 50', line=dict(color='orange', width=1.5)
        ), row=1, col=1)

        fig.add_trace(go.Scatter(
            x=df_chart['datetime'], y=df_chart['rsi'],
            mode='lines', name='RSI', line=dict(color='purple', width=1.5)
        ), row=2, col=1)

        fig.add_hline(y=70, line_dash="dash", line_color="red", row=2, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="green", row=2, col=1)

        fig.update_layout(height=500, xaxis_rangeslider_visible=False, template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)

# --- BÖLÜM 4: TELEGRAM BİLDİRİMLERİ ---
def build_telegram_report(df_raw, title):
    if df_raw.empty:
        return ""
    
    msg = f"{title}\n"
    has_signal = False
    for _, row in df_raw.iterrows():
        if only_signals_telegram and row['Sinyal'] not in ["AL", "GÜÇLÜ AL", "AL (KISA VADELİ TEPKİ)"]:
            continue
        has_signal = True
        msg += f"• *{row['Sembol']}* ({row['Kaynak Borsa']}): `${row['Fiyat ($)']}`\n"
        msg += f"  └ Sinyal: `{row['Sinyal']}` | Önerilen Poz: `${row['Önerilen Pozisyon ($)']}`\n"
        msg += f"  └ SL: `${row['Stop Loss']}` | TP1: `${row['Hedef (TP1)']}` | R:R: `{row['R:R Oranı']}`\n"
    
    return msg if has_signal else ""

st.sidebar.markdown("---")
if st.sidebar.button("📤 Telegram Raporunu Şimdi Gönder"):
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = f"🛡️ *AKILLI KRİPTO FIRSAT RAPORU*\n⏱️ *Saat:* `{now_str}`\n"
    msg += f"📊 *BTC Trend:* `{btc_status}` (`${btc_price}`)\n\n"

    quntry_msg = build_telegram_report(df_quntry_raw, "🍟 *QUNTRY FRY SİNYALLERİ:*")
    genel_msg = build_telegram_report(df_genel_raw, "🎯 *GENEL PİYASA SİNYALLERİ:*")

    total_msg = msg + quntry_msg + "\n" + genel_msg

    if quntry_msg or genel_msg or not only_signals_telegram:
        success, err = send_telegram_message(total_msg)
        if success:
            st.sidebar.success("✅ Akıllı Rapor Telegram'a gönderildi!")
        else:
            st.sidebar.error(f"❌ Hata: {err}")
    else:
        st.sidebar.info("ℹ️ Şu an filtrelere uygun riskiz 'AL' sinyali yok.")

# ==========================================
# 7. OTOMATİK ZAMANLAYICI
# ==========================================
if enable_auto_telegram:
    if "last_bot_run" not in st.session_state:
        st.session_state["last_bot_run"] = 0

    CURRENT_TIME = time.time()
    THIRTY_MINUTES = 1800

    if (CURRENT_TIME - st.session_state["last_bot_run"]) > THIRTY_MINUTES:
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msg = f"🛡️ *AKILLI KRİPTO OTOMATİK RAPOR*\n⏱️ *Saat:* `{now_str}`\n"
        msg += f"📊 *BTC Trend:* `{btc_status}` (`${btc_price}`)\n\n"

        quntry_msg = build_telegram_report(df_quntry_raw, "🍟 *QUNTRY FRY LİSTESİ:*")
        genel_msg = build_telegram_report(df_genel_raw, "🎯 *GENEL PİYASA LİSTESİ:*")
        
        total_msg = msg + quntry_msg + "\n" + genel_msg

        if quntry_msg or genel_msg or not only_signals_telegram:
            send_telegram_message(total_msg)
        
        st.session_state["last_bot_run"] = CURRENT_TIME
