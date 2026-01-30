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
.app-title{ font-size:1.9rem;font-weight:900;margin:0 }
.app-subtitle{ font-size:.9rem;opacity:.75;margin:.25rem 0 .8rem }
.section-title{ font-size:1.15rem;font-weight:800;margin:1.2rem 0 .6rem }
.kpi-card{
  border:1px solid rgba(255,255,255,.12);
  border-radius:14px;padding:14px 16px;
  background:rgba(255,255,255,.04);
  box-shadow:0 6px 22px rgba(0,0,0,.18)
}
.kpi-title{ font-size:.85rem;opacity:.85 }
.kpi-value{ font-size:2rem;font-weight:800 }
.kpi-sub{ font-size:.8rem;opacity:.75;margin-top:4px }
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
資料基準：<b>Position（結算資料）</b> ｜ 收盤價定義：<b>Settlement Price</b><br/>
非交易日（週六日）不顯示任何資料
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

# ======================================================
# ===================== 期貨（完全不動邏輯） =====================
# ======================================================
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
    return cand.sort_values("contract_ym").iloc[0] if not cand.empty else x.sort_values("contract_ym").iloc[-1]

def calc_ai_scores(main_row, df_all):
    open_ = float(main_row.get("open", 0) or 0)
    settle_price = main_row.get("settlement_price")
    close_price = main_row.get("close")
    final_close = float(settle_price) if settle_price not in (None, "", 0) else float(close_price or 0)
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
        "main_contract": str(main_row.get("contract_date", "")),
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
    st.error("❌ 無結算資料")
    st.stop()

st.markdown("<div class='section-title'>📈 台指期貨｜結算方向判斷</div>", unsafe_allow_html=True)

main_row = pick_main_contract_position(df_day_all, trade_date)
ai = calc_ai_scores(main_row, df_day_all)

cls = "bull" if ai["direction_text"]=="偏多" else "bear" if ai["direction_text"]=="偏空" else "neut"

c1,c2,c3,c4,c5 = st.columns([1.6,1.6,1.2,1.2,1.4],gap="small")
with c1:
    st.markdown(f"<div class='kpi-card'><div class='kpi-title'>方向</div><div class='kpi-value {cls}'>{ai['direction_text']}</div></div>",unsafe_allow_html=True)
with c2:
    st.markdown(f"<div class='kpi-card'><div class='kpi-title'>收盤價（結算）</div><div class='kpi-value'>{ai['tx_last_price']:.0f}</div></div>",unsafe_allow_html=True)
with c3:
    st.markdown(f"<div class='kpi-card'><div class='kpi-title'>一致性</div><div class='kpi-value'>{ai['consistency_pct']}%</div></div>",unsafe_allow_html=True)
with c4:
    st.markdown(f"<div class='kpi-card'><div class='kpi-title'>風險</div><div class='kpi-value'>{ai['risk_score']}/100</div></div>",unsafe_allow_html=True)
with c5:
    st.markdown(f"<div class='kpi-card'><div class='kpi-title'>日變化</div><div class='kpi-value {cls}'>{ai['tx_spread_points']:+.0f}</div></div>",unsafe_allow_html=True)

# ======================================================
# ===================== 選擇權 v2（升級） =====================
# ======================================================
st.divider()
st.markdown("<div class='section-title'>🧩 選擇權｜結構 × ΔOI × 價格確認</div>", unsafe_allow_html=True)

@st.cache_data(ttl=600, show_spinner=False)
def fetch_option_for_trade_date(d: dt.date) -> pd.DataFrame:
    return finmind_get(
        dataset="TaiwanOptionDaily",
        data_id="TXO",
        start_date=d.strftime("%Y-%m-%d"),
        end_date=d.strftime("%Y-%m-%d"),
    )

@st.cache_data(ttl=600, show_spinner=False)
def fetch_option_prev_trade_date(trade_date: dt.date) -> pd.DataFrame:
    for i in range(1, 6):
        d = trade_date - dt.timedelta(days=i)
        if d.weekday() >= 5:
            continue
        df = fetch_option_for_trade_date(d)
        if not df.empty:
            return df
    return pd.DataFrame()


