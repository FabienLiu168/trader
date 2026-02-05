import requests
import pandas as pd

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
    r.raise_for_status()
    data = r.json()
    if data.get("status") != 200:
        return pd.DataFrame()
    return pd.DataFrame(data.get("data", []))


def fetch_top5_broker_buy_sell(stock_id: str, date: str):
    """
    回傳：
    - 前五大券商買超合計（張）
    - 前五大券商賣超合計（張）
    """
    df = finmind_get(
        "TaiwanStockInstitutionalInvestorsBuySell",
        stock_id,
        date,
    )

    if df.empty:
        print("❌ 無資料")
        return

    # 確保數值欄位正確
    for col in ["buy", "sell", "net"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    print("📌 原始資料（前 10 筆）")
    print(df[["name", "buy", "sell", "net"]].head(10))
    print("-" * 60)

    # 前五大買超（net 最大）
    top5_buy_df = df.sort_values("net", ascending=False).head(5)
    top5_buy_sum = top5_buy_df["net"].sum()

    # 前五大賣超（net 最小）
    top5_sell_df = df.sort_values("net").head(5)
    top5_sell_sum = top5_sell_df["net"].sum()

    print(f"🔍 股票代碼：{stock_id}")
    print(f"📅 交易日：{date}")
    print()
    print("🟢 前五大券商【買超】")
    print(top5_buy_df[["name", "net"]])
    print(f"👉 合計買超：{int(top5_buy_sum):,} 張")
    print()
    print("🔴 前五大券商【賣超】")
    print(top5_sell_df[["name", "net"]])
    print(f"👉 合計賣超：{int(abs(top5_sell_sum)):,} 張")


# =========================
# 主程式（測試 2337）
# =========================
if __name__ == "__main__":
    STOCK_ID = "2337"          # 旺宏
    TRADE_DATE = "2024-02-04"  # 可自行更換為其他交易日

    fetch_top5_broker_buy_sell(STOCK_ID, TRADE_DATE)
