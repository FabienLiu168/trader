import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
from io import StringIO

# ----------------------------
# 基本設定
# ----------------------------
st.set_page_config(page_title="台指期貨/選擇權 AI 儀表板", layout="wide")

st.title("📊 台指期貨 / 選擇權 AI 儀表板（第二階段：真實盤後資料接入）")

# ----------------------------
# Debug：確認 Secrets
# ----------------------------
st.markdown("## 🔧 Debug 狀態檢查")

FINMIND_TOKEN = None
if "FINMIND_TOKEN" in st.secrets:
    FINMIND_TOKEN = st.secrets["FINMIND_TOKEN"]
    st.success("✅ FINMIND_TOKEN 已成功載入")
    st.write("Token 長度：", len(FINMIND_TOKEN))
else:
    st.error("❌ FINMIND_TOKEN 未讀取到（請到 Streamlit Secrets 設定）")
    st.stop()

# ----------------------------
# FinMind API：通用取資料
# ----------------------------
def finmind_get(dataset: str, data_id: str = None, start_date: str = None, end_date: str = None):
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {
        "dataset": dataset,
        "token": FINMIND_TOKEN,
    }
    if data_id:
        params["data_id"] = data_id
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date

    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    js = r.json()
    if js.get("status") != 200:
        return pd.DataFrame()
    data = js.get("data", [])
    return pd.DataFrame(data)

# ----------------------------
# Step 3-1 核心：回溯找最近有效交易日
# ----------------------------
def find_latest_valid_date(fetch_func, target_date: datetime, lookback_days: int = 15):
    """
    fetch_func(date_str) -> df
    從 target_date 往前最多 lookback_days 天，找到第一天 df 非空的日期
    """
    for i in range(0, lookback_days + 1):
        d = target_date - timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        try:
            df = fetch_func(d_str)
            if df is not None and not df.empty:
                return d_str, df
        except Exception:
            continue
    return None, pd.DataFrame()

# ----------------------------
# UI：日期選擇
# ----------------------------
st.markdown("---")
col1, col2 = st.columns([2, 3])

with col1:
    user_date = st.date_input("查詢日期（盤後）", value=datetime.now().date())
    user_date_dt = datetime.combine(user_date, datetime.min.time())

with col2:
    st.info("提示：盤後資料常在收盤後更新；若當天尚未更新，本程式會自動往前找最近有資料的交易日。")

# ----------------------------
# 你目前用的：TXF 盤後資料抓取（先做一個可驗證的版本）
# 注意：FinMind 的 dataset 可能會依你帳號/方案不同而可用不同
# 我們用「回溯找日期」方式先把資料抓出來
# ----------------------------
def fetch_txf_daily(date_str: str):
    # 這裡先用 start_date=end_date=date_str 方式抓當日
    # dataset 名稱如你原本用的那個（若不同請告訴我，我會對應修正）
    # 常見：TaiwanFuturesDaily / FuturesDaily / TaiwanFutures ... (依 FinMind 定義)
    # 你先用這個跑，看 df 是否抓到；抓不到我們再精準校正 dataset / data_id
    df = finmind_get(
        dataset="TaiwanFuturesDaily",
        data_id="TX",  # TX 代表台指期(常見)，若你原程式不同再改
        start_date=date_str,
        end_date=date_str
    )
    return df

# ----------------------------
# 執行：回溯找最近有資料的日期
# ----------------------------
st.markdown("## 📌 TXF 盤後資料（自動回溯找最近有效交易日）")

latest_date, df_txf = find_latest_valid_date(fetch_txf_daily, user_date_dt, lookback_days=15)

if latest_date is None or df_txf.empty:
    st.error("❌ 回溯 15 天仍抓不到 TXF 盤後資料。代表 dataset/data_id 需校正（我會幫你直接修正）。")
    st.stop()

st.success(f"✅ 抓到資料！你選的日期：{user_date_dt.strftime('%Y-%m-%d')} → 實際抓到資料日期：{latest_date}")
st.write("筆數：", len(df_txf))

# 顯示資料（先把欄位全部展開給你看，方便我們確認欄位名稱）
st.dataframe(df_txf, width='stretch')

st.markdown("---")
st.caption("Step 3-1 完成：已做到『自動回溯抓到最近一個有資料的交易日』。下一步會把欄位對應到日盤/夜盤與分數計算。")
