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
st.set_page_config(page_title="台指期貨 Position 儀表板", layout="wide")

APP_TITLE = "台指期貨 / 選擇權 AI 儀表板（Position 結算版）"

st.markdown(
    """
<style>
div[data-testid="stAppViewContainer"] > .main { padding-top: 3.6rem; }
.app-title{ font-size:2.1rem;font-weight:900;margin:0 }
.app-subtitle{ font-size:0.95rem;opacity:.75;margin:.4rem 0 1rem }
.kpi-card{
  border:1px solid rgba(255,255,255,.15);
  border-radius:14px;padding:14px;background:rgba(255,255,255,.04)
}
.kpi-title{ font-size:.9rem;opacity:.8 }
.kpi-value{ font-size:2rem;font-weight:800 }
.bull{ color:#FF3B30 } .bear{ color:#34C759 } .neut{ color:#C7C7CC }
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    f"""
<div class="app-title">{APP_TITLE}</div>
<div class="app-subtitle">
✅ 本版 **僅使用 Position（結算部位）資料**<br/>
❌ 不顯示日盤 / 夜盤 / 盤後估算<br/>
❌ 不回溯最近有效交易日
</div>
""",
    unsafe_allow_html=True,
)

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
# 抓取 Position
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
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    return df

# =========================
# 主力合約
# =========================
def pick_main_contract(df):
    if df.empty:
        return None
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
    return df.loc[df["volume"].idxmax()]

# =========================
# UI
# =========================
target_date = st.date_input("查詢結算日（Position）", value=dt.date.today())

with st.spinner("抓取 Position 結算資料中..."):
    df_day = fetch_position(target_date)

if df_day.empty:
    st.error(f"❌ {target_date} 尚未產生 Position 結算資料（假日 / 尚未結算）")
    st.stop()

st.success(f"✅ Position 結算日：{target_date}")
st.caption(f"結算合約筆數：{len(df_day)}")

# KPI
main = pick_main_contract(df_day)
if main is None:
    st.error("找不到主力合約")
    st.stop()

close_ = float(main.get("settlement_price") or main.get("close") or 0)
open_ = float(main.get("open") or 0)
spread = close_ - open_

mood = "偏多" if spread > 0 else "偏空" if spread < 0 else "中性"
cls = "bull" if spread > 0 else "bear" if spread < 0 else "neut"

c1, c2, c3 = st.columns(3)

with c1:
    st.markdown(
        f"""
<div class="kpi-card">
<div class="kpi-title">方向（Position）</div>
<div class="kpi-value {cls}">{mood}</div>
</div>
""",
        unsafe_allow_html=True,
    )

with c2:
    st.markdown(
        f"""
<div class="kpi-card">
<div class="kpi-title">結算價</div>
<div class="kpi-value">{close_:.0f}</div>
</div>
""",
        unsafe_allow_html=True,
    )

with c3:
    st.markdown(
        f"""
<div class="kpi-card">
<div class="kpi-title">日變化</div>
<div class="kpi-value {cls}">{spread:+.0f}</div>
</div>
""",
        unsafe_allow_html=True,
    )

st.divider()

# =========================
# 表格（Position Only）
# =========================
show_cols = [
    "date",
    "futures_id",
    "contract_date",
    "open",
    "close",
    "settlement_price",
    "volume",
    "open_interest",
]
for c in show_cols:
    if c not in df_day.columns:
        df_day[c] = None

with st.expander("📊 Position 結算原始資料表", expanded=True):
    st.dataframe(df_day[show_cols], height=360, width="stretch")
