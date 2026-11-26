"""页面 1：活动管理（新建、修改、取消、状态变更）。组织者/管理员可用。"""
from datetime import datetime, timedelta

import streamlit as st

from services.activities import (STATUS_CN, change_status, get_activity,
                                 list_activities, list_venues, save_activity)
from services.auth import require_role
from services.rules import RuleError

st.set_page_config(page_title="活动管理", layout="wide")
st.title("活动管理")

user = require_role("organizer", "admin")

acts = list_activities(organizer_id=user["user_id"] if user["role"] == "organizer" else None,
                       role=user["role"])
venues = {v["name"]: v for v in list_venues()}
categories = ["讲座", "竞赛", "志愿服务", "文体", "实践"]

tab_list, tab_new = st.tabs(["活动列表", "新建 / 编辑活动"])

with tab_list:
    st.subheader("活动列表")
    for a in acts:
        with st.expander("%s  |  %s  |  %s  |  %s" % (
                a["title"], STATUS_CN.get(a["status"], a["status"]),
                a["venue_name"], a["start_time"])):
            st.write("类别：%s ｜ 名额：%d ｜ 报名截止：%s" % (
                a["category"], a["capacity"], a["signup_deadline"]))
            st.write("描述：%s" % (a["description"] or "（无）"))
            st.markdown("**状态变更**")
            cols = st.columns(len(STATUS_CN))
            for i, (code, label) in enumerate(STATUS_CN.items()):
                if cols[i].button(label, key="st_%d_%s" % (a["activity_id"], code),
                                  disabled=(code == a["status"])):
                    try:
                        change_status(a["activity_id"], code)
                        st.success("状态已更新为“%s”" % label)
                        st.rerun()
                    except RuleError as e:
                        st.error(str(e))

with tab_new:
    st.subheader("新建 / 编辑活动")
    editable = [a for a in acts if a["organizer_id"] == user["user_id"]] \
        if user["role"] == "organizer" else acts
    edit_id = st.selectbox("选择要编辑的活动（新建请选第一个）",
                           ["— 新建活动 —"] + ["%d - %s" % (a["activity_id"], a["title"])
                                           for a in editable])
    editing = None
    if edit_id != "— 新建活动 —":
        editing = get_activity(int(edit_id.split(" - ")[0]))
    base = datetime.now() + timedelta(days=3)
    title = st.text_input("活动标题", value=editing["title"] if editing else "")
    category = st.selectbox("类别", categories,
                            index=categories.index(editing["category"]) if editing else 0)
    venue_name = st.selectbox("场地", list(venues.keys()),
                              index=list(venues.keys()).index(editing["venue_name"])
                              if editing and editing["venue_name"] in venues else 0)
    col1, col2 = st.columns(2)
    start = col1.datetime_input("开始时间",
                                value=datetime.fromisoformat(editing["start_time"])
                                if editing else base)
    end = col2.datetime_input("结束时间",
                              value=datetime.fromisoformat(editing["end_time"])
                              if editing else base + timedelta(hours=2))
    deadline = st.datetime_input("报名截止时间",
                                 value=datetime.fromisoformat(editing["signup_deadline"])
                                 if editing else base - timedelta(days=1))
    cap = st.number_input("名额", min_value=1, max_value=venues[venue_name]["capacity"],
                          value=editing["capacity"] if editing else 30)
    desc = st.text_area("描述", value=editing["description"] if editing else "")
    if st.button("保存活动"):
        data = {
            "title": title, "category": category, "venue_id": venues[venue_name]["venue_id"],
            "start_time": start.isoformat(timespec="minutes"),
            "end_time": end.isoformat(timespec="minutes"),
            "signup_deadline": deadline.isoformat(timespec="minutes"),
            "capacity": int(cap), "description": desc,
        }
        if editing:
            data["activity_id"] = editing["activity_id"]
        try:
            save_activity(data, user)
            st.success("活动已保存" + ("（新建为草稿，请到列表发布）" if not editing else ""))
            st.rerun()
        except RuleError as e:
            st.error(str(e))
