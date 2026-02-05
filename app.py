def debug_branch_top5(stock_id: str, trade_date: dt.date):
    df = finmind_get(
        "TaiwanStockInstitutionalInvestorsBuySell",
        stock_id,
        trade_date.strftime("%Y-%m-%d"),
        trade_date.strftime("%Y-%m-%d"),
    )

    if df.empty:
        st.error(f"❌ {stock_id} 無券商分點資料")
        return

    # 數值轉型保護
    for col in ["buy", "sell", "net"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    st.subheader(f"🔍 {stock_id} 券商分點測試（{trade_date}）")

    # 原始分點資料
    st.dataframe(
        df[["name", "buy", "sell", "net"]]
        .sort_values("net", ascending=False),
        use_container_width=True
    )

    # 前五大買超 / 賣超
    top5_buy = df.sort_values("net", ascending=False).head(5)
    top5_sell = df.sort_values("net").head(5)

    st.success(f"🟢 前五大券商【買超】合計：{top5_buy['net'].sum():,.0f} 張")
    st.error(f"🔴 前五大券商【賣超】合計：{top5_sell['net'].sum():,.0f} 張")


tab1, tab2 = st.tabs(["📈 期權趨勢", "📊 個股期貨"])

with tab1:
    render_tab_option_market(trade_date)

with tab2:
    render_tab_stock_futures(trade_date)

    # ✅ Debug 測試（此時 trade_date 一定已存在）
    debug_branch_top5("2337", trade_date)
