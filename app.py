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

APP_TITLE = "台指期貨 / 選擇權 AI 儀表板（Position 結算版）"

st.markdown(
    """
<style>
div[data-testid="stAppViewContainer"] > .main { padding-top: 3.8rem; }
.block-container { padding-top: 0.8rem; padding-bottom: 0.8rem; }
header[data-testid="stHeader"] { background: transparent; }

.app-title{
  font-size: 2.15rem; font-weight: 900; line-height: 1.20;
  margin: 0; padding-top: 0.35rem;
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

.bull { color: #FF3B30; }
.bear { color: #34C759; }
.neut { color: #C7C7CC; }
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    f"""
<div class="app-title">{APP_TITLE}</div>
<div class="app-subtitle">
✅ 資料基準：<b>Position（結算資料）</b><br/>
✅ 收盤價定義：<b>Settlement Price（結算價）</b><br/>
❌ 不使用 after_market / regular 作為判斷
</div>
""",
    unsafe_allow_html=True,
)

# =========================
# Debug
# =========================
params = st.query_params
debug_mode = str(params.get("debug", "0")).lower() in ("1", "true", "yes", "y")

# =========================
# Token
# =========================
def get_finmind_token():
    return (
        str(st.secrets.get("FINMIND_TOKEN", "")).strip()
        or os.environ.get("FINMIND_TOKEN", "").strip()
    )

FINMIND_TOKEN = get_finmind_token()

# =========================
# FinMind API
# =========================
FINMIND_API = "https://api.finmindtrade.com/api/v4/data"

@st.cache_data(ttl=600, show_spinner=False)
def finmind_get(dataset, data_id, start_date, end_date):
    if not FINMIND_TOKEN:
        return pd.DataFrame()
    r = requests.get(
        FINMIND_API,
        params=dict(
            dataset=dataset,
            data_id=data_id,
            start_date=start_date,
            end_date=end_date,
            token=FINMIND_TOKEN,
        ),
        timeout=30,
    )
    if r.status_code != 200:
        return pd.DataFrame()
    return pd.DataFrame(r.json().get("data", []))

# =========================
# 抓取 Position（結算）
# =========================
@st.cache_data(ttl=600, show_spinner=False)
def fetch_position(date: dt.date) -> pd.DataFrame:
    df = finmind_get(
        dataset="TaiwanFuturesDaily",
        data_id="TX",
        start_date=date.strftime("%Y-%m-%d"),
        end_date=date.strftime("%Y-%m-%d"),
    )
    if df.empty:
        return df

    df = df[df["trading_session"].astype(str) == "position"].copy()
    df["trade_date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    return df

# =========================
# 工具
# =========================
def clamp(v, lo, hi): return max(lo, min(hi, v))
def clamp01(x, lo=-1, hi=1): return max(lo, min(hi, x))

def pick_main_contract(df):
    x = df.copy()
    x["contract_date_str"] = x["contract_date"].astype(str)
    x = x[x["contract_date_str"].str.fullmatch(r"\d{6}", na=False)]
    if x.empty:
        return None
    x["volume_num"] = pd.to_numeric(x["volume"], errors="coerce").fillna(0)
    return x.loc[x["volume_num"].idxmax()]

# =========================
# AI 分析（以結算價為準）
# =========================
def calc_ai_scores(main_row, df_all):
    open_ = float(main_row.get("open", 0) or 0)

    # ✅ 結算收盤價（官方）
    settle_price = main_row.get("settlement_price")
    close_price = main_row.get("close")
    final_close = (
        float(settle_price)
        if settle_price not in (None, "", 0)
        else float(close_price or 0)
    )

    high_ = float(main_row.get("max", 0) or 0)
    low_ = float(main_row.get("min", 0) or 0)

    spread = final_close - open_
    range_ = max(0.0, high_ - low_)

    vol = float(pd.to_numeric(main_row.get("volume", 0), errors="coerce") or 0)
    vol_med = max(float(pd.to_numeric(df_all["volume"], errors="coerce").median() or 1), 1)
    vol_ratio = vol / vol_med

    momentum = clamp(spread / 100.0, -3, 3)
    vol_score = clamp((vol_ratio - 1) * 2, -2, 2)

    final = momentum * 0.7 + vol_score * 0.3
    direction = "偏多" if final > 1 else "偏空" if final < -1 else "中性"

    return {
        "direction_text": direction,
        "final_score": round(final, 2),
        "consistency_pct": int(abs(final) / 3 * 100),
        "risk_score": int(clamp(range_ / 3, 0, 100)),
        "tx_last_price": final_close,
        "tx_spread_points": spread,
        "tx_range_points": range_,
        "vol_ratio": round(vol_ratio, 2),
        "main_contract": str(main_row.get("contract_date", "")),
    }

# =========================
# UI
# =========================
target_date = st.date_input("查詢結算日（Position）", value=dt.date.today())

with st.spinner("抓取 Position 結算資料中..."):
    df_day_all = fetch_position(target_date)

if df_day_all.empty:
    st.error(f"❌ {target_date} 尚未產生結算資料（假日或尚未結算）")
    st.stop()

st.success(f"✅ 結算日：{target_date}")
st.caption(f"合約筆數：{len(df_day_all)}")

main_row = pick_main_contract(df_day_all)
if main_row is None:
    st.error("找不到主力合約")
    st.stop()

ai = calc_ai_scores(main_row, df_day_all)

mood = ai["direction_text"]
cls = "bull" if mood == "偏多" else "bear" if mood == "偏空" else "neut"

c1, c2, c3, c4, c5 = st.columns([1.6,1.6,1.2,1.2,1.4], gap="small")

with c1:
    st.markdown(f"<div class='kpi-card'><div class='kpi-title'>方向</div><div class='kpi-value {cls}'>{mood}</div></div>", unsafe_allow_html=True)
with c2:
    st.markdown(f"<div class='kpi-card'><div class='kpi-title'>收盤價（結算價）</div><div class='kpi-value'>{ai['tx_last_price']:.0f}</div></div>", unsafe_allow_html=True)
with c3:
    st.markdown(f"<div class='kpi-card'><div class='kpi-title'>一致性</div><div class='kpi-value'>{ai['consistency_pct']}%</div></div>", unsafe_allow_html=True)
with c4:
    st.markdown(f"<div class='kpi-card'><div class='kpi-title'>風險</div><div class='kpi-value'>{ai['risk_score']}/100</div></div>", unsafe_allow_html=True)
with c5:
    st.markdown(f"<div class='kpi-card'><div class='kpi-title'>日變化</div><div class='kpi-value {cls}'>{ai['tx_spread_points']:+.0f}</div></div>", unsafe_allow_html=True)

st.divider()

# =========================
# 原始資料表（結算）
# =========================
show_cols = [
    "trade_date", "trading_session", "futures_id", "contract_date",
    "open", "close", "settlement_price", "volume", "open_interest"
]
for c in show_cols:
    if c not in df_day_all.columns:
        df_day_all[c] = None

with st.expander("📊 Position 結算原始資料表", expanded=False):
    st.dataframe(df_day_all[show_cols], height=340, width="stretch")

if debug_mode:
    st.divider()
    st.subheader("🔎 Debug：trading_session 分布")
    st.write(df_day_all["trading_session"].value_counts())
