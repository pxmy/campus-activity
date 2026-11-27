"""页面 7：图像、语音与多模态资料处理。识别结果须人工确认才入库。

本页只负责交互与展示；全部业务计算在 services.media，页面不写 SQL。
模型函数可通过 session_state 注入桩（离线测试/截图用）。
"""
import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from services.auth import require_role
from services.db import get_conn, get_conn_manual
from services.llm import LLMError, is_configured
from services.media import (activity_start, apply_signin, check_rows,
                            export_corrections, extract_field_errors,
                            extract_signin, extract_todos, join_transcript,
                            locate_quote, signin_activities, split_wav,
                            transcript_body, transcribe, validate_wav)

st.set_page_config(page_title="资料处理", layout="wide")
st.title("图像、语音与多模态资料处理")
user = require_role("organizer", "admin")

if not is_configured() and st.session_state.get("_llm_stub") is not True:
    st.warning("未配置密钥：识别功能暂不可用。")

# 离线桩：测试/截图脚本注入，正常用户不会设置
stub_image = st.session_state.get("_stub_extract_signin")
stub_todos = st.session_state.get("_stub_extract_todos")
stub_transcribe = st.session_state.get("_stub_transcribe")

tab_signin, tab_audio = st.tabs(["签到表识别与核对", "会议录音转写与待办"])

with tab_signin:
    st.subheader("签到表核对（原图对照 + 人工修正）")
    conn = get_conn()
    try:
        acts = signin_activities(conn)
    finally:
        conn.close()
    sel = st.selectbox("关联活动", ["%d - %s" % (a["activity_id"], a["title"]) for a in acts])
    aid = int(sel.split(" - ")[0])
    start = activity_start(get_conn(), aid)
    up = st.file_uploader("上传签到表图片", type=["jpg", "jpeg", "png"])

    if up is not None:
        img_path = Path("outputs/uploads") / ("signin_" + up.name)
        img_path.parent.mkdir(parents=True, exist_ok=True)
        img_path.write_bytes(up.getvalue())
        if "signin_rows" not in st.session_state or st.button("重新识别"):
            try:
                if stub_image:
                    data = stub_image(str(img_path))
                else:
                    data = extract_signin(str(img_path))
                conn = get_conn()
                try:
                    rows = check_rows(conn, aid, data.get("rows", []),
                                      expected_count=data.get("expected_rows"))
                finally:
                    conn.close()
                # 原始识别值快照：按 seq 保存，用于修正记录比对
                st.session_state["signin_raw"] = {
                    r.get("seq"): dict(r) for r in rows}
                st.session_state["signin_rows"] = rows
                st.session_state["signin_img"] = str(img_path)
            except (LLMError, ValueError) as e:
                st.error(str(e))

    if "signin_rows" in st.session_state:
        col1, col2 = st.columns([1, 2])
        with col1:
            st.image(st.session_state["signin_img"], use_container_width=True)
        with col2:
            rows = st.session_state["signin_rows"]
            errs = extract_field_errors(rows)
            if errs:
                st.warning("有问题的行 %d 行：%s" %
                           (sum(errs.values()),
                            "、".join("%s %d" % (k, v) for k, v in errs.items())))
            else:
                st.success("识别结果暂未发现问题，仍需人工对照原图确认。")
            st.caption("异常行已排在前面；对照原图修改后点击确认才会入库。")
            editable = [dict(r) for r in rows]  # 保留 status 列，异常行一眼可见
            df = st.data_editor(
                editable, use_container_width=True, num_rows="dynamic",
                key="signin_editor",
                column_config={"status": st.column_config.TextColumn(
                    "核对状态", disabled=True, help="程序自动标注，异常行已排前")})
            if st.button("确认写入到场情况"):
                raw_snapshot = st.session_state["signin_raw"]
                raw_rows = list(raw_snapshot.values())
                conn = get_conn()
                try:
                    rechecked = check_rows(conn, aid, df)
                finally:
                    conn.close()
                bad = [r for r in rechecked if r.get("status") != "正常"]
                if bad:
                    st.error("仍有 %d 行存在问题，未写入" % len(bad))
                else:
                    wconn = get_conn_manual()
                    try:
                        result = apply_signin(wconn, aid, df, raw_rows, start,
                                              user["username"])
                        wconn.commit()
                    finally:
                        wconn.close()
                    st.success("已写入 %d 条到场记录，记录人工修正 %d 处。"
                               % (result["written"], result["corrections"]))
                    st.caption("迟到由程序按开始时间判定，不由模型判断。")

