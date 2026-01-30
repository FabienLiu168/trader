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
# 工具：交易日判斷（第一階段）
# =========================
def is_trading_day(d: dt.date) -> bool:
    # 台指期：週一(0) ~ 週五(4)
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
# Position 資料抓取（以交易日為主）
# =========================
@st.cache_data(ttl=600, show_spinner=False)
def fetch_position_for_trade_date(trade_date: dt.date) -> pd.DataFrame:
    """
    取得「屬於 trade_date 的結算資料」
    注意：結算資料可能於隔日公告
    """
    df = finmind_get(
        dataset="TaiwanFuturesDaily",
        data_id="TX",
        start_date=trade_date.strftime("%Y-%m-%d"),
        end_date=(trade_date + dt.timedelta(days=3)).strftime("%Y-%m-%d"),
    )
    if df.empty:
        return df

    df = df[df["trading_session"].astype(str) == "position"].copy()

    # 人工指定：這批資料屬於查詢的交易日
    df["trade_date"] = trade_date

    return df

# =========================
# 工具
# =========================
def clamp(v, lo, hi): return max(lo, min(hi, v))

# =========================
# Position 專用主力合約選擇
# =========================
def pick_main_contract_position(df: pd.DataFrame, trade_date: dt.date):
    x = df.copy()
    x["contract_ym"] = pd.to_numeric(x["contract_date"], errors="coerce")

    target_ym = trade_date.year * 100 + trade_date.month

    cand = x[x["contract_ym"] >= target_ym]
    if not cand.empty:
        return cand.sort_values("contract_ym").iloc[0]

    return x.sort_values("contract_ym").iloc[-1]

# =========================
# AI 分析（以結算價為準）
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
# UI
# =========================
trade_date = st.date_input("查詢交易日（結算）", value=dt.date.today())

# 🚫 非交易日直接中止
if not is_trading_day(trade_date):
    st.warning(
        f"📅 {trade_date} 為非交易日（週六 / 週日）\n\n"
        "期貨市場無交易、無結算資料，故不顯示任何數據。"
    )
    st.stop()

with st.spinner("抓取 Position 結算資料中..."):
    df_day_all = fetch_position_for_trade_date(trade_date)

if df_day_all.empty:
    st.error(f"❌ {trade_date} 無結算資料（可能尚未公告或為休市日）")
    st.stop()

st.success(f"✅ 交易日：{trade_date}")
st.caption("結算價屬於該交易日，可能於隔日公告")

main_row = pick_main_contract_position(df_day_all, trade_date)
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
# 原始資料表（僅該交易日）
# =========================
show_cols = [
    "trade_date",
    "trading_session",
    "futures_id",
    "contract_date",
    "open",
    "close",
    "settlement_price",
    "volume",
    "open_interest",
]

for c in show_cols:
    if c not in df_day_all.columns:
        df_day_all[c] = None

with st.expander("📊 Position 結算原始資料表", expanded=False):
    st.dataframe(df_day_all[show_cols], height=360, width="stretch")

# =========================
# （以下為「新增」：選擇權模組，不影響既有期貨）
# =========================

@st.cache_data(ttl=600, show_spinner=False)
def fetch_option_for_trade_date(trade_date: dt.date) -> pd.DataFrame:
    df = finmind_get(
        dataset="TaiwanOptionDaily",
        data_id="TXO",
        start_date=trade_date.strftime("%Y-%m-%d"),
        end_date=trade_date.strftime("%Y-%m-%d"),
    )
    return df if df is not None else pd.DataFrame()


def calc_option_market_bias(df_opt: pd.DataFrame, settlement_price: float):
    """
    選擇權市場偏向分析（防呆版）
    回傳 dict 或 None
    """
    if df_opt is None or df_opt.empty:
        return None

    # 嘗試辨識 Call / Put 欄位
    cp_col = None
    for c in ["option_type", "call_put", "right"]:
        if c in df_opt.columns:
            cp_col = c
            break
    if cp_col is None:
        return None

    if "strike_price" not in df_opt.columns or "open_interest" not in df_opt.columns:
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

    x = df_opt.copy()
    x["cp"] = x[cp_col].apply(norm_cp)
    x["strike"] = pd.to_numeric(x["strike_price"], errors="coerce")
    x["oi"] = pd.to_numeric(x["open_interest"], errors="coerce")

    call = x[x["cp"] == "call"].dropna(subset=["strike", "oi"])
    put  = x[x["cp"] == "put"].dropna(subset=["strike", "oi"])

    if call.empty or put.empty:
        return None

    total_oi = call["oi"].sum() + put["oi"].sum()
    if total_oi <= 0:
        return None

    # 市場共識價
    oi_center = (
        (call["strike"] * call["oi"]).sum() +
        (put["strike"] * put["oi"]).sum()
    ) / total_oi

    # 壓力 / 支撐
    call_pressure = call.loc[call["oi"].idxmax()]["strike"]
    put_support = put.loc[put["oi"].idxmax()]["strike"]

    # 偏向判斷
    if settlement_price > oi_center + 30:
        bias = "偏多"
        cls = "bull"
    elif settlement_price < oi_center - 30:
        bias = "偏空"
        cls = "bear"
    else:
        bias = "中性"
        cls = "neut"

    return {
        "bias": bias,
        "cls": cls,
        "oi_center": oi_center,
        "call_pressure": call_pressure,
        "put_support": put_support,
    }


# =========================
# UI：選擇權市場分析（新增）
# =========================
st.divider()
st.subheader("🧩 選擇權市場結構分析（不影響期貨）")

with st.spinner("分析選擇權市場中..."):
    df_opt = fetch_option_for_trade_date(trade_date)
    opt = calc_option_market_bias(df_opt, ai["tx_last_price"])

if opt is None:
    st.info("ℹ️ 本交易日選擇權資料不足，暫不顯示市場偏向")
else:
    c1, c2, c3, c4 = st.columns([1.4, 1.4, 1.6, 1.6], gap="small")

    with c1:
        st.markdown(
            f"<div class='kpi-card'><div class='kpi-title'>選擇權市場偏向</div>"
            f"<div class='kpi-value {opt['cls']}'>{opt['bias']}</div></div>",
            unsafe_allow_html=True,
        )

    with c2:
        st.markdown(
            f"<div class='kpi-card'><div class='kpi-title'>OI 共識價</div>"
            f"<div class='kpi-value'>{opt['oi_center']:.0f}</div></div>",
            unsafe_allow_html=True,
        )

    with c3:
        st.markdown(
            f"<div class='kpi-card'><div class='kpi-title'>上方壓力（Call OI 最大）</div>"
            f"<div class='kpi-value'>{opt['call_pressure']:.0f}</div></div>",
            unsafe_allow_html=True,
        )

    with c4:
        st.markdown(
            f"<div class='kpi-card'><div class='kpi-title'>下方支撐（Put OI 最大）</div>"
            f"<div class='kpi-value'>{opt['put_support']:.0f}</div></div>",
            unsafe_allow_html=True,
        )

