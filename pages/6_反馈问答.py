"""页面 6：反馈分析与知识问答。全部角色可用（带来源、未覆盖拒答）。

业务计算全部在 services 层；本页只负责展示与交互。
模型函数可通过 session_state 注入桩（离线测试/截图用），正常运行时走 services.llm。
"""
from pathlib import Path

import streamlit as st

from services.auth import current_user
from services.db import get_conn
from services.feedback import (batch_classify, classify_failure_count,
                               feedback_activities, raw_feedback,
                               representative_feedback, summarize,
                               topic_distribution)
from services.llm import LLMError, is_configured
from services.qa import answer, build_index

st.set_page_config(page_title="反馈与问答", layout="wide")
st.title("反馈分析与知识问答")

user = current_user()
if user is None:
    st.info("请先在左侧选择登录身份。")
    st.stop()

configured = is_configured() or st.session_state.get("_llm_stub") is True
if not configured:
    st.warning("未配置 DEEPSEEK_API_KEY：智能功能暂不可用，但平台其他功能不受影响。")

# 离线桩：由测试/截图脚本注入，正常用户不会设置
stub_json = st.session_state.get("_stub_chat_json")
stub_text = st.session_state.get("_stub_chat_text")

tab_fb, tab_qa = st.tabs(["反馈主题与摘要", "资料问答（带来源）"])

with tab_fb:
    st.subheader("反馈主题分类与摘要")
    if user["role"] == "student":
        st.info("反馈分析仅对组织者和管理员开放。")
    else:
        conn = get_conn()
        try:
            acts = feedback_activities(conn)
        finally:
            conn.close()
        if not acts:
            st.info("暂无反馈数据。")
        else:
            sel = st.selectbox("活动", ["%d - %s" % (aid, title) for aid, title in acts])
            aid = int(sel.split(" - ")[0])

            conn = get_conn()
            try:
                total = conn.execute(
                    "SELECT COUNT(*) FROM feedback WHERE activity_id=?", (aid,)
                ).fetchone()[0]
            finally:
                conn.close()
            st.caption("本场反馈 %d 条" % total)

            c1, c2 = st.columns(2)
            with c1:
                if st.button("试运行前 10 条") and configured:
                    conn = get_conn()
                    try:
                        res = batch_classify(conn, aid, llm_chat_json=stub_json, limit=10)
                        st.success("试运行：成功 %d 条，失败 %d 条（请人工核对下列结果）"
                                   % (len(res["classified"]), len(res["failed"])))
                        for fid, r in res["classified"][:10]:
                            st.write("- 反馈%d：%s / %s" % (
                                fid, "、".join(r["topics"]), r["sentiment"]))
                        for fid, err in res["failed"][:5]:
                            st.error("反馈%d 分类失败：%s" % (fid, err))
                    except LLMError as e:
                        st.error(str(e))
                    finally:
                        conn.close()
            with c2:
                if st.button("分类全部剩余反馈") and configured:
                    conn = get_conn()
                    try:
                        res = batch_classify(conn, aid, llm_chat_json=stub_json)
                        st.success("完成：成功 %d 条，失败 %d 条"
                                   % (len(res["classified"]), len(res["failed"])))
                        for fid, err in res["failed"][:5]:
                            st.error("反馈%d 分类失败：%s" % (fid, err))
                    except LLMError as e:
                        st.error(str(e))
                    finally:
                        conn.close()

            conn = get_conn()
            try:
                dist = topic_distribution(conn, aid)
                reps = representative_feedback(conn, aid, per_topic=2)
                failures = classify_failure_count(conn, aid)
            finally:
                conn.close()
            if failures:
                st.warning("有 %d 条反馈尚未成功分类（分类失败或小样本试运行未覆盖），未写入主题表。"
                           % failures)
            if dist:
                st.markdown("**主题分布**")
                st.bar_chart(dist)
                st.markdown("**各主题代表性反馈**")
                for topic, items in reps.items():
                    with st.expander("%s（%d 条）" % (topic, dist.get(topic, 0))):
                        for it in items:
                            st.write("- 「%s」　评分 %d／%s"
                                     % (it["content"], it["rating"], it["sentiment"]))
            elif total < 5:
                st.markdown("**反馈原文**（不足 5 条，不生成摘要）")
                conn = get_conn()
                try:
                    for r in raw_feedback(conn, aid):
                        st.write("- %s　评分 %d（%s）"
                                 % (r["content"], r["rating"], r["created_at"][:16]))
                finally:
                    conn.close()

            if st.button("生成摘要") and configured:
                conn = get_conn()
                try:
                    summ = summarize(conn, aid, llm_chat_text=stub_text)
                    if summ is None:
                        st.info("反馈少于 5 条，不生成摘要，已在上方展示原文。")
                    else:
                        st.markdown("**反馈摘要**（每条标注依据的反馈数量）")
                        for label, key in [("主要肯定", "main_praise"),
                                           ("主要问题", "main_problems"),
                                           ("改进建议", "suggestions")]:
                            st.markdown("**%s**" % label)
                            for item in summ[key]:
                                st.write("- " + item)
                except (LLMError, ValueError) as e:
                    st.error("智能功能暂不可用：" + str(e))
                finally:
                    conn.close()

with tab_qa:
    st.subheader("基于活动资料的问答")
    doc_dir = Path("data/docs")
    if "qa_index" not in st.session_state:
        st.session_state["qa_index"] = build_index(doc_dir)
    index, chunks = st.session_state["qa_index"]
    st.caption("已索引 %d 个资料片段（%d 份资料）"
               % (len(chunks), len({c["file"] for c in chunks})))
    q = st.text_input("输入问题，例如：实践学分认定的条件是什么？")
    if st.button("提问") and q:
        try:
            res = answer(q, index, chunks, llm_chat_text=stub_text)
        except (LLMError, ValueError) as e:
            st.error("智能功能暂不可用：" + str(e))
        else:
            if res["answered"]:
                st.markdown("**回答**")
                st.write(res["text"])
                st.markdown("**来源**（点击展开片段原文核对）")
                for i, src in enumerate(res["sources"], 1):
                    with st.expander("[%d] %s / %s（相似度 %.3f，覆盖率 %.2f）" % (
                            i, src["file"], src["section"],
                            src["score"], src["coverage"])):
                        st.write(src["text"])
            else:
                st.info(res["text"])
                if res.get("refused_by") == "model":
                    st.caption("程序检索到资料片段并调用了模型，模型判断片段不足以回答，未生成内容。")
                else:
                    st.caption("程序在调用模型前判定资料未覆盖，直接拒答，未生成内容。")
