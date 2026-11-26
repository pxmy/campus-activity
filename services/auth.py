"""用户与权限：当前用户、角色校验、数据归属校验。

页面层只负责展示；真正的权限拦截必须落在业务函数中（单元 9 审查重点）。
"""
import streamlit as st

from services.db import get_conn


def list_users():
    """返回全部用户，供侧边栏“当前用户”下拉框使用。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT u.user_id, u.username, u.role, u.student_id "
            "FROM users u ORDER BY u.role, u.user_id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def current_user():
    """返回 st.session_state 中保存的当前用户字典；未选择时返回 None。"""
    return st.session_state.get("current_user")


def require_role(*roles):
    """在当前页面校验角色：不符则在页面显示“无权访问”并停止渲染。

    用法：require_role("organizer", "admin")
    """
    user = current_user()
    if user is None or user["role"] not in roles:
        st.error("无权访问：当前角色不具备该页面的访问权限。")
        st.stop()
    return user


def can_manage_activity(user, activity):
    """数据归属校验：管理员可管理全部活动；组织者只能管理自己发布的活动。"""
    if user is None:
        return False
    if user["role"] == "admin":
        return True
    if user["role"] == "organizer":
        return activity["organizer_id"] == user["user_id"]
    return False
