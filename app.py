def fetch_branch_top5_buy_sell(stock_id: str, trade_date: dt.date):
    df = finmind_get(
        "TaiwanStockInstitutionalInvestorsBuySell",
        stock_id,
        trade_date.strftime("%Y-%m-%d"),
        trade_date.strftime("%Y-%m-%d"),
    )

    if df.empty:
        return {"top5_buy": "-", "top5_sell": "-"}

    # 防呆
    for c in ["buy", "sell", "net"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # 只保留有 net 的
    df = df.dropna(subset=["net"])
    if df.empty:
        return {"top5_buy": "-", "top5_sell": "-"}

    top5_buy = (
        df.sort_values("net", ascending=False)
        .head(5)["net"]
        .sum()
    )

    top5_sell = (
        df.sort_values("net")
        .head(5)["net"]
        .sum()
    )

    return {
        "top5_buy": f"{int(top5_buy):,}",
        "top5_sell": f"{int(abs(top5_sell)):,}",
    }
