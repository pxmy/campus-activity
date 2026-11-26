"""页面 8：自动化工作流与工具调用助手。"""
import streamlit as st

from services.auth import current_user, require_role
from services.db import get_conn
from services.llm import LLMError, get_client, is_configured
from services.tools import run_assistant
from services.workflow import run_workflow

st.set_page_config(page_title="工作流与助手", layout="wide")
st.title("自动化工作流与工具调用助手")

user = current_user()
if user is None:
    st.info("请先在左侧选择登录身份。")
    st.stop()

tab_wf, tab_asst = st.tabs(["周报工作流（管理员）", "工具调用助手"])

with tab_wf:
    if user["role"] != "admin":
        st.info("周报工作流仅管理员可用。")
    else:
        st.subheader("一键生成活动周报：统计—摘要—报告—归档")
        week = st.text_input("周次标签", "2026-W48")
        if st.button("运行工作流"):
            conn = get_conn()
            res = run_workflow(conn, week)
            conn.close()
            st.write("结果：", "成功" if res["all_ok"] else "失败")
            for step in res["steps"]:
                st.write("- %s：%s%s" % (
                    step["step"],
                    "成功" if step.get("ok") else "失败（%s）" % step.get("error", ""),
                    "（已降级）" if step.get("degraded") else ""))
        conn = get_conn()
        runs = conn.execute("SELECT * FROM workflow_runs ORDER BY run_id DESC LIMIT 10").fetchall()
        conn.close()
        if runs:
            st.subheader("历史运行记录")
            for r in runs:
                st.write("%s ｜ %s ｜ %s" % (
                    r["ts"], r["week"], "成功" if r["all_ok"] else "失败"))

with tab_asst:
    st.subheader("自然语言查询助手（只读工具）")
    if not is_configured():
        st.warning("未配置密钥：助手暂不可用。")
    else:
        q = st.text_input("提问，例如：有哪些报名中的活动？")
        if st.button("提问") and q:
            try:
                conn = get_conn()
                resp = run_assistant(get_client(), conn, user, q)
                conn.close()
                st.write(resp)
            except (LLMError, Exception) as e:
                st.error("助手调用失败：" + str(e))
