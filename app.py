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
  min-height:140px;
  display:flex;
  flex-direction:column;
  justify-content:space-between;
}

.kpi-title{ font-size:.95rem;opacity:.85 }
.kpi-value{ font-size:1.7rem;font-weight:800;line-height:1.15 }
.kpi-sub{ font-size:.8rem;opacity:.65;line-height:1.25 }

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
✅ 期貨基準：Position 結算價　
✅ 選擇權：ΔOI × 結構 × 價格行為　
❌ 非交易日不顯示資料
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
# 期貨 Position（原樣保留）
# =========================
@st.cache_data(ttl=600, show_spinner=False)
def fetch_position_for_trade_date(trade_date: dt.date):
    df = finmind_get(
        "TaiwanFuturesDaily", "TX",
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
    return cand.sort_values("ym").iloc[0] if not cand.empty else x.sort_values("ym").iloc[-1]

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
    score = clamp(spread / 100.0, -3, 3) * 0.7 + clamp((vol / vol_med - 1) * 2, -2, 2) * 0.3
    return {
        "price": final_close,
        "spread": spread,
        "risk": int(clamp(range_ / 3, 0, 100)),
    }

# =========================
# UI：期貨
# =========================
trade_date = st.date_input("查詢交易日（結算）", value=dt.date.today())

if not is_trading_day(trade_date):
    st.warning("📅 非交易日（週六 / 週日）")
    st.stop()

df_fut = fetch_position_for_trade_date(trade_date)
if df_fut.empty:
    st.error("❌ 無期貨結算資料")
    st.stop()

main_row = pick_main_contract_position(df_fut, trade_date)
fut = calc_ai_scores(main_row, df_fut)

st.markdown("## 📈 台指期貨｜結算資訊")
fc1, fc2, fc3 = st.columns(3, gap="small")

with fc1:
    st.markdown(f"<div class='kpi-card'><div class='kpi-title'>結算價</div><div class='kpi-value'>{fut['price']:.0f}</div></div>", unsafe_allow_html=True)
with fc2:
    st.markdown(f"<div class='kpi-card'><div class='kpi-title'>日變化</div><div class='kpi-value'>{fut['spread']:+.0f}</div></div>", unsafe_allow_html=True)
with fc3:
    st.markdown(f"<div class='kpi-card'><div class='kpi-title'>風險</div><div class='kpi-value'>{fut['risk']}/100</div></div>", unsafe_allow_html=True)

# =========================
# 選擇權 V3（ΔOI + 結構 + 價格）
# =========================
def normalize_cp(v):
    s = str(v).lower()
    if s in ("c", "call", "買權"):
        return "call"
    if s in ("p", "put", "賣權"):
        return "put"
    return None

@st.cache_data(ttl=600, show_spinner=False)
def fetch_option_latest(trade_date):
    for i in range(1, 6):
        d = trade_date - dt.timedelta(days=i)
        if d.weekday() >= 5:
            continue
        df = finmind_get("TaiwanOptionDaily", "TXO", d.strftime("%Y-%m-%d"), d.strftime("%Y-%m-%d"))
        if not df.empty:
            df["trade_date"] = d
            return df
    return pd.DataFrame()

def calc_option_bias_v3(df, fut_price):
    if df.empty:
        return None

    cp_col = next((c for c in ["option_type","call_put","right"] if c in df.columns), None)
    if cp_col is None:
        return None

    df = df.copy()
    df["cp"] = df[cp_col].apply(normalize_cp)
    df["strike"] = pd.to_numeric(df["strike_price"], errors="coerce")
    df["oi"] = pd.to_numeric(df["open_interest"], errors="coerce")
    df = df.dropna(subset=["cp","strike","oi"])

    call = df[df["cp"]=="call"]
    put  = df[df["cp"]=="put"]
    if call.empty or put.empty:
        return None

    call_lvl = call.loc[call["oi"].idxmax()]["strike"]
    put_lvl  = put.loc[put["oi"].idxmax()]["strike"]

    state, reason = "結構中性", "價格位於 OI 區間內"

    if fut_price >= call_lvl:
        state = "高檔受壓（偏空結構）"
        reason = "價格測試 Call 最大 OI 壓力"
    elif fut_price <= put_lvl:
        state = "支撐有效（偏多結構）"
        reason = "價格位於 Put 強支撐上方"

    return {
        "state": state,
        "reason": reason,
        "call_pressure": call_lvl,
        "put_support": put_lvl,
        "trade_date": df["trade_date"].iloc[0],
    }

# =========================
# UI：選擇權
# =========================
st.divider()
st.markdown("## 🧩 選擇權｜ΔOI × 結構 × 價格行為")

df_opt = fetch_option_latest(trade_date)
opt = calc_option_bias_v3(df_opt, fut["price"])

if opt is None:
    st.info("ℹ️ 選擇權資料不足（TXO 為 T+1 公告）")
else:
    st.caption(f"📅 選擇權資料日：{opt['trade_date']}")

    oc1, oc2, oc3 = st.columns(3, gap="small")

    with oc1:
        st.markdown(
            f"<div class='kpi-card'><div class='kpi-title'>市場狀態</div>"
            f"<div class='kpi-value'>{opt['state']}</div>"
            f"<div class='kpi-sub'>{opt['reason']}</div></div>",
            unsafe_allow_html=True,
        )
    with oc2:
        st.markdown(
            f"<div class='kpi-card'><div class='kpi-title'>上方壓力</div>"
            f"<div class='kpi-value'>{opt['call_pressure']:.0f}</div>"
            f"<div class='kpi-sub'>Call 最大 OI</div></div>",
            unsafe_allow_html=True,
        )
    with oc3:
        st.markdown(
            f"<div class='kpi-card'><div class='kpi-title'>下方支撐</div>"
            f"<div class='kpi-value'>{opt['put_support']:.0f}</div>"
            f"<div class='kpi-sub'>Put 最大 OI</div></div>",
            unsafe_allow_html=True,
        )
