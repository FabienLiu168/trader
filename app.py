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
✅ 本版已改成：只有「查詢日期本身有資料」才顯示 UI；不再顯示最近有效交易日。<br/>
✅ 並修正「僅日盤」表格空白問題：若資料源無 regular，會提示並自動 fallback 顯示 after_market（避免空白誤判）。
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


# =========================
# ✅ 核心：建立 trade_date（交易日）避免夜盤跨日
# =========================
def add_trade_date(df: pd.DataFrame) -> pd.DataFrame:
    """
    建立 trade_date（交易日）：
    - regular：trade_date = date
    - after_market：
        (1) 週末回推到週五
        (2) 若 date 當天沒有 regular 但前一天有 regular → 歸屬前一天（解決 1/26 & 1/27 同時出現）
    """
    x = df.copy()
    x["date_dt"] = pd.to_datetime(x["date"], errors="coerce")
    x = x.dropna(subset=["date_dt"])
    x["cal_date"] = x["date_dt"].dt.date

    if "trading_session" not in x.columns:
        x["trading_session"] = "after_market"  # ✅ 保底：此 dataset 常見只有 after_market
    x["trading_session"] = x["trading_session"].astype(str)

    regular_dates = set(x.loc[x["trading_session"] == "regular", "cal_date"].unique().tolist())

    def _map_trade_date(row) -> dt.date:
        d: dt.date = row["cal_date"]
        sess = row["trading_session"]

        if sess != "after_market":
            return d

        # 週末回推
        if d.weekday() == 5:
            return d - dt.timedelta(days=1)
        if d.weekday() == 6:
            return d - dt.timedelta(days=2)

        # 週內跨日：當天沒 regular、前一天有 regular → 歸屬前一天
        prev = d - dt.timedelta(days=1)
        if (d not in regular_dates) and (prev in regular_dates):
            return prev

        return d

    x["trade_date"] = x.apply(_map_trade_date, axis=1)
    return x


# =========================
# ✅ 抓取一段範圍（含跨日夜盤），但只顯示「查詢日 trade_date」
# =========================
@st.cache_data(ttl=60 * 10, show_spinner=False)
def fetch_tx_window(end_date: dt.date, lookback_days: int = 25) -> pd.DataFrame:
    start = end_date - dt.timedelta(days=lookback_days)
    df = finmind_get(
        dataset="TaiwanFuturesDaily",
        data_id="TX",
        start_date=to_ymd(start),
        end_date=to_ymd(end_date + dt.timedelta(days=2)),  # ✅ 多抓 2 天，涵蓋夜盤跨日
        token=FINMIND_TOKEN,
    )
    if df.empty:
        return df
    df = df[df["futures_id"].astype(str) == "TX"].copy()
    if not is_trading_data_ok(df):
        return pd.DataFrame()
    return add_trade_date(df)


def filter_by_display_mode(df_day: pd.DataFrame, mode: str) -> tuple[pd.DataFrame, str | None]:
    """
    回傳 (df_filtered, warning_text)
    ✅ 修正：若使用者選「僅日盤」但資料源根本沒有 regular，就不要回空白
       → 顯示提示，並 fallback 顯示 after_market
    """
    if df_day is None or df_day.empty:
        return df_day, None

    sess = df_day.get("trading_session")
    has_regular = False
    if sess is not None:
        has_regular = (sess.astype(str) == "regular").any()

    if mode == "僅日盤(regular)":
        if has_regular:
            return df_day[df_day["trading_session"] == "regular"].copy(), None
        # ✅ 來源沒有 regular（常見於 TaiwanFuturesDaily）
        return df_day[df_day["trading_session"] == "after_market"].copy(), "⚠️ 本資料源在此交易日沒有 regular（日盤）欄位，僅提供 after_market（盤後/結算）。已自動改以 after_market 顯示，避免表格空白。"

    if mode == "僅夜盤(after_market)":
        return df_day[df_day["trading_session"] == "after_market"].copy(), None

    return df_day.copy(), None


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
    "盤別顯示模式",
    ["僅日盤(regular)", "僅夜盤(after_market)", "日盤+夜盤(區分顯示)"],
    horizontal=True,
)

with st.spinner("抓取 TX 資料中..."):
    df_win = fetch_tx_window(end_date=target_date, lookback_days=25)

if df_win is None or df_win.empty:
    st.error("目前抓不到 TX 資料（可能連續假期 / 或資料尚未更新 / 或 Token 權限問題）。")
    st.stop()

# ✅ 不回溯：只取「查詢日期本身」的 trade_date
df_day_all = df_win[df_win["trade_date"] == target_date].copy()

if df_day_all.empty:
    st.error(f"❌ 查詢日期 {to_ymd(target_date)} 沒有資料（本版已設定：不回溯最近有效交易日）。請改選有資料的交易日。")
    if debug_mode:
        st.caption("Debug：最近 10 筆可用 trade_date：")
        dates = sorted({d for d in df_win["trade_date"].unique().tolist() if isinstance(d, dt.date)})
        st.write([to_ymd(d) for d in dates[-10:]])
    st.stop()

# 套用顯示模式（含「僅日盤」fallback 修正）
df_day, warn_text = filter_by_display_mode(df_day_all, display_mode)
if warn_text:
    st.warning(warn_text)

st.success(f"✅ 查詢日期有資料：{to_ymd(target_date)}（trade_date）")
st.caption(f"本交易日筆數（全部盤別）：{len(df_day_all)} ｜ 目前顯示筆數：{len(df_day)}")

# KPI 計算：用 df_day_all（不受你選的顯示模式影響，避免 KPI 因切換而崩）
main_row = pick_main_contract(df_day_all)
if main_row is None:
    st.warning("抓到資料，但找不到可判定的『主力單一合約』（可能欄位異常）。")
    st.dataframe(df_day, width="stretch", height=280)
    st.stop()

ai = calc_ai_scores(main_row, df_day_all)

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

# 方向強度（簡版，不再依 VWAP，避免你切盤別造成混淆；之後要再接 VWAP 我再幫你加回）
try:
    factor_scores = calc_directional_score(
        close_price=float(main_row.get("close", 0) or 0),
        vwap20=None,
        vol_ratio=ai.get("vol_ratio"),
        open_price=main_row.get("open"),
    )
    WEIGHTS = {"volume": 0.55, "intraday": 0.45}
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

st.divider()

# =========================
# 表格（清楚顯示 trade_date / cal_date / session）
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

with st.expander("📊 盤後原始資料表（只顯示查詢日 trade_date）", expanded=False):
    st.dataframe(df_show2, width="stretch", height=320)

if debug_mode:
    st.divider()
    st.subheader("🔎 Debug：trading_session 分布（本查詢日）")
    st.write(df_day_all["trading_session"].value_counts(dropna=False))
    st.subheader("🔎 Debug：方向因子分數")
    st.write(factor_scores)
