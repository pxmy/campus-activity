"""页面 5：到场预测与活动分群。组织者/管理员可用。

页面层只负责输入与展示，预测、聚类和学生特征汇总都在 services/ml.py 完成。
"""
import pandas as pd
import streamlit as st

from services.auth import require_role
from services.db import get_conn
from services.ml import (WEEKDAY_CN, cluster_diagnostics, cluster_students,
                         evaluate, name_clusters, predict, student_features)

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
            st.caption("训练 %d 场、检验 %d 场，按开始时间先后切分。"
                       % (res["n_train"], res["n_test"]))
            st.caption("MAE 是平均每场预测差了多少人；预测是估计值，不是确定数字。")

            st.markdown("**回归系数（通俗解释）**")
            st.write("- 报名人数每多 1 人，预计到场多约 %.2f 人。" % res["coefs"]["signed"])
            st.write("- 晚间活动比非晚间预计多约 %.1f 人到场。" % res["coefs"]["is_evening"])
            st.caption("类别与星期已做独热编码，系数含义见 docs/模型说明.md。")

            st.subheader("预测一场新活动")
            cats = sorted(history["category"].unique())
            cat = st.selectbox("活动类别", cats)
            weekday_cn = st.selectbox("星期", list(WEEKDAY_CN.keys()))
            evening = st.checkbox("是否晚间")
            signed = st.number_input("当前报名人数", min_value=0, value=80)
            if st.button("预测"):
                p = predict(history, cat, weekday_cn, int(evening), int(signed))
                st.success("基线预测：%s 人 ｜ 回归预测：%s 人" % (p["baseline"], p["regression"]))
                st.caption("参考误差：基线 MAE %.2f 人、回归 MAE %.2f 人。"
                           % (res["baseline_mae"], res["regression_mae"]))
        else:
            st.error("历史数据缺少必要列。")
    else:
        st.info("请先准备历史活动数据。")

with tab_cluster:
    st.subheader("学生参与分群（仅展示群体，不评价个人）")
    conn = get_conn()
    feats, few = student_features(conn)
    conn.close()
    if feats.empty:
        st.info("暂无满足聚类条件的学生（需报名至少 2 次）。")
    else:
        st.write("学生共 %d 人：%d 人参与聚类，%d 人报名少于 2 次归为“参与较少”。"
                 % (len(feats) + len(few), len(feats), len(few)))
        st.caption("聚类前已对四个特征做标准化，固定随机种子；结果只反映群体，不用于评价个人。")

        st.markdown("**候选簇数对比（轮廓系数）**")
        diag = cluster_diagnostics(feats, ks=(3, 4, 5), seed=42)
        st.dataframe(pd.DataFrame([
            {"簇数": d["k"], "轮廓系数": d["silhouette"],
             "各簇人数": "、".join(str(n) for n in d["sizes"])} for d in diag
        ]), use_container_width=True)
        st.caption("轮廓系数越接近 1 分簇越清晰；最终簇数还要看每个簇能否起一个说得通的名字。")

        k = st.slider("选择簇数", 3, 5, 3)
        out, centers, sil = cluster_students(feats, k=k, seed=42)
        overall = feats[["signup_count", "attendance_rate", "avg_score", "category_count"]].mean()
        names, descriptions = name_clusters(centers, overall)

        st.markdown("**各簇名称、人数与描述**")
        summary_rows = []
        for cid in sorted(names):
            n = int((out["cluster"] == cid).sum())
            row = {"簇": names[cid], "人数": n}
            row.update(centers.loc[cid].round(2).to_dict())
            summary_rows.append(row)
        st.dataframe(pd.DataFrame(summary_rows).rename(columns={
            "signup_count": "平均报名次数", "attendance_rate": "平均到场率",
            "avg_score": "平均实践成绩", "category_count": "平均参与类别数"}),
            use_container_width=True)
        for cid in sorted(names):
            st.write("- **%s**：%s" % (names[cid], descriptions[cid]))

        st.write("各簇人数：")
        st.bar_chart(out["cluster"].value_counts().sort_index())
        st.info("本页只展示群体统计，不展示任何学生的个人分群结果。")