def calc_option_market_bias_v2(df_today, df_prev, settlement_price, atm_range=2):
    if df_today is None or df_today.empty:
        return None

    # ---------- 欄位安全判斷 ----------
    cp_col = next((c for c in ["option_type", "call_put", "right"] if c in df_today.columns), None)
    if cp_col is None:
        return None

    def norm_cp(v):
        s = str(v).lower()
        if s.startswith("c"):
            return "call"
        if s.startswith("p"):
            return "put"
        return None

    def prep(df):
        x = df.copy()
        x["cp"] = x[cp_col].apply(norm_cp)
        x["strike"] = pd.to_numeric(x["strike_price"], errors="coerce")
        x["oi"] = pd.to_numeric(x["open_interest"], errors="coerce")
        return x.dropna(subset=["cp", "strike", "oi"])

    t = prep(df_today)
    p = prep(df_prev) if df_prev is not None else pd.DataFrame()

    call = t[t["cp"] == "call"]
    put  = t[t["cp"] == "put"]
    if call.empty or put.empty:
        return None

    # ---------- ✅ strike 合併（關鍵） ----------
    call_oi = call.groupby("strike")["oi"].sum()
    put_oi  = put.groupby("strike")["oi"].sum()

    total_oi = call_oi.sum() + put_oi.sum()
    if total_oi <= 0:
        return None

    # ---------- ✅ OI 共識價（已修正 Index 型別問題） ----------
    call_strikes = call_oi.index.to_numpy(dtype=float)
    put_strikes  = put_oi.index.to_numpy(dtype=float)

    oi_center = (
        (call_strikes * call_oi.values).sum() +
        (put_strikes  * put_oi.values).sum()
    ) / total_oi

    call_pressure = float(call_oi.idxmax())
    put_support   = float(put_oi.idxmax())

    # ---------- ΔOI ----------
    delta_call = delta_put = 0.0
    if not p.empty:
        prev_call_oi = p[p["cp"] == "call"].groupby("strike")["oi"].sum()
        prev_put_oi  = p[p["cp"] == "put"].groupby("strike")["oi"].sum()

        atm = round(settlement_price / 50) * 50
        strikes = sorted(call_oi.index.tolist())

        if strikes:
            idx = strikes.index(atm) if atm in strikes else len(strikes) // 2
            sel = strikes[max(0, idx - atm_range): idx + atm_range + 1]

            delta_call = (
                call_oi.reindex(sel).fillna(0) -
                prev_call_oi.reindex(sel).fillna(0)
            ).sum()

            delta_put = (
                put_oi.reindex(sel).fillna(0) -
                prev_put_oi.reindex(sel).fillna(0)
            ).sum()

    # ---------- 評分 ----------
    score_structure = 1 if settlement_price > oi_center else -1 if settlement_price < oi_center else 0

    if delta_call > 0 and settlement_price > oi_center:
        score_flow = 1        # 軋空
    elif delta_call > 0 and settlement_price < oi_center:
        score_flow = -1       # 空方加碼
    elif delta_put > 0 and settlement_price < oi_center:
        score_flow = -1
    else:
        score_flow = 0

    score_price = 1 if settlement_price > call_pressure else -1 if settlement_price < put_support else 0

    final_score = 0.35 * score_structure + 0.45 * score_flow + 0.20 * score_price

    if final_score >= 0.5:
        bias, cls = "偏多", "bull"
    elif final_score <= -0.5:
        bias, cls = "偏空", "bear"
    else:
        bias, cls = "結構中性", "neut"

    return {
        "bias": bias,
        "cls": cls,
        "score": round(final_score, 2),
        "oi_center": oi_center,
        "call_pressure": call_pressure,
        "put_support": put_support,
        "delta_call": delta_call,
        "delta_put": delta_put,
    }


df_opt_today = fetch_option_for_trade_date(trade_date)
df_opt_prev = fetch_option_prev_trade_date(trade_date)

opt = calc_option_market_bias_v2(df_opt_today, df_opt_prev, ai["tx_last_price"])

if opt is None:
    st.info("ℹ️ 選擇權資料不足，無法進行完整分析")
else:
    c1,c2,c3,c4 = st.columns([1.4,1.4,1.6,1.6],gap="small")
    with c1:
        st.markdown(f"<div class='kpi-card'><div class='kpi-title'>選擇權方向</div><div class='kpi-value {opt['cls']}'>{opt['bias']}</div><div class='kpi-sub'>Score {opt['score']:+.2f}</div></div>",unsafe_allow_html=True)
    with c2:
        st.markdown(f"<div class='kpi-card'><div class='kpi-title'>OI 共識價</div><div class='kpi-value'>{opt['oi_center']:.0f}</div></div>",unsafe_allow_html=True)
    with c3:
        st.markdown(f"<div class='kpi-card'><div class='kpi-title'>上方壓力（Call OI）</div><div class='kpi-value'>{opt['call_pressure']:.0f}</div><div class='kpi-sub'>ΔCall OI {opt['delta_call']:+.0f}</div></div>",unsafe_allow_html=True)
    with c4:
        st.markdown(f"<div class='kpi-card'><div class='kpi-title'>下方支撐（Put OI）</div><div class='kpi-value'>{opt['put_support']:.0f}</div><div class='kpi-sub'>ΔPut OI {opt['delta_put']:+.0f}</div></div>",unsafe_allow_html=True)
