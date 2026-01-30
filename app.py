import re
import datetime as dt
import pandas as pd
import requests
from bs4 import BeautifulSoup
import streamlit as st

st.markdown("## 🔧 Debug 狀態檢查")

if "FINMIND_TOKEN" in st.secrets:
    token = st.secrets["FINMIND_TOKEN"]
    st.success("✅ FINMIND_TOKEN 已成功載入")
    st.write("Token 長度：", len(token))
else:
    st.error("❌ FINMIND_TOKEN 未讀取到")

st.set_page_config(page_title="台指期貨/選擇權 AI 儀表板", layout="wide")

TAIFEX_FUT_DAILY_URL = "https://www.taifex.com.tw/cht/3/futDailyMarketReport"
TAIFEX_OPT_PCR_URL = "https://www.taifex.com.tw/cht/3/pcRatio"

# -----------------------------
# Utils
# -----------------------------
def tw_date_str(d: dt.date) -> str:
    # TAIFEX 多數表單吃 yyyy/mm/dd
    return d.strftime("%Y/%m/%d")

def guess_last_trade_date(today: dt.date) -> dt.date:
    # 簡化：週末往前推（不含國定假日判斷）
    if today.weekday() == 5:   # Sat
        return today - dt.timedelta(days=1)
    if today.weekday() == 6:   # Sun
        return today - dt.timedelta(days=2)
    return today

@st.cache_data(ttl=60 * 30, show_spinner=False)
def fetch_fut_daily_table(query_date: dt.date, market_code: str, commodity_id: str = "TXF") -> pd.DataFrame:
    """
    market_code:
      '0' 通常代表一般日盤
      '1' 常用來查夜盤(盤後) (TAIFEX 站內表單用法可能調整，若取不到就會回空表)
    """
    payload = {
        "queryType": "2",
        "marketCode": market_code,
        "commodity_id": commodity_id,
        "queryDate": tw_date_str(query_date),
    }

    r = requests.post(TAIFEX_FUT_DAILY_URL, data=payload, timeout=20)
    r.raise_for_status()

    # 解析 HTML 表格（盤後資料）
    soup = BeautifulSoup(r.text, "lxml")
    table = soup.find("table", {"class": "table_f"})
    if table is None:
        return pd.DataFrame()

    df_list = pd.read_html(str(table))
    if not df_list:
        return pd.DataFrame()

    df = df_list[0].copy()
    # 清理欄名
    df.columns = [str(c).strip() for c in df.columns]
    return df

@st.cache_data(ttl=60 * 30, show_spinner=False)
def fetch_put_call_ratio(query_date: dt.date) -> pd.DataFrame:
    """
    Put/Call Ratio 盤後資料（TXO/全市場）
    """
    payload = {
        "queryDate": tw_date_str(query_date),
    }
    r = requests.post(TAIFEX_OPT_PCR_URL, data=payload, timeout=20)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "lxml")
    table = soup.find("table", {"class": "table_f"})
    if table is None:
        return pd.DataFrame()

    df_list = pd.read_html(str(table))
    if not df_list:
        return pd.DataFrame()
    df = df_list[0].copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df

def pick_txf_main_row(df: pd.DataFrame) -> pd.Series | None:
    """
    從期貨每日行情表中抓出 TXF 近月(通常第一列)資訊。
    TAIFEX 表格欄位偶爾會調整，這裡做較寬鬆的抓法。
    """
    if df.empty:
        return None

    # 可能的欄位：到期月份/契約、成交量、未平倉、收盤價、漲跌...
    # 通常第一列就是近月，先保守取第一列
    row = df.iloc[0]
    return row

def safe_float(x):
    try:
        if isinstance(x, str):
            x = x.replace(",", "").strip()
        return float(x)
    except:
        return None

# -----------------------------
# UI
# -----------------------------
st.title("📊 台指期貨 / 選擇權 AI 儀表板（第二階段：真實盤後資料接入）")