with tab_audio:
    st.subheader("会议录音转写与待办提取")
    st.caption("接口限制：单次 ≤120 秒、16 位 PCM 单声道 WAV、≤8 MiB。长录音自动切分。")
    up2 = st.file_uploader("上传会议录音（WAV）", type=["wav"])
    if up2 is not None:
        wav_path = Path("outputs/uploads") / ("meeting_" + up2.name)
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        wav_path.write_bytes(up2.getvalue())
        st.session_state["wav_path"] = str(wav_path)
        if st.button("切分并转写"):
            try:
                info = validate_wav(str(wav_path))
                parts = split_wav(str(wav_path), "outputs/uploads/asr_parts")
                key = os.getenv("DEEPSEEK_API_KEY", "")
                for p in parts:
                    try:
                        if stub_transcribe:
                            p["text"] = stub_transcribe(p)
                        else:
                            p["text"] = transcribe(p["path"], key)
                        p["error"] = ""
                    except Exception as e:
                        p["text"] = ""
                        p["error"] = str(e)
                st.session_state["asr_parts"] = parts
                st.caption("录音 %.1f 秒，切为 %d 段：%s" %
                           (info["duration"], len(parts),
                            "、".join("%.0f-%.0fs" % (p["start"], p["end"]) for p in parts)))
            except ValueError as e:
                st.error(str(e))

    parts = st.session_state.get("asr_parts")
    if parts:
        st.markdown("**转写稿（含片段边界标记）**")
        st.text_area("片段边界即固定时长切分点，通读时检查断点处是否有断句错误",
                     join_transcript(parts), height=180, disabled=True)
        failed = [p for p in parts if p.get("error")]
        if failed:
            st.warning("有 %d 段转写失败，可单独重试（已完成的片段会保留）" % len(failed))
            for p in failed:
                if st.button("重试片段 %d（%.0f-%.0fs）" %
                             (p["index"], p["start"], p["end"])):
                    try:
                        key = os.getenv("DEEPSEEK_API_KEY", "")
                        p["text"] = (stub_transcribe(p) if stub_transcribe
                                     else transcribe(p["path"], key))
                        p["error"] = ""
                        st.success("片段 %d 重试成功" % p["index"])
                    except Exception as e:
                        p["error"] = str(e)
                        st.error("片段 %d 仍失败：%s" % (p["index"], e))
        body = transcript_body(parts)
        edited = st.text_area("转写稿（可修正人名、活动名后用于摘要）",
                              body, height=220)
        if st.button("提取摘要与待办"):
            try:
                data = (stub_todos(edited) if stub_todos
                        else extract_todos(edited))
                st.session_state["meeting_summary"] = data
                st.session_state["meeting_transcript"] = edited
            except (LLMError, ValueError) as e:
                st.error(str(e))

    data = st.session_state.get("meeting_summary")
    if data:
        st.markdown("**会议主题**：" + str(data.get("topic", "")))
        st.write("**讨论要点**：", "；".join(data.get("points", [])))
        st.write("**形成的决定**：", "；".join(data.get("decisions", [])))
        todos = data.get("todos", [])
        st.markdown("**待办事项**（点击行展开转写稿原句，核对后确认保存）")
        table = pd.DataFrame([{
            "事项": t["task"], "负责人": t["owner"], "截止时间": t["deadline"],
            "原句定位": locate_quote(st.session_state["meeting_transcript"],
                                  t.get("quote", "")),
        } for t in todos])
        st.dataframe(table, use_container_width=True)
        for i, t in enumerate(todos):
            with st.expander("[%d] %s ｜ 负责人：%s ｜ 截止：%s" %
                             (i + 1, t["task"], t["owner"], t["deadline"])):
                st.write("转写稿原句：" + t.get("quote", ""))
                st.caption("未在转写稿中明确的负责人/时间填“未明确”，不由模型补全。")
        if st.button("确认并保存待办"):
            path = Path("outputs") / "会议待办_已确认.json"
            path.parent.mkdir(exist_ok=True)
            path.write_text(json.dumps({
                "transcript": st.session_state["meeting_transcript"],
                "summary": data, "confirmed_by": user["username"],
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            st.success("已保存：" + str(path))

