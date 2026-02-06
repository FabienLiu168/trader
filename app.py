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

    /* =======================
       查詢日期（date_input）
       ======================= */
    label {
        font-size: 20px !important;
        font-weight: 600;
    }

    div[data-baseweb="input"] input {
        font-size: 20px !important;
        font-weight: 600;
    }

    /* =======================
       Tab 模組名稱
       ======================= */
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
    """
    顯示收盤價，並依『今日 - 昨日』決定顏色與漲跌幅
    ⚠️ 此函式必須 100% 防呆，否則 DataFrame.apply 會整表炸掉
    """
    try:
        stock_id = str(row.get("股票代碼", "")).strip()
        close_today = row.get("收盤", None)

        # 沒股票代碼或沒收盤價 → 空白
        if not stock_id or close_today is None or pd.isna(close_today):
            return ""

        close_today = float(close_today)

        prev_close = get_prev_stock_close(stock_id, trade_date)
        if prev_close is None or prev_close == 0:
            return f"{close_today:.2f}"

        diff = close_today - prev_close
        pct = diff / prev_close * 100

        if diff > 0:
            color = "#FF3B30"   # 漲：紅
        elif diff < 0:
            color = "#34C759"   # 跌：綠
        else:
            color = "#000000"

        return (
            f"<span style='color:{color};font-weight:600'>"
            f"{close_today:.2f} ({pct:+.2f}%)</span>"
        )

    except Exception:
        # ❗ 保證任何異常都不影響整張表
        return ""



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
# HTML 表格 render
# =========================
def render_stock_table_html(df: pd.DataFrame):
    gray_cols = {"成交量", "成交金額", "買超", "賣超"}

    html = "<table style='width:100%;border-collapse:collapse;'>"
    html += "<thead><tr>"

    for c in df.columns:
        # 👉 深灰底 + 白字
        bg = "#3a3a3a" if c in gray_cols else "#2b2b2b"
        color = "#ffffff"

        html += (
            f"<th style='padding:8px;border:1px solid #555;"
            f"background:{bg};color:{color};"
            f"text-align:center;font-weight:600'>"
            f"{c}</th>"
        )

    html += "</tr></thead><tbody>"

    for _, row in df.iterrows():
        html += "<tr>"
        for v in row:
            html += (
                "<td style='padding:8px;border:1px solid #444;"
                "text-align:center'>"
                f"{v}</td>"
            )
        html += "</tr>"

    html += "</tbody></table>"
    st.markdown(html, unsafe_allow_html=True)

    st.markdown("### ⬆️ 上傳各股券商分點 CSV（逐檔）")
    
    for sid in df["股票代碼"].astype(str):
        uploaded = st.file_uploader(
            f"📤 上傳 {sid} 券商分點 CSV",
            type=["csv"],
            key=f"upload_{sid}",
        )
    
        if uploaded:
            df_branch = parse_branch_csv(uploaded)
            if df_branch.empty:
                st.error(f"❌ {sid} CSV 無法解析")
            else:
                result = calc_top5_buy_sell(df_branch)
                if sid in result:
                    st.session_state.broker_done[sid] = result[sid]
                    st.success(f"✅ {sid} 已完成買賣超計算")


def fetch_twse_broker_trade(stock_id: str, trade_date: dt.date) -> pd.DataFrame:
    """
    從 TWSE 官方 bsr 系統抓取【單一股票】當日券商買賣明細
    """
    roc_year = trade_date.year - 1911
    date_str = f"{roc_year}/{trade_date.month:02d}/{trade_date.day:02d}"

    session = requests.Session()
    url = "https://bsr.twse.com.tw/bshtm/bsMenu.aspx"

    # 先 GET 拿頁面（建立 session）
    r = session.get(url, timeout=10)
    r.raise_for_status()

    # POST 查詢
    payload = {
        "TextBox_Stkno": stock_id,
        "TextBox_Date": date_str,
        "Button_Query": "查詢",
    }

    r2 = session.post(url, data=payload, timeout=10)
    r2.raise_for_status()

    # 解析 HTML table
    dfs = pd.read_html(r2.text)
    df = dfs[-1]  # 真正的券商表通常在最後

    df = df.rename(columns={
        "證券商": "券商",
        "買進股數": "買進",
        "賣出股數": "賣出",
    })

    for c in ["買進", "賣出"]:
        df[c] = (
            df[c]
            .astype(str)
            .str.replace(",", "")
            .astype(float)
        )

    df["買賣超"] = df["買進"] - df["賣出"]

    return df
def calc_top5_from_twse(df_broker: pd.DataFrame) -> dict:
    buy = (
        df_broker[df_broker["買賣超"] > 0]
        .nlargest(5, "買賣超")["買賣超"]
        .sum()
    )

    sell = (
        df_broker[df_broker["買賣超"] < 0]
        .nsmallest(5, "買賣超")["買賣超"]
        .sum()
    )

    return {
        "買超": int(buy),
        "賣超": int(abs(sell)),
    }
