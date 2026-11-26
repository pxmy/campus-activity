"""页面 5：到场预测与活动分群。组织者/管理员可用。"""
import pandas as pd
import streamlit as st

from services.auth import require_role
from services.db import get_conn
from services.ml import cluster_students, evaluate, predict

st.set_page_config(page_title="预测与分群", layout="wide")
st.title("到场预测与活动分群")
user = require_role("organizer", "admin")

hist_path = "data/raw/history_activities.csv"
try:
    history = pd.read_csv(hist_path)
except FileNotFoundError:
    st.warning("未找到历史活动数据（data/raw/history_activities.csv），预测功能不可用。")
    st.info("教师下发数据后放入该路径即可启用。")
    history = None

tab_pred, tab_cluster = st.tabs(["到场预测", "学生参与分群"])

with tab_pred:
    st.subheader("基线与回归对比")
    if history is not None:
        if {"category", "weekday", "is_evening", "signed", "arrived", "start_time"}.issubset(history.columns):
            res = evaluate(history)
            c1, c2, c3 = st.columns(3)
            c1.metric("基线 MAE", res["baseline_mae"])
            c2.metric("回归 MAE", res["regression_mae"])
            c3.metric("胜出", "基线" if res["winner"] == "baseline" else "回归")
            st.caption("检验集 %d 场；预测人数是估计值，不是确定数字。" % res["n_test"])
            st.markdown("**回归系数（通俗解释）**")
            for k, v in res["coefs"].items():
                st.write("- %s：%s" % (k, v))
            st.subheader("预测一场新活动")
            cats = sorted(history["category"].unique())
            cat = st.selectbox("活动类别", cats)
            weekday = st.selectbox("星期", ["周一", "周二", "周三", "周四", "周五", "周六", "周日"])
            evening = st.checkbox("是否晚间")
            signed = st.number_input("当前报名人数", min_value=0, value=50)
            if st.button("预测"):
                p = predict(history, cat, weekday, int(evening), int(signed))
                st.success("基线预测：%s 人 ｜ 回归预测：%s 人" % (p["baseline"], p["regression"]))
        else:
            st.error("历史数据缺少必要列。")
    else:
        st.info("请先准备历史活动数据。")

with tab_cluster:
    st.subheader("学生参与分群（仅展示群体，不评价个人）")
    conn = get_conn()
    rows = conn.execute(
        "SELECT r.student_id, COUNT(*) AS signup_count, "
        "COALESCE(SUM(r.attendance IN ('present','late'))*1.0/COUNT(*),0) AS attendance_rate, "
        "AVG(CASE WHEN r.practice_score IS NOT NULL THEN r.practice_score END) AS avg_score, "
        "COUNT(DISTINCT a.category) AS category_count "
        "FROM registrations r JOIN activities a ON r.activity_id=a.activity_id "
        "WHERE r.status='registered' GROUP BY r.student_id HAVING signup_count>=2"
    ).fetchall()
    conn.close()
    if not rows:
        st.info("暂无满足聚类条件的学生（需报名至少 2 次）。")
    else:
        feats = pd.DataFrame([dict(r) for r in rows])
        k = st.slider("簇数", 3, 5, 3)
        out, centers, sil = cluster_students(feats, k=k)
        if sil is not None:
            st.write("轮廓系数：%.3f" % sil)
        st.caption("各簇特征均值（用于给簇命名）：")
        st.dataframe(centers.round(2), use_container_width=True)
        st.write("各簇人数：")
        st.bar_chart(out["cluster"].value_counts().sort_index())
        st.info("本页只展示群体统计，不展示任何学生的个人分群结果。")
