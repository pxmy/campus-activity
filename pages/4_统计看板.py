"""页面 4：活动统计看板。组织者只看自己活动，管理员看全部。

页面层只负责筛选输入和展示，指标计算全部在 services/stats.py 完成。
"""
import altair as alt
import pandas as pd
import streamlit as st

from services.auth import require_role
from services.db import get_conn
from services.stats import (activity_metrics, display_frame, export_frame,
                            filter_options, score_distribution, summary)

st.set_page_config(page_title="活动统计看板", layout="wide")
st.title("活动统计看板")
user = require_role("organizer", "admin")

conn = get_conn()
options = filter_options(conn)
conn.close()

with st.sidebar:
    st.header("筛选条件")
    date_from = st.date_input("开始日期（起）", value=None)
    date_to = st.date_input("开始日期（止）", value=None)
    category = st.selectbox("活动类别", ["全部"] + options["categories"])
    college = st.selectbox("学院", ["全部"] + options["colleges"])
    st.caption("筛选条件同时作用于指标卡片、对比图、成绩分布和明细表。")

filters = {}
if date_from:
    filters["date_from"] = date_from.isoformat()
if date_to:
    # 结束日期取当天 23:59:59，避免当天活动被排除
    filters["date_to"] = date_to.isoformat() + "T23:59:59"
if category != "全部":
    filters["category"] = category
if college != "全部":
    filters["college"] = college
if user["role"] == "organizer":
    filters["organizer_id"] = user["user_id"]

conn = get_conn()
df = activity_metrics(conn, filters)
dist = score_distribution(conn, filters)
conn.close()
s = summary(df)


def pct(v):
    return "—" if v is None or pd.isna(v) else "%.1f%%" % (v * 100)


c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("活动数", s["activities"])
c2.metric("报名人次", s["signed"])
c3.metric("汇总报名率", pct(s["signup_rate"]))
c4.metric("汇总到场率", pct(s["attendance_rate"]))
c5.metric("汇总完成率", pct(s["completion_rate"]))

st.subheader("各活动三项比率对比")
if not df.empty:
    long = df.melt(id_vars=["title"], value_vars=["signup_rate", "attendance_rate", "completion_rate"],
                   var_name="指标", value_name="比率")
    long["指标"] = long["指标"].map({"signup_rate": "报名率", "attendance_rate": "到场率",
                                  "completion_rate": "完成率"})
    chart = alt.Chart(long).mark_bar().encode(
        x=alt.X("title:N", title="活动"), y=alt.Y("比率:Q", axis=alt.Axis(format="%")),
        color="指标:N", column="指标:N").properties(width=220, height=250)
    st.altair_chart(chart, use_container_width=True)

    st.subheader("实践成绩分布（每 10 分一档，另设“未评定”一档）")
    st.bar_chart(dist.set_index("分数段"))

    st.subheader("明细表")
    show = display_frame(df)
    st.dataframe(show, use_container_width=True)

    st.subheader("导出当前筛选结果")
    st.caption("导出内容与上方明细表一致，CSV 使用带 BOM 的 UTF-8。")
    col_x, col_c = st.columns(2)
    if col_c.button("导出 CSV（带 BOM）"):
        p = export_frame(show, "outputs/统计明细.csv")
        with open(p, "rb") as f:
            st.download_button("下载 CSV", f.read(), "统计明细.csv")
    if col_x.button("导出 Excel"):
        p = export_frame(show, "outputs/统计明细.xlsx")
        with open(p, "rb") as f:
            st.download_button("下载 Excel", f.read(), "统计明细.xlsx")
else:
    st.info("当前筛选条件下没有数据。")
