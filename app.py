# app.py
# -*- coding: utf-8 -*-

import os
import math
import datetime as dt
from io import StringIO

import requests
import pandas as pd
import streamlit as st


# =========================
# 基本設定
# =========================
st.set_page_config(page_title="台指期貨 / 選擇權 AI 儀表板", layout="wide")

APP_TITLE = "台指期貨 / 選擇權 AI 儀表板（第二階段：真實盤後資料接入）"
st.title(APP_TITLE)

# Debug 開關：可用網址加參數 ?debug=1
params = st.query_params
debug_mode = str(params.get("debug", "0")).lower() in ("1", "true", "yes", "y")


# =========================
# Secrets / Token
# =========================
def get_finmind_token() -> str:
    # 1) Streamlit Cloud secrets: st.secrets["FINMIND_TOKEN"]
    # 2) fallback 環境變數 FINMIND_TOKEN
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
    # 若 token 缺失，仍顯示提醒（避免使用者以為壞掉）
    if not FINMIND_TOKEN:
        st.warning("FINMIND_TOKEN 尚未設定，資料將無法抓取。可在網址加 ?debug=1 查看詳細。")


# =========================
# FinMind API (盤後：TaiwanFuturesDaily)
# =========================
FINMIND_API = "https://api.finmindtrade.com/api/v4/data"


@st.cache_data(ttl=60 * 10, show_spinner=False)
def finmind_get(dataset: str, data_id: str, start_date: str, end_date: str, token: str) -> pd.DataFrame:
    """
    用 FinMind API 抓資料（快取 10 分鐘）
    """
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


def is_trading_data_ok(df: pd.DataFrame) -> bool:
    if df is None or df.empty:
        return False
    # 有 close/volume 才算有效
    need_cols = {"date", "futures_id", "contract_date", "close", "volume"}
    return need_cols.issubset(set(df.columns))


def backtrack_find_valid_date(
    target_date: dt.date,
    max_back_days: int = 14,
) -> tuple[dt.date | None, pd.DataFrame]:
    """
    盤後資料常遇到：輸入日期是非交易日 or 尚未更新
    這裡自動回溯最多 max_back_days 天，找到最近有資料的交易日
    """
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
            # 只留 TX
            df = df[df["futures_id"].astype(str) == "TX"].copy()
            return d, df
    return None, pd.DataFrame()


# =========================
# 主力合約選擇 + AI 分數
# =========================
def pick_main_contract(df: pd.DataFrame) -> pd.Series | None:
    """
    主力近月：用「同一天、TX、after_market」中 volume 最大的那筆 (且是單一合約，不是跨期價差)
    - contract_date 像 202602 代表單一合約
    - contract_date 像 202602/202603 代表價差
    """
    if df.empty:
        return None

    x = df.copy()

    # 僅取盤後 after_market（你的資料就是 after_market，保險起見仍加）
    if "trading_session" in x.columns:
        x = x[x["trading_session"].astype(str) == "after_market"]

    # 只留「單一合約」：contract_date 應該是 6 碼數字
    x["contract_date_str"] = x["contract_date"].astype(str)
    x = x[x["contract_date_str"].str.fullmatch(r"\d{6}", na=False)]

    if x.empty:
        return None

    # volume 轉數字
    x["volume_num"] = pd.to_numeric(x["volume"], errors="coerce").fillna(0)

    # 主力 = volume 最大
    idx = x["volume_num"].idxmax()
    row = x.loc[idx]
    return row


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def score_to_label(score: float) -> str:
    if score >= 1.5:
        return "偏多"
    if score <= -1.5:
        return "偏空"
    return "震盪/中性"


