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
    div[data-testid="stAppViewContainer"] > .main {
        padding-top: 3.2rem;
    }

    .app-title{
        color: #2d82b5;
        font-size:2.5rem;
        font-weight:750;
        margin-top:-62px;
        text-align:center;
        letter-spacing:0.5px;
        margin-bottom:1px;
    }

    .app-subtitle{
        font-size:1.0rem;
        margin:.45rem 0 1.1rem;
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
        padding:16px 18px;
        background:#F4F6F5;
        box-shadow:0 6px 22px rgba(0,0,0,.18);
        min-height:140px;
        display:flex;
        flex-direction:column;
        justify-content:space-between;
    }

    .kpi-title{ font-size:1.2rem;opacity:.85 }
    .kpi-value{ font-size:1.7rem;font-weight:500;line-height:1.5 }
    .kpi-sub{ font-size:1.0rem;opacity:.65;line-height:1.5}

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

    r = requests.get(FINMIND_API, params=params, timeout=30)

    try:
        j = r.json()
    except Exception:
        return pd.DataFrame()

    if j.get("status") != 200:
        return pd.DataFrame()

    return pd.DataFrame(j.get("data", []))


@st.cache_data(ttl=600, show_spinner=False)
def fetch_single_stock_daily(stock_id: str, trade_date: dt.date):
    return finmind_get(
        dataset="TaiwanStockPrice",
        data_id=stock_id,
        start_date=(trade_date - dt.timedelta(days=3)).strftime("%Y-%m-%d"),
        end_date=trade_date.strftime("%Y-%m-%d"),
    )


def render_stock_table_html(df: pd.DataFrame):
    st.markdown(
        """
        <style>
        .stock-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 18px;
        }
        .stock-table th {
            background-color: #f4f6f8;
            padding: 10px;
            text-align: center;
            font-size: 16px;
            border-bottom: 1px solid #ddd;
        }
        .stock-table td {
            padding: 10px;
            text-align: right;
            border-bottom: 1px solid #eee;
        }
        .stock-table td:nth-child(1),
        .stock-table td:nth-child(2) {
            text-align: center;
            font-weight: 600;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    html = "<table class='stock-table'><thead><tr>"
    for col in df.columns:
        html += f"<th>{col}</th>"
    html += "</tr></thead><tbody>"

    for _, row in df.iterrows():
        html += "<tr>"
        for v in row:
            html += f"<td>{v}</td>"
        html += "</tr>"

    html += "</tbody></table>"
    st.markdown(html, unsafe_allow_html=True)


# =========================
# 第一模組：期權大盤
# =========================
def render_tab_option_market(trade_date: dt.date):
    st.markdown(
        "<h2 class='fut-section-title'>📈 台指期貨｜趨勢方向</h2>",
        unsafe_allow_html=True,
    )

    df = finmind_get(
        "TaiwanFuturesDaily",
        "TX",
        trade_date.strftime("%Y-%m-%d"),
        (trade_date + dt.timedelta(days=3)).strftime("%Y-%m-%d"),
    )

    if df.empty:
        st.error("❌ 無期貨結算資料")
        return

    row = df.iloc[0]
    st.metric("期貨收盤價", f"{float(row.get('close', 0)):.0f}")


# =========================
# 第二模組：個股期貨（測試版）
# =========================
def render_tab_stock_futures(trade_date: dt.date):
    st.markdown(
        "<h2 class='fut-section-title'>📊 個股期貨｜測試資料</h2>",
        unsafe_allow_html=True,
    )

    rows = []
    for sid, name in [("2330", "台積電"), ("2303", "聯電")]:
        df = fetch_single_stock_daily(sid, trade_date)
        df_day = df[df["date"] == trade_date.strftime("%Y-%m-%d")]

        if df_day.empty:
            continue

        r = df_day.iloc[0]
        rows.append({
            "股票代碼": sid,
            "股票名稱": name,
            "開盤": r["open"],
            "最高": r["max"],
            "最低": r["min"],
            "收盤": r["close"],
            "成交量": f"{int(r['Trading_Volume'] / 10000):,} 萬",
            "成交金額": f"{int(r['Trading_money'] / 1_000_000):,} 百萬",
        })

    if not rows:
        st.warning("⚠️ 查詢日無任何個股資料")
        return

    render_stock_table_html(pd.DataFrame(rows))


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
