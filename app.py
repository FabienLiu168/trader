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
    .bull{color:#FF3B30}
    .bear{color:#34C759}
    .neut{color:#000000}
    table {font-size:16px;}
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

def fetch_branch_top5_buy_sell(stock_id: str, trade_date: dt.date):
    """
    回傳：
    {
        "top5_buy": 前五大買超合計,
        "top5_sell": 前五大賣超合計
    }
    """
    df = finmind_get(
        "TaiwanStockInstitutionalInvestorsBuySell",
        stock_id,
        trade_date.strftime("%Y-%m-%d"),
        trade_date.strftime("%Y-%m-%d"),
    )

    if df.empty or "net" not in df.columns:
        return {"top5_buy": None, "top5_sell": None}

    df["net"] = pd.to_numeric(df["net"], errors="coerce")

    # 前五大買超（net 最大）
    top5_buy = (
        df.sort_values("net", ascending=False)
        .head(5)["net"]
        .sum()
    )

    # 前五大賣超（net 最小，取絕對值）
    top5_sell = (
        df.sort_values("net")
        .head(5)["net"]
        .sum()
    )

    return {
        "top5_buy": int(top5_buy),
        "top5_sell": int(abs(top5_sell)),
    }

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
        df = finmind_get("TaiwanStockPrice", "2330", d.strftime("%Y-%m-%d"), d.strftime("%Y-%m-%d"))
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


# =========================
# 第一模組（保留原樣）
# =========================
# =========================
# 外資期貨 OI（安全版）
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
# KPI 邏輯
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
# 第一模組 KPI
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
        fut_dir, _, _, oi_diff = fut_trend_engine(price_today, price_prev, oi_today, oi_prev)
        oi_disp = f"{oi_diff:+,.0f}"
    else:
        fut_dir = "中性"
        oi_disp = "資料不足"

    opt_today = option_structure_engine(fetch_option_latest(trade_date))
    opt_prev = option_structure_engine(fetch_option_latest(trade_date - dt.timedelta(days=1)))
    opt_shift = "昨日無資料"
    if opt_today and opt_prev:
        opt_shift = f"Put {opt_today['put_wall']-opt_prev['put_wall']:+}｜Call {opt_today['call_wall']-opt_prev['call_wall']:+}"

    spot_today = spot_confirm_engine(fetch_index_confirm(trade_date))
    spot_prev = spot_confirm_engine(fetch_index_confirm(trade_date - dt.timedelta(days=1)))

    if spot_today["confirm"] and not spot_prev["confirm"]:
        spot_trend = "🟢 結構轉強"
    elif not spot_today["confirm"] and spot_prev["confirm"]:
        spot_trend = "🔴 結構轉弱"
    else:
        spot_trend = "⏸ 結構延續"

    final_today = trend_engine(fut_dir, opt_today, spot_today)
    final_prev = trend_engine(fut_dir, opt_prev, spot_prev)
    final_shift = f"{final_prev} → {final_today}" if final_today != final_prev else "狀態延續"

    st.subheader("📊 大盤分析（昨日 vs 今日）")
    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.metric("📈 期貨趨勢", fut_dir, f"價差 {price_diff:+.0f}｜OI {oi_disp}")
    with c2:
        st.metric("🧩 選擇權防線",
                  f"{opt_today['put_wall']}–{opt_today['call_wall']}" if opt_today else "N/A",
                  opt_shift)
    with c3:
        st.metric("📊 現貨確認", "✔" if spot_today["confirm"] else "✖", spot_trend)
    with c4:
        st.metric("🧠 綜合評估", final_today, final_shift)

# =========================
# HTML 表格 render（支援超連結）
# =========================
def render_stock_table_html(df: pd.DataFrame):
    html = "<table style='width:100%;border-collapse:collapse;'>"
    html += "<thead><tr style='background:#f5f5f5;'>"
    for c in df.columns:
        html += f"<th style='padding:8px;border:1px solid #ddd'>{c}</th>"
    html += "</tr></thead><tbody>"

    for _, row in df.iterrows():
        html += "<tr>"
        for v in row:
            html += f"<td style='padding:8px;border:1px solid #ddd;text-align:center'>{v}</td>"
        html += "</tr>"

    html += "</tbody></table>"
    st.markdown(html, unsafe_allow_html=True)

# =========================
# 第二模組：前20大成交金額
# =========================
@st.cache_data(ttl=600)
def fetch_top20_by_amount_twse_csv(trade_date):
    date_str = trade_date.strftime("%Y%m%d")
    url = "https://www.twse.com.tw/exchangeReport/MI_INDEX"
    params = {"response": "csv", "date": date_str, "type": "ALL"}
    r = requests.get(url, params=params, timeout=20, verify=False)
    content = r.content.decode("big5", errors="ignore")

    lines = [l for l in content.split("\n") if l.startswith('"') and len(l.split('","')) >= 16]
    df = pd.read_csv(io.StringIO("\n".join(lines)))

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

def format_close_with_prev(row, trade_date):
    close_today = row["收盤"]
    prev_close = get_prev_stock_close(row["股票代碼"], trade_date)
    if prev_close is None or pd.isna(close_today):
        return f"{close_today:.2f}"
    pct = (close_today - prev_close) / prev_close * 100
    color = "#34C759" if pct > 0 else "#FF3B30" if pct < 0 else "#000000"
    return f"<span style='color:{color};font-weight:600'>{close_today:.2f} ({pct:+.2f}%)</span>"

def render_tab_stock_futures(trade_date):
    df = fetch_top20_by_amount_twse_csv(trade_date)
    if df.empty:
        st.warning("⚠️ 無成交資料")
        return

    st.markdown("### ● 前20大成交金額個股")

    df_view = df.copy()

    df_view["收盤"] = df_view.apply(lambda r: format_close_with_prev(r, trade_date), axis=1)
    df_view["成交量"] = df_view["成交量"].apply(lambda x: f"{int(x/1000):,}" if pd.notna(x) else "-")
    df_view["成交金額"] = df_view["成交金額"].apply(lambda x: f"{x/1_000_000:,.0f} M" if pd.notna(x) else "-")
    df_view["券商分點"] = df_view["股票代碼"].apply(
        lambda sid: f"<a href='https://histock.tw/stock/branch.aspx?no={sid}' target='_blank'>🔗</a>"
    )

    # === 券商分點前五大買賣超 ===
    branch_data = df_view["股票代碼"].apply(
        lambda sid: fetch_branch_top5_buy_sell(sid, trade_date)
    )
    
    df_view["分點買超"] = branch_data.apply(
        lambda x: f"{x['top5_buy']:,}" if x["top5_buy"] is not None else "-"
    )
    
    df_view["分點賣超"] = branch_data.apply(
        lambda x: f"{x['top5_sell']:,}" if x["top5_sell"] is not None else "-"
    )

    
    display_cols = ["股票代碼", "股票名稱", "收盤", "成交量", "成交金額", "券商分點", "分點買超",
    "分點賣超",]
    render_stock_table_html(df_view[display_cols])

# =========================
# 分點前五大買賣超（自動回溯）
# =========================
@st.cache_data(ttl=600)
def fetch_branch_top5_buy_sell(stock_id: str, trade_date: dt.date, lookback=5):
    for i in range(lookback):
        d = trade_date - dt.timedelta(days=i)
        if d.weekday() >= 5:
            continue

        df = finmind_get(
            "TaiwanStockInstitutionalInvestorsBuySell",
            stock_id,
            d.strftime("%Y-%m-%d"),
            d.strftime("%Y-%m-%d"),
        )

        if df.empty or "net" not in df.columns:
            continue

        df["net"] = pd.to_numeric(df["net"], errors="coerce")
        df = df.dropna(subset=["net"])

        if df.empty:
            continue

        top5_buy = df.sort_values("net", ascending=False).head(5)["net"].sum()
        top5_sell = abs(df.sort_values("net").head(5)["net"].sum())

        return int(top5_buy), int(top5_sell)

    return None, None

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
