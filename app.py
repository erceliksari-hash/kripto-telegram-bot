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

# Dinamik Tarama Slider Ayarı
st.sidebar.subheader("🔥 Dinamik Genel Piyasa Taraması")
top_coin_limit = st.sidebar.slider(
    "Borsada Taranacak En Hacimli Coin Sayısı", 
    min_value=20, 
    max_value=100, 
    value=50, 
    step=10
)

st.sidebar.markdown("---")

enable_auto_telegram = st.sidebar.checkbox(
    "30 Dk'da Bir Otomatik Telegram Sinyali Gönder", value=True
)

min_score_telegram = st.sidebar.slider(
    "🎯 Telegram Sinyal Filtresi (Min Skor)", 
    min_value=50, 
    max_value=90, 
    value=75, 
    step=5,
    help="Sadece belirlenen puanın üzerindeki kaliteli sinyaller Telegram'a gönderilir."
)

st.sidebar.markdown("---")

# Quntry Fry Özel Takip Listesi
st.sidebar.subheader("🍟 Quntry Fry Özel Takip Listesi")
quntry_default = "BICOUSDT, RECALLUSDT, ZDTUSDT, BEATUSDT,
BTCUSDT, ETHUSDT, SOLUSDT, AVAXUSDT, NEARUSDT, LINKUSDT, DOGEUSDT, XRPUSDT, 
ADAUSDT, DOTUSDT, SHIBUSDT, MATICUSDT, LTCUSDT, TRONUSDT, UNIUSDT, ATOMUSDT, APTUSDT, ARBUSDT, 
OPUSDT, INJUSDT, SUIUSDT, FETUSDT, RENDERUSDT, PEPEUSDT, FLOKIUSDT, BONKUSDT, TIAUSDT, SEIUSDT, FILUSDT, ICPUSDT"

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
# 4. AKILLI ANALİZ MOTORU, SKORLAMA & KAZANÇ HESABI
# ==========================================

