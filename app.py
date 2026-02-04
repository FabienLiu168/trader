# app.py
# -*- coding: utf-8 -*-

import os
import datetime as dt
import requests
import pandas as pd
import streamlit as st
import io
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# =========================
# 基本設定
# =========================
st.set_page_config(
    page_title="O'發哥操盤室",
    layout="wide"
)

APP_TITLE = "O'發哥操盤室"

# =========================
# CSS
# =========================
st.markdown(
    """
    <style>
    .bull{color:#FF3B30}
    .bear{color:#34C759}
    .neut{color:#000000}
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    f"""
    <div style="font-size:2.5rem;font-weight:700;text-align:center;color:#2d82b5;">
        {APP_TITLE}
    </div>
    """,
    unsafe_allow_html=True,
)

# =========================
# FinMind 基礎
# =========================
def get_finmind_token():
    return (
        str(st.secrets.get("FINMIND_TOKEN", "")).strip()
        or os.environ.get("FINMIND_TOKEN", "").strip()
    )

FINMIND_TOKEN = get_finmind_token()
FINMIND_API = "https://api.finmindtrade.com/api/v4/data"

@st.cache_data(ttl=600, show_spinner=False)
def finmind_get(dataset, data_id, start_date, end_date):
    params = {
        "dataset": dataset,
        "start_date": start_date,
        "end_date": end_date,
        "token": FINMIND_TOKEN,
    }
    if data_id:
        params["data_id"] = data_id

    try:
        r = requests.get(FINMIND_API, params=params, timeout=30)
        j = r.json()
    except Exception:
        return pd.DataFrame()

    if j.get("status") != 200:
        return pd.DataFrame()

    return pd.DataFrame(j.get("data", []))

# =========================
# 期權 / 現貨資料
# =========================
@st.cache_data(ttl=600, show_spinner=False)
def fetch_option_latest(trade_date):
    for i in range(1, 6):
        d = trade_date - dt.timedelta(days=i)
        if d.weekday() >= 5:
            continue
        df = finmind_get(
            "TaiwanOptionDaily",
            "TXO",
            d.strftime("%Y-%m-%d"),
            d.strftime("%Y-%m-%d"),
        )
        if not df.empty:
            return df
    return pd.DataFrame()

def option_structure_engine(df_opt):
    if df_opt is None or df_opt.empty:
        return None

    if "call_put" not in df_opt.columns:
        return None

    df = df_opt.copy()
    df["cp"] = df["call_put"].str.lower()
    df["strike"] = pd.to_numeric(df["strike_price"], errors="coerce")
    df["oi"] = pd.to_numeric(df["open_interest"], errors="coerce")
    df = df.dropna(subset=["cp", "strike", "oi"])

    call = df[df["cp"] == "call"]
    put = df[df["cp"] == "put"]
    if call.empty or put.empty:
        return None

    return {
        "call_wall": int(call.loc[call["oi"].idxmax(), "strike"]),
        "put_wall": int(put.loc[put["oi"].idxmax(), "strike"]),
        "dominant": "call" if call["oi"].sum() > put["oi"].sum() else "put",
    }

@st.cache_data(ttl=600, show_spinner=False)
def fetch_index_confirm(trade_date):
    df = finmind_get(
        "TaiwanStockStatisticsOfOrderBookAndTrade",
        None,
        (trade_date - dt.timedelta(days=7)).strftime("%Y-%m-%d"),
        trade_date.strftime("%Y-%m-%d"),
    )
    if df.empty:
        return None

    df = df.sort_values("date")
    today = df.iloc[-1]

    return {
        "vol_today": today["Trading_Volume"],
        "vol_ma5": df["Trading_Volume"].tail(5).mean(),
        "up": today["Up_Count"],
        "down": today["Down_Count"],
    }

def spot_confirm_engine(spot):
    if not spot:
        return {"confirm": False, "reason": "無資料"}

    if spot["vol_today"] > spot["vol_ma5"] and spot["up"] > spot["down"]:
        return {"confirm": True, "reason": "量增價揚"}

    if spot["up"] < spot["down"]:
        return {"confirm": False, "reason": "跌家數多"}

    return {"confirm": False, "reason": "量能不足"}

# =========================
# 期貨 OI
# =========================
def fetch_fut_foreign_oi(trade_date):
    df = finmind_get(
        "TaiwanFuturesInstitutionalInvestors",
        "TX",
        trade_date.strftime("%Y-%m-%d"),
        trade_date.strftime("%Y-%m-%d"),
    )
    if df.empty:
        return None

    df = df[df["institutional_investors"] == "Foreign_Investor"]
    if df.empty:
        return None

    return float(df.iloc[0]["open_interest_net"])

# =========================
# KPI 引擎
# =========================
def fut_trend_engine(price_today, price_prev, oi_today, oi_prev):
    price_diff = price_today - price_prev
    oi_diff = oi_today - oi_prev

    if price_diff > 0 and oi_diff > 0:
        return "趨勢多", "bull", price_diff, oi_diff
    if price_diff < 0 and oi_diff > 0:
        return "趨勢空", "bear", price_diff, oi_diff
    if oi_diff < 0:
        return "震盪", "neut", price_diff, oi_diff
    return "中性", "neut", price_diff, oi_diff

def trend_engine(fut_dir, opt, spot):
    if fut_dir == "趨勢多" and opt and opt["dominant"] == "put" and spot["confirm"]:
        return "偏多可操作"
    if fut_dir == "趨勢空" and opt and opt["dominant"] == "call" and spot["confirm"]:
        return "偏空可操作"
    return "觀望 / 區間"

# =========================
# 第一模組：KPI（已補昨天 vs 今天）
# =========================
def render_tab_option_market(trade_date):
    prev_date = trade_date - dt.timedelta(days=1)

    # === 期貨價格（用台積電當 proxy，避免整段太長）
    df_price = finmind_get(
        "TaiwanStockPrice",
        "2330",
        prev_date.strftime("%Y-%m-%d"),
        trade_date.strftime("%Y-%m-%d"),
    )
    if len(df_price) < 2:
        st.warning("期貨 Proxy 資料不足")
        return

    price_prev = df_price.iloc[-2]["close"]
    price_today = df_price.iloc[-1]["close"]

    oi_today = fetch_fut_foreign_oi(trade_date)
    oi_prev = fetch_fut_foreign_oi(prev_date)

    if oi_today is None or oi_prev is None:
        st.warning("外資 OI 資料不足")
        return

    fut_dir, fut_bias, price_diff, oi_diff = fut_trend_engine(
        price_today, price_prev, oi_today, oi_prev
    )

    # === 選擇權（今日 vs 昨日）
    opt_today = option_structure_engine(fetch_option_latest(trade_date))
    opt_prev = option_structure_engine(fetch_option_latest(prev_date))

    opt_shift = "昨日無資料"
    if opt_today and opt_prev:
        opt_shift = (
            f"Put {opt_today['put_wall']-opt_prev['put_wall']:+}｜"
            f"Call {opt_today['call_wall']-opt_prev['call_wall']:+}"
        )

    # === 現貨（今日 vs 昨日）
    spot_today = spot_confirm_engine(fetch_index_confirm(trade_date))
    spot_prev = spot_confirm_engine(fetch_index_confirm(prev_date))

    if spot_today["confirm"] and not spot_prev["confirm"]:
        spot_trend = "🟢 結構轉強"
    elif not spot_today["confirm"] and spot_prev["confirm"]:
        spot_trend = "🔴 結構轉弱"
    else:
        spot_trend = "⏸ 結構延續"

    final_today = trend_engine(fut_dir, opt_today, spot_today)
    final_prev = trend_engine(fut_dir, opt_prev, spot_prev)

    final_shift = (
        f"{final_prev} → {final_today}"
        if final_today != final_prev
        else "狀態延續"
    )

    st.subheader("📊 大盤分析（昨日 vs 今日）")

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.metric(
            "📈 期貨趨勢",
            fut_dir,
            f"價差 {price_diff:+.0f}｜OI {oi_diff:+,}"
        )

    with c2:
        st.metric(
            "🧩 選擇權防線",
            f"{opt_today['put_wall']}–{opt_today['call_wall']}" if opt_today else "N/A",
            opt_shift
        )

    with c3:
        st.metric(
            "📊 現貨確認",
            "✔" if spot_today["confirm"] else "✖",
            spot_trend
        )

    with c4:
        st.metric(
            "🧠 綜合評估",
            final_today,
            final_shift
        )

# =========================
# 工具函式
# =========================
def is_trading_day(d: dt.date) -> bool:
    return d.weekday() < 5

@st.cache_data(ttl=600)
def get_latest_trading_date(max_lookback=10):
    today = dt.date.today()
    if not FINMIND_TOKEN:
        return today
    for i in range(max_lookback):
        d = today - dt.timedelta(days=i)
        if d.weekday() >= 5:
            continue
        df = finmind_get("TaiwanStockPrice", "2330", d.strftime("%Y-%m-%d"), d.strftime("%Y-%m-%d"))
        if not df.empty:
            return d
    return today

# =========================
# 期貨 / 選擇權
# =========================
@st.cache_data(ttl=600)
def fetch_position_for_trade_date(trade_date):
    df = finmind_get(
        "TaiwanFuturesDaily",
        "TX",
        trade_date.strftime("%Y-%m-%d"),
        (trade_date + dt.timedelta(days=3)).strftime("%Y-%m-%d"),
    )
    if df.empty:
        return df
    return df[df["trading_session"] == "position"].copy()

def pick_main_contract_position(df, trade_date):
    x = df.copy()
    x["ym"] = pd.to_numeric(x["contract_date"], errors="coerce")
    target = trade_date.year * 100 + trade_date.month
    cand = x[x["ym"] >= target]
    return cand.sort_values("ym").iloc[0] if not cand.empty else x.sort_values("ym").iloc[-1]

def get_prev_trading_close(trade_date, lookback_days=7):
    for i in range(1, lookback_days + 1):
        d = trade_date - dt.timedelta(days=i)
        if d.weekday() >= 5:
            continue
        df = fetch_position_for_trade_date(d)
        if df.empty:
            continue
        row = pick_main_contract_position(df, d)
        for k in ("settlement_price", "close"):
            v = row.get(k)
            if v not in (None, "", 0) and pd.notna(v):
                return float(v)
    return None

@st.cache_data(ttl=600)
def fetch_fut_foreign_oi(trade_date):
    df = finmind_get(
        "TaiwanFuturesInstitutionalInvestors",
        "TX",
        trade_date.strftime("%Y-%m-%d"),
        trade_date.strftime("%Y-%m-%d"),
    )
    if df.empty:
        return None
    df = df[df["institutional_investors"] == "Foreign_Investor"]
    if df.empty:
        return None
    return float(df.iloc[0]["open_interest_net"])

# =========================
# TWSE CSV（已修正）
# =========================
@st.cache_data(ttl=600)
def fetch_top20_by_volume_twse_csv(trade_date: dt.date) -> pd.DataFrame:
    date_str = trade_date.strftime("%Y%m%d")
    url = "https://www.twse.com.tw/exchangeReport/MI_INDEX"
    params = {"response": "csv", "date": date_str, "type": "ALL"}

    try:
        r = requests.get(url, params=params, timeout=20, verify=False)
        content = r.content.decode("big5", errors="ignore")
    except Exception as e:
        st.error(f"❌ TWSE CSV 下載失敗：{e}")
        return pd.DataFrame()

    lines = [
        line for line in content.split("\n")
        if line.startswith('"') and len(line.split('","')) >= 16
    ]

    if not lines:
        st.error("❌ TWSE CSV 無有效資料")
        return pd.DataFrame()

    df = pd.read_csv(io.StringIO("\n".join(lines)))

    df = df.rename(columns={
        "證券代號": "股票代碼",
        "證券名稱": "股票名稱",
        "成交股數": "成交量",
        "成交金額": "成交金額",
        "收盤價": "收盤",
    })

    for col in ["成交量", "成交金額", "收盤"]:
        if col in df.columns:
            df[col] = (
                df[col].astype(str)
                .str.replace(",", "", regex=False)
                .replace("--", None)
            )
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["股票代碼", "成交量"])
    return df.sort_values("成交量", ascending=False).head(20).reset_index(drop=True)

# =========================
# 畫表格
# =========================
def render_stock_table_html(df: pd.DataFrame):
    html = "<table border='1' style='width:100%;border-collapse:collapse;'>"
    html += "<tr>" + "".join(f"<th>{c}</th>" for c in df.columns) + "</tr>"
    for _, r in df.iterrows():
        html += "<tr>" + "".join(f"<td>{v}</td>" for v in r) + "</tr>"
    html += "</table>"
    st.markdown(html, unsafe_allow_html=True)

# =========================
# 第二模組
# =========================
def render_tab_stock_futures(trade_date):
    top20 = fetch_top20_by_volume_twse_csv(trade_date)
    if top20.empty:
        st.warning("⚠️ 無成交量資料")
        return

    render_stock_table_html(
        top20[["股票代碼", "股票名稱", "收盤", "成交量", "成交金額"]]
    )

# =========================
# 主流程
# =========================
default_trade_date = get_latest_trading_date()
trade_date = st.date_input("📅 查詢交易日", value=default_trade_date)

if not is_trading_day(trade_date):
    st.warning("📅 非交易日")
    st.stop()

tab1, tab2 = st.tabs(["📈 期權趨勢", "📊 個股期貨"])

with tab1:
    render_tab_option_market(trade_date)
with tab2:
    render_tab_stock_futures(trade_date)
