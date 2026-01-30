import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta

st.set_page_config(page_title="台指交易儀表板 v7", layout="wide")

TW_TZ = timezone(timedelta(hours=8))

# -----------------------------
# 工具：顯示燈號
# -----------------------------
def render_light(color, title, subtitle):
    st.markdown(
        f"""
        <div style="display:flex;align-items:center;gap:12px;padding:10px;border-radius:14px;border:1px solid #ddd;">
            <div style="width:16px;height:16px;border-radius:50%;background:{color};box-shadow:0 0 12px {color};"></div>
            <div>
                <div style="font-weight:700">{title}</div>
                <div style="font-size:12px;opacity:.7">{subtitle}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

# -----------------------------
# Step 2-1：抓 TAIFEX 即時 TXF
# 來源：mis.taifex.com.tw
# -----------------------------
@st.cache_data(ttl=15)
def fetch_txf_realtime():
    """
    盡量抓 'TXF 近月' 即時行情。
    若網站回應格式有變，會回傳 None，介面不會掛掉。
    """
    url = "https://mis.taifex.com.tw/futures/api/quote"
    # 這裡使用常見查詢參數；若之後要更精準，我們再微調
    params = {"symbol": "TXF"}  # 先用 TXF 總代號抓，後續可改近月合約代碼
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()

        # 嘗試找出最接近「近月」的一筆
        # 不同時間/不同回傳格式可能會不同，所以採保守寫法
        items = None
        if isinstance(data, dict):
            # 常見 key
            for k in ["data", "result", "quotes", "items"]:
                if k in data and isinstance(data[k], list):
                    items = data[k]
                    break

        if not items:
            return None

        # 取第一筆當作 demo（下一步我們會做「近月判斷」）
        q = items[0] if items else None
        if not isinstance(q, dict):
            return None

        # 盡可能取出欄位（沒有就 None）
        last = q.get("last") or q.get("LastPrice") or q.get("lastPrice")
        chg = q.get("chg") or q.get("Change") or q.get("change")
        vol = q.get("vol") or q.get("Volume") or q.get("volume")
        symbol = q.get("symbol") or q.get("Symbol") or q.get("contract") or "TXF"

        # 轉成可用型別（失敗就保持 None）
        def to_float(x):
            try:
                return float(str(x).replace(",", ""))
            except:
                return None

        def to_int(x):
            try:
                return int(float(str(x).replace(",", "")))
            except:
                return None

        return {
            "symbol": symbol,
            "last": to_float(last),
            "chg": to_float(chg),
            "vol": to_int(vol),
            "ts": datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M:%S"),
            "raw": q
        }
    except:
        return None

# -----------------------------
# 簡易決策（先用 TXF 漲跌做 demo）
# 下一階段會加：PCR / IV / OI / 金流 / 台積
# -----------------------------
def simple_score(txf):
    if not txf or txf["last"] is None or txf["chg"] is None:
        return {"direction": "未知", "final_score": 0.0, "align": 0.55, "risk": 50}

    # Demo：漲 → 偏多、跌 → 偏空，並給一個簡單分數
    chg = txf["chg"]
    direction = "偏多" if chg > 0 else "偏空" if chg < 0 else "中性"

    # 分數（demo）：用漲跌幅度粗估，限制在 -3~+3
    score = max(-3.0, min(3.0, round(chg / 100.0, 2)))

    # 一致性與風險（demo）：先給可跑的數值
    align = 0.65 if abs(chg) > 30 else 0.58
    risk = 35 if abs(chg) < 80 else 55

    return {"direction": direction, "final_score": score, "align": align, "risk": risk}

# ======================
# UI
# ======================
st.title("📊 台指期貨 / 選擇權 AI 儀表板（第二階段：真實資料接入中）")

txf = fetch_txf_realtime()
sig = simple_score(txf)

# 燈號邏輯
align = sig["align"]
risk_score = sig["risk"]

if align > 0.72:
    a_color, a_label = "green", "一致性高"
elif align > 0.6:
    a_color, a_label = "orange", "一致性中"
else:
    a_color, a_label = "red", "一致性低"

if risk_score > 55:
    r_color, r_label = "red", "高風險"
elif risk_score > 30:
    r_color, r_label = "orange", "中風險"
else:
    r_color, r_label = "green", "低風險"

k1,k2,k3,k4,k5,k6 = st.columns(6)

k1.metric("方向", sig["direction"])
k2.metric("Final Score", sig["final_score"])

with k3:
    render_light(a_color, f"一致性 {align*100:.0f}%", a_label)
with k4:
    render_light(r_color, f"風險 {risk_score}/100", r_label)

# 先把 TXF 真實數據放進 KPI（PCR/IV 下一步加）
if txf and txf["last"] is not None:
    k5.metric("TXF 即時價", f'{txf["last"]:.0f}', delta=None)
else:
    k5.metric("TXF 即時價", "—")

if txf and txf["chg"] is not None:
    k6.metric("TXF 漲跌", f'{txf["chg"]:+.0f}', delta=None)
else:
    k6.metric("TXF 漲跌", "—")

st.caption(f"更新時間：{txf['ts'] if txf else '無法取得（請稍後再試）'}")

st.divider()

m1,m2,m3,m4 = st.columns(4)
m1.info("IV / Skew 模組（下一步接 TXO）")
m2.info("Term Spread 模組（下一步做近月/次月）")
m3.info("Breadth 模組（下一步接現貨金流/漲跌家數）")
m4.info("Alert / 結算模組（下一步加結算日與警報）")

st.divider()

tab1,tab2,tab3,tab4 = st.tabs(["期貨 TXF","選擇權 TXO","台積&金流","分數拆解"])

with tab1:
    st.subheader("TXF 即時資料（真實）")
    if not txf:
        st.warning("目前無法取得 TAIFEX 即時資料（可能是網站暫時限制或格式變動）。下一步我會幫你做更穩定的抓取方式。")
    else:
        df = pd.DataFrame([{
            "symbol": txf["symbol"],
            "last": txf["last"],
            "chg": txf["chg"],
            "vol": txf["vol"],
            "time": txf["ts"]
        }])
        st.dataframe(df, use_container_width=True)
        with st.expander("原始回傳資料（debug）"):
            st.json(txf["raw"])

with tab2:
    st.subheader("TXO（下一步）")
    st.write("下一步我們會加入：Put/Call OI、Volume PCR、ATM IV、Skew。")

with tab3:
    st.subheader("台積電 + 現貨金流（下一步）")
    st.write("下一步會加：台積電現貨/期貨、外資買賣超、台股漲跌家數/成交值等。")

with tab4:
    st.subheader("分數拆解（下一步）")
    st.write("下一步會把 v7 各模組分數拆開顯示，並驅動雙燈號。")

st.success("✅ 第二階段 Step 2-1 完成：已嘗試接入 TXF 真實即時資料（可在 TXF 分頁查看）")
