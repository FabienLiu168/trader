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
    f"<div style='font-size:2.5rem;font-weight:700;text-align:center;color:#2d82b5;'>{APP_TITLE}</div>",
    unsafe_allow_html=True,
)

# =========================
# 工具函式
# =========================
def is_trading_day(d: dt.date) -> bool:
    return d.weekday() < 5


def fmt_num(x):
    return f"{int(x):,}" if isinstance(x, (int, float)) else ""


def twse_bsr_download_link(stock_id: str) -> str:
    return (
        "<a href='https://bsr.twse.com.tw/bshtm/bsMenu.aspx' "
        f"target='_blank' title='股票代碼 {stock_id}'>查詢</a>"
    )


# =========================
# 資料來源
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

def parse_branch_csv(file):
    """
    解析 TWSE 券商分點『純文字格式』CSV（例如 2330.csv）
    """
    try:
        # 直接當純文字讀
        text = file.read().decode("big5", errors="ignore")
    except Exception:
        return pd.DataFrame()

    lines = text.splitlines()

    rows = []

    for line in lines:
        # 略過說明列
        if "券商買賣股票成交價量資訊" in line:
            continue
        if line.strip().startswith("股票代碼"):
            continue
        if line.strip().startswith("序號"):
            continue

        # 用空白切（同時處理全形空白）
        parts = line.replace("　", " ").split()

        # 至少要有左邊一組
        if len(parts) >= 5:
            # 左半部
            try:
                rows.append({
                    "券商": parts[1],
                    "買進": int(parts[3]),
                    "賣出": int(parts[4]),
                })
            except Exception:
                pass

        # 右半部（有些行會有）
        if len(parts) >= 11:
            try:
                rows.append({
                    "券商": parts[7],
                    "買進": int(parts[9]),
                    "賣出": int(parts[10]),
                })
            except Exception:
                pass

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["買賣超"] = df["買進"] - df["賣出"]

    return df


def calc_top5_buy_sell(df):
    if df.empty or "買賣超" not in df.columns:
        return {}

    top_buy = (
        df[df["買賣超"] > 0]
        .sort_values("買賣超", ascending=False)
        .head(5)["買賣超"]
        .sum()
    )

    top_sell = (
        df[df["買賣超"] < 0]
        .sort_values("買賣超")
        .head(5)["買賣超"]
        .sum()
    )

    return {
        "買超": int(top_buy),
        "賣超": int(abs(top_sell)),
    }



# =========================
# HTML 表格
# =========================
def render_stock_table_html(df: pd.DataFrame):
    html = "<table style='width:100%;border-collapse:collapse;'>"
    html += "<thead><tr>"
    for c in df.columns:
        html += f"<th style='padding:8px;border:1px solid #555;background:#2b2b2b;color:white'>{c}</th>"
    html += "</tr></thead><tbody>"

    for _, row in df.iterrows():
        html += "<tr>"
        for v in row:
            html += f"<td style='padding:8px;border:1px solid #444;text-align:center'>{v}</td>"
        html += "</tr>"

    html += "</tbody></table>"
    st.markdown(html, unsafe_allow_html=True)


# =========================
# 主表模組
# =========================
def render_tab_stock_futures(trade_date):
    st.subheader("📊 前20大個股盤後籌碼")

    if "broker_done" not in st.session_state:
        st.session_state.broker_done = {}

    df = fetch_top20_by_amount_twse_csv(trade_date)

    if df.empty:
        st.warning("無資料")
        return

    df["成交量"] = df["成交量"].apply(lambda x: f"{int(x/1000):,}")
    df["成交金額"] = df["成交金額"].apply(lambda x: f"{x/1_000_000:,.0f} M")

    df["買超"] = df["股票代碼"].apply(
        lambda s: fmt_num(st.session_state.broker_done.get(str(s), {}).get("買超"))
    )
    df["賣超"] = df["股票代碼"].apply(
        lambda s: fmt_num(st.session_state.broker_done.get(str(s), {}).get("賣超"))
    )

    df["券商分點"] = df["股票代碼"].apply(
        lambda s: "✔ 已完成" if str(s) in st.session_state.broker_done else ""
    )
    df["下載"] = df["股票代碼"].apply(twse_bsr_download_link)
    df["上傳"] = ""

    render_stock_table_html(
        df[["股票代碼","股票名稱","成交量","成交金額","買超","賣超","券商分點","下載","上傳"]]
    )

    st.markdown("### ⬆️ 單一股票券商分點 CSV 上傳")

    for sid in df["股票代碼"].astype(str):
        if sid in st.session_state.broker_done:
            continue

        uploaded = st.file_uploader(
            f"📤 上傳 {sid} 券商分點 CSV",
            type=["csv"],
            key=f"upload_{sid}"
        )

        if uploaded:
            df_branch = parse_branch_csv(uploaded)
            if df_branch.empty:
                st.error(f"❌ {sid} CSV 無法解析")
            else:
                result = calc_top5_buy_sell(df_branch)
                if sid in result:
                    st.session_state.broker_done[sid] = result[sid]
                    st.success(f"✅ {sid} 買賣超已完成")


# =========================
# 主流程
# =========================
trade_date = st.date_input("📅 查詢交易日", value=dt.date.today())

if not is_trading_day(trade_date):
    st.warning("非交易日")
    st.stop()

render_tab_stock_futures(trade_date)
