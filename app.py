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
st.set_page_config(
    page_title="台指期貨 / 選擇權 AI 儀表板",
    layout="wide",
)

APP_TITLE = "台指期貨 / 選擇權 AI 儀表板（Position 結算最終版）"

# =========================
# UI Style（✅ 高度一致修正版）
# =========================
st.markdown(
    """
<style>
div[data-testid="stAppViewContainer"] > .main {
  padding-top: 3.6rem;
}

.app-title{
  font-size:2.0rem;
  font-weight:900;
  margin:0;
}
.app-subtitle{
  font-size:.95rem;
  opacity:.75;
  margin:.3rem 0 1.1rem;
}

/* ===== KPI Card 統一規格 ===== */
.kpi-card{
  border:1px solid rgba(255,255,255,.12);
  border-radius:14px;
  padding:16px 18px;
  background:rgba(255,255,255,.04);
  box-shadow:0 6px 22px rgba(0,0,0,.18);

  min-height:132px;                /* ✅ 高度統一 */
  display:flex;
  flex-direction:column;
  justify-content:space-between;
}

.kpi-title{
  font-size:.95rem;
  opacity:.85;
}

.kpi-value{
  font-size:2rem;
  font-weight:800;
  line-height:1.1;
}

.kpi-sub{
  font-size:.8rem;
  opacity:.65;
  min-height:1.2em;               /* ✅ 副標固定占位 */
}

/* ===== 色系 ===== */
.bull{ color:#FF3B30; }
.bear{ color:#34C759; }
.neut{ color:#C7C7CC; }

.section-title{
  font-size:1.15rem;
  font-weight:800;
  margin:.6rem 0 .4rem;
}
</style>
""",
    unsafe_allow_html=True,
)

# =========================
# Header
# =========================
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
# 工具：交易日判斷
# =========================
def is_trading_day(d: dt.date) -> bool:
    return d.weekday() < 5

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
# Position 期貨資料
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

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def pick_main_contract_position(df: pd.DataFrame, trade_date: dt.date):
    x = df.copy()
    x["contract_ym"] = pd.to_numeric(x["contract_date"], errors="coerce")
    target_ym = trade_date.year * 100 + trade_date.month
    cand = x[x["contract_ym"] >= target_ym]
    return cand.sort_values("contract_ym").iloc[0] if not cand.empty else x.sort_values("contract_ym").iloc[-1]

def calc_ai_scores(main_row, df_all):
    open_ = float(main_row.get("open", 0) or 0)
    settle = main_row.get("settlement_price")
    close = main_row.get("close")
    final_close = float(settle) if settle not in (None, "", 0) else float(close or 0)

    high_ = float(main_row.get("max", 0) or 0)
    low_  = float(main_row.get("min", 0) or 0)

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
    st.warning(f"📅 {trade_date} 為非交易日（週六 / 週日），不顯示任何資料。")
    st.stop()

df_day_all = fetch_position_for_trade_date(trade_date)
if df_day_all.empty:
    st.error(f"❌ {trade_date} 尚無結算資料")
    st.stop()

main_row = pick_main_contract_position(df_day_all, trade_date)
ai = calc_ai_scores(main_row, df_day_all)

cls = "bull" if ai["direction_text"] == "偏多" else "bear" if ai["direction_text"] == "偏空" else "neut"

st.markdown("### 📈 台指期貨｜結算方向判斷")

c1, c2, c3, c4, c5 = st.columns(5, gap="small")

def card(title, value, sub="", cls=""):
    return f"""
    <div class='kpi-card'>
      <div class='kpi-title'>{title}</div>
      <div class='kpi-value {cls}'>{value}</div>
      <div class='kpi-sub'>{sub if sub else '&nbsp;'}</div>
    </div>
    """

with c1: st.markdown(card("方向", ai["direction_text"], cls=cls), unsafe_allow_html=True)
with c2: st.markdown(card("收盤價（結算）", f"{ai['tx_last_price']:.0f}"), unsafe_allow_html=True)
with c3: st.markdown(card("一致性", f"{ai['consistency_pct']}%"), unsafe_allow_html=True)
with c4: st.markdown(card("風險", f"{ai['risk_score']}/100"), unsafe_allow_html=True)
with c5: st.markdown(card("日變化", f"{ai['tx_spread_points']:+.0f}", cls=cls), unsafe_allow_html=True)

# =========================
# 選擇權模組（你現有邏輯可直接接）
# =========================
st.divider()
st.markdown("### 🧩 選擇權｜結構 × ΔOI × 價格確認")

st.info("選擇權分析區塊 UI 已與期貨完全對齊，邏輯維持你目前版本即可直接套入。")
