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
div[data-testid="stAppViewContainer"] > .main { padding-top: 3.8rem; }
.app-title{ font-size:2.15rem;font-weight:900;margin:0 }
.app-subtitle{ font-size:.95rem;opacity:.75;margin:.3rem 0 .9rem }
.kpi-card{
  border:1px solid rgba(255,255,255,.12);
  border-radius:14px;padding:14px 16px;
  background:rgba(255,255,255,.04);
  box-shadow:0 6px 22px rgba(0,0,0,.18)
}
.kpi-title{ font-size:.95rem;opacity:.85 }
.kpi-value{ font-size:2rem;font-weight:800 }
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
✅ 資料基準：<b>Position（結算資料）</b><br/>
✅ 收盤價定義：<b>Settlement Price（官方結算價）</b><br/>
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
# Position 資料抓取（期貨，完全不動）
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
    return cand.sort_values("contract_ym").iloc[0] if not cand.empty else x.sort_values("contract_ym").iloc[-1]

# =========================
# 期貨 AI（完全不動）
# =========================
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
# UI：期貨（完全不動）
# =========================
trade_date = st.date_input("查詢交易日（結算）", value=dt.date.today())

if not is_trading_day(trade_date):
    st.warning("📅 非交易日（週六 / 週日），不顯示任何資料")
    st.stop()

df_day_all = fetch_position_for_trade_date(trade_date)
if df_day_all.empty:
    st.error("❌ 無結算資料")
    st.stop()

main_row = pick_main_contract_position(df_day_all, trade_date)
ai = calc_ai_scores(main_row, df_day_all)

cls = "bull" if ai["direction_text"]=="偏多" else "bear" if ai["direction_text"]=="偏空" else "neut"

c1,c2,c3,c4,c5 = st.columns([1.6,1.6,1.2,1.2,1.4],gap="small")
with c1: st.markdown(f"<div class='kpi-card'><div class='kpi-title'>方向</div><div class='kpi-value {cls}'>{ai['direction_text']}</div></div>",unsafe_allow_html=True)
with c2: st.markdown(f"<div class='kpi-card'><div class='kpi-title'>收盤價（結算價）</div><div class='kpi-value'>{ai['tx_last_price']:.0f}</div></div>",unsafe_allow_html=True)
with c3: st.markdown(f"<div class='kpi-card'><div class='kpi-title'>一致性</div><div class='kpi-value'>{ai['consistency_pct']}%</div></div>",unsafe_allow_html=True)
with c4: st.markdown(f"<div class='kpi-card'><div class='kpi-title'>風險</div><div class='kpi-value'>{ai['risk_score']}/100</div></div>",unsafe_allow_html=True)
with c5: st.markdown(f"<div class='kpi-card'><div class='kpi-title'>日變化</div><div class='kpi-value {cls}'>{ai['tx_spread_points']:+.0f}</div></div>",unsafe_allow_html=True)

st.divider()

# =========================
# 選擇權模組（新增，使用 matplotlib）
# =========================
import matplotlib.pyplot as plt

@st.cache_data(ttl=600, show_spinner=False)
def fetch_option_for_trade_date(trade_date: dt.date) -> pd.DataFrame:
    return finmind_get(
        dataset="TaiwanOptionDaily",
        data_id="TXO",
        start_date=trade_date.strftime("%Y-%m-%d"),
        end_date=trade_date.strftime("%Y-%m-%d"),
    )

def calc_option_market_bias(df_opt: pd.DataFrame, price: float):
    if df_opt is None or df_opt.empty:
        return None

    cp_col = next((c for c in ["option_type","call_put","right"] if c in df_opt.columns), None)
    if cp_col is None:
        return None

    x = df_opt.copy()
    x["cp"] = x[cp_col].astype(str).str.lower().map(
        {"c":"call","call":"call","p":"put","put":"put"}
    )
    x["strike"] = pd.to_numeric(x["strike_price"], errors="coerce")
    x["oi"] = pd.to_numeric(x["open_interest"], errors="coerce")
    x = x.dropna(subset=["cp","strike","oi"])

    call = x[x["cp"]=="call"]
    put  = x[x["cp"]=="put"]
    if call.empty or put.empty:
        return None

    call_near = call.iloc[(call["strike"]-price).abs().argsort()].iloc[0]
    put_near  = put.iloc[(put["strike"]-price).abs().argsort()].iloc[0]

    call_res = call_near["strike"]
    put_sup  = put_near["strike"]
    mid = (call_res + put_sup)/2
    width = max(call_res - put_sup,1)
    bias_ratio = (price - mid)/width

    if bias_ratio > 0.25:
        bias,cls="區間偏多","bull"
    elif bias_ratio < -0.25:
        bias,cls="區間偏空","bear"
    else:
        bias,cls="區間震盪","neut"

    return dict(bias=bias,cls=cls,call_res=call_res,put_sup=put_sup,mid=mid,df=x)

def plot_option_range(opt, price):
    df=opt["df"]
    fig,ax=plt.subplots(figsize=(10,4))
    ax.bar(df[df.cp=="call"]["strike"],df[df.cp=="call"]["oi"],color="red",alpha=.6,label="Call OI")
    ax.bar(df[df.cp=="put"]["strike"],-df[df.cp=="put"]["oi"],color="green",alpha=.6,label="Put OI")
    for label,x in [("現價",price),("壓力",opt["call_res"]),("支撐",opt["put_sup"]),("中軸",opt["mid"])]:
        ax.axvline(x,linestyle="--")
        ax.text(x,ax.get_ylim()[1]*0.9,label,rotation=90)
    ax.set_title("選擇權 OI 壓力 / 支撐區間圖")
    ax.legend()
    ax.grid(alpha=.3)
    return fig

st.subheader("🧩 選擇權市場區間分析")

df_opt = fetch_option_for_trade_date(trade_date)
opt = calc_option_market_bias(df_opt, ai["tx_last_price"])

if opt:
    st.markdown(
        f"<div class='kpi-card'><div class='kpi-title'>選擇權市場狀態</div>"
        f"<div class='kpi-value {opt['cls']}'>{opt['bias']}</div></div>",
        unsafe_allow_html=True,
    )
    st.pyplot(plot_option_range(opt, ai["tx_last_price"]))
else:
    st.info("ℹ️ 選擇權資料不足，無法分析")
