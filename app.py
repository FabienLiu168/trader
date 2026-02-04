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

st.markdown(
    """
    <style>

    /* =========================
       KPI Card RWD Fix
       ========================= */
    @media (max-width: 768px) {
      .kpi-card {
        min-height: auto;
        padding: 12px;
      }

      .kpi-value {
        font-size: 1.3rem;
      }
    }

    /* =========================
   Global Design System
   ========================= */
    :root {
      --font-title: 1.15rem;
      --font-value: 1.6rem;
      --font-sub: 0.9rem;
      --space-xs: 6px;
      --space-sm: 10px;
      --space-md: 16px;
      --space-lg: 24px;
    }

    /* 手機自動縮排與縮字 */
    @media (max-width: 768px) {
      :root {
        --font-title: 1.0rem;
        --font-value: 1.3rem;
        --font-sub: 0.8rem;
      }
    }

    div[data-testid="stAppViewContainer"] > .main {
        padding-top: 3.5rem;
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
    padding: var(--space-md);
    min-height: 120px;
    }

    .kpi-title{ 
        font-size:var(--font-title);
    }
    .kpi-value{ 
        font-size:var(--font-value);
        line-height: 1.4;
        }
    .kpi-sub{ 
        font-size: var(--font-sub);
    }

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
  background-color: #4A557E !important;
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
# 工具區
# =========================
# === 選擇權資料（TXO，取最近一個交易日）===
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
    
@st.cache_data(ttl=600, show_spinner=False)
def fut_trend_engine(fut_today, fut_prev, oi_today, oi_prev):
    price_chg = fut_today - fut_prev
    delta_oi = oi_today - oi_prev

    if price_chg > 0 and delta_oi > 0:
        direction = "趨勢多"
        bias = "bull"
    elif price_chg < 0 and delta_oi > 0:
        direction = "趨勢空"
        bias = "bear"
    elif delta_oi < 0:
        direction = "震盪"
        bias = "neut"
    else:
        direction = "中性"
        bias = "neut"

    confidence = min(100, int(abs(delta_oi) / 500))

    return {
        "direction": direction,
        "bias": bias,
        "delta_oi": int(delta_oi),
        "confidence": confidence,
    }

def option_structure_engine(df_opt):
    if df_opt is None or df_opt.empty:
        return None

    df = df_opt.copy()

    # === 欄位標準化（關鍵修正） ===
    if "call_put" not in df.columns:
        return None

    df["cp"] = (
        df["call_put"]
        .astype(str)
        .str.lower()
        .map({"call": "call", "put": "put"})
    )

    df["strike"] = pd.to_numeric(df["strike_price"], errors="coerce")
    df["oi"] = pd.to_numeric(df["open_interest"], errors="coerce")

    df = df.dropna(subset=["cp", "strike", "oi"])

    call = df[df["cp"] == "call"]
    put  = df[df["cp"] == "put"]

    if call.empty or put.empty:
        return None

    call_wall = int(call.loc[call["oi"].idxmax(), "strike"])
    put_wall  = int(put.loc[put["oi"].idxmax(), "strike"])

    dominant = "neutral"
    if call["oi"].sum() > put["oi"].sum():
        dominant = "call"
    elif put["oi"].sum() > call["oi"].sum():
        dominant = "put"

    return {
        "call_wall": call_wall,
        "put_wall": put_wall,
        "dominant": dominant,
        "range": (put_wall, call_wall),
    }


def spot_confirm_engine(spot):
    if spot is None:
        return {"confirm": False, "reason": "無資料"}

    if spot["vol_today"] > spot["vol_ma5"] and spot["up"] > spot["down"]:
        return {"confirm": True, "reason": "量增價揚"}

    if spot["up"] < spot["down"]:
        return {"confirm": False, "reason": "跌家數多"}

    return {"confirm": False, "reason": "量能不足"}


def trend_engine(fut, opt, spot):
    if fut["direction"] == "趨勢多" and opt and opt["dominant"] != "call" and spot["confirm"]:
        return "偏多可操作"
    if fut["direction"] == "趨勢空" and opt and opt["dominant"] != "put" and spot["confirm"]:
        return "偏空可操作"
    return "觀望 / 區間"

def fetch_fut_foreign_oi(trade_date: dt.date):
    """
    外資台指期貨未平倉（TX）
    """
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

    return {
        "net_oi": float(df.iloc[0]["open_interest_net"]),
    }

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
    return (
        cand.sort_values("ym").iloc[0]
        if not cand.empty
        else x.sort_values("ym").iloc[-1]
    )


def get_prev_trading_close(trade_date: dt.date, lookback_days=7):
    for i in range(1, lookback_days + 1):
        d = trade_date - dt.timedelta(days=i)
        if d.weekday() >= 5:
            continue

        df = fetch_position_for_trade_date(d)
        if df.empty:
            continue

        row = pick_main_contract_position(df, d)

        settle = row.get("settlement_price")
        close = row.get("close")

        if settle not in (None, "", 0) and pd.notna(settle):
            return float(settle)

        if close not in (None, "", 0) and pd.notna(close):
            return float(close)

    return None


@st.cache_data(ttl=600, show_spinner=False)
def fetch_index_confirm(trade_date: dt.date):
    """
    現貨確認：加權量能 + 漲跌家數
    """
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

    vol_today = today["Trading_Volume"]
    vol_ma5 = df["Trading_Volume"].tail(5).mean()

    return {
        "vol_today": vol_today,
        "vol_ma5": vol_ma5,
        "up": today["Up_Count"],
        "down": today["Down_Count"],
    }

def is_trading_day(d: dt.date) -> bool:
    return d.weekday() < 5
@st.cache_data(ttl=600, show_spinner=False)
def get_latest_trading_date(max_lookback: int = 10) -> dt.date:
    """
    安全取得最近交易日：
    - FINMIND_TOKEN 有 → 用 FinMind 驗證
    - 沒 token / API 掛 → 直接 fallback 今天
    """
    today = dt.date.today()

    # 沒 token 直接退回今天（避免整個 app 掛掉）
    if not FINMIND_TOKEN:
        return today

    for i in range(max_lookback):
        d = today - dt.timedelta(days=i)

        # 跳過週末
        if d.weekday() >= 5:
            continue

        try:
            df = finmind_get(
                dataset="TaiwanStockPrice",
                data_id="2330",  # 流動性最高，當探針
                start_date=d.strftime("%Y-%m-%d"),
                end_date=d.strftime("%Y-%m-%d"),
            )
        except Exception:
            continue

        if not df.empty:
            return d

    # 最差情況保底
    return today


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
def fetch_multi_stock_daily(stock_ids: list[str], trade_date: dt.date):
    """
    一次抓多檔股票日資料（避免 N 次 HTTP）
    """
    dfs = []
    start = (trade_date - dt.timedelta(days=3)).strftime("%Y-%m-%d")
    end = trade_date.strftime("%Y-%m-%d")

    for sid in stock_ids:
        df = finmind_get(
            dataset="TaiwanStockPrice",
            data_id=sid,
            start_date=start,
            end_date=end,
        )
        if not df.empty:
            df["stock_id"] = sid
            dfs.append(df)

    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()


#@st.cache_data(ttl=600, show_spinner=False)
#def fetch_top20_by_volume_twse_csv(trade_date: dt.date) -> list[str]:
    """
    使用 TWSE 官方 CSV，取得成交量 Top20 股票代碼
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
    return df[code_col].head(20).astype(str).tolist()


@st.cache_data(ttl=600, show_spinner=False)
def fetch_top20_by_volume_twse_csv(trade_date: dt.date) -> pd.DataFrame:
    """
    使用 TWSE 官方 CSV，取得「成交量 Top20 股票」，再用 FinMind 補齊股價資料
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

        content = r.content.decode("big5", errors="ignore")

        lines = [
            line for line in content.split("\n")
            if line.startswith('"') and len(line.split('","')) >= 16
        ]
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

    # === 4️⃣ 成交量排序，取 Top20 ===
    top20 = (
        df.sort_values("volume", ascending=False)
          .head(20)
          .copy()
    )

    if top20.empty:
        return pd.DataFrame()

    # === 5️⃣ 用 FinMind 補齊資料（保證你後面邏輯一致） ===
    rows = []
    for _, r in top20.iterrows():
        df_price = fetch_single_stock_daily(r["stock_id"], trade_date)
        df_day = df_price[df_price["date"] == trade_date.strftime("%Y-%m-%d")]

        if df_day.empty:
            continue

        p = df_day.iloc[0]

        stock_name = str(r["stock_name"]).strip()
        rows.append({
            "代碼": r["stock_id"],
            "股票": r["stock_name"],
            "開盤": p["open"],
            "最高": p["max"],
            "最低": p["min"],
            "收盤": p["close"],
            "成交量": p["Trading_Volume"],
            "成交金額": p["Trading_money"],
        })

    return pd.DataFrame(rows)

@st.cache_data(ttl=600, show_spinner=False)
def fetch_top20_volume_from_twse(trade_date: dt.date) -> list[str]:
    """
    從 TWSE 官方 JSON 取得『上市成交量 Top20 股票代碼』
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
    top20_ids = (
        df.sort_values("volume", ascending=False)
          .head(20)["stock_id"]
          .tolist()
    )

    return top20_ids

def format_stock_cell(row: dict, col: dict):
    key = col["key"]
    v = row.get(key)

    if col.get("formatter") == "price_change":
        open_p = row.get("open")
        close_p = row.get("close")
        if open_p and close_p:
            diff = (close_p - open_p) / open_p * 100
            color = "#FF3B30" if diff > 0 else "#34C759" if diff < 0 else "#000000"
            return (
                f"<span style='color:{color};font-weight:600'>"
                f"{close_p:.2f} ({diff:+.2f}%)"
                f"</span>"
            )
        return f"{close_p:.2f}" if close_p else "-"

    if col.get("formatter") == "volume_k":
        return f"{int(v / 1000):,} K" if v else "-"

    if col.get("formatter") == "amount_m":
        return f"{int(v / 1_000_000):,} M" if v else "-"

    return v if v is not None else "-"


def render_stock_table_html(df: pd.DataFrame):
    st.markdown(
        """
        <style>
        .stock-table {
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
            font-size: 16px;
            background: #ffffff;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 8px 24px rgba(0,0,0,.12);
        }
        .stock-table thead th {
            background: linear-gradient(180deg, #2c2c2c, #1f1f1f);
            color: #ffffff;
            padding: 12px 10px;
            text-align: center;
            font-size: 15px;
            letter-spacing: .5px;
        }
        .stock-table tbody td {
            padding: 10px;
            text-align: right;
            border-bottom: 1px solid #eee;
            color: #111;
        }
        .stock-table tbody tr:hover {
            background-color: #f6f8fa;
        }
        .stock-table td:nth-child(1),
        .stock-table td:nth-child(2) {
            text-align: center;
            font-weight: 600;
        }
        .stock-table td:last-child {
            text-align: center;
            font-size: 18px;
        }
        @media (max-width: 768px) {
          .stock-table {
            display: block;
            overflow-x: auto;
            white-space: nowrap;
          }
          .stock-table thead th,
          .stock-table tbody td {
            font-size: 13px;
            padding: 8px;
          }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # ===== 表頭 =====
    html = "<table class='stock-table'><thead><tr>"
    for col in STOCK_TABLE_COLUMNS:
        html += f"<th>{col['label']}</th>"
    html += "</tr></thead><tbody>"

    # ===== 表身 =====
    for _, row in df.iterrows():
        row_dict = row.to_dict()
        html += "<tr>"
        for col in STOCK_TABLE_COLUMNS:
            cell_html = format_stock_cell(row_dict, col)
            html += f"<td>{cell_html}</td>"
        html += "</tr>"

    html += "</tbody></table>"
    st.markdown(html, unsafe_allow_html=True)


# =========================
# 第一模組：期權大盤
# =========================
def render_tab_option_market(trade_date: dt.date):
    # ===============================
    # ✅ KPI 所有變數預設值（防炸彈）
    # ===============================
    fut_price = 0.0
    prev_close = None

    # ===== 期貨主力資料 =====
    df_day_all = fetch_position_for_trade_date(trade_date)
    if df_day_all.empty:
        st.error("❌ 無期貨結算資料")
        return
    
    main_row = pick_main_contract_position(df_day_all, trade_date)
    
    settle = main_row.get("settlement_price")
    close = main_row.get("close")
    
    if settle not in (None, "", 0) and pd.notna(settle):
        fut_price = float(settle)
    elif close not in (None, "", 0) and pd.notna(close):
        fut_price = float(close)
    
    prev_close = get_prev_trading_close(trade_date)

    # === 外資 OI ===
    oi_today = fetch_fut_foreign_oi(trade_date)
    oi_prev = fetch_fut_foreign_oi(trade_date - dt.timedelta(days=1))

    df_opt = fetch_option_latest(trade_date)


    if oi_today and oi_prev and prev_close is not None:
        fut_engine = fut_trend_engine(
            fut_price,
            prev_close,
            oi_today["net_oi"],
            oi_prev["net_oi"],
        )
    else:
        fut_engine = {"direction": "中性", "bias": "neut", "delta_oi": 0, "confidence": 0}

    # === 選擇權結構 ===
    opt_engine = option_structure_engine(df_opt)

    # === 現貨確認 ===
    spot_raw = fetch_index_confirm(trade_date)
    spot_engine = spot_confirm_engine(spot_raw)

    # === Step 4：三合一總控 ===
    final_state = trend_engine(fut_engine, opt_engine, spot_engine)
    # =========================
    # 四大區塊｜專業操盤卡片
    # =========================
    st.markdown(
        "<h2 class='fut-section-title'>📊 大盤分析</h2>",
        unsafe_allow_html=True,
    )
    
    c1, c2, c3, c4 = st.columns(4, gap="small")
    
    # ==================================================
    # 🟥 1️⃣ 期貨卡片（價格 × 外資 OI）
    # ==================================================
    # === 期貨 OI 結構判斷（給人看的）===
    # 預設值（避免 Streamlit rerun 變數不存在）
    price_diff = 0
    price_sign = ""
    price_color = "#000000"

    oi_structure = ""
    if fut_engine["direction"] == "趨勢多" and fut_engine["delta_oi"] > 0:
        oi_structure = "🟢 價漲＋加碼（多方主導）"
    elif fut_engine["direction"] == "趨勢空" and fut_engine["delta_oi"] > 0:
        oi_structure = "🔴 價跌＋加碼（空方主導）"
    elif fut_engine["delta_oi"] < 0:
        oi_structure = "🟡 減碼中（可能進入整理）"
    else:
        oi_structure = "⚪ 結構中性"

    if prev_close is not None:
        price_diff = fut_price - prev_close
    else:
        price_diff = 0

    price_sign = "+" if price_diff > 0 else ""
    price_color = "#FF3B30" if price_diff > 0 else "#34C759" if price_diff < 0 else "#000000"

    
    with c1:
        st.markdown(
            f"""
            <div class='kpi-card'>
                <div class='kpi-title'>📈 期貨趨勢</div>
                <div class='kpi-value {fut_engine['bias']}'>
                    {fut_engine['direction']}
                </div>
                <div class='kpi-sub'>
                    收盤 {fut_price:,.0f}
                    <span style='color:{price_color}'>
                        ({price_sign}{price_diff:,.0f})
                    </span><br>
                    外資 OI {fut_engine['delta_oi']:+,} 口<br>
                    信心 {fut_engine['confidence']}%
                </div>
                <div class='kpi-sub' style='margin-top:6px; opacity:.75'>
                    結構判讀：{oi_structure}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    
    # ==================================================
    # 🟨 2️⃣ 選擇權卡片（防線 × 壓力）
    # ==================================================
    opt_text = (
        f"{opt_engine['put_wall']} – {opt_engine['call_wall']}"
        if opt_engine else "資料不足"
    )

    opt_shift = "（尚未取得昨日選擇權防線）"        
    opt_note = (
        "多方防守（Put）" if opt_engine and opt_engine["dominant"] == "put"
        else "空方防守（Call）" if opt_engine and opt_engine["dominant"] == "call"
        else "防守中性"
    )
    
    with c2:
        st.markdown(
            f"""
            <div class='kpi-card'>
                <div class='kpi-title'>🧩 選擇權防線</div>
                <div class='kpi-value'>
                    {opt_text}
                </div>
                <div class='kpi-sub'>
                    {opt_note}<br>
                    Put 支撐 / Call 壓力
                </div>
                <div class='kpi-sub' style='opacity:.75'>
                    昨日比較：{ opt_shift }
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    
    # ==================================================
    # 🟩 3️⃣ 現貨卡片（量 × 結構）
    # ==================================================
    spot_trend = "（尚未取得昨日現貨確認）"
    spot_symbol = "✔" if spot_engine["confirm"] else "✖"
    spot_color = "#FF3B30" if spot_engine["confirm"] else "#34C759"
    
    with c3:
        st.markdown(
            f"""
            <div class='kpi-card'>
                <div class='kpi-title'>📊 現貨確認</div>
                <div class='kpi-value' style='color:{spot_color}'>
                    {spot_symbol}
                </div>
                <div class='kpi-sub'>
                    {spot_engine['reason']}<br>
                    量能 vs 結構
                </div>
                <div class='kpi-sub' style='opacity:.75'>
                昨日比較：{ spot_trend }
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    
    # ==================================================
    # 🟦 4️⃣ 綜合評估卡片（最終決策）
    # ==================================================
    final_trend = "（尚未取得昨日綜合判斷）"
    state_color = (
        "#FF3B30" if "偏多" in final_state
        else "#34C759" if "偏空" in final_state
        else "#000000"
    )
    
    with c4:
        st.markdown(
            f"""
            <div class='kpi-card'>
                <div class='kpi-title'>🧠 綜合評估</div>
                <div class='kpi-value' style='color:{state_color}'>
                    {final_state}
                </div>
                <div class='kpi-sub'>
                    期貨 × 選擇權 × 現貨<br>
                    綜合判斷
                </div>
                <div class='kpi-sub' style='opacity:.75'>
                昨日比較：{ final_trend }
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

# =========================
# 第二模組：個股期貨（測試版）
# =========================
# 第二模組｜股票表格欄位設定（可擴充）
STOCK_TABLE_COLUMNS = [
    {"key": "stock_id", "label": "代碼"},
    {"key": "stock_name", "label": "名稱"},
    {"key": "close", "label": "收盤", "formatter": "price_change"},
    {"key": "volume", "label": "成交量", "formatter": "volume_k"},
    {"key": "amount", "label": "成交金額", "formatter": "amount_m"},
    {"key": "branch", "label": "券商分點"},
]

st.caption("📱 手機可左右滑動表格查看完整數據")
def render_tab_stock_futures(trade_date: dt.date):

    # 1️⃣ 先拿原始 Top20（可能是 list 或 DataFrame）
    top20_raw = fetch_top20_by_volume_twse_csv(trade_date)

    if top20_raw is None or (hasattr(top20_raw, "empty") and top20_raw.empty):
        st.warning("⚠️ 查詢日無成交量資料")
        return

    # 2️⃣ 強制轉成股票代碼 list（關鍵）
    top20_list = (
        top20_raw[["股票代碼", "股票名稱"]]
        .astype(str)
        .to_dict("records")
        if isinstance(top20_raw, pd.DataFrame)
        else [{"股票代碼": sid, "股票名稱": ""} for sid in top20_raw]
    )

    # ✅ 一次抓完所有 Top20 股票日資料
    stock_ids = [x["股票代碼"] for x in top20_list]
    df_all_stock = fetch_multi_stock_daily(stock_ids, trade_date)

    if df_all_stock.empty:
        st.warning("⚠️ 查詢日無任何個股資料")
        return

    st.markdown("### ⬤ TWSE 成交量 TOP20 股票")
    #st.write(top20_ids)

    #if not top20_ids:
    #    st.warning("⚠️ 無前十大股票")
    #    return
    
    # 3️⃣ 蒐集個股資料
    rows = []

    for item in top20_list:
        sid = item["股票代碼"]
        stock_name = item["股票名稱"]

        df_sid = df_all_stock[df_all_stock["stock_id"] == sid]
        df_day = df_sid[df_sid["date"] == trade_date.strftime("%Y-%m-%d")]
        if df_day.empty:
            continue
        r = df_day.iloc[0]

        branch_url = f"https://histock.tw/stock/branch.aspx?no={sid}"
        branch_link = (
            f"<a href='{branch_url}' target='_blank' "
            f"style='text-decoration:none;font-weight:700;'>🔗</a>"
        )
        
        # 取得前一交易日收盤價（同一 API 內）
        df_prev = (
            df_sid[df_sid["date"] < trade_date.strftime("%Y-%m-%d")]
            .sort_values("date")
        )

        prev_close = (
            df_prev.iloc[-1]["close"]
            if not df_prev.empty and pd.notna(df_prev.iloc[-1]["close"])
            else None
        )

        close_price = r["close"]

        if prev_close:
            diff_pct = (close_price - prev_close) / prev_close * 100

            # ✅ 判斷顏色
            color = "#FF3B30" if diff_pct > 0 else "#34C759" if diff_pct < 0 else "#000000"

            close_display = (
                f"<span style='color:{color}; font-weight:600;'>"
                f"{close_price:.2f} ({diff_pct:+.2f}%)"
                f"</span>"
            )
        else:
            close_display = f"{close_price:.2f}"

            
        rows.append({
            "stock_id": sid,
            "stock_name": stock_name,
            "open": r["open"],          # 保留，給 formatter 用
            "close": r["close"],
            "volume": r["Trading_Volume"],
            "amount": r["Trading_money"],
            "branch": branch_link,
        })

    if not rows:
        st.warning("⚠️ 查詢日無任何個股資料")
        return

    df_view = pd.DataFrame(rows)
    render_stock_table_html(df_view)

# =========================
# 主流程
# =========================
default_trade_date = get_latest_trading_date()
trade_date = st.date_input(
    "📅 查詢交易日（結算）",
    value=default_trade_date
)

if not is_trading_day(trade_date):
    st.warning("📅 非交易日")
    st.stop()

tab1, tab2 = st.tabs(["📈 期權趨勢", "📊 個股期貨"])

with tab1:
    render_tab_option_market(trade_date)

with tab2:
    render_tab_stock_futures(trade_date)
