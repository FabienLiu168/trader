import requests
import pandas as pd
from bs4 import BeautifulSoup

def fetch_histock_branch_top5(stock_id: str):
    url = f"https://histock.tw/stock/branch.aspx?no={stock_id}"
    r = requests.get(url, timeout=15)
    r.encoding = "utf-8"

    soup = BeautifulSoup(r.text, "html.parser")
    tables = soup.find_all("table")

    if len(tables) < 2:
        return None, None

    # 第 1 表：買超，第 2 表：賣超（目前 histock 結構）
    buy_df = pd.read_html(str(tables[0]))[0]
    sell_df = pd.read_html(str(tables[1]))[0]

    buy_top5 = buy_df.head(5)["買超"].str.replace(",", "").astype(int).sum()
    sell_top5 = sell_df.head(5)["賣超"].str.replace(",", "").astype(int).sum()

    return buy_top5, sell_top5
print(fetch_histock_branch_top5("2337"))
