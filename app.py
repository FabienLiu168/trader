import pandas as pd
import requests

FINMIND_API = "https://api.finmindtrade.com/api/v4/data"
FINMIND_TOKEN = "<你的 TOKEN>"

def finmind_get(dataset, stock_id, start_date, end_date):
    params = {
        "dataset": dataset,
        "data_id": stock_id,
        "start_date": start_date,
        "end_date": end_date,
        "token": FINMIND_TOKEN,
    }
    r = requests.get(FINMIND_API, params=params, timeout=30)
    try:
        data = r.json()
    except Exception:
        return pd.DataFrame()
    if data.get("status") != 200:
        return pd.DataFrame()
    return pd.DataFrame(data.get("data", []))


# =========================
# 測試：2337 旺宏｜2026-02-04
# =========================
df = finmind_get(
    "TaiwanStockInstitutionalInvestorsBuySell",
    "2337",
    "2026-02-04",
    "2026-02-04",
)

if df.empty:
    print("❌ 無券商買賣資料")
    exit()

# 確保數值欄位為數字
for col in ["buy", "sell", "net"]:
    df[col] = pd.to_numeric(df[col], errors="coerce")

print("=== 原始券商資料（前 10 筆） ===")
print(df[["name", "buy", "sell", "net"]].head(10))


# =========================
# 前五大買超
# =========================
top5_buy = (
    df.sort_values("net", ascending=False)
      .head(5)
)

buy_sum = top5_buy["net"].sum()

print("\n=== 前五大【買超】券商 ===")
print(top5_buy[["name", "net"]])
print(f"👉 前五大買超合計：{buy_sum:,.0f} 張")


# =========================
# 前五大賣超
# =========================
top5_sell = (
    df.sort_values("net")
      .head(5)
)

sell_sum = top5_sell["net"].sum()

print("\n=== 前五大【賣超】券商 ===")
print(top5_sell[["name", "net"]])
print(f"👉 前五大賣超合計：{sell_sum:,.0f} 張")

