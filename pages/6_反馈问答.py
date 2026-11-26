"""页面 6：反馈分析与知识问答。全部角色可用（带来源、未覆盖拒答）。"""
from pathlib import Path

import streamlit as st

from services.auth import current_user
from services.db import get_conn
from services.feedback import batch_classify, summarize, topic_distribution
from services.llm import LLMError, is_configured
from services.qa import answer, build_index

st.set_page_config(page_title="反馈与问答", layout="wide")
st.title("反馈分析与知识问答")

user = current_user()
if user is None:
    st.info("请先在左侧选择登录身份。")
    st.stop()

if not is_configured():
    st.warning("未配置 DEEPSEEK_API_KEY：智能功能暂不可用，但平台其他功能不受影响。")

tab_fb, tab_qa = st.tabs(["反馈主题与摘要", "资料问答（带来源）"])

with tab_fb:
    st.subheader("反馈主题分类与摘要")
    if user["role"] == "student":
        st.info("反馈分析仅对组织者和管理员开放。")
    else:
        conn = get_conn()
        acts = conn.execute("SELECT activity_id,title FROM activities ORDER BY activity_id").fetchall()
        conn.close()
        sel = st.selectbox("活动", ["%d - %s" % (a[0], a[1]) for a in acts])
        aid = int(sel.split(" - ")[0])
        if st.button("分类该活动反馈") and is_configured():
            conn = get_conn()
            try:
                res = batch_classify(conn, aid)
                st.success("成功分类 %d 条，失败 %d 条" % (
                    len(res["classified"]), len(res["failed"])))
                if res["failed"]:
                    st.write("失败样例：", res["failed"][:3])
            except LLMError as e:
                st.error(str(e))
            finally:
                conn.close()
        conn = get_conn()
        dist = topic_distribution(conn, aid)
        conn.close()
        if dist:
            st.write("**主题分布**")
            st.bar_chart(dist)
        if st.button("生成摘要") and is_configured():
            conn = get_conn()
            try:
                summ = summarize(conn, aid)
                if summ is None:
                    st.info("反馈少于 5 条，不生成摘要，请查看原文。")
                else:
                    for label, key in [("主要肯定", "main_praise"),
                                       ("主要问题", "main_problems"),
                                       ("改进建议", "suggestions")]:
                        st.markdown("**%s**" % label)
                        for item in summ[key]:
                            st.write("- " + item)
            except (LLMError, ValueError) as e:
                st.error(str(e))
            finally:
                conn.close()

with tab_qa:
    st.subheader("基于活动资料的问答")
    doc_dir = Path("data/docs")
    if "qa_index" not in st.session_state:
        st.session_state["qa_index"] = build_index(doc_dir)
    index, chunks = st.session_state["qa_index"]
    st.caption("已索引 %d 个资料片段" % len(chunks))
    q = st.text_input("输入问题，例如：实践学分认定的条件是什么？")
    if st.button("提问") and q:
        if not is_configured():
            st.warning("智能功能暂不可用。")
        else:
            try:
                res = answer(q, index, chunks)
                if res["answered"]:
                    st.markdown("**回答**")
                    st.write(res["text"])
                    st.markdown("**来源**")
                    for src in res["sources"]:
                        with st.expander("%s / %s（相似度 %.3f）" % (
                                src["file"], src["section"], src["score"])):
                            st.write(src["text"])
                else:
                    st.info(res["text"])
            except (LLMError, ValueError) as e:
                st.error(str(e))
