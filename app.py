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

APP_TITLE = "台指期貨 / 選擇權 AI 儀表板（Position 結算最終版）"

st.markdown(
    """
<style>
div[data-testid="stAppViewContainer"] > .main { padding-top: 3.2rem; }

.app-title{ font-size:2.1rem;font-weight:900;margin:0 }
.app-subtitle{ font-size:.95rem;opacity:.75;margin:.35rem 0 .9rem }

.kpi-card{
  border:1px solid rgba(255,255,255,.12);
  border-radius:14px;
  padding:16px 18px;
  background:rgba(255,255,255,.04);
  box-shadow:0 6px 22px rgba(0,0,0,.18);

  min-height:132px;
  display:flex;
  flex-direction:column;
  justify-content:space-between;
}

.kpi-title{ font-size:.95rem;opacity:.85 }
.kpi-value{ font-size:2rem;font-weight:800;line-height:1.1 }
.kpi-sub{ font-size:.8rem;opacity:.65;min-height:1.2em }

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
✅ 資料基準：<b>Position（結算資料）</b>　
✅ 收盤價定義：<b>Settlement Price</b>　
❌ 非交易日不顯示任何資料
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
# 期貨 Position（完全保留原邏輯）
# =========================
@st.cache_data(ttl=600, show_spinner=False)
def fetch_position_for_trade_date(trade_date: dt.date) -> pd.DataFrame:
    df = finmind_get(
        dataset="TaiwanFuturesDaily",
        data_id="TX",
        start_date=trade_date.strftime("%Y-%m-%d"),
        end_date=(trade_date + dt.timedelta(days=3)).strftime("%Y-%m-%d"),
    )
    if df.empty:
        return df
    df = df[df["trading_session"].astype(str) == "position"].copy()
    df["trade_date"] = trade_date
    return df

def pick_main_contract_position(df: pd.DataFrame, trade_date: dt.date):
    x = df.copy()
    x["contract_ym"] = pd.to_numeric(x["contract_date"], errors="coerce")
    target_ym = trade_date.year * 100 + trade_date.month
    cand = x[x["contract_ym"] >= target_ym]
    if not cand.empty:
        return cand.sort_values("contract_ym").iloc[0]
    return x.sort_values("contract_ym").iloc[-1]

def calc_ai_scores(main_row, df_all):
    open_ = float(main_row.get("open", 0) or 0)
    settle = main_row.get("settlement_price")
    close = main_row.get("close")
    final_close = float(settle) if settle not in (None, "", 0) else float(close or 0)
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
        "tx_last_price": final_close,
        "tx_spread_points": spread,
        "tx_range_points": range_,
        "consistency_pct": int(abs(final) / 3 * 100),
        "risk_score": int(clamp(range_ / 3, 0, 100)),
    }

# =========================
# UI：期貨
# =========================
trade_date = st.date_input("查詢交易日（結算）", value=dt.date.today())

if not is_trading_day(trade_date):
    st.warning("📅 非交易日（週六 / 週日），不顯示任何資料")
    st.stop()

df_day_all = fetch_position_for_trade_date(trade_date)
if df_day_all.empty:
    st.error("❌ 無期貨結算資料")
    st.stop()

main_row = pick_main_contract_position(df_day_all, trade_date)
ai = calc_ai_scores(main_row, df_day_all)

cls = "bull" if ai["direction_text"] == "偏多" else "bear" if ai["direction_text"] == "偏空" else "neut"

st.markdown("## 📈 台指期貨｜結算方向判斷")
c1, c2, c3, c4, c5 = st.columns(5, gap="small")

with c1:
    st.markdown(f"<div class='kpi-card'><div class='kpi-title'>方向</div><div class='kpi-value {cls}'>{ai['direction_text']}</div><div class='kpi-sub'>&nbsp;</div></div>", unsafe_allow_html=True)
with c2:
    st.markdown(f"<div class='kpi-card'><div class='kpi-title'>收盤價（結算）</div><div class='kpi-value'>{ai['tx_last_price']:.0f}</div><div class='kpi-sub'>&nbsp;</div></div>", unsafe_allow_html=True)
with c3:
    st.markdown(f"<div class='kpi-card'><div class='kpi-title'>一致性</div><div class='kpi-value'>{ai['consistency_pct']}%</div><div class='kpi-sub'>&nbsp;</div></div>", unsafe_allow_html=True)
with c4:
    st.markdown(f"<div class='kpi-card'><div class='kpi-title'>風險</div><div class='kpi-value'>{ai['risk_score']}/100</div><div class='kpi-sub'>&nbsp;</div></div>", unsafe_allow_html=True)
with c5:
    st.markdown(f"<div class='kpi-card'><div class='kpi-title'>日變化</div><div class='kpi-value {cls}'>{ai['tx_spread_points']:+.0f}</div><div class='kpi-sub'>&nbsp;</div></div>", unsafe_allow_html=True)

# =========================
# 選擇權（安全完整版）
# =========================
def normalize_cp(v):
    if pd.isna(v):
        return None
    s = str(v).strip().lower()
    if s in ("c", "call", "買權"):
        return "call"
    if s in ("p", "put", "賣權"):
        return "put"
    return None

@st.cache_data(ttl=600, show_spinner=False)
def fetch_option_latest_valid(trade_date: dt.date):
    for i in range(1, 6):
        d = trade_date - dt.timedelta(days=i)
        if d.weekday() >= 5:
            continue
        df = finmind_get(
            dataset="TaiwanOptionDaily",
            data_id="TXO",
            start_date=d.strftime("%Y-%m-%d"),
            end_date=d.strftime("%Y-%m-%d"),
        )
        if df is not None and not df.empty:
            df["option_trade_date"] = d
            return df
    return pd.DataFrame()

def calc_option_market_bias(df_opt: pd.DataFrame, fut_price: float):
    if df_opt is None or df_opt.empty:
        return None
    cp_col = None
    for c in ["option_type", "call_put", "right"]:
        if c in df_opt.columns:
            cp_col = c
            break
    if cp_col is None:
        return None
    if "strike_price" not in df_opt.columns or "open_interest" not in df_opt.columns:
        return None
    x = df_opt.copy()
    x["cp"] = x[cp_col].apply(normalize_cp)
    x["strike"] = pd.to_numeric(x["strike_price"], errors="coerce")
    x["oi"] = pd.to_numeric(x["open_interest"], errors="coerce")
    x = x.dropna(subset=["cp", "strike", "oi"])
    if x.empty:
        return None
    call = x[x["cp"] == "call"]
    put  = x[x["cp"] == "put"]
    if call.empty or put.empty:
        return None
    total_oi = call["oi"].sum() + put["oi"].sum()
    oi_center = (
        (call["strike"] * call["oi"]).sum() +
        (put["strike"] * put["oi"]).sum()
    ) / total_oi
    call_pressure = call.loc[call["oi"].idxmax()]["strike"]
    put_support   = put.loc[put["oi"].idxmax()]["strike"]
    if fut_price > oi_center + 30:
        bias, cls = "偏多", "bull"
    elif fut_price < oi_center - 30:
        bias, cls = "偏空", "bear"
    else:
        bias, cls = "中性", "neut"
    return {
        "bias": bias,
        "cls": cls,
        "oi_center": oi_center,
        "call_pressure": call_pressure,
        "put_support": put_support,
        "option_trade_date": df_opt["option_trade_date"].iloc[0],
    }

st.divider()
st.markdown("## 🧩 選擇權｜結構 × OI × 價格確認")

df_opt = fetch_option_latest_valid(trade_date)
opt = calc_option_market_bias(df_opt, ai["tx_last_price"])

if opt is None:
    st.info("ℹ️ 近期無完整選擇權 OI 資料（FinMind TXO 為 T+1）")
else:
    st.caption(f"📅 選擇權資料日：{opt['option_trade_date']}")
    oc1, oc2, oc3, oc4 = st.columns(4, gap="small")

    with oc1:
        st.markdown(f"<div class='kpi-card'><div class='kpi-title'>市場偏向</div><div class='kpi-value {opt['cls']}'>{opt['bias']}</div><div class='kpi-sub'>OI 結構</div></div>", unsafe_allow_html=True)
    with oc2:
        st.markdown(f"<div class='kpi-card'><div class='kpi-title'>OI 共識價</div><div class='kpi-value'>{opt['oi_center']:.0f}</div><div class='kpi-sub'>加權中心</div></div>", unsafe_allow_html=True)
    with oc3:
        st.markdown(f"<div class='kpi-card'><div class='kpi-title'>上方壓力</div><div class='kpi-value'>{opt['call_pressure']:.0f}</div><div class='kpi-sub'>Call OI 最大</div></div>", unsafe_allow_html=True)
    with oc4:
        st.markdown(f"<div class='kpi-card'><div class='kpi-title'>下方支撐</div><div class='kpi-value'>{opt['put_support']:.0f}</div><div class='kpi-sub'>Put OI 最大</div></div>", unsafe_allow_html=True)