@st.cache_data(ttl=3600)
def fetch_twse_broker_summary(stock_ids, trade_date):
    result = {}

    for sid in stock_ids:
        try:
            df_broker = fetch_twse_broker_trade(sid, trade_date)
            result[sid] = calc_top5_from_twse(df_broker)
        except Exception:
            result[sid] = {"買超": "", "賣超": ""}

        time.sleep(1.2)  # ⚠️ 必須限速，避免被 TWSE 擋

    return result


# =========================
# 第二模組：個股＋籌碼
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
        df[c] = pd.to_numeric(
            df[c].astype(str).str.replace(",", ""), errors="coerce"
        )
    return df.sort_values("成交金額", ascending=False).head(20)

def parse_branch_csv(file):
    try:
        df = pd.read_csv(file)
    except Exception:
        return pd.DataFrame()

    col_map = {}
    for c in df.columns:
        if "代號" in c and "股票代碼" not in col_map.values():
            col_map[c] = "股票代碼"
        elif "買" in c and "買進" not in col_map.values():
            col_map[c] = "買進"
        elif "賣" in c and "賣出" not in col_map.values():
            col_map[c] = "賣出"

    df = df.rename(columns=col_map)

    if not {"股票代碼", "買進", "賣出"}.issubset(df.columns):
        return pd.DataFrame()

    df["股票代碼"] = df["股票代碼"].astype(str)
    df["買進"] = pd.to_numeric(df["買進"], errors="coerce").fillna(0)
    df["賣出"] = pd.to_numeric(df["賣出"], errors="coerce").fillna(0)
    df["買賣超"] = df["買進"] - df["賣出"]

    return df


def calc_top5_buy_sell(df):
    result = {}
    for sid, g in df.groupby("股票代碼"):
        buy = g[g["買賣超"] > 0].nlargest(5, "買賣超")["買賣超"].sum()
        sell = g[g["買賣超"] < 0].nsmallest(5, "買賣超")["買賣超"].sum()
        result[sid] = {"買超": int(buy), "賣超": int(abs(sell))}
    return result

def render_tab_stock_futures(trade_date):
def fmt_num(x):
    return f"{x:,}" if isinstance(x, (int, float)) else ""
    
    st.subheader("📊 前20大個股盤後籌碼")
     # ✅ 新增：券商分點完成狀態
    if "broker_done" not in st.session_state:
        st.session_state.broker_done = {}

    df = fetch_top20_by_amount_twse_csv(trade_date)

    if df.empty:
        st.warning("無資料")
        return

    # ✅【第 3 步】單一股票券商分點上傳（逐檔）
    for sid in df["股票代碼"].astype(str):
        if sid in st.session_state.broker_done:
            continue

        uploaded = st.file_uploader(
            f"⬆ 上傳 {sid} 券商分點 CSV",
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
                    st.success(f"✅ {sid} 券商分點已完成")

        
    summary = {}

    df["收盤"] = df.apply(lambda r: format_close_with_prev(r, trade_date), axis=1)
    df["成交量"] = df["成交量"].apply(lambda x: f"{int(x/1000):,}")
    df["成交金額"] = df["成交金額"].apply(lambda x: f"{x/1_000_000:,.0f} M")
    df["買超"] = df["股票代碼"].apply(
        lambda s: fmt_num(st.session_state.broker_done.get(str(s), {}).get("買超"))
    )
    df["賣超"] = df["股票代碼"].apply(
        lambda s: fmt_num(st.session_state.broker_done.get(str(s), {}).get("賣超"))
    )

    df["券商分點"] = df["股票代碼"].apply(
        lambda s: f"<a href='https://histock.tw/stock/branch.aspx?no={s}' target='_blank'>🔗</a>"
    )

    df["券商分點"] = df["股票代碼"].apply(
        lambda s: "✔ 已完成" if str(s) in st.session_state.broker_done else ""
    )
    
    df["下載"] = df["股票代碼"].apply(
        lambda s: "<a href='https://bsr.twse.com.tw/bshtm/bsMenu.aspx' target='_blank'>查詢</a>"
    )
    df["上傳"] = ""  # 佔位，實際 uploader 在表格下方


def twse_bsr_download_link(stock_id: str) -> str:
    return (
        "<a href='https://bsr.twse.com.tw/bshtm/bsMenu.aspx' "
        f"title='股票代碼 {stock_id}' target='_blank'>查詢</a>"
    )

    
    render_stock_table_html(
        df[["股票代碼","股票名稱","收盤","成交量","成交金額","買超","賣超","券商分點","下載","上傳"]]
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