colA, colB = st.columns([2, 3])
with colA:
    today = dt.date.today()
    default_date = guess_last_trade_date(today)
    qdate = st.date_input("查詢日期（盤後）", value=default_date)
with colB:
    st.caption("提示：盤後資料通常在收盤後更新；若當天尚未更新，請改查前一交易日。")

tab1, tab2, tab3 = st.tabs(["期貨 TXF（日盤/夜盤）", "選擇權 TXO（PCR）", "總結（燈號）"])

# -----------------------------
# Tab 1: Futures
# -----------------------------
with tab1:
    st.subheader("TXF 盤後資料（分日盤/夜盤）")

    c1, c2 = st.columns(2)

    with c1:
        st.markdown("### ☀️ 日盤（盤後）")
        try:
            df_day = fetch_fut_daily_table(qdate, market_code="0", commodity_id="TXF")
        except Exception as e:
            df_day = pd.DataFrame()
            st.error(f"日盤資料抓取失敗：{e}")

        if df_day.empty:
            st.warning("日盤盤後資料目前抓不到（可能當日尚未更新 / TAIFEX 表單參數調整）。")
        else:
            st.dataframe(df_day, use_container_width=True)
            r = pick_txf_main_row(df_day)
            if r is not None:
                st.info(f"日盤近月（第一列）摘要：{r.to_dict()}")

    with c2:
        st.markdown("### 🌙 夜盤（盤後）")
        try:
            df_night = fetch_fut_daily_table(qdate, market_code="1", commodity_id="TXF")
        except Exception as e:
            df_night = pd.DataFrame()
            st.error(f"夜盤資料抓取失敗：{e}")

        if df_night.empty:
            st.warning("夜盤盤後資料目前抓不到（常見原因：TAIFEX 夜盤 marketCode 參數可能已調整）。")
            st.caption("如果你要我幫你精準對齊夜盤參數：你只要回我「夜盤頁面能查到，但程式查不到」，我會用你實際查到的頁面條件反推正確參數。")
        else:
            st.dataframe(df_night, use_container_width=True)
            r = pick_txf_main_row(df_night)
            if r is not None:
                st.info(f"夜盤近月（第一列）摘要：{r.to_dict()}")

# -----------------------------
# Tab 2: Options PCR
# -----------------------------
with tab2:
    st.subheader("Put/Call Ratio（盤後）")
    try:
        df_pcr = fetch_put_call_ratio(qdate)
    except Exception as e:
        df_pcr = pd.DataFrame()
        st.error(f"PCR 抓取失敗：{e}")

    if df_pcr.empty:
        st.warning("PCR 目前抓不到（可能當日尚未更新 / TAIFEX 網站結構調整）。")
    else:
        st.dataframe(df_pcr, use_container_width=True)

# -----------------------------
# Tab 3: Summary lights (simple demo)
# -----------------------------
with tab3:
    st.subheader("一致性 + 風險狀態（示範版）")

    # 目前先用「有無資料」做示範，等你日/夜盤與 PCR 都穩定抓到後再接 v7 多因子分數
    have_day = "df_day" in locals() and not df_day.empty
    have_night = "df_night" in locals() and not df_night.empty
    have_pcr = "df_pcr" in locals() and not df_pcr.empty

    score = sum([have_day, have_night, have_pcr])
    if score >= 3:
        st.success("🟢 一致性：高（資料齊全，可開始做多因子）")
    elif score == 2:
        st.warning("🟡 一致性：中（資料缺一塊，建議先補齊）")
    else:
        st.error("🔴 一致性：低（目前資料不足，先把資料源穩定）")

    st.caption("下一步：把 v7 的多因子條件（PCR/IV/Volume/OI/結算/散戶多空比/外資/台積電等）逐一接入，並用『日盤 vs 夜盤』分開算分，再做合併建議。")
