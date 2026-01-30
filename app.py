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
st.set_page_config(page_title="台指期貨 / 選擇權 AI 儀表板", layout="wide")

APP_TITLE = "台指期貨 / 選擇權 AI 儀表板（第二階段：真實盤後資料接入）"

st.markdown(
    """
<style>
/* ✅ 預留 header 空間，避免標題被截掉 */
div[data-testid="stAppViewContainer"] > .main { padding-top: 3.8rem; }
.block-container { padding-top: 0.8rem; padding-bottom: 0.8rem; }
header[data-testid="stHeader"] { background: transparent; }

.app-title{
  font-size: 2.15rem; font-weight: 900; line-height: 1.20;
  margin: 0; padding-top: 0.35rem;
  word-break: break-word; overflow-wrap: anywhere;
}
.app-subtitle{ font-size: 0.95rem; opacity: 0.75; margin: 0.25rem 0 0.8rem 0; }

.kpi-card{
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: 14px;
  padding: 14px 16px;
  background: rgba(255,255,255,0.04);
  box-shadow: 0 6px 22px rgba(0,0,0,0.18);
}
.kpi-title{ font-size: 0.95rem; opacity: 0.85; margin-bottom: 6px; }
.kpi-value{ font-size: 2.0rem; font-weight: 800; line-height: 1.1; }
.kpi-sub{ font-size: 0.9rem; opacity: 0.75; margin-top: 6px; }

.bull { color: #FF3B30; } /* 偏多紅 */
.bear { color: #34C759; } /* 偏空綠 */
.neut { color: #C7C7CC; } /* 中性灰 */

[data-testid="stDataFrame"] { border-radius: 12px; overflow: hidden; }
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    f"""
<div class="app-title">{APP_TITLE}</div>
<div class="app-subtitle">
⚠️ 本儀表板已加入「交易日 trade_date」正規化：避免夜盤跨日導致週末出現資料、或週內相鄰日資料雷同。
你可選擇只看日盤 / 只看夜盤 / 日盤+夜盤（清楚區分）。
</div>
""",
    unsafe_allow_html=True,
)

# Debug 開關：可用網址加參數 ?debug=1
params = st.query_params
debug_mode = str(params.get("debug", "0")).lower() in ("1", "true", "yes", "y")


# =========================
# Secrets / Token
# =========================
def get_finmind_token() -> str:
    token = ""
    try:
        token = str(st.secrets.get("FINMIND_TOKEN", "")).strip()
    except Exception:
        token = ""
    if not token:
        token = os.environ.get("FINMIND_TOKEN", "").strip()
    return token


FINMIND_TOKEN = get_finmind_token()


def debug_panel():
    st.subheader("🛠️ Debug 狀態檢查")
    if FINMIND_TOKEN:
        st.success("✅ FINMIND_TOKEN 已成功載入")
        st.caption(f"Token 長度：{len(FINMIND_TOKEN)}")
    else:
        st.error("❌ FINMIND_TOKEN 未載入（請至 Streamlit Cloud → Manage app → Settings → Secrets 設定）")
    st.caption("提示：在網址後面加上 ?debug=1 可顯示更多 debug 資訊。")


if debug_mode:
    debug_panel()
else:
    if not FINMIND_TOKEN:
        st.warning("FINMIND_TOKEN 尚未設定，資料將無法抓取。可在網址加 ?debug=1 查看詳細。")


# =========================
# FinMind API
# =========================
FINMIND_API = "https://api.finmindtrade.com/api/v4/data"


@st.cache_data(ttl=60 * 10, show_spinner=False)
def finmind_get(dataset: str, data_id: str, start_date: str, end_date: str, token: str) -> pd.DataFrame:
    if not token:
        return pd.DataFrame()

    params = {
        "dataset": dataset,
        "data_id": data_id,
        "start_date": start_date,
        "end_date": end_date,
        "token": token,
    }
    r = requests.get(FINMIND_API, params=params, timeout=30)
    if r.status_code != 200:
        return pd.DataFrame()

    js = r.json()
    data = js.get("data", [])
    if not data:
        return pd.DataFrame()

    return pd.DataFrame(data)


def to_ymd(d: dt.date) -> str:
    return d.strftime("%Y-%m-%d")


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def clamp01(x: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, x))


def is_trading_data_ok(df: pd.DataFrame) -> bool:
    if df is None or df.empty:
        return False
    need_cols = {"date", "futures_id", "contract_date", "close", "volume"}
    return need_cols.issubset(set(df.columns))


def is_weekend(d: dt.date) -> bool:
    return d.weekday() in (5, 6)


def rollback_to_friday(d: dt.date) -> dt.date:
    # Sat->Fri (-1), Sun->Fri (-2)
    if d.weekday() == 5:
        return d - dt.timedelta(days=1)
    if d.weekday() == 6:
        return d - dt.timedelta(days=2)
    return d


# =========================
# ✅ 核心：建立 trade_date（交易日）避免夜盤跨日
# =========================
def add_trade_date(df: pd.DataFrame) -> pd.DataFrame:
    """
    建立 trade_date（交易日）：
    - regular：trade_date = date
    - after_market：
        (1) 若 date 落在週末，trade_date 回推到週五
        (2) 若 date 當天沒有 regular，但前一天有 regular，trade_date = 前一天
    """
    x = df.copy()

    x["date_dt"] = pd.to_datetime(x["date"], errors="coerce")
    x = x.dropna(subset=["date_dt"])
    x["cal_date"] = x["date_dt"].dt.date

    if "trading_session" not in x.columns:
        x["trading_session"] = "unknown"
    x["trading_session"] = x["trading_session"].astype(str)

    # 收集所有 regular 的日期，用來判斷夜盤是否被寫到隔天
    regular_dates = set(x.loc[x["trading_session"] == "regular", "cal_date"].unique().tolist())

    def _map_trade_date(row) -> dt.date:
        d: dt.date = row["cal_date"]
        sess = row["trading_session"]

        if sess != "after_market":
            return d

        # (1) 週末回推
        if d.weekday() == 5:
            return d - dt.timedelta(days=1)
        if d.weekday() == 6:
            return d - dt.timedelta(days=2)

        # (2) 週內跨日：如果當天沒有 regular，但前一天有 regular → 歸屬前一天
        prev = d - dt.timedelta(days=1)
        if (d not in regular_dates) and (prev in regular_dates):
            return prev

        # 否則保留當日（避免把週一夜盤錯歸到週日）
        return d

    x["trade_date"] = x.apply(_map_trade_date, axis=1)
    return x


# =========================
# ✅ 抓取一段範圍，再用 trade_date 取「最近有效交易日」
# =========================
@st.cache_data(ttl=60 * 10, show_spinner=False)
def fetch_tx_window(end_date: dt.date, lookback_days: int = 20) -> pd.DataFrame:
    start = end_date - dt.timedelta(days=lookback_days)
    df = finmind_get(
        dataset="TaiwanFuturesDaily",
        data_id="TX",
        start_date=to_ymd(start),
        end_date=to_ymd(end_date),
        token=FINMIND_TOKEN,
    )
    if df.empty:
        return df
    df = df[df["futures_id"].astype(str) == "TX"].copy()
    if not is_trading_data_ok(df):
        return pd.DataFrame()
    return add_trade_date(df)


def select_valid_trade_date(df_win: pd.DataFrame, target_date: dt.date) -> dt.date | None:
    """
    ✅ 選擇 <= target_date 的最近 trade_date
    target_date 若是週末，就用週末本身當上限（自然會回到週五）
    """
    if df_win is None or df_win.empty:
        return None
    candidates = sorted({d for d in df_win["trade_date"].unique().tolist() if isinstance(d, dt.date)})
    candidates = [d for d in candidates if d <= target_date]
    return max(candidates) if candidates else None


def filter_by_display_mode(df_day: pd.DataFrame, mode: str) -> pd.DataFrame:
    if df_day is None or df_day.empty:
        return df_day
    if mode == "僅日盤(regular)":
        return df_day[df_day["trading_session"] == "regular"].copy()
    if mode == "僅夜盤(after_market)":
        return df_day[df_day["trading_session"] == "after_market"].copy()
    # 日盤+夜盤
    return df_day.copy()


# =========================
# 主力合約 + AI 分數
# =========================
def pick_main_contract(df: pd.DataFrame) -> pd.Series | None:
    if df is None or df.empty:
        return None

    x = df.copy()
    x["contract_date_str"] = x["contract_date"].astype(str)
    x = x[x["contract_date_str"].str.fullmatch(r"\d{6}", na=False)]
    if x.empty:
        return None

    x["volume_num"] = pd.to_numeric(x["volume"], errors="coerce").fillna(0)
    idx = x["volume_num"].idxmax()
    return x.loc[idx]


def score_to_label(score: float) -> str:
    if score >= 1.5:
        return "偏多"
    if score <= -1.5:
        return "偏空"
    return "震盪/中性"


def calc_ai_scores(main_row: pd.Series, df_all: pd.DataFrame) -> dict:
    open_ = float(main_row.get("open", 0) or 0)
    close_ = float(main_row.get("close", 0) or 0)
    high_ = float(main_row.get("max", 0) or 0)
    low_ = float(main_row.get("min", 0) or 0)

    spread_points = close_ - open_
    range_points = max(0.0, high_ - low_)
    body = abs(spread_points)

    vol = float(pd.to_numeric(main_row.get("volume", 0), errors="coerce") or 0)

    base_df = df_all.copy()
    base_df["contract_date_str"] = base_df["contract_date"].astype(str)
    base_df = base_df[base_df["contract_date_str"].str.fullmatch(r"\d{6}", na=False)]
    base_df["volume_num"] = pd.to_numeric(base_df["volume"], errors="coerce").fillna(0)
    vol_med = float(base_df["volume_num"].median()) if not base_df.empty else max(vol, 1.0)

    vol_ratio = vol / max(vol_med, 1.0)
    vol_score = clamp((vol_ratio - 1.0) * 2.0, -2.0, 2.0)

    structure_score = 0.0
    structure_text = "無法計算"
    try:
        base_df_sorted = base_df.sort_values("contract_date_str")
        first_two = base_df_sorted.head(2)
        if len(first_two) >= 2:
            near_close = float(first_two.iloc[0]["close"])
            next_close = float(first_two.iloc[1]["close"])
            term_spread = next_close - near_close
            structure_score = clamp(term_spread / 80.0, -2.0, 2.0)
            structure_text = f"{term_spread:+.0f} 點（次月-近月）"
        elif len(first_two) == 1:
            structure_text = "僅一個合約"
    except Exception:
        pass

    momentum_score = clamp(spread_points / 100.0, -3.0, 3.0)

    final_score = (momentum_score * 0.60) + (structure_score * 0.25) + (vol_score * 0.15)
    final_score = float(clamp(final_score, -5.0, 5.0))
    direction_text_local = score_to_label(final_score)

    sign_m = 1 if momentum_score > 0 else (-1 if momentum_score < 0 else 0)
    sign_s = 1 if structure_score > 0 else (-1 if structure_score < 0 else 0)
    sign_v = 1 if vol_score > 0 else (-1 if vol_score < 0 else 0)
    votes = [sign_m, sign_s, sign_v]
    majority = max(votes.count(1), votes.count(-1), votes.count(0))
    consistency_pct = int(round((majority / 3.0) * 100))

    if range_points <= 0:
        risk_score = 50
    else:
        wick_ratio = 1.0 - (body / range_points)
        volat = clamp(range_points / 250.0, 0.0, 2.0)
        risk_raw = (wick_ratio * 60.0) + (volat * 20.0) + (abs(structure_score) * 10.0)
        risk_score = int(clamp(risk_raw, 0.0, 100.0))

    return {
        "direction_text": direction_text_local,
        "final_score": round(final_score, 2),
        "consistency_pct": consistency_pct,
        "risk_score": risk_score,
        "tx_last_price": close_,
        "tx_spread_points": spread_points,
        "tx_range_points": range_points,
        "structure_text": structure_text,
        "vol_ratio": round(vol_ratio, 2),
        "main_contract": str(main_row.get("contract_date", "")),
    }


# =========================
# 主力成本（VWAP）
# =========================
@st.cache_data(ttl=60 * 30, show_spinner=False)
def fetch_tx_contract_history(end_date: dt.date, contract_yyyymm: str, lookback_days: int = 60) -> pd.DataFrame:
    start_date = end_date - dt.timedelta(days=lookback_days)
    df = finmind_get(
        dataset="TaiwanFuturesDaily",
        data_id="TX",
        start_date=to_ymd(start_date),
        end_date=to_ymd(end_date),
        token=FINMIND_TOKEN,
    )
    if df.empty:
        return df

    df = df[df["futures_id"].astype(str) == "TX"].copy()
    df = add_trade_date(df)

    # VWAP 計算建議以日盤為主（避免夜盤跨日干擾）
    if "trading_session" in df.columns:
        df_reg = df[df["trading_session"] == "regular"].copy()
        if not df_reg.empty:
            df = df_reg

    df["contract_date_str"] = df["contract_date"].astype(str)
    df = df[df["contract_date_str"].str.fullmatch(r"\d{6}", na=False)]
    df = df[df["contract_date_str"] == str(contract_yyyymm)]

    df["close_num"] = pd.to_numeric(df.get("close", 0), errors="coerce")
    df["settle_num"] = pd.to_numeric(df.get("settlement_price", 0), errors="coerce")
    df["vol_num"] = pd.to_numeric(df.get("volume", 0), errors="coerce").fillna(0)

    df["date_dt"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date_dt"]).sort_values("date_dt")
    return df


def calc_cost_vwap(df_hist: pd.DataFrame, n: int = 20, price_col: str = "close_num") -> float | None:
    if df_hist is None or df_hist.empty:
        return None

    x = df_hist.tail(n).copy()
    if price_col not in x.columns:
        return None

    x = x.dropna(subset=[price_col])
    if x.empty:
        return None

    vol_sum = float(x["vol_num"].sum())
    if vol_sum <= 0:
        return float(x[price_col].mean())

    return float((x[price_col] * x["vol_num"]).sum() / vol_sum)


# =========================
# 方向強度（-100%~+100%）
# =========================
def calc_directional_score(close_price: float, vwap20: float | None, vol_ratio: float | None, open_price: float | None = None) -> dict:
    scores = {}
    if vwap20 is not None and vwap20 > 0:
        diff = (close_price - vwap20) / vwap20
        scores["cost"] = clamp01(diff * 5.0)
    else:
        scores["cost"] = 0.0

    if vol_ratio is not None:
        scores["volume"] = clamp01((float(vol_ratio) - 1.0) * 1.2)
    else:
        scores["volume"] = 0.0

    if open_price is not None and float(open_price) > 0:
        scores["intraday"] = clamp01((close_price - float(open_price)) / float(open_price) * 5.0)
    else:
        scores["intraday"] = 0.0
    return scores


# =========================
# UI
# =========================
today = dt.date.today()
target_date = st.date_input("查詢日期（盤後）", value=today)

display_mode = st.radio(
    "盤別顯示模式（已用 trade_date 正規化）",
    ["僅日盤(regular)", "僅夜盤(after_market)", "日盤+夜盤(區分顯示)"],
    horizontal=True,
)

with st.spinner("抓取 TX 盤後資料中..."):
    df_win = fetch_tx_window(end_date=target_date, lookback_days=25)

if df_win is None or df_win.empty:
    st.error("目前抓不到 TX 盤後資料（可能連續假期 / 或資料尚未更新 / 或 Token 權限問題）。")
    st.stop()

valid_trade_date = select_valid_trade_date(df_win, target_date)
if valid_trade_date is None:
    st.error("在回溯範圍內找不到 <= 查詢日期 的有效交易日資料。")
    st.stop()

# 取同一個交易日（trade_date）資料
df_day_all = df_win[df_win["trade_date"] == valid_trade_date].copy()
df_day = filter_by_display_mode(df_day_all, display_mode)

# ✅ UI 提示：週末/非交易日
if target_date != valid_trade_date:
    st.warning(f"📌 你選的日期：{to_ymd(target_date)} 為非交易日/無日盤資料，本程式顯示最近有效交易日：{to_ymd(valid_trade_date)}")
else:
    st.success(f"✅ 交易日：{to_ymd(valid_trade_date)}")

st.caption(f"視窗資料筆數：{len(df_win)} ｜ 本交易日筆數（全部盤別）：{len(df_day_all)} ｜ 目前顯示筆數：{len(df_day)}")

# =========================
# ✅ KPI 計算：為了穩定，方向/強度基準以「日盤」優先
# =========================
df_for_calc = df_day_all.copy()
if "trading_session" in df_for_calc.columns:
    df_reg = df_for_calc[df_for_calc["trading_session"] == "regular"].copy()
    if not df_reg.empty:
        df_for_calc = df_reg

main_row = pick_main_contract(df_for_calc)
if main_row is None:
    st.warning("抓到資料，但找不到可判定的『主力單一合約』（可能欄位異常）。")
    st.dataframe(df_day, width="stretch", height=260)
    st.stop()

ai = calc_ai_scores(main_row, df_for_calc)

# 方向顏色
raw_dir = str(ai.get("direction_text", "震盪/中性"))
if "偏多" in raw_dir:
    mood_class = "bull"
    mood_text = "偏多"
elif "偏空" in raw_dir:
    mood_class = "bear"
    mood_text = "偏空"
else:
    mood_class = "neut"
    mood_text = "中性"

# VWAP（以交易日 valid_trade_date 作為 end_date）
main_contract = ai["main_contract"]
df_main_hist = fetch_tx_contract_history(valid_trade_date, main_contract, lookback_days=60)

vwap_20_close = calc_cost_vwap(df_main_hist, n=20, price_col="close_num")
vwap_10_close = calc_cost_vwap(df_main_hist, n=10, price_col="close_num")
vwap_20_settle = calc_cost_vwap(df_main_hist, n=20, price_col="settle_num")

avg20_close = None
if df_main_hist is not None and not df_main_hist.empty:
    avg20_close = float(df_main_hist.tail(20)["close_num"].dropna().mean())

# 方向強度
try:
    factor_scores = calc_directional_score(
        close_price=float(main_row.get("close", 0) or 0),
        vwap20=vwap_20_close,
        vol_ratio=ai.get("vol_ratio"),
        open_price=main_row.get("open"),
    )
    WEIGHTS = {"cost": 0.45, "volume": 0.25, "intraday": 0.30}
    raw_score = sum(factor_scores.get(k, 0.0) * WEIGHTS[k] for k in WEIGHTS)
    final_score_pct = int(clamp01(raw_score) * 100)
except Exception:
    final_score_pct = 0
    factor_scores = {}

# 正負號跟方向一致
if mood_text == "偏空":
    final_score_pct = -abs(int(final_score_pct))
elif mood_text == "偏多":
    final_score_pct = abs(int(final_score_pct))
else:
    final_score_pct = int(clamp(final_score_pct / 100.0, -0.19, 0.19) * 100)

direction_text = (
    "強烈偏多" if final_score_pct >= 60 else
    "偏多" if final_score_pct >= 20 else
    "中性" if final_score_pct > -20 else
    "偏空" if final_score_pct > -60 else
    "強烈偏空"
)

cons_dot = "🟢" if ai["consistency_pct"] >= 70 else ("🟠" if ai["consistency_pct"] >= 45 else "🔴")
risk_dot = "🔴" if ai["risk_score"] >= 70 else ("🟠" if ai["risk_score"] >= 45 else "🟢")

c1, c2, c3, c4, c5 = st.columns([1.6, 1.6, 1.2, 1.2, 1.4], gap="small")

with c1:
    st.markdown(f"""
    <div class="kpi-card">
      <div class="kpi-title">方向</div>
      <div class="kpi-value {mood_class}">{mood_text}</div>
      <div class="kpi-sub">原始：{ai["direction_text"]} ｜ 主力：{ai["main_contract"]}</div>
    </div>
    """, unsafe_allow_html=True)

with c2:
    st.markdown(f"""
    <div class="kpi-card">
      <div class="kpi-title">方向強度（-100%~+100%）</div>
      <div class="kpi-value {mood_class}">{final_score_pct:+d}%</div>
      <div class="kpi-sub">{direction_text}</div>
    </div>
    """, unsafe_allow_html=True)

with c3:
    st.markdown(f"""
    <div class="kpi-card">
      <div class="kpi-title">{cons_dot} 一致性</div>
      <div class="kpi-value">{ai["consistency_pct"]}%</div>
      <div class="kpi-sub">多因子同向程度</div>
    </div>
    """, unsafe_allow_html=True)

with c4:
    st.markdown(f"""
    <div class="kpi-card">
      <div class="kpi-title">{risk_dot} 風險</div>
      <div class="kpi-value">{ai["risk_score"]}/100</div>
      <div class="kpi-sub">波動與不確定性</div>
    </div>
    """, unsafe_allow_html=True)

with c5:
    st.markdown(f"""
    <div class="kpi-card">
      <div class="kpi-title">TXF 盤後收盤</div>
      <div class="kpi-value">{ai["tx_last_price"]:.0f}</div>
      <div class="kpi-sub">日變化：{ai["tx_spread_points"]:+.0f} 點 ｜ 區間：{ai["tx_range_points"]:.0f} 點</div>
    </div>
    """, unsafe_allow_html=True)

with st.expander("📌 主力成本與量能細節", expanded=True):
    info1, info2, info3, info4, info5, info6 = st.columns(6)
    info1.caption(f"主力合約：**{ai['main_contract']}**")
    info2.caption(f"主力成本(10D VWAP)：**{(f'{vwap_10_close:.0f}' if vwap_10_close is not None else '—')}**")
    info3.caption(f"主力成本(20D VWAP)：**{(f'{vwap_20_close:.0f}' if vwap_20_close is not None else '—')}**")
    info4.caption(f"主力成本(20D settle)：**{(f'{vwap_20_settle:.0f}' if vwap_20_settle is not None else '—')}**")
    info5.caption(f"20D 平均收盤：**{(f'{avg20_close:.0f}' if avg20_close is not None else '—')}**")
    info6.caption(f"量能比：**{ai['vol_ratio']}x**")

st.divider()

# =========================
# ✅ 表格：清楚顯示 trade_date / cal_date / session
# =========================
show_cols = [
    "trade_date", "cal_date", "trading_session",
    "date", "futures_id", "contract_date",
    "open", "max", "min", "close",
    "spread", "spread_per", "volume",
    "settlement_price", "open_interest",
]
for c in show_cols:
    if c not in df_day.columns:
        df_day[c] = None

df_show = df_day[show_cols].copy()
df_show["contract_date_str"] = df_show["contract_date"].astype(str)
is_single = df_show["contract_date_str"].str.fullmatch(r"\d{6}", na=False)
df_single = df_show[is_single].sort_values(["trade_date", "contract_date_str", "trading_session"])
df_spread = df_show[~is_single].sort_values(["trade_date", "contract_date_str", "trading_session"])
df_show2 = pd.concat([df_single, df_spread], ignore_index=True).drop(columns=["contract_date_str"], errors="ignore")

with st.expander("📊 盤後原始資料表（以 trade_date 篩選同一交易日）", expanded=False):
    st.dataframe(df_show2, width="stretch", height=280)

if debug_mode:
    st.divider()
    st.subheader("🔎 Debug：候選 trade_date（<=查詢日）")
    cand = sorted({d for d in df_win["trade_date"].unique().tolist() if isinstance(d, dt.date) and d <= target_date})
    st.write([to_ymd(d) for d in cand][-10:])
    st.subheader("🔎 Debug：方向因子分數")
    st.write(factor_scores)
