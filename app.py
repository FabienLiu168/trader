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
st.title(APP_TITLE)
st.markdown("""
<style>
/* 讓整體上方留白變小，避免畫面浪費 */
.block-container { padding-top: 1.0rem; padding-bottom: 0.8rem; }

/* KPI 卡片 */
.kpi-card{
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: 14px;
  padding: 14px 16px;
  background: rgba(255,255,255,0.04);
  box-shadow: 0 6px 22px rgba(0,0,0,0.18);
}

/* 大字標題 */
.kpi-title{
  font-size: 0.95rem;
  opacity: 0.85;
  margin-bottom: 6px;
}

/* 超大數字 */
.kpi-value{
  font-size: 2.0rem;
  font-weight: 800;
  line-height: 1.1;
}

/* 次資訊 */
.kpi-sub{
  font-size: 0.9rem;
  opacity: 0.75;
  margin-top: 6px;
}

/* 多空顏色：你指定「偏多紅、偏空綠」 */
.bull { color: #FF3B30; } /* 大紅 */
.bear { color: #34C759; } /* 大綠 */
.neut { color: #C7C7CC; } /* 灰 */

/* 讓 dataframe 不要把畫面撐太長：可視區域內顯示 */
[data-testid="stDataFrame"] { border-radius: 12px; overflow: hidden; }
</style>
""", unsafe_allow_html=True)


# Debug 開關：可用網址加參數 ?debug=1
params = st.query_params
debug_mode = str(params.get("debug", "0")).lower() in ("1", "true", "yes", "y")

# 保底預設（避免 NameError）
final_score_pct = 0
direction_text = "中性"


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


# =========================
# Debug 區塊
# =========================
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
# FinMind API (盤後：TaiwanFuturesDaily)
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
    """通用夾限（給你原本 calc_ai_scores 用）"""
    return max(lo, min(hi, v))


def clamp01(x: float, low: float = -1.0, high: float = 1.0) -> float:
    """方向分數專用（-1~+1）"""
    return max(low, min(high, x))


def is_trading_data_ok(df: pd.DataFrame) -> bool:
    if df is None or df.empty:
        return False
    need_cols = {"date", "futures_id", "contract_date", "close", "volume"}
    return need_cols.issubset(set(df.columns))


def backtrack_find_valid_date(target_date: dt.date, max_back_days: int = 14) -> tuple[dt.date | None, pd.DataFrame]:
    for i in range(max_back_days + 1):
        d = target_date - dt.timedelta(days=i)
        s = to_ymd(d)
        df = finmind_get(
            dataset="TaiwanFuturesDaily",
            data_id="TX",
            start_date=s,
            end_date=s,
            token=FINMIND_TOKEN,
        )
        if is_trading_data_ok(df):
            df = df[df["futures_id"].astype(str) == "TX"].copy()
            return d, df
    return None, pd.DataFrame()


# =========================
# 主力合約選擇 + AI 分數
# =========================
def pick_main_contract(df: pd.DataFrame) -> pd.Series | None:
    if df.empty:
        return None

    x = df.copy()

    if "trading_session" in x.columns:
        x = x[x["trading_session"].astype(str) == "after_market"]

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
    if "trading_session" in df.columns:
        df = df[df["trading_session"].astype(str) == "after_market"]

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
# 方向分數（-100%~+100%）
# =========================
def calc_directional_score(
    close_price: float,
    vwap20: float | None,
    vol_ratio: float | None,
    pcr: float | None,
    atm_iv: float | None,
    open_price: float | None = None,
) -> dict:
    scores = {}

    # 主力成本偏離
    if vwap20 is not None and vwap20 > 0:
        diff = (close_price - vwap20) / vwap20
        scores["cost"] = clamp01(diff * 5.0)
    else:
        scores["cost"] = 0.0

    # 量能（>1 偏多）
    if vol_ratio is not None:
        scores["volume"] = clamp01((float(vol_ratio) - 1.0) * 1.2)
    else:
        scores["volume"] = 0.0

    # PCR（尚未接：先給 0）
    if pcr is not None:
        scores["pcr"] = clamp01((1.0 - float(pcr)) * 1.5)
    else:
        scores["pcr"] = 0.0

    # IV（尚未接：先給 0）
    if atm_iv is not None:
        scores["iv"] = clamp01((20.0 - float(atm_iv)) / 20.0)
    else:
        scores["iv"] = 0.0

    # 日內動能
    if open_price is not None and float(open_price) > 0:
        scores["intraday"] = clamp01((close_price - float(open_price)) / float(open_price) * 5.0)
    else:
        scores["intraday"] = 0.0

    return scores


# =========================
# UI：查詢日期（盤後）
# =========================
today = dt.date.today()
st.caption("提示：盤後資料通常在收盤後更新；若當天尚未更新，本程式會自動回溯到最近有資料的交易日。")
target_date = st.date_input("查詢日期（盤後）", value=today)

with st.spinner("抓取 TX 盤後資料中..."):
    valid_date, df_tx = backtrack_find_valid_date(target_date, max_back_days=14)

if valid_date is None or df_tx.empty:
    st.error("目前抓不到 TX 盤後資料（可能連續假期 / 或資料尚未更新 / 或 Token 權限問題）。")
    st.stop()