@st.cache_data(ttl=300)
def get_top_volume_symbols(limit=50):
    """Binance borsasından 24h hacmi en yüksek USDT çiftlerini otomatik çeker."""
    try:
        ex = EXCHANGES["Binance"]
        tickers = ex.fetch_tickers()
        usdt_pairs = []
        for symbol, ticker in tickers.items():
            if symbol.endswith("/USDT") and ticker.get("quoteVolume") is not None:
                if not any(x in symbol for x in ["UP/", "DOWN/", "BEAR/", "BULL/"]):
                    usdt_pairs.append({
                        "symbol": symbol.replace("/", ""),
                        "volume": ticker["quoteVolume"]
                    })
        df_sorted = pd.DataFrame(usdt_pairs).sort_values(by="volume", ascending=False)
        return df_sorted.head(limit)["symbol"].tolist()
    except Exception:
        return ["BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "NEARUSDT", "LINKUSDT", "DOGEUSDT", "XRPUSDT"]


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
    return True


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

            recent_resistance = float(df["high"].tail(20).max())
            first_price = float(df.iloc[0]["close"])
            change_24h = ((price - first_price) / first_price) * 100
            vol_24h_m = (df["volume"].sum() * price) / 1_000_000

            # --- AKILLI PUANLAMA (SKOR) HESABI ---
            score = 0
            score_reasons = []

            # 1. BTC Piyasa Durumu (+20 Puan)
            if btc_status == "BULLISH":
                score += 20
                score_reasons.append("BTC Trendi Pozitif")

            # 2. 1H Trend (EMA50 üzeri) (+20 Puan)
            is_bullish_1h = price > latest["ema50"]
            if is_bullish_1h:
                score += 20
                score_reasons.append("1H EMA50 Üzerinde")

            # 3. 4H Ana Trend Uyumu (+20 Puan)
            is_bullish_4h = check_4h_trend(ex_instance, formatted_symbol)
            if is_bullish_4h:
                score += 20
                score_reasons.append("4H Ana Trend Uyumlu")

            # 4. Hacim Teyidi (+20 Puan)
            is_volume_surge = latest["volume"] > (latest["vol_sma"] * 1.3)
            if is_volume_surge:
                score += 20
                score_reasons.append("Yüksek Hacim Patlaması")

            # 5. MACD Kesişimi & RSI İdeal Seviye (+20 Puan)
            is_macd_cross = (prev["macd"] < prev["macd_signal"]) and (latest["macd"] > latest["macd_signal"])
            rsi_val = float(latest["rsi"])
            if is_macd_cross and (35 <= rsi_val <= 65):
                score += 20
                score_reasons.append("MACD Al Kesişimi & RSI İdeal")

            # Sinyal Sınıflandırması
            if score >= 80:
                signal = "🔥 GÜÇLÜ AL"
            elif score >= 60:
                signal = "🟢 AL"
            elif score >= 40:
                signal = "🟡 NÖTR / İZLE"
            else:
                signal = "🔴 SAT / ZAYIF"

            comment = " | ".join(score_reasons) if score_reasons else "Zayıf göstergeler"

            # --- HEDEF (TP), STOP LOSS VE POZİSYON HESABI ---
            atr_val = float(latest["atr"])
            stop_loss = round(price - (atr_val * 1.5), 4)
            target_tp1 = round(price + (atr_val * 1.2), 4)  # Hızlı Kar Al (Break-even)
            target_tp2 = round(price + (atr_val * 2.5), 4)  # Ana Hedef
            target_tp3 = round(max(price + (atr_val * 4.0), recent_resistance), 4) # Maksimum Direnç Hedefi

            risk_per_coin = price - stop_loss
            reward_per_coin = target_tp2 - price
            rr_ratio = round(reward_per_coin / risk_per_coin, 2) if risk_per_coin > 0 else 0

            sl_pct = (risk_per_coin / price)
            max_risk_amount = user_balance * (user_risk_pct / 100)
            rec_position_size = round(max_risk_amount / sl_pct, 2) if sl_pct > 0 else 0
            rec_position_size = min(rec_position_size, user_balance)

            # --- KADEMELİ KÂR VE RİSK HESAPLAMALARI ($) ---
            # TP1: Pozisyonun %50'si satılır
            tp1_gain = round((rec_position_size * 0.50) * ((target_tp1 - price) / price), 2)
            # TP2: Pozisyonun %30'u satılır
            tp2_gain = round((rec_position_size * 0.30) * ((target_tp2 - price) / price), 2)
            # TP3: Kalan %20'si satılır
            tp3_gain = round((rec_position_size * 0.20) * ((target_tp3 - price) / price), 2)
            
            total_potential_gain = round(tp1_gain + tp2_gain + tp3_gain, 2)
            max_potential_loss = round(rec_position_size * sl_pct, 2)

            return {
                "Sembol": symbol,
                "Kaynak Borsa": ex_name,
                "Fiyat ($)": price,
                "Güven Skoru": score,
                "24h Değişim (%)": round(change_24h, 2),
                "24h Hacim (M$)": round(vol_24h_m, 2),
                "RSI (14)": round(rsi_val, 1),
                "Stop Loss": stop_loss,
                "Hedef (TP1)": target_tp1,
                "Hedef (TP2)": target_tp2,
                "Hedef (TP3)": target_tp3,
                "TP1 Kar ($)": tp1_gain,
                "TP2 Kar ($)": tp2_gain,
                "TP3 Kar ($)": tp3_gain,
                "Toplam Potansiyel Kar ($)": total_potential_gain,
                "Maks Risk ($)": max_potential_loss,
                "R:R Oranı": rr_ratio,
                "Önerilen Poz ($)": rec_position_size,
                "Sinyal": signal,
                "Yorum": comment,
                "Update Time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

        except Exception:
            continue

    return None if not return_df else (None, None)


def analyze_symbol_list_fast(symbols, timeframe="1h", btc_status="BULLISH"):
    results = []
    with ThreadPoolExecutor(max_workers=12) as executor:
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


def build_clean_telegram_report(df_raw, title, min_score=75):
    """Kademeli kâr tutarlarını ($) içeren net ve sade Telegram mesaj kartı oluşturur."""
    if df_raw.empty:
        return ""
    
    filtered_df = df_raw[df_raw["Güven Skoru"] >= min_score].sort_values(by="Güven Skoru", ascending=False)
    
    if filtered_df.empty:
        return ""

    msg = f"{title}\n"
    for _, row in filtered_df.iterrows():
        msg += f"───────────────────────\n"
        msg += f"🎯 *{row['Sinyal']}* (%{row['Güven Skoru']} Güven Skoru)\n"
        msg += f"🪙 *Coin:* `{row['Sembol']}` ({row['Kaynak Borsa']})\n"
        msg += f"🟢 *Giriş Fiyatı:* `${row['Fiyat ($)']}` | *Önerilen Poz:* `${row['Önerilen Poz ($)']}`\n"
        msg += f"🛑 *Stop Loss:* `${row['Stop Loss']}` _(Maks Risk: -${row['Maks Risk ($)']})_\n"
        msg += f"🎯 *TP1 (`${row['Hedef (TP1)']}`):* Poz %50 Kapat ➡️ *+${row['TP1 Kar ($)']} Kâr* _(Stop Girişe Çekilir)_\n"
        msg += f"🎯 *TP2 (`${row['Hedef (TP2)']}`):* Poz %30 Kapat ➡️ *+${row['TP2 Kar ($)']} Kâr*\n"
        msg += f"🚀 *TP3 (`${row['Hedef (TP3)']}`):* Poz %20 Kapat ➡️ *+${row['TP3 Kar ($)']} Kâr*\n"
        msg += f"💰 *Tüm Hedefler Gelirse Toplam Kâr:* *+${row['Toplam Potansiyel Kar ($)']}*\n"
        msg += f"💡 *Özet Neden:* _{row['Yorum']}_\n"
    
    return msg


# ==========================================
# 6. EKRAN ARAYÜZÜ VE TARAMA
# ==========================================
st.title("🛡️ Akıllı Kripto Analiz & Risk Yönetim Paneli")

# Dinamik Liste Çekimi
dynamic_genel_symbols = get_top_volume_symbols(limit=top_coin_limit)

# BTC Trend Kontrolü
btc_status, btc_price = get_btc_market_status()

if btc_status == "BULLISH":
    st.success(f"🟢 **Piyasa Durumu:** Bitcoin (BTC) `${btc_price}` ile **YÜKSELİŞ TRENDİNDE**. Altcoin sinyalleri güvenli.")
elif btc_status == "BEARISH":
    st.error(f"🔴 **Piyasa Durumu:** Bitcoin (BTC) `${btc_price}` ile **DÜŞÜŞ TRENDİNDE**. Altcoin sinyallerinde DİKKATLİ olun!")
else:
    st.warning("⚠️ BTC piyasa trendi alınamadı, genel tarama yapılıyor.")

# Paralel Tarama Başlat
start_time = time.time()
df_quntry_raw = analyze_symbol_list_fast(quntry_symbol_list, timeframe=quntry_timeframe, btc_status=btc_status)
df_genel_raw = analyze_symbol_list_fast(dynamic_genel_symbols, timeframe="1h", btc_status=btc_status)
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
c3.metric("Dinamik Taranan Coin", f"{len(df_genel_raw)} / {top_coin_limit}")
c4.metric("Kasa / İşlem Riski", f"${user_balance} / %{user_risk_pct}")

# --- BÖLÜM 1: QUNTRY FRY LİSTESİ ---
st.markdown("### 🍟 Quntry Fry Özel Takip Listesi")
if not df_quntry.empty:
    st.dataframe(df_quntry.sort_values(by="Güven Skoru", ascending=False), use_container_width=True)
else:
    st.warning("⚠️ Belirlenen filtrelere uyan Quntry Fry coini bulunamadı.")

st.markdown("---")

# --- BÖLÜM 2: GENEL PİYASA ANALİZİ ---
st.markdown(f"### 🎯 Piyasadaki En Hacimli Top {top_coin_limit} Coin Analizi (Otomatik)")
if not df_genel.empty:
    st.dataframe(df_genel.sort_values(by="Güven Skoru", ascending=False), use_container_width=True)
else:
    st.warning("⚠️ Belirlenen filtrelere uyan Genel piyasa coini bulunamadı.")

st.markdown("---")

# --- BÖLÜM 3: İNTERAKTİF GRAFİK EKRANI ---
st.markdown("### 📈 Canlı Grafik İnceleme Paneli")
all_available_symbols = list(set(dynamic_genel_symbols + quntry_symbol_list))
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
        ), row=1, col=1)

        fig.add_hline(y=70, line_dash="dash", line_color="red", row=2, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="green", row=2, col=1)

        fig.update_layout(height=500, xaxis_rangeslider_visible=False, template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)

