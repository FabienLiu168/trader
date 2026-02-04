filename,content
app.py,"# app.py
# -*- coding: utf-8 -*-

import os
import datetime as dt
import requests
import pandas as pd
import streamlit as st
import io
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ======================================================
# 基本設定
# ======================================================
st.set_page_config(page_title=""O'發哥操盤室"", layout=""wide"")

APP_TITLE = ""O'發哥操盤室""

st.markdown(f"""
<style>
.bull {{ color:#FF3B30; }}
.bear {{ color:#34C759; }}
.neut {{ color:#000000; }}

.kpi-card {{
  border-radius:14px;
  padding:16px;
  background:#F4F6F5;
  box-shadow:0 6px 18px rgba(0,0,0,.12);
}}

.kpi-title {{ font-size:1.1rem; }}
.kpi-value {{ font-size:1.6rem; font-weight:600; }}
.kpi-sub {{ font-size:.9rem; opacity:.7; }}

.stock-table {{
  width:100%;
  border-collapse:collapse;
}}
.stock-table th {{
  background:#222;
  color:#fff;
  padding:8px;
}}
.stock-table td {{
  padding:8px;
  border-bottom:1px solid #eee;
  text-align:right;
}}
.stock-table td:nth-child(1),
.stock-table td:nth-child(2) {{
  text-align:center;
  font-weight:600;
}}
</style>
<div style='text-align:center;font-size:2.3rem;font-weight:700'>{APP_TITLE}</div>
""", unsafe_allow_html=True)

# ======================================================
# FinMind 基礎
# ======================================================
def get_finmind_token():
    return (
        str(st.secrets.get(""FINMIND_TOKEN"", """")).strip()
        or os.environ.get(""FINMIND_TOKEN"", """").strip()
    )

FINMIND_TOKEN = get_finmind_token()
FINMIND_API = ""https://api.finmindtrade.com/api/v4/data""

@st.cache_data(ttl=600, show_spinner=False)
def finmind_get(dataset, data_id, start_date, end_date):
    params = dict(dataset=dataset, start_date=start_date, end_date=end_date, token=FINMIND_TOKEN)
    if data_id:
        params["data_id"] = data_id
    try:
        r = requests.get(FINMIND_API, params=params, timeout=20)
        j = r.json()
        if j.get("status") != 200:
            return pd.DataFrame()
        return pd.DataFrame(j["data"])
    except Exception:
        return pd.DataFrame()

# =========================
# TWSE 成交量 Top20（穩定版）
# =========================
@st.cache_data(ttl=600, show_spinner=False)
def fetch_top20_by_volume_twse_csv(trade_date: dt.date) -> pd.DataFrame:
    date_str = trade_date.strftime("%Y%m%d")
    url = "https://www.twse.com.tw/exchangeReport/MI_INDEX"
    params = dict(response="csv", date=date_str, type="ALL")

    r = requests.get(url, params=params, timeout=20, verify=False)
    content = r.content.decode("big5", errors="ignore")

    lines = [l for l in content.split("\n") if l.startswith('"') and len(l.split('","')) >= 16]
    if not lines:
        return pd.DataFrame()

    df = pd.read_csv(io.StringIO("\n".join(lines)))

    if not {"證券代號", "成交股數"}.issubset(df.columns):
        return pd.DataFrame()

    df = df.rename(columns={
        "證券代號": "stock_id",
        "證券名稱": "stock_name",
        "成交股數": "volume",
        "成交金額": "amount",
    })

    for c in ["volume", "amount"]:
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", ""), errors="coerce")

    df = df.dropna(subset=["stock_id", "volume"])
    return df.sort_values("volume", ascending=False).head(20).reset_index(drop=True)

# =========================
# 個股日資料
# =========================
@st.cache_data(ttl=600, show_spinner=False)
def fetch_multi_stock_daily(stock_ids, trade_date):
    dfs = []
    for sid in stock_ids:
        df = finmind_get(
            "TaiwanStockPrice",
            sid,
            (trade_date - dt.timedelta(days=3)).strftime("%Y-%m-%d"),
            trade_date.strftime("%Y-%m-%d"),
        )
        if not df.empty:
            df["stock_id"] = sid
            dfs.append(df)
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

# =========================
# 第二模組 Table Schema（⭐ 重點）
# =========================
STOCK_TABLE_SCHEMA = [
    {"key": "stock_id", "label": "股票代碼", "value": lambda r, ctx: r["sid"]},
    {"key": "stock_name", "label": "股票名稱", "value": lambda r, ctx: r["stock_name"]},
    {"key": "close", "label": "收盤", "value": lambda r, ctx: ctx["close_display"]},
    {"key": "volume", "label": "成交量", "value": lambda r, ctx: f"{int(r['Trading_Volume']/1000):,}"},
    {"key": "amount", "label": "成交金額", "value": lambda r, ctx: f"{int(r['Trading_money']/1_000_000):,} M"},
    {"key": "branch", "label": "券商分點", "value": lambda r, ctx: ctx["branch_link"]},
]

# =========================
# 第二模組 Render
# =========================
def render_tab_stock_futures(trade_date):
    top20 = fetch_top20_by_volume_twse_csv(trade_date)
    if top20.empty:
        st.warning("⚠️ 無成交量資料")
        return

    stock_ids = top20["stock_id"].astype(str).tolist()
    df_all = fetch_multi_stock_daily(stock_ids, trade_date)
    if df_all.empty:
        st.warning("⚠️ 無個股資料")
        return

    rows = []
    for _, base in top20.iterrows():
        sid = str(base["stock_id"])
        df_sid = df_all[df_all["stock_id"] == sid]
        today = df_sid[df_sid["date"] == trade_date.strftime("%Y-%m-%d")]
        if today.empty:
            continue

        r = today.iloc[0]
        prev = df_sid[df_sid["date"] < trade_date.strftime("%Y-%m-%d")].tail(1)
        prev_close = prev.iloc[0]["close"] if not prev.empty else None

        diff = ""
        if prev_close and pd.notna(prev_close):
            pct = (r["close"] - prev_close) / prev_close * 100
            color = "#FF3B30" if pct > 0 else "#34C759"
            diff = f"<span style='color:{color}'>{r['close']:.2f} ({pct:+.2f}%)</span>"
        else:
            diff = f"{r['close']:.2f}"

        ctx = dict(
            close_display=diff,
            branch_link=f"<a href='https://histock.tw/stock/branch.aspx?no={sid}' target='_blank'>🔗</a>",
        )

        row = {}
        for col in STOCK_TABLE_SCHEMA:
            row[col["label"]] = col["value"](r | {"sid": sid, "stock_name": base["stock_name"]}, ctx)
        rows.append(row)

    df_view = pd.DataFrame(rows)
    st.write(df_view, unsafe_allow_html=True)

# =========================
# 主流程
# =========================
trade_date = st.date_input("📅 查詢交易日", dt.date.today())
tab1, tab2 = st.tabs(["📈 期權趨勢", "📊 個股期貨"])

with tab2:
    render_tab_stock_futures(trade_date)
