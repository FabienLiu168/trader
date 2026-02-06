# app.py
# -*- coding: utf-8 -*-

import os
import datetime as dt
import requests
import pandas as pd
import streamlit as st
import io
import urllib3
import time

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# =========================
# 基本設定
# =========================
st.set_page_config(page_title="O'法哥操盤室", layout="wide")
APP_TITLE = "O'法哥操盤室"

st.markdown(
    """
    <style>
    .bull{color:#FF3B30}
    .bear{color:#34C759}
    .neut{color:#000000}
    table {font-size:16px;}

    label {
        font-size: 20px !important;
        font-weight: 600;
    }

    div[data-baseweb="input"] input {
        font-size: 20px !important;
        font-weight: 600;
    }

    button[data-baseweb="tab"] {
        font-size: 18px !important;
        font-weight: 600;
        padding: 10px 16px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    f"<div style='font-size:2.5rem;font-weight:700;text-align:center;color:#2d82b5;'>{APP_TITLE}</div>",
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


@st.cache_data(ttl=600)
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
# 安全工具
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
        df = finmind_get(
            "TaiwanStockPrice",
            "2330",
            d.strftime("%Y-%m-%d"),
            d.strftime("%Y-%m-%d"),
        )
        if not df.empty:
            return d
    return today


@st.cache_data(ttl=600)
def get_prev_stock_close(stock_id: str, trade_date: dt.date):
    df = finmind_get(
        "TaiwanStockPrice",
        stock_id,
        (trade_date - dt.timedelta(days=7)).strftime("%Y-%m-%d"),
        trade_date.strftime("%Y-%m-%d"),
    )
    if df.empty:
        return None

    df = df.sort_values("date")
    prev = df[df["date"] < trade_date.strftime("%Y-%m-%d")]
    if prev.empty:
        return None

    return float(prev.iloc[-1]["close"])


def format_close_with_prev(row, trade_date):
    try:
        stock_id = str(row.get("股票代碼", "")).strip()
        close_today = row.get("收盤", None)

        if not stock_id or close_today is None or pd.isna(close_today):
            return ""

        close_today = float(close_today)
        prev_close = get_prev_stock_close(stock_id, trade_date)
        if prev_close in (None, 0):
            return f"{close_today:.2f}"

        diff = close_today - prev_close
        pct = diff / prev_close * 100

        if diff > 0:
            color = "#FF3B30"
        elif diff < 0:
            color = "#34C759"
        else:
            color = "#000000"

        return (
            f"<span style='color:{color};font-weight:600'>"
            f"{close_today:.2f} ({pct:+.2f}%)</span>"
        )
    except Exception:
        return ""


# =========================
# 外資期貨 OI
# =========================
@st.cache_data(ttl=600)
def fetch_fut_foreign_oi(trade_date: dt.date):
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


def get_prev_fut_foreign_oi(trade_date: dt.date, lookback_days=7):
    for i in range(1, lookback_days + 1):
        d = trade_date - dt.timedelta(days=i)
        if d.weekday() >= 5:
            continue
        oi = fetch_fut_foreign_oi(d)
        if oi is not None:
            return oi
    return None


# =========================
# 選擇權
# =========================
@st.cache_data(ttl=600)
def fetch_option_latest(trade_date):
    for i in range(1, 6):
        d = trade_date - dt.timedelta(days=i)
        if d.weekday() >= 5:
            continue
        df = finmind_get("TaiwanOptionDaily", "TXO", d.strftime("%Y-%m-%d"), d.strftime("%Y-%m-%d"))
        if not df.empty:
            return df
    return pd.DataFrame()


def option_structure_engine(df):
    if df is None or df.empty or "call_put" not in df.columns:
        return None

    x = df.copy()
    x["cp"] = x["call_put"].str.lower()
    x["strike"] = pd.to_numeric(x["strike_price"], errors="coerce")
    x["oi"] = pd.to_numeric(x["open_interest"], errors="coerce")
    x = x.dropna(subset=["cp", "strike", "oi"])

    call = x[x["cp"] == "call"]
    put = x[x["cp"] == "put"]
    if call.empty or put.empty:
        return None

    return {
        "call_wall": int(call.loc[call["oi"].idxmax(), "strike"]),
        "put_wall": int(put.loc[put["oi"].idxmax(), "strike"]),
        "dominant": "call" if call["oi"].sum() > put["oi"].sum() else "put",
    }


# =========================
# 現貨
# =========================
@st.cache_data(ttl=600)
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
    t = df.iloc[-1]
    return {
        "vol_today": t["Trading_Volume"],
        "vol_ma5": df["Trading_Volume"].tail(5).mean(),
        "up": t["Up_Count"],
        "down": t["Down_Count"],
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
# KPI & 主頁
# =========================
def render_tab_option_market(trade_date):
    df_price = finmind_get(
        "TaiwanStockPrice",
        "2330",
        (trade_date - dt.timedelta(days=3)).strftime("%Y-%m-%d"),
        trade_date.strftime("%Y-%m-%d"),
    )

    if len(df_price) < 2:
        st.warning("價格資料不足")
        return

    df_price = df_price.sort_values("date")
    price_prev = df_price.iloc[-2]["close"]
    price_today = df_price.iloc[-1]["close"]
    price_diff = price_today - price_prev

    oi_today = fetch_fut_foreign_oi(trade_date)
    oi_prev = get_prev_fut_foreign_oi(trade_date)

    fut_dir = "中性"
    oi_disp = "資料不足"
    if oi_today is not None and oi_prev is not None:
        fut_dir, _, _, oi_diff = fut_trend_engine(price_today, price_prev, oi_today, oi_prev)
        oi_disp = f"{oi_diff:+,.0f}"

    opt_today = option_structure_engine(fetch_option_latest(trade_date))
    spot_today = spot_confirm_engine(fetch_index_confirm(trade_date))

    st.subheader("📊 大盤分析")
    st.metric("📈 期貨趨勢", fut_dir, f"價差 {price_diff:+.0f}｜OI {oi_disp}")

def render_tab_stock_futures(trade_date):
    st.subheader("📊 前20大個股盤後籌碼")

    df = fetch_top20_by_amount_twse_csv(trade_date)

    required_cols = {"股票代碼", "股票名稱"}
    if df.empty or not required_cols.issubset(df.columns):
        st.warning("⚠️ 查無當日前 20 大成交資料")
        return

    st.markdown("### 📥 券商分點查詢輔助")

    query_list = df[["股票代碼", "股票名稱"]].copy()
    query_list["查詢日"] = trade_date.strftime("%Y-%m-%d")

    st.download_button(
        "📥 下載『今日券商分點查詢清單（CSV）』",
        data=query_list.to_csv(index=False, encoding="utf-8-sig"),
        file_name=f"twse_bsr_query_list_{trade_date.strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )

    use_twse = st.checkbox("📡 使用 TWSE 官方券商買賣資料（較慢）", value=False)
    stock_ids = df["股票代碼"].astype(str).tolist()

    summary = {}

    if use_twse:
        with st.spinner("📡 讀取 TWSE 官方券商資料中，請稍候..."):
            summary = fetch_twse_broker_summary(stock_ids, trade_date)
    else:
        uploaded = st.file_uploader(
            "📤 上傳券商分點 CSV（用於買賣超分析）",
            type=["csv"],
        )
        if uploaded:
            df_branch = parse_branch_csv(uploaded)
            if df_branch.empty:
                st.error("❌ CSV 無法解析")
            else:
                summary = calc_top5_buy_sell(df_branch)
                st.success("✅ 已完成券商分點分析")

    df["收盤"] = df.apply(lambda r: format_close_with_prev(r, trade_date), axis=1)
    df["成交量"] = df["成交量"].apply(lambda x: f"{int(x/1000):,}")
    df["成交金額"] = df["成交金額"].apply(lambda x: f"{x/1_000_000:,.0f} M")
    df["買超"] = df["股票代碼"].apply(
        lambda s: f"{summary.get(s, {}).get('買超', ''):,}" if s in summary else ""
    )
    df["賣超"] = df["股票代碼"].apply(
        lambda s: f"{summary.get(s, {}).get('賣超', ''):,}" if s in summary else ""
    )
    df["券商分點"] = df["股票代碼"].apply(
        lambda s: twse_bsr_hint_link(s, trade_date)
    )

    render_stock_table_html(
        df[["股票代碼", "股票名稱", "收盤", "成交量", "成交金額", "買超", "賣超", "券商分點"]]
    )

# =========================
# 主流程
# =========================
default_trade_date = get_latest_trading_date()
trade_date = st.date_input("📅 查詢交易日", value=default_trade_date)

if not is_trading_day(trade_date):
    st.warning("非交易日")
    st.stop()

tab1, tab2 = st.tabs(["📈 期權趨勢", "📊 個股期貨"])
with tab1:
    render_tab_option_market(trade_date)
with tab2:
    render_tab_stock_futures(trade_date)
