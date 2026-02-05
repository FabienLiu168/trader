import requests
import pandas as pd
import streamlit as st

# =========================
# 請填入你的 FinMind Token
# =========================
FINMIND_TOKEN = "請在這裡填入你的_FINMIND_TOKEN"
FINMIND_API = "https://api.finmindtrade.com/api/v4/data"


def finmind_get(dataset, stock_id, date):
    params = {
        "dataset": dataset,
        "data_id": stock_id,
        "start_date": date,
        "end_date": date,
        "token": FINMIND_TOKEN,
    }
    r = requests.get(FINMIND_API, params=params, timeout=30)
    data = r.json()
    if data.get("status") != 200:
        return pd.DataFrame()
    return pd.DataFrame(data.get("data", []))


def fetch_top5_broker_buy_sell(stock_id: str, date: str):
    df = finmind_get(
        "TaiwanStockInstitutionalInvestorsBuySell",
        stock_id,
        date,
    )

    if df.empty:
        st.error("❌ 無券商資料")
        return

    # 數值轉型
    for col in ["buy", "sell", "net"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    st.subheader(f"🔍 股票 {stock_id}｜交易日 {date}")

    st.markdown("### 📌 原始券商資料（依 net 排序）")
    st.dataframe(
        df[["name", "buy", "sell", "net"]]
        .sort_values("net", ascending=False),
        use_container_width=True
    )

    # 前五大買超
    top5_buy = df.sort_values("net", ascending=False).head(5)
    buy_sum = int(top5_buy["net"].sum())

    # 前五大賣超
    top5_sell = df.sort_values("net").head(5)
    sell_sum = int(abs(top5_sell["net"].sum()))

    st.success(f"🟢 前五大券商【買超】合計：{buy_sum:,} 張")
    st.error(f"🔴 前五大券商【賣超】合計：{sell_sum:,} 張")


# =========================
# Streamlit UI
# =========================
st.title("📊 FinMind 券商前五大買賣超測試")

stock_id = st.text_input("股票代碼", value="2337")
trade_date = st.text_input("交易日 (YYYY-MM-DD)", value="2024-02-04")

if st.button("▶ 執行查詢"):
    fetch_top5_broker_buy_sell(stock_id, trade_date)
