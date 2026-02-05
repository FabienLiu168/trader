import requests
import pandas as pd
import streamlit as st
from bs4 import BeautifulSoup

def debug_histock_branch_top5(stock_id: str):
    st.subheader(f"🔍 histock 分點測試：{stock_id}")

    url = f"https://histock.tw/stock/branch.aspx?no={stock_id}"
    r = requests.get(url, timeout=15)
    r.encoding = "utf-8"

    soup = BeautifulSoup(r.text, "html.parser")

    # 🔑 只抓 histock 的分點表
    tables = soup.find_all("table", class_="tb-stock")

    st.write(f"找到 table 數量：{len(tables)}")

    if len(tables) < 2:
        st.error("❌ 找不到分點買賣表（histock 結構可能改版）")
        return

    # 第 1 個：買超，第 2 個：賣超（目前實測）
    buy_df = pd.read_html(str(tables[0]))[0]
    sell_df = pd.read_html(str(tables[1]))[0]

    st.markdown("### 🟢 券商買超排行")
    st.dataframe(buy_df, use_container_width=True)

    st.markdown("### 🔴 券商賣超排行")
    st.dataframe(sell_df, use_container_width=True)

    # 計算前五大
    buy_top5 = (
        buy_df.head(5)["買超"]
        .astype(str)
        .str.replace(",", "")
        .astype(int)
        .sum()
    )

    sell_top5 = (
        sell_df.head(5)["賣超"]
        .astype(str)
        .str.replace(",", "")
        .astype(int)
        .sum()
    )

    st.success(f"🟢 前五大買超合計：{buy_top5:,} 張")
    st.error(f"🔴 前五大賣超合計：{sell_top5:,} 張")
debug_histock_branch_top5("2337")
