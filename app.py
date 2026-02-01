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
    page_title="法酷交易室(大盤 / 股期)",
    layout="wide"
)

APP_TITLE = "法酷交易室(大盤 / 股期)"

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

    .kpi-title{ font-size:1.2rem;opacity:.85;color:#000000 }
    .kpi-value{ font-size:1.7rem;font-weight:500;line-height:1.5;color:#000000 }
    .kpi-sub{ font-size:1.0rem;opacity:.65;line-height:1.5;color:#000000}

    /* date_input 標題文字 */
    div[data-testid="stDateInput"] label {
        font-size: 1.7rem;
        font-weight: 600;
    }

    /* date_input 內的日期數字 */
    div[data-testid="stDateInput"] input {
        font-size: 1.7rem;
        font-weight: 600;
        height: 2.4rem;
    }

    /* =========================
   Tabs：黑底白字（未選中）
   ========================= */
div[data-baseweb="tab-list"] {
  background-color: #000000;
  border-radius: 10px;
  padding: 6px;
}

/* 每一個 tab */
button[data-baseweb="tab"] {
  background-color: #000000 !important;
  color: #FFFFFF !important;
  border-radius: 8px;
  margin: 0 6px;
}

/* tab 文字 */
button[data-baseweb="tab"] > div {
  font-size: 1.5rem;
  font-weight: 600;
  color: #FFFFFF !important;
}

/* =========================
   Tabs：被選中（反白）
   ========================= */
button[data-baseweb="tab"][aria-selected="true"] {
  background-color: #2a2a2a !important;
}

/* 被選中的 tab 文字 */
button[data-baseweb="tab"][aria-selected="true"] > div {
  color: #ffd401 !important;  /* 金黃色 */
  font-weight: 700;
}

/* Hover 效果 */
button[data-baseweb="tab"]:hover {
  background-color: #1a1a1a !important;
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

@st.cache_data(ttl=600, show_spinner=False)
def fetch_top10_by_volume_twse_csv(trade_date: dt.date) -> list[str]:
    """
    使用 TWSE 官方 CSV，取得成交量 Top10 股票代碼
    """
    import io
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    date_str = trade_date.strftime("%Y%m%d")
    url = (
        "https://www.twse.com.tw/exchangeReport/MI_INDEX"
        f"?response=csv&date={date_str}&type=ALL"
    )

    try:
        r = requests.get(url, timeout=20, verify=False)
        r.encoding = "utf-8"
    except Exception:
        return []

    lines = [
        l for l in r.text.split("\n")
        if l.count('",') > 10 and l.startswith('"')
    ]

    if not lines:
        return []

    df = pd.read_csv(io.StringIO("\n".join(lines)))
    df.columns = df.columns.str.strip()

    # 統一欄位名稱
    code_col = "證券代號"
    vol_col = "成交股數"

    if code_col not in df.columns or vol_col not in df.columns:
        return []

    df[vol_col] = (
        df[vol_col]
        .astype(str)
        .str.replace(",", "", regex=False)
        .astype(float)
    )

    df = df.sort_values(vol_col, ascending=False)
    return df[code_col].head(10).astype(str).tolist()


@st.cache_data(ttl=600, show_spinner=False)
def fetch_top10_by_volume_twse_csv(trade_date: dt.date) -> pd.DataFrame:
    """
    使用 TWSE 官方 CSV，取得「成交量 Top10 股票」，再用 FinMind 補齊股價資料
    """

    # === 1️⃣ TWSE 官方 CSV（最穩定） ===
    date_str = trade_date.strftime("%Y%m%d")
    url = "https://www.twse.com.tw/exchangeReport/MI_INDEX"
    params = {
        "response": "csv",
        "date": date_str,
        "type": "ALL",
    }

    try:
        # r = requests.get(url, params=params, timeout=20)
        r = requests.get(
            url,
            params=params,
            timeout=20,
            verify=False   # ✅ 關閉 SSL 驗證（關鍵）
        )

        r.encoding = "big5"
    except Exception as e:
        st.error(f"❌ TWSE CSV 下載失敗：{e}")
        return pd.DataFrame()

    # === 2️⃣ 解析 CSV（只抓「每日收盤行情」那一段） ===
    lines = [
        line for line in r.text.split("\n")
        if line.startswith('"') and len(line.split('","')) >= 16
    ]

    if not lines:
        return pd.DataFrame()

    df = pd.read_csv(
        io.StringIO("\n".join(lines)),
        header=0
    )

    # 標準化欄位
    df = df.rename(columns={
        "證券代號": "stock_id",
        "證券名稱": "stock_name",
        "成交股數": "volume",
        "成交金額": "amount",
        "開盤價": "open",
        "最高價": "high",
        "最低價": "low",
        "收盤價": "close",
    })

    # === 3️⃣ 數值清洗 ===
    for col in ["volume", "amount", "open", "high", "low", "close"]:
        df[col] = (
            df[col]
            .astype(str)
            .str.replace(",", "", regex=False)
            .replace("--", None)
        )
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["stock_id", "volume"])

    # === 4️⃣ 成交量排序，取 Top10 ===
    top10 = (
        df.sort_values("volume", ascending=False)
          .head(10)
          .copy()
    )

    if top10.empty:
        return pd.DataFrame()

    # === 5️⃣ 用 FinMind 補齊資料（保證你後面邏輯一致） ===
    rows = []
    for _, r in top10.iterrows():
        df_price = fetch_single_stock_daily(r["stock_id"], trade_date)
        df_day = df_price[df_price["date"] == trade_date.strftime("%Y-%m-%d")]

        if df_day.empty:
            continue

        p = df_day.iloc[0]
        rows.append({
            "股票代碼": r["stock_id"],
            "股票名稱": r["stock_name"],
            "開盤": p["open"],
            "最高": p["max"],
            "最低": p["min"],
            "收盤": p["close"],
            "成交量": p["Trading_Volume"],
            "成交金額": p["Trading_money"],
        })

    return pd.DataFrame(rows)

@st.cache_data(ttl=600, show_spinner=False)
def fetch_top10_volume_from_twse(trade_date: dt.date) -> list[str]:
    """
    從 TWSE 官方 JSON 取得『上市成交量 Top10 股票代碼』
    """

    # TWSE 使用民國年
    roc_year = trade_date.year - 1911
    date_str = f"{roc_year}{trade_date.strftime('%m%d')}"

    url = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX20"
    params = {
        "date": date_str,
        "response": "json",
    }

    try:
        # r = requests.get(url, params=params, timeout=15)
        r = requests.get(
            url,
            params=params,
            timeout=15,
            verify=False,   # 👈 關鍵
        )

        r.raise_for_status()
        j = r.json()
    except Exception as e:
        st.error(f"❌ TWSE 成交量抓取失敗：{e}")
        return []

    if j.get("stat") != "OK":
        return []

    df = pd.DataFrame(j["data"], columns=j["fields"])

    # 標準化欄位
    df = df.rename(columns={
        "證券代號": "stock_id",
        "成交股數": "volume",
    })

    # 數值清洗
    df["volume"] = (
        df["volume"]
        .astype(str)
        .str.replace(",", "", regex=False)
        .astype(int)
    )

    # 依成交量排序取前 10
    top10_ids = (
        df.sort_values("volume", ascending=False)
          .head(10)["stock_id"]
          .tolist()
    )

    return top10_ids


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

    @st.cache_data(ttl=600, show_spinner=False)
    def fetch_position_for_trade_date(trade_date: dt.date):
        df = finmind_get(
            "TaiwanFuturesDaily",
            "TX",
            trade_date.strftime("%Y-%m-%d"),
            (trade_date + dt.timedelta(days=3)).strftime("%Y-%m-%d"),
        )
        if df.empty:
            return df
        df = df[df["trading_session"].astype(str) == "position"].copy()
        df["trade_date"] = trade_date
        return df

    def pick_main_contract_position(df, trade_date):
        x = df.copy()
        x["ym"] = pd.to_numeric(x["contract_date"], errors="coerce")
        target = trade_date.year * 100 + trade_date.month
        cand = x[x["ym"] >= target]
        return cand.sort_values("ym").iloc[0] if not cand.empty else x.sort_values("ym").iloc[-1]

    def calc_ai_scores(main_row, df_all):
        open_ = float(main_row.get("open", 0) or 0)
        settle = main_row.get("settlement_price")
        close = main_row.get("close")
        final_close = float(settle) if settle not in (None, "", 0) else float(close or 0)

        high_ = float(main_row.get("max", 0) or 0)
        low_ = float(main_row.get("min", 0) or 0)
        spread = final_close - open_
        day_range = abs(high_ - low_)

        vol = float(pd.to_numeric(main_row.get("volume", 0), errors="coerce") or 0)
        vol_med = max(float(pd.to_numeric(df_all["volume"], errors="coerce").median() or 1), 1)

        score = (
            clamp(spread / 100.0, -3, 3) * 0.7 +
            clamp((vol / vol_med - 1) * 2, -2, 2) * 0.3
        )

        direction = "偏多" if score > 0.8 else "偏空" if score < -0.8 else "中性"

        return {
            "direction_text": direction,
            "tx_last_price": final_close,
            "day_range": day_range,
            "risk_score": int(clamp(day_range / 3, 0, 100)),
            "consistency_pct": int(abs(score) / 3 * 100),
        }

    def get_prev_trading_close(trade_date: dt.date, lookback_days=7):
        for i in range(1, lookback_days + 1):
            d = trade_date - dt.timedelta(days=i)
            if d.weekday() >= 5:
                continue
            df = fetch_position_for_trade_date(d)
            if not df.empty:
                row = pick_main_contract_position(df, d)
                settle = row.get("settlement_price")
                close = row.get("close")
                return float(settle) if settle not in (None, "", 0) else float(close or 0)
        return None

    # ===== 取資料 =====
    df_day_all = fetch_position_for_trade_date(trade_date)
    if df_day_all.empty:
        st.error("❌ 無期貨結算資料")
        return

    main_row = pick_main_contract_position(df_day_all, trade_date)
    ai = calc_ai_scores(main_row, df_day_all)

    fut_price = ai["tx_last_price"]
    prev_close = get_prev_trading_close(trade_date)

    price_diff = pct_diff = None
    price_color = "#000000"
    if prev_close:
        price_diff = fut_price - prev_close
        pct_diff = price_diff / prev_close * 100
        price_color = "#FF3B30" if price_diff > 0 else "#34C759" if price_diff < 0 else "#000000"

    # ===== UI =====
    st.markdown("<h2 class='fut-section-title'>📈 台指期貨｜趨勢方向</h2>", unsafe_allow_html=True)

    mood = ai["direction_text"]
    cls = "bull" if mood == "偏多" else "bear" if mood == "偏空" else "neut"

    c1, c2, c3, c4, c5 = st.columns([1.6, 1.6, 1.2, 1.2, 1.4])

    with c1:
        st.markdown(
            f"<div class='kpi-card'><div class='kpi-title'>方向</div>"
            f"<div class='kpi-value {cls}'>{mood}</div></div>",
            unsafe_allow_html=True,
        )

    with c2:
        st.markdown(
            f"<div class='kpi-card'><div class='kpi-title'>收盤價</div>"
            f"<div class='kpi-value' style='color:{price_color}'>{fut_price:.0f}"
            f"<span style='font-size:1.05rem'> ({price_diff:+.0f}，{pct_diff:+.1f}%)</span>"
            f"</div></div>",
            unsafe_allow_html=True,
        )

    with c3:
        st.markdown(
            f"<div class='kpi-card'><div class='kpi-title'>一致性</div>"
            f"<div class='kpi-value'>{ai['consistency_pct']}%</div></div>",
            unsafe_allow_html=True,
        )

    with c4:
        st.markdown(
            f"<div class='kpi-card'><div class='kpi-title'>風險</div>"
            f"<div class='kpi-value'>{ai['risk_score']}/100</div></div>",
            unsafe_allow_html=True,
        )

    with c5:
        st.markdown(
            f"<div class='kpi-card'><div class='kpi-title'>日震幅</div>"
            f"<div class='kpi-value'>{ai['day_range']:.0f}</div></div>",
            unsafe_allow_html=True,
        )
    # ===== 選擇權 UI（完整復原）=====
    def normalize_cp(v):
        s = str(v).lower()
        if s in ("c", "call", "買權"):
            return "call"
        if s in ("p", "put", "賣權"):
            return "put"
        return None

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
                df["trade_date"] = d
                return df
        return pd.DataFrame()

    def calc_option_bias_v3(df, fut_price):
        if df.empty:
            return None

        cp_col = next(
            (c for c in ["option_type", "call_put", "right"] if c in df.columns),
            None,
        )
        if cp_col is None:
            return None

        df = df.copy()
        df["cp"] = df[cp_col].apply(normalize_cp)
        df["strike"] = pd.to_numeric(df["strike_price"], errors="coerce")
        df["oi"] = pd.to_numeric(df["open_interest"], errors="coerce")
        df = df.dropna(subset=["cp", "strike", "oi"])

        call = df[df["cp"] == "call"]
        put = df[df["cp"] == "put"]

        if call.empty or put.empty:
            return None

        call_lvl = call.loc[call["oi"].idxmax()]["strike"]
        put_lvl = put.loc[put["oi"].idxmax()]["strike"]

        state, reason = "結構中性", "價格位於 OI 區間內"

        if fut_price >= call_lvl:
            state, reason = "高檔受壓（偏空結構）", "價格測試 Call 最大 OI 壓力"
        elif fut_price <= put_lvl:
            state, reason = "支撐有效（偏多結構）", "價格位於 Put 強支撐上方"

        return {
            "state": state,
            "reason": reason,
            "call_pressure": call_lvl,
            "put_support": put_lvl,
            "trade_date": df["trade_date"].iloc[0],
        }

    st.divider()
    st.markdown(
        "<h2 class='opt-section-title'>🧩 選擇權｜市場狀態與稱壓區間</h2>",
        unsafe_allow_html=True,
    )

    df_opt = fetch_option_latest(trade_date)
    opt = calc_option_bias_v3(df_opt, fut_price)

    if opt is None:
        st.info("ℹ️ 選擇權資料不足（TXO 為 T+1 公告）")
        return

    opt_state = opt["state"]
    opt_cls = (
        "bull" if "偏多" in opt_state else
        "bear" if "偏空" in opt_state else
        "neut"
    )

    st.caption(f"📅 選擇權資料日：{opt['trade_date']}")

    oc1, oc2, oc3 = st.columns(3)

    with oc1:
        st.markdown(
            f"<div class='kpi-card'><div class='kpi-title'>市場狀態</div>"
            f"<div class='kpi-value {opt_cls}'>{opt_state}</div>"
            f"<div class='kpi-sub'>{opt['reason']}</div></div>",
            unsafe_allow_html=True,
        )

    with oc2:
        st.markdown(
            f"<div class='kpi-card'><div class='kpi-title'>上方壓力</div>"
            f"<div class='kpi-value'>{opt['call_pressure']:.0f}</div>"
            f"<div class='kpi-sub'>Call 最大 OI</div></div>",
            unsafe_allow_html=True,
        )

    with oc3:
        st.markdown(
            f"<div class='kpi-card'><div class='kpi-title'>下方支撐</div>"
            f"<div class='kpi-value'>{opt['put_support']:.0f}</div>"
            f"<div class='kpi-sub'>Put 最大 OI</div></div>",
            unsafe_allow_html=True,
        )


# =========================
# 第二模組：個股期貨（測試版）
# =========================
def render_tab_stock_futures(trade_date: dt.date):

    # 1️⃣ 先拿原始 Top10（可能是 list 或 DataFrame）
    top10_raw = fetch_top10_by_volume_twse_csv(trade_date)

    if top10_raw is None or (hasattr(top10_raw, "empty") and top10_raw.empty):
        st.warning("⚠️ 查詢日無成交量資料")
        return

    # 2️⃣ 強制轉成股票代碼 list（關鍵）
    top10_list = (
        top10_raw[["股票代碼", "股票名稱"]]
        .astype(str)
        .to_dict("records")
        if isinstance(top10_raw, pd.DataFrame)
        else [{"股票代碼": sid, "股票名稱": ""} for sid in top10_raw]
    )

    st.markdown("### ⬤ TWSE 成交量 TOP10 股票")
    #st.write(top10_ids)

    #if not top10_ids:
    #    st.warning("⚠️ 無前十大股票")
    #    return
    if top10_ids is None or (hasattr(top10_ids, "__len__") and len(top10_ids) == 0):
    st.warning("⚠️ 無前十大股票")
    return

    # 3️⃣ 蒐集個股資料
    rows = []

    for item in top10_list:
        sid = item["股票代碼"]
        stock_name = item["股票名稱"]

        df = fetch_single_stock_daily(sid, trade_date)
        if df.empty or "date" not in df.columns:
            continue

        df_day = df[df["date"] == trade_date.strftime("%Y-%m-%d")]
        if df_day.empty:
            continue

        r = df_day.iloc[0]

        rows.append({
            "股票代碼": sid,
            "股票名稱": stock_name,   # ✅ 正確中文名稱
            "開盤": r["open"],
            "最高": r["max"],
            "最低": r["min"],
            "收盤": r["close"],
            "成交量": r["Trading_Volume"],
            "成交金額": r["Trading_money"],
        })


    if not rows:
        st.warning("⚠️ 查詢日無任何個股資料")
        return

    # 4️⃣ ✅「畫面顯示前」統一轉單位（最重要）
    df_view = pd.DataFrame(rows)

    df_view["成交量"] = df_view["成交量"].apply(
        lambda x: f"{int(x / 10000):,} 萬" if pd.notna(x) else "-"
    )

    df_view["成交金額"] = df_view["成交金額"].apply(
        lambda x: f"{int(x / 1_000_000):,} 百萬" if pd.notna(x) else "-"
    )

    # 5️⃣ 只畫這一份（不要再用 rows）
    render_stock_table_html(df_view)


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
