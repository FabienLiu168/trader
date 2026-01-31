# app.py
# -*- coding: utf-8 -*-

import os
import datetime as dt
import requests
import pandas as pd
import streamlit as st

# =========================
# 基本設定
# =========================
st.set_page_config(
    page_title="大盤趨勢/個股期貨 (法酷交易室)",
    layout="wide"
)

APP_TITLE = "大盤趨勢/個股期貨 (法酷交易室)"

st.markdown(
    """
    <style>
    div[data-testid="stAppViewContainer"] > .main { padding-top: 3.2rem; }

    .app-title{
        color: #2d82b5;
        font-size:2.5rem;
        font-weight:750;
        margin-top:-62px;
        text-align:center;
    }

    .app-subtitle{
        font-size:1.0rem;
        text-align:center;
    }

    .fut-section-title,.opt-section-title{
        font-size:1.8rem !important;
        font-weight:400 !important;
        display:flex;
        align-items:center;
    }

    .kpi-card{
        border:1px solid rgba(255,255,255,.12);
        border-radius:14px;
        padding:16px;
        background:#F4F6F5;
        box-shadow:0 6px 22px rgba(0,0,0,.18);
        min-height:140px;
    }

    .bull{color:#FF3B30}
    .bear{color:#34C759}
    .neut{color:#000000}
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    f"""
    <div class="app-title">{APP_TITLE}</div>
    <div class="app-subtitle">
        ✅ 期貨基準：Position 結算價　
        ✅ 選擇權：ΔOI × 結構 × 價格行為　
    </div>
    """,
    unsafe_allow_html=True,
)

# =========================
# 工具
# =========================
def is_trading_day(d: dt.date) -> bool:
    return d.weekday() < 5


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def get_finmind_token():
    return (
        str(st.secrets.get("FINMIND_TOKEN", "")).strip()
        or os.environ.get("FINMIND_TOKEN", "").strip()
    )


FINMIND_TOKEN = get_finmind_token()
FINMIND_API = "https://api.finmindtrade.com/api/v4/data"


@st.cache_data(ttl=600)
def finmind_get(dataset, data_id, start_date, end_date):
    if not FINMIND_TOKEN:
        return pd.DataFrame()

    r = requests.get(
        FINMIND_API,
        params={
            "dataset": dataset,
            "data_id": data_id,
            "start_date": start_date,
            "end_date": end_date,
            "token": FINMIND_TOKEN,
        },
        timeout=30,
    )

    if r.status_code != 200:
        return pd.DataFrame()

    return pd.DataFrame(r.json().get("data", []))


# =========================
# 第一模組：期權大盤
# =========================
def render_tab_option_market(trade_date: dt.date):
    st.markdown(
        "<h2 class='fut-section-title'>📈 台指期貨｜結算方向判斷</h2>",
        unsafe_allow_html=True,
    )

    df = finmind_get(
        "TaiwanFuturesDaily",
        "TX",
        trade_date.strftime("%Y-%m-%d"),
        (trade_date + dt.timedelta(days=3)).strftime("%Y-%m-%d"),
    )

    if df.empty:
        st.error("❌ 無期貨資料")
        return

    row = df.iloc[0]
    price = float(row.get("close", 0))

    st.metric("期貨收盤價", f"{price:,.0f}")


# =========================
# 第二模組（暫留）
# =========================
def render_tab_stock_futures(trade_date: dt.date):
    st.markdown(
        "<h2 class='fut-section-title'>📊 個股期貨｜現貨成交量 Top10</h2>",
        unsafe_allow_html=True,
    )
    st.info("⚠️ 尚未載入資料")


# =========================
# 主流程
# =========================
trade_date = st.date_input(
    "📅 查詢交易日（結算）",
    value=dt.date.today()
)

if not is_trading_day(trade_date):
    st.warning("📅 非交易日")
    st.stop()

tab1, tab2 = st.tabs(["📈 期權大盤", "📊 個股期貨"])

with tab1:
    render_tab_option_market(trade_date)

with tab2:
    render_tab_stock_futures(trade_date)
