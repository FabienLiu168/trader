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
st.set_page_config(page_title="台指期貨專業交易決策面板", layout="wide")

APP_TITLE = "台指期貨｜專業交易決策面板（結算 × 夜盤 × 選擇權）"

st.markdown(
    """
<style>
div[data-testid="stAppViewContainer"] > .main { padding-top: 3.6rem; }
.app-title{ font-size:2.1rem;font-weight:900;margin:0 }
.app-subtitle{ font-size:.95rem;opacity:.75;margin:.4rem 0 1rem }
.card{
  border:1px solid rgba(255,255,255,.12);
  border-radius:14px;padding:14px 16px;
  background:rgba(255,255,255,.04);
  box-shadow:0 6px 22px rgba(0,0,0,.18)
}
.card-title{ font-size:.95rem;opacity:.85 }
.card-value{ font-size:2rem;font-weight:800 }
.bull{color:#FF3B30}
.bear{color:#34C759}
.neut{color:#C7C7CC}
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    f"""
<div class="app-title">{APP_TITLE}</div>
<div class="app-subtitle">
• 價格錨點：<b>Position 結算價</b><br/>
• 夜盤僅作偏移加權（不影響結算）<br/>
• 選擇權以 OI 結構判斷市場預期
</div>
""",
    unsafe_allow_html=True,
)

# =========================
# 工具
# =========================
def is_trading_day(d: dt.date) -> bool:
    # 台指期：週一 ~ 週五
    return d.weekday() < 5

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

# =========================
# FinMind Token
# =========================
def get_finmind_token():
    return (
        str(st.secrets.get("FINMIND_TOKEN", "")).strip()
        or os.environ.get("FINMIND_TOKEN", "").strip()
    )

FINMIND_TOKEN = get_finmind_token()
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
# ① Position 結算資料
# =========================
@st.cache_data(ttl=600, show_spinner=False)
def fetch_position(trade_date: dt.date) -> pd.DataFrame:
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

def pick_main_contract(df: pd.DataFrame, trade_date: dt.date):
    df = df.copy()
    df["ym"] = pd.to_numeric(df["contract_date"], errors="coerce")
    target_ym = trade_date.year * 100 + trade_date.month
    cand = df[df["ym"] >= target_ym]
    return cand.sort_values("ym").iloc[0] if not cand.empty else df.sort_values("ym").iloc[-1]

# =========================
# ② 夜盤偏移模組
# =========================
@st.cache_data(ttl=600, show_spinner=False)
def fetch_night(trade_date: dt.date):
    df = finmind_get(
        "TaiwanFuturesDaily",
        "TX",
        trade_date.strftime("%Y-%m-%d"),
        (trade_date + dt.timedelta(days=1)).strftime("%Y-%m-%d"),
    )
    if df.empty:
        return df
    return df[df["trading_session"].astype(str) == "after_market"].copy()

def calc_night_bias(night_df: pd.DataFrame, settlement_price: float):
    if night_df is None or night_df.empty:
        return {"score": 0.0, "text": "無夜盤資料"}
    close = float(night_df.iloc[-1]["close"])
    bias = close - settlement_price
    score = clamp(bias / 100.0, -1.0, 1.0)
    return {"score": score, "text": f"{bias:+.0f} 點"}

# =========================
# ③ 選擇權 OI 模組（防呆版）
# =========================
@st.cache_data(ttl=600, show_spinner=False)
def fetch_options(trade_date: dt.date):
    df = finmind_get(
        "TaiwanOptionDaily",
        "TXO",
        trade_date.strftime("%Y-%m-%d"),
        trade_date.strftime("%Y-%m-%d"),
    )
    return df if df is not None else pd.DataFrame()

def calc_option_bias(df: pd.DataFrame, price: float):
    """
    防呆版選擇權 OI 分析：
    - 自動辨識 Call / Put 欄位
    - 若資料結構不符，直接停用此模組
    """
    if df is None or df.empty:
        return None

    # 自動找 Call / Put 欄位
    cp_col = None
    for c in ["option_type", "call_put", "right"]:
        if c in df.columns:
            cp_col = c
            break
    if cp_col is None:
        return None

    def norm_cp(v):
        if pd.isna(v):
            return None
        s = str(v).lower()
        if s in ("c", "call"):
            return "call"
        if s in ("p", "put"):
            return "put"
        return None

    if "strike_price" not in df.columns or "open_interest" not in df.columns:
        return None

    df = df.copy()
    df["cp"] = df[cp_col].apply(norm_cp)
    df["strike"] = pd.to_numeric(df["strike_price"], errors="coerce")
    df["oi"] = pd.to_numeric(df["open_interest"], errors="coerce")

    call = df[df["cp"] == "call"].dropna(subset=["strike", "oi"])
    put  = df[df["cp"] == "put"].dropna(subset=["strike", "oi"])
    if call.empty or put.empty:
        return None

    total_oi = call["oi"].sum() + put["oi"].sum()
    if total_oi <= 0:
        return None

    oi_center = (
        (call["strike"] * call["oi"]).sum() +
        (put["strike"] * put["oi"]).sum()
    ) / total_oi

    call_pressure = call.loc[call["oi"].idxmax()]["strike"]
    put_support   = put.loc[put["oi"].idxmax()]["strike"]

    score = 0.6 if price > oi_center else -0.6

    return {
        "oi_center": oi_center,
        "call_pressure": call_pressure,
        "put_support": put_support,
        "score": score,
    }

# =========================
# UI
# =========================
trade_date = st.date_input("查詢交易日", value=dt.date.today())

if not is_trading_day(trade_date):
    st.warning("📅 非交易日（週六 / 週日），不顯示任何資料")
    st.stop()

df_pos = fetch_position(trade_date)
if df_pos.empty:
    st.error("❌ 查無結算資料（可能尚未公告）")
    st.stop()

main = pick_main_contract(df_pos, trade_date)
settlement_price = float(main["settlement_price"])
direction = "偏多" if settlement_price > float(main.get("open", settlement_price)) else "偏空"

night = calc_night_bias(fetch_night(trade_date), settlement_price)
opt = calc_option_bias(fetch_options(trade_date), settlement_price)

option_score = opt["score"] if isinstance(opt, dict) else 0.0

final_score = (
    0.55 * (1 if direction == "偏多" else -1) +
    0.20 * night["score"] +
    0.25 * option_score
)

final_view = "偏多" if final_score > 0.5 else "偏空" if final_score < -0.5 else "震盪"
cls = "bull" if final_view == "偏多" else "bear" if final_view == "偏空" else "neut"

st.subheader("📊 交易決策總覽")

c1, c2, c3, c4 = st.columns(4)

with c1:
    st.markdown(f"<div class='card'><div class='card-title'>結算價</div><div class='card-value'>{settlement_price:.0f}</div></div>", unsafe_allow_html=True)
with c2:
    st.markdown(f"<div class='card'><div class='card-title'>夜盤偏移</div><div class='card-value'>{night['text']}</div></div>", unsafe_allow_html=True)
with c3:
    if opt:
        st.markdown(f"<div class='card'><div class='card-title'>OI 重心</div><div class='card-value'>{opt['oi_center']:.0f}</div></div>", unsafe_allow_html=True)
    else:
        st.markdown(f"<div class='card'><div class='card-title'>OI 模組</div><div class='card-value neut'>不可用</div></div>", unsafe_allow_html=True)
with c4:
    st.markdown(f"<div class='card'><div class='card-title'>最終判斷</div><div class='card-value {cls}'>{final_view}</div></div>", unsafe_allow_html=True)

st.divider()

with st.expander("📊 Position 結算原始資料"):
    st.dataframe(df_pos, height=360)
