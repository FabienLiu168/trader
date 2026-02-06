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
st.set_page_config(page_title="O'法哥操盤室", layout="wide")
APP_TITLE = "O'法哥操盤室"

st.markdown(
    """
    <style>
    table {font-size:16px;}
    label { font-size: 20px !important; font-weight: 600; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    f"<div style='font-size:2.2rem;font-weight:700;text-align:center;color:#2d82b5;'>{APP_TITLE}</div>",
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
        df = finmind_get(
            "TaiwanOptionDaily",
            "TXO",
            d.strftime("%Y-%m-%d"),
            d.strftime("%Y-%m-%d"),
        )
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
# 第一組模組：期權趨勢（完整保留）
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

    if oi_today is not None and oi_prev is not None:
        if price_diff > 0 and oi_today - oi_prev > 0:
            fut_dir = "趨勢多"
        elif price_diff < 0 and oi_today - oi_prev > 0:
            fut_dir = "趨勢空"
        else:
            fut_dir = "震盪"
        oi_disp = f"{oi_today - oi_prev:+,.0f}"
    else:
        fut_dir = "中性"
        oi_disp = "資料不足"

    opt_today = option_structure_engine(fetch_option_latest(trade_date))

    st.subheader("📈 期權趨勢（第一模組）")
    st.metric(
        "期貨趨勢",
        fut_dir,
        f"價差 {price_diff:+.0f}｜OI {oi_disp}",
    )

    if opt_today:
        st.info(
            f"選擇權防線：Put {opt_today['put_wall']} / Call {opt_today['call_wall']}"
        )


# =========================
# 第二組模組：個股表格（穩定版）
# =========================
@st.cache_data(ttl=600)
def fetch_top20_by_amount_twse_csv(trade_date):
    url = "https://www.twse.com.tw/exchangeReport/MI_INDEX"
    params = {
        "response": "csv",
        "date": trade_date.strftime("%Y%m%d"),
        "type": "ALL",
    }
    r = requests.get(url, params=params, timeout=20, verify=False)
    text = r.content.decode("big5", errors="ignore")

    rows = [
        l for l in text.split("\n")
        if l.startswith('"') and len(l.split('","')) >= 16
    ]
    if not rows:
        return pd.DataFrame()

    df = pd.read_csv(io.StringIO("\n".join(rows)), engine="python")
    df = df.rename(columns={
        "證券代號": "股票代碼",
        "證券名稱": "股票名稱",
        "成交股數": "成交量",
        "成交金額": "成交金額",
        "收盤價": "收盤",
    })

    for c in ["成交量", "成交金額", "收盤"]:
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", ""), errors="coerce")

    return df.sort_values("成交金額", ascending=False).head(20)


def render_tab_stock_futures(trade_date):
    st.subheader("📊 前20大個股盤後籌碼（第二模組）")

    df = fetch_top20_by_amount_twse_csv(trade_date)
    if df.empty:
        st.warning("無資料")
        return

    df["成交量"] = df["成交量"].apply(lambda x: f"{int(x/1000):,}")
    df["成交金額"] = df["成交金額"].apply(lambda x: f"{x/1_000_000:,.0f} M")
    df["買超"] = ""
    df["賣超"] = ""
    df["券商分點"] = df["股票代碼"].apply(
        lambda s: (
            "<a href='https://bsr.twse.com.tw/bshtm/bsMenu.aspx' "
            f"target='_blank' title='股票代碼 {s}'>查詢</a>"
        )
    )

    st.dataframe(
        df[["股票代碼","股票名稱","收盤","成交量","成交金額","買超","賣超","券商分點"]],
        use_container_width=True,
    )


# =========================
# 主流程
# =========================
trade_date = st.date_input("📅 查詢交易日", value=dt.date.today())

if not is_trading_day(trade_date):
    st.warning("非交易日")
    st.stop()

tab1, tab2 = st.tabs(["📈 期權趨勢", "📊 個股期貨"])

with tab1:
    render_tab_option_market(trade_date)

with tab2:
    render_tab_stock_futures(trade_date)
