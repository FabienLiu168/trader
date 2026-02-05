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

# 取 2026/02/04 期間資料
df = finmind_get(
    "TaiwanStockInstitutionalInvestorsBuySell",
    "2337",
    "2026-02-04",
    "2026-02-04",
)

print(df.head())