def calc_ai_scores(main_row: pd.Series, df_all: pd.DataFrame) -> dict:
    """
    產出：
    - direction_text
    - final_score (約 -5 ~ +5)
    - consistency_pct (0~100)
    - risk_score (0~100, 越高越危險)
    - tx_last_price / tx_spread_points
    """
    # 主力價格與當日變化
    open_ = float(main_row.get("open", 0) or 0)
    close_ = float(main_row.get("close", 0) or 0)
    high_ = float(main_row.get("max", 0) or 0)
    low_ = float(main_row.get("min", 0) or 0)

    spread_points = close_ - open_  # 當日變化點
    range_points = max(0.0, high_ - low_)
    body = abs(spread_points)

    # =========
    # 量能分數
    # =========
    vol = float(pd.to_numeric(main_row.get("volume", 0), errors="coerce") or 0)
    oi = float(pd.to_numeric(main_row.get("open_interest", 0), errors="coerce") or 0)

    # 量能基準：同日 TX 單一合約的 volume 中位數（避免只有一筆時爆掉）
    base_df = df_all.copy()
    base_df["contract_date_str"] = base_df["contract_date"].astype(str)
    base_df = base_df[base_df["contract_date_str"].str.fullmatch(r"\d{6}", na=False)]
    base_df["volume_num"] = pd.to_numeric(base_df["volume"], errors="coerce").fillna(0)
    vol_med = float(base_df["volume_num"].median()) if not base_df.empty else max(vol, 1.0)

    vol_ratio = vol / max(vol_med, 1.0)  # >1 代表高於同日中位數
    vol_score = clamp((vol_ratio - 1.0) * 2.0, -2.0, 2.0)  # 大概落在 -2~+2

    # =========
    # 結構分數：近月 vs 次月（正價差 / 逆價差）
    # =========
    structure_score = 0.0
    structure_text = "無法計算"

    # 取近月與次月 close
    try:
        # 依 contract_date 升序，取前兩個作近/次月
        base_df_sorted = base_df.sort_values("contract_date_str")
        first_two = base_df_sorted.head(2)
        if len(first_two) >= 2:
            near_close = float(first_two.iloc[0]["close"])
            next_close = float(first_two.iloc[1]["close"])
            term_spread = next_close - near_close  # 次月-近月
            # 正價差通常偏多；逆價差偏空
            structure_score = clamp(term_spread / 80.0, -2.0, 2.0)  # 80 點做縮放（可再調）
            structure_text = f"{term_spread:+.0f} 點（次月-近月）"
        elif len(first_two) == 1:
            structure_text = "僅一個合約"
    except Exception:
        pass

    # =========
    # 價格動能分數
    # =========
    # 用點數變化縮放：200 點 ≈ 2 分
    momentum_score = clamp(spread_points / 100.0, -3.0, 3.0)

    # =========
    # Final Score（核心）
    # =========
    # 權重可調：動能 60%、結構 25%、量能 15%
    final_score = (momentum_score * 0.60) + (structure_score * 0.25) + (vol_score * 0.15)
    final_score = float(clamp(final_score, -5.0, 5.0))

    direction_text = score_to_label(final_score)

    # =========
    # 一致性：各指標方向是否同向（0~100）
    # =========
    sign_m = 1 if momentum_score > 0 else (-1 if momentum_score < 0 else 0)
    sign_s = 1 if structure_score > 0 else (-1 if structure_score < 0 else 0)
    sign_v = 1 if vol_score > 0 else (-1 if vol_score < 0 else 0)

    votes = [sign_m, sign_s, sign_v]
    pos = votes.count(1)
    neg = votes.count(-1)
    neu = votes.count(0)

    # 多數決一致性：最大票數 / 3
    majority = max(pos, neg, neu)
    consistency_pct = int(round((majority / 3.0) * 100))

    # =========
    # 風險分數（0~100，越高越危險）
    # =========
    # 以「波動範圍」與「K棒實體比例」估算：range 越大、實體越小 → 不確定性越高
    if range_points <= 0:
        risk_score = 50
    else:
        wick_ratio = 1.0 - (body / range_points)  # 越接近 1 → 上下影線多 → 越不確定
        # range_points 用 250 點做尺度
        volat = clamp(range_points / 250.0, 0.0, 2.0)  # 0~2
        risk_raw = (wick_ratio * 60.0) + (volat * 20.0) + (abs(structure_score) * 10.0)  # 0~100+
        risk_score = int(clamp(risk_raw, 0.0, 100.0))

    return {
        "direction_text": direction_text,
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
# UI：查詢日期（盤後）
# =========================
today = dt.date.today()
default_date = today

st.caption("提示：盤後資料通常在收盤後更新；若當天尚未更新，本程式會自動回溯到最近有資料的交易日。")
target_date = st.date_input("查詢日期（盤後）", value=default_date)

# =========================
# 抓取資料 + 回溯
# =========================
with st.spinner("抓取 TX 盤後資料中..."):
    valid_date, df_tx = backtrack_find_valid_date(target_date, max_back_days=14)

if valid_date is None or df_tx.empty:
    st.error("目前抓不到 TX 盤後資料（可能連續假期 / 或資料尚未更新 / 或 Token 權限問題）。")
    if debug_mode:
        st.info("Debug 建議：確認 FINMIND_TOKEN、以及 FinMind 服務狀態。")
    st.stop()

@st.cache_data(ttl=60 * 30, show_spinner=False)
def fetch_tx_contract_history(end_date: dt.date, contract_yyyymm: str, lookback_days: int = 35) -> pd.DataFrame:
    """
    抓取 TX 指定單一合約 (contract_date=YYYYMM) 在最近一段期間的盤後日資料
    - lookback_days 取大一點（例如 35）是為了包含假日/沒資料日，最後再用 N 筆交易日計算
    """
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

    # 只留單一合約
    df["contract_date_str"] = df["contract_date"].astype(str)
    df = df[df["contract_date_str"].str.fullmatch(r"\d{6}", na=False)]
    df = df[df["contract_date_str"] == str(contract_yyyymm)]

    # 數字化
    df["close_num"] = pd.to_numeric(df.get("close", 0), errors="coerce")
    df["settle_num"] = pd.to_numeric(df.get("settlement_price", 0), errors="coerce")
    df["vol_num"] = pd.to_numeric(df.get("volume", 0), errors="coerce").fillna(0)

    # date 轉 datetime 方便排序
    df["date_dt"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date_dt"]).sort_values("date_dt")

    return df


def calc_cost_vwap(df_hist: pd.DataFrame, n: int = 20, price_col: str = "close_num") -> float | None:
    """
    用最近 n 筆交易日做 VWAP（成交量加權均價）
    price_col 可用 close_num 或 settle_num
    """
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
        # 如果 volume 全為 0，就退化成簡單平均
        return float(x[price_col].mean())

    vwap = float((x[price_col] * x["vol_num"]).sum() / vol_sum)
    return vwap

def clamp(x: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, x))


def calc_directional_score(
    close_price: float,
    vwap20: float | None,
    vol_ratio: float | None,
    pcr: float | None,
    atm_iv: float | None,
    open_price: float | None = None,
) -> dict:
    scores = {}

    # 1️⃣ 主力成本偏離（最重要）
    if vwap20 and vwap20 > 0:
        diff = (close_price - vwap20) / vwap20
        scores["cost"] = clamp(diff * 5)   # 5 是放大係數（可微調）
    else:
        scores["cost"] = 0.0

    # 2️⃣ 量能（大於 1 偏多，小於 1 偏空）
    if vol_ratio:
        scores["volume"] = clamp((vol_ratio - 1.0) * 1.2)
    else:
        scores["volume"] = 0.0

    # 3️⃣ PCR（<1 偏多，>1 偏空）
    if pcr:
        scores["pcr"] = clamp((1.0 - pcr) * 1.5)
    else:
        scores["pcr"] = 0.0

    # 4️⃣ ATM IV（過高＝風險偏空）
    if atm_iv:
        scores["iv"] = clamp((20 - atm_iv) / 20)  # 20% 為中性基準
    else:
        scores["iv"] = 0.0

    # 5️⃣ 日內動能（可選）
    if open_price and open_price > 0:
        scores["intraday"] = clamp((close_price - open_price) / open_price * 5)
    else:
        scores["intraday"] = 0.0

    return scores

# 顯示回溯結果
st.markdown("### 📌 TXF 盤後資料（自動回溯找最近有效交易日）")
st.success(f"✅ 抓到資料！你選的日期：{to_ymd(target_date)} → 實際抓到資料日期：{to_ymd(valid_date)}")
st.caption(f"筆數：{len(df_tx)}")

# =========================
# 主力與 AI 分數
# =========================
main_row = pick_main_contract(df_tx)
if main_row is None:
    st.warning("抓到資料，但找不到可判定的『主力單一合約』（可能資料結構變更或欄位異常）。")
    st.dataframe(df_tx, width="stretch")
    st.stop()

ai = calc_ai_scores(main_row, df_tx)

# ===== 主力成本均價（估算）=====
main_contract = ai["main_contract"]  # 例如 "202602"
df_main_hist = fetch_tx_contract_history(valid_date, main_contract, lookback_days=60)

vwap_20_close = calc_cost_vwap(df_main_hist, n=20, price_col="close_num")
vwap_10_close = calc_cost_vwap(df_main_hist, n=10, price_col="close_num")

# 若你想用 settlement_price 當代表價（有些人更愛結算價）
vwap_20_settle = calc_cost_vwap(df_main_hist, n=20, price_col="settle_num")

avg20_close = None
if df_main_hist is not None and not df_main_hist.empty:
    avg20_close = float(df_main_hist.tail(20)["close_num"].dropna().mean())

# 顶部 KPI 區
k1, k2, k3, k4, k5 = st.columns([1.2, 1.2, 1.6, 1.2, 1.2])

with k1:
    st.metric("方向", ai["direction_text"])

with k2:
    direction_text = (
    "強烈偏多" if final_score_pct >= 60 else
    "偏多" if final_score_pct >= 20 else
    "中性" if final_score_pct > -20 else
    "偏空" if final_score_pct > -60 else
    "強烈偏空"
)

st.metric(
    "Final Score（方向強度）",
    f"{final_score_pct:+d}%",
    help=direction_text
)


with k3:
    # 一致性顏色提示（用 emoji）
    if ai["consistency_pct"] >= 70:
        dot = "🟢"
        sub = "一致性高"
    elif ai["consistency_pct"] >= 45:
        dot = "🟠"
        sub = "一致性中"
    else:
        dot = "🔴"
        sub = "一致性低"
    st.metric(f"{dot} 一致性", f'{ai["consistency_pct"]}%', help=sub)

with k4:
    # 風險顏色提示
    if ai["risk_score"] >= 70:
        dot = "🔴"
        sub = "高風險"
    elif ai["risk_score"] >= 45:
        dot = "🟠"
        sub = "中風險"
    else:
        dot = "🟢"
        sub = "低風險"
    st.metric(f"{dot} 風險", f'{ai["risk_score"]}/100', help=sub)

with k5:
    st.metric("TXF 盤後收盤", f'{ai["tx_last_price"]:.0f}', delta=f'{ai["tx_spread_points"]:+.0f} 點')


# ===== Final Directional Score (-100% ~ +100%) =====
factor_scores = calc_directional_score(
    close_price=main_row["close"],
    vwap20=vwap_20_close,
    vol_ratio=ai["vol_ratio"],
    pcr=ai["pcr"],
    atm_iv=ai["atm_iv"],
    open_price=main_row.get("open"),
)

WEIGHTS = {
    "cost": 0.35,
    "volume": 0.20,
    "pcr": 0.20,
    "iv": 0.15,
    "intraday": 0.10,
}

raw_score = sum(
    factor_scores[k] * WEIGHTS[k]
    for k in WEIGHTS
)

final_score_pct = int(clamp(raw_score) * 100)

# 額外資訊（讓你確認主力選擇是對的）
info1, info2, info3, info4, info5, info6 = st.columns(6)
info1.caption(f"主力合約：**{ai['main_contract']}**")
info2.caption(f"主力成本(10D VWAP, close)：**{(f'{vwap_10_close:.0f}' if vwap_10_close is not None else '—')}**")
info3.caption(f"主力成本(20D VWAP, close)：**{(f'{vwap_20_close:.0f}' if vwap_20_close is not None else '—')}**")
info4.caption(f"主力成本(20D VWAP, settle)：**{(f'{vwap_20_settle:.0f}' if vwap_20_settle is not None else '—')}**")
info5.caption(f"20D 平均收盤：**{(f'{avg20_close:.0f}' if avg20_close is not None else '—')}**")
info6.caption(f"量能比（同日中位數）：**{ai['vol_ratio']}x**")


st.divider()

# =========================
# 表格：保留你現在看到的盤後資料
# =========================
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

# 排序：先單一合約，再價差；單一合約依月份升序
df_show["contract_date_str"] = df_show["contract_date"].astype(str)
is_single = df_show["contract_date_str"].str.fullmatch(r"\d{6}", na=False)
df_single = df_show[is_single].sort_values("contract_date_str")
df_spread = df_show[~is_single].sort_values("contract_date_str")
df_show2 = pd.concat([df_single, df_spread], ignore_index=True).drop(columns=["contract_date_str"], errors="ignore")

st.dataframe(df_show2, width="stretch")

# =========================
# Debug 額外輸出（可選）
# =========================
if debug_mode:
    st.divider()
    st.subheader("🔎 Debug：主力合約原始列")
    st.write(main_row.to_dict())