# 顯示回溯結果
st.markdown("### 📌 TXF 盤後資料（自動回溯找最近有效交易日）")
st.success(f"✅ 抓到資料！你選的日期：{to_ymd(target_date)} → 實際抓到資料日期：{to_ymd(valid_date)}")
st.caption(f"筆數：{len(df_tx)}")

# 主力與 AI
main_row = pick_main_contract(df_tx)
if main_row is None:
    st.warning("抓到資料，但找不到可判定的『主力單一合約』（可能資料結構變更或欄位異常）。")
    st.dataframe(df_tx, width="stretch")
    st.stop()

ai = calc_ai_scores(main_row, df_tx)

# 主力成本
main_contract = ai["main_contract"]
df_main_hist = fetch_tx_contract_history(valid_date, main_contract, lookback_days=60)

vwap_20_close = calc_cost_vwap(df_main_hist, n=20, price_col="close_num")
vwap_10_close = calc_cost_vwap(df_main_hist, n=10, price_col="close_num")
vwap_20_settle = calc_cost_vwap(df_main_hist, n=20, price_col="settle_num")

avg20_close = None
if df_main_hist is not None and not df_main_hist.empty:
    avg20_close = float(df_main_hist.tail(20)["close_num"].dropna().mean())

# ✅ 先算 final_score_pct（避免 NameError / 0 值問題）
try:
    factor_scores = calc_directional_score(
        close_price=float(main_row.get("close", 0) or 0),
        vwap20=vwap_20_close,
        vol_ratio=ai.get("vol_ratio"),
        pcr=None,       # TXO 尚未接入，先 None
        atm_iv=None,    # TXO 尚未接入，先 None
        open_price=main_row.get("open"),
    )

    WEIGHTS = {
        "cost": 0.45,
        "volume": 0.25,
        "intraday": 0.30,
        # pcr/iv 後續接 TXO 再加回來
    }

    raw_score = sum(factor_scores.get(k, 0.0) * WEIGHTS[k] for k in WEIGHTS)
    final_score_pct = int(clamp01(raw_score) * 100)
except Exception:
    final_score_pct = 0
    factor_scores = {}   # ✅ 保底避免 debug_mode 時引用不到


direction_text = (
    "強烈偏多" if final_score_pct >= 60 else
    "偏多" if final_score_pct >= 20 else
    "中性" if final_score_pct > -20 else
    "偏空" if final_score_pct > -60 else
    "強烈偏空"
)

# KPI 區
# ===== KPI 顏色邏輯 =====
if final_score_pct >= 20:
    mood_class = "bull"
    mood_text = "偏多"
elif final_score_pct <= -20:
    mood_class = "bear"
    mood_text = "偏空"
else:
    mood_class = "neut"
    mood_text = "中性"

# 一致性/風險燈號
cons_dot = "🟢" if ai["consistency_pct"] >= 70 else ("🟠" if ai["consistency_pct"] >= 45 else "🔴")
risk_dot = "🔴" if ai["risk_score"] >= 70 else ("🟠" if ai["risk_score"] >= 45 else "🟢")

# ===== KPI 區（頂部卡片：單螢幕設計）=====
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

# 額外資訊
# 額外資訊
with st.expander("📌 主力成本與量能細節", expanded=True):
    info1, info2, info3, info4, info5, info6 = st.columns(6)
    info1.caption(f"主力合約：**{ai['main_contract']}**")
    info2.caption(f"主力成本(10D VWAP)：**{(f'{vwap_10_close:.0f}' if vwap_10_close is not None else '—')}**")
    info3.caption(f"主力成本(20D VWAP)：**{(f'{vwap_20_close:.0f}' if vwap_20_close is not None else '—')}**")
    info4.caption(f"主力成本(20D settle)：**{(f'{vwap_20_settle:.0f}' if vwap_20_settle is not None else '—')}**")
    info5.caption(f"20D 平均收盤：**{(f'{avg20_close:.0f}' if avg20_close is not None else '—')}**")
    info6.caption(f"量能比：**{ai['vol_ratio']}x**")


st.divider()

# 表格
show_cols = [
    "date", "futures_id", "contract_date",
    "open", "max", "min", "close",
    "spread", "spread_per", "volume",
    "settlement_price", "open_interest", "trading_session"
]
for c in show_cols:
    if c not in df_tx.columns:
        df_tx[c] = None

df_show = df_tx[show_cols].copy()
df_show["contract_date_str"] = df_show["contract_date"].astype(str)
is_single = df_show["contract_date_str"].str.fullmatch(r"\d{6}", na=False)
df_single = df_show[is_single].sort_values("contract_date_str")
df_spread = df_show[~is_single].sort_values("contract_date_str")
df_show2 = pd.concat([df_single, df_spread], ignore_index=True).drop(columns=["contract_date_str"], errors="ignore")

with st.expander("📊 盤後原始資料表（點我展開）", expanded=False):
    st.dataframe(df_show2, width="stretch", height=240)


if debug_mode:
    st.divider()
    st.subheader("🔎 Debug：主力合約原始列")
    st.write(main_row.to_dict())
    st.subheader("🔎 Debug：方向因子分數")
    st.write(factor_scores)
