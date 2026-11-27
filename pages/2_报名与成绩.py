"""页面 2：报名与成绩（学生报名/取消/查成绩；组织者登记到场与任务）。"""
import streamlit as st

from services.activities import (ATT_CN, ATT_OPTIONS, ATT_REVERSE, STATUS_CN,
                                 activity_registrations, do_cancel_registration,
                                 do_register, list_activities, my_registrations,
                                 record_attendance)
from services.auth import current_user, require_role
from services.rules import RuleError, score_level

st.set_page_config(page_title="报名与成绩", layout="wide")
st.title("报名与成绩")

user = current_user()
if user is None:
    st.info("请先在左侧选择登录身份。")
    st.stop()

role = user["role"]
if role == "student":
    st.subheader("可报名的活动")
    acts = list_activities(role="student")
    for a in acts:
        with st.expander("%s（%s）" % (a["title"], STATUS_CN.get(a["status"], a["status"]))):
            st.write("时间：%s—%s ｜ 场地：%s ｜ 名额：%d" % (
                a["start_time"], a["end_time"], a["venue_name"], a["capacity"]))
            st.write(a["description"] or "")
            if a["status"] == "open":
                if st.button("报名", key="reg_%d" % a["activity_id"]):
                    try:
                        do_register(a["activity_id"], user["student_id"])
                        st.success("报名成功")
                        st.rerun()
                    except RuleError as e:
                        st.error(str(e))
            else:
                st.info("当前不在报名阶段")

    st.subheader("我的报名与成绩")
    for r in my_registrations(user["student_id"]):
        sc = r["practice_score"]
        st.write("- %s ｜ 到场：%s ｜ 成绩：%s ｜ 等级：%s" % (
            r["title"], ATT_CN.get(r["attendance"], "未登记"),
            "未评定" if sc is None else sc, score_level(sc)))
        if r["act_status"] == "open":
            if st.button("取消报名", key="cancel_%d" % r["activity_id"]):
                try:
                    do_cancel_registration(r["activity_id"], user["student_id"])
                    st.success("已取消报名")
                    st.rerun()
                except RuleError as e:
                    st.error(str(e))

elif role in ("organizer", "admin"):
    org_id = user["user_id"] if role == "organizer" else None
    acts = list_activities(organizer_id=org_id, role=role)
    st.subheader("选择活动登记成绩")
    if not acts:
        st.info("没有可管理的活动。")
        st.stop()
    sel = st.selectbox("活动", ["%d - %s" % (a["activity_id"], a["title"]) for a in acts])
    aid = int(sel.split(" - ")[0])
    rows = activity_registrations(aid)
    st.write("共 %d 条有效报名" % len(rows))
    for r in rows:
        sc = r["practice_score"]
        with st.expander("%s %s ｜ 当前成绩：%s" % (
                r["student_id"], r["name"], "未评定" if sc is None else sc)):
            att = st.selectbox(
                "到场情况", ATT_OPTIONS,
                index=ATT_OPTIONS.index(ATT_CN.get(r["attendance"], "未登记")),
                key="att_%d" % r["reg_id"])
            task = st.number_input("任务完成度（0-100，留空为未评定）", min_value=0, max_value=100,
                                   value=r["task_score"] if r["task_score"] is not None else 0,
                                   key="task_%d" % r["reg_id"])
            if st.button("保存登记", key="save_%d" % r["reg_id"]):
                try:
                    score, level = record_attendance(
                        r["reg_id"], ATT_REVERSE.get(att), int(task))
                    st.success("已保存，成绩：%s（%s）" % (
                        "未评定" if score is None else score, level))
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
else:
    st.info("当前角色无报名与成绩功能。")
