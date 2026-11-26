"""校园活动与实践管理平台入口：侧边栏当前用户、首页、页面导航。"""
import streamlit as st

from services.auth import list_users

st.set_page_config(page_title="校园活动与实践管理平台", page_icon="🎓", layout="wide")

st.title("校园活动与实践管理平台")
st.caption("AI 协同开发课程设计 · 演示版本")

# 侧边栏：当前用户下拉框（模拟不同角色登录，不做真实账号密码）
with st.sidebar:
    st.header("当前用户")
    users = list_users()
    options = {"%s（%s）" % (u["username"], u["role"]): u for u in users}
    labels = ["— 请选择 —"] + list(options.keys())
    chosen = st.selectbox("选择登录身份", labels, index=0)
    if chosen == "— 请选择 —":
        st.session_state["current_user"] = None
        st.info("请选择一个身份以访问各功能页面。")
    else:
        st.session_state["current_user"] = options[chosen]
        u = options[chosen]
        role_cn = {"student": "学生", "organizer": "活动组织者", "admin": "管理员"}
        st.success("当前身份：%s（%s）" % (u["username"], role_cn.get(u["role"], u["role"])))
    st.markdown("---")
    st.markdown("**角色说明**")
    st.markdown("- 学生：浏览报名、提交反馈、查看本人成绩与提问")
    st.markdown("- 组织者：维护本人活动、登记到场与任务、导入数据、查看统计")
    st.markdown("- 管理员：管理全部活动与场地、运行工作流、查看日志")

user = st.session_state.get("current_user")
if user is None:
    st.info("👈 请在左侧选择一个登录身份，然后访问功能页面。")
else:
    st.subheader("欢迎使用")
    st.write(
        "本平台覆盖活动从发布到归档的全过程：活动管理、报名与成绩、数据导入、"
        "统计看板、预测分群、反馈问答、资料处理、自动化工作流与工具助手。"
    )
    st.markdown("请通过左侧 **页面导航** 进入各功能模块。")
