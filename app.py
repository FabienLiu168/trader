import streamlit as st
import random

# ======================
# Page config
# ======================

st.set_page_config(page_title="台指交易儀表板 v7", layout="wide")

# ======================
# Fake demo signals (之後會換成真實資料)
# ======================

final_score = round(random.uniform(-3, 3), 2)
alignment = random.uniform(0.5, 0.9)
risk_score = random.randint(10, 70)

direction = "偏多" if final_score > 0 else "偏空"

# ----------------------
# Alignment Light
# ----------------------

if alignment > 0.72:
    a_color = "green"
    a_label = "一致性高"
elif alignment > 0.6:
    a_color = "orange"
    a_label = "一致性中"
else:
    a_color = "red"
    a_label = "一致性低"

# ----------------------
# Risk Light
# ----------------------

if risk_score > 55:
    r_color = "red"
    r_label = "高風險"
elif risk_score > 30:
    r_color = "orange"
    r_label = "中風險"
else:
    r_color = "green"
    r_label = "低風險"

# ======================
# Render light function
# ======================

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

# ======================
# UI
# ======================

st.title("📊 台指期貨 / 選擇權 AI 儀表板")

k1,k2,k3,k4,k5,k6 = st.columns(6)

k1.metric("方向", direction)
k2.metric("Final Score", final_score)

with k3:
    render_light(a_color, f"一致性 {alignment*100:.0f}%", a_label)

with k4:
    render_light(r_color, f"風險 {risk_score}/100", r_label)

k5.metric("ATM IV", f"{random.randint(15,25)}%")
k6.metric("PCR", round(random.uniform(0.8,1.2),2))

st.divider()

m1,m2,m3,m4 = st.columns(4)

m1.info("IV / Skew 模組")
m2.info("Term Spread 模組")
m3.info("Breadth 模組")
m4.info("Alert / 結算模組")

st.divider()

tab1,tab2,tab3,tab4 = st.tabs(["期貨 TXF","選擇權 TXO","台積&金流","分數拆解"])

with tab1:
    st.write("TXF 日盤 / 夜盤 / OI / Volume")

with tab2:
    st.write("PCR / OI牆 / IV 結構")

with tab3:
    st.write("台積電現貨 / 股期 / 外資")

with tab4:
    st.write("每個模組分數與昨日變化")

st.success("第一階段 UI 建立完成（目前為模擬數據）")
