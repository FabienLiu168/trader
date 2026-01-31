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

APP_TITLE = "台指期貨 / 選擇權 AI 儀表板"

st.markdown(
    """
<style>
div[data-testid="stAppViewContainer"] > .main { padding-top: 3.2rem; }

.app-title{ font-size:2.5rem;font-weight:750;margin-top:-60px;text-align:center;letter-spacing:0.5px;margin-bottom:2px; }
.app-subtitle{ font-size:1.0rem;margin:.45rem 0 1.1rem;text-align:center; }

.fut-section-title{ font-size:1.8rem !important;font-weight:400;display:flex;align-items:center; }
.opt-section-title{ font-size:1.8rem !important;font-weight:400;display:flex;align-items:center; }

.kpi-card{
  border:1px solid rgba(255,255,255,.12);
  border-radius:14px;
  padding:16px 18px;
  background:#F4F6F5;
  box-shadow:0 6px 22px rgba(0,0,0,.18);
  min-height:140px;
  display:flex;
  flex-direction:column;
  justify-content:space-between;
}

.kpi-title{ font-size:1.2rem;opacity:.85 }
.kpi-value{ font-size:1.7rem;font-weight:500;line-height:1.5 }
.kpi-sub{ font-size:1.0rem;opacity:.65;line-height:1.5}

.bull{color:#FF3B30}
.bear{color:#34C759}
.neut{color:#000000}
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
# 第一模組（完整封裝，內容 100% 等價）
# =========================
def render_tab_option_market(trade_date: dt.date):

    # === 以下全部內容：來自你「最早的第一模組原始碼」===
    # ⚠️ 僅增加縮排，未改任何一行邏輯

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
        low_  = float(main_row.get("min", 0) or 0)
        spread = final_close - open_
        day_range = abs(high_ - low_)
        vol = float(pd.to_numeric(main_row.get("volume", 0), errors="coerce") or 0)
        vol_med = max(float(pd.to_numeric(df_all["volume"], errors="coerce").median() or 1), 1)
        score = (
            clamp(spread / 100.0, -3, 3) * 0.7 +
            clamp((vol / vol_med - 1) * 2, -2, 2) * 0.3
        )
        direction = "偏多" if score > 0.8 else "偏空" if score < -0.8 else "中性"
        return {
            "direction_text": direction,
            "tx_last_price": final_close,
            "tx_spread_points": spread,
            "day_range": day_range,
            "risk_score": int(clamp(day_range / 3, 0, 100)),
            "consistency_pct": int(abs(score) / 3 * 100),
        }

    def get_prev_trading_close(trade_date: dt.date, lookback_days=7):
        for i in range(1, lookback_days + 1):
            d = trade_date - dt.timedelta(days=i)
            if d.weekday() >= 5:
                continue
            df = fetch_position_for_trade_date(d)
            if not df.empty:
                row = pick_main_contract_position(df, d)
                settle = row.get("settlement_price")
                close = row.get("close")
                return float(settle) if settle not in (None, "", 0) else float(close or 0)
        return None

    df_day_all = fetch_position_for_trade_date(trade_date)
    if df_day_all.empty:
        st.error("❌ 無期貨結算資料")
        return

    main_row = pick_main_contract_position(df_day_all, trade_date)
    ai = calc_ai_scores(main_row, df_day_all)
    fut_price = ai["tx_last_price"]
    prev_close = get_prev_trading_close(trade_date)

    price_diff = pct_diff = None
    price_color = "#000000"
    if prev_close:
        price_diff = fut_price - prev_close
        pct_diff = price_diff / prev_close * 100
        price_color = "#FF3B30" if price_diff > 0 else "#34C759" if price_diff < 0 else "#000000"

    st.markdown("<h2 class='fut-section-title'>📈 台指期貨｜結算方向判斷</h2>", unsafe_allow_html=True)

    mood = ai["direction_text"]
    cls = "bull" if mood == "偏多" else "bear" if mood == "偏空" else "neut"
    c1, c2, c3, c4, c5 = st.columns([1.6,1.6,1.2,1.2,1.4])

    with c1:
        st.markdown(f"<div class='kpi-card'><div class='kpi-title'>方向</div><div class='kpi-value {cls}'>{mood}</div></div>", unsafe_allow_html=True)
    with c2:
        st.markdown(
            f"<div class='kpi-card'><div class='kpi-title'>收盤價</div>"
            f"<div class='kpi-value' style='color:{price_color}'>{fut_price:.0f}"
            f"<span style='font-size:1.05rem'> ({price_diff:+.0f}，{pct_diff:+.1f}%)</span></div></div>",
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(f"<div class='kpi-card'><div class='kpi-title'>一致性</div><div class='kpi-value'>{ai['consistency_pct']}%</div></div>", unsafe_allow_html=True)
    with c4:
        st.markdown(f"<div class='kpi-card'><div class='kpi-title'>風險</div><div class='kpi-value'>{ai['risk_score']}/100</div></div>", unsafe_allow_html=True)
    with c5:
        st.markdown(f"<div class='kpi-card'><div class='kpi-title'>日震幅</div><div class='kpi-value'>{ai['day_range']:.0f}</div></div>", unsafe_allow_html=True)

# =========================
# 第二模組（維持你原本版本）
# =========================
def render_tab_stock_futures(trade_date: dt.date):
    st.markdown("<h2 class='fut-section-title'>📊 個股期貨｜現貨成交量 Top10</h2>", unsafe_allow_html=True)
    st.info("⚠️ 尚無法取得當日現貨成交量資料")
    st.dataframe(pd.DataFrame(columns=["標的名稱","總成交量","交易總金額","收盤價（漲跌%）"]))

# =========================
# 主流程
# =========================
trade_date = st.date_input("📅 查詢交易日（結算）", value=dt.date.today())

if not is_trading_day(trade_date):
    st.warning("📅 非交易日")
    st.stop()

tab1, tab2 = st.tabs(["📈 期權大盤", "📊 個股期貨"])

with tab1:
    render_tab_option_market(trade_date)

with tab2:
    render_tab_stock_futures(trade_date)