# --- BÖLÜM 4: TELEGRAM BİLDİRİMLERİ ---
st.sidebar.markdown("---")
if st.sidebar.button("📤 Telegram Raporunu Şimdi Gönder"):
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = f"🛡️ *AKILLI KRİPTO FIRSAT RAPORU*\n⏱️ *Saat:* `{now_str}`\n"
    msg += f"📊 *BTC Trend:* `{btc_status}` (`${btc_price}`)\n"

    quntry_msg = build_clean_telegram_report(df_quntry_raw, "\n🍟 *QUNTRY FRY SİNYALLERİ:*", min_score=min_score_telegram)
    genel_msg = build_clean_telegram_report(df_genel_raw, f"\n🎯 *DİNAMİK TOP {top_coin_limit} SİNYALLERİ:*", min_score=min_score_telegram)

    total_msg = msg + quntry_msg + genel_msg

    if quntry_msg or genel_msg:
        success, err = send_telegram_message(total_msg)
        if success:
            st.sidebar.success("✅ Yüksek kaliteli sinyal raporu Telegram'a gönderildi!")
        else:
            st.sidebar.error(f"❌ Hata: {err}")
    else:
        st.sidebar.info(f"ℹ️ Şu an {min_score_telegram}+ puanı geçen kalitede sinyal bulunamadı.")

# ==========================================
# 7. OTOMATİK ZAMANLAYICI (30 DAKİKADA BİR)
# ==========================================
if enable_auto_telegram:
    if "last_bot_run" not in st.session_state:
        st.session_state["last_bot_run"] = 0

    CURRENT_TIME = time.time()
    THIRTY_MINUTES = 1800

    if (CURRENT_TIME - st.session_state["last_bot_run"]) > THIRTY_MINUTES:
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msg = f"🛡️ *AKILLI KRİPTO OTOMATİK RAPOR*\n⏱️ *Saat:* `{now_str}`\n"
        msg += f"📊 *BTC Trend:* `{btc_status}` (`${btc_price}`)\n"

        quntry_msg = build_clean_telegram_report(df_quntry_raw, "\n🍟 *QUNTRY FRY SİNYALLERİ:*", min_score=min_score_telegram)
        genel_msg = build_clean_telegram_report(df_genel_raw, f"\n🎯 *DİNAMİK TOP {top_coin_limit} SİNYALLERİ:*", min_score=min_score_telegram)
        
        total_msg = msg + quntry_msg + genel_msg

        if quntry_msg or genel_msg:
            send_telegram_message(total_msg)
        
        st.session_state["last_bot_run"] = CURRENT_TIME
