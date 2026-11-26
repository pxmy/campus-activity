"""页面 7：图像、语音与多模态资料处理。识别结果须人工确认才入库。"""
import os
from pathlib import Path

import streamlit as st

from services.auth import require_role
from services.db import get_conn, get_conn_manual
from services.llm import LLMError, is_configured
from services.media import (check_rows, extract_signin, extract_todos,
                            is_late, split_wav, transcribe)

st.set_page_config(page_title="资料处理", layout="wide")
st.title("图像、语音与多模态资料处理")
user = require_role("organizer", "admin")

if not is_configured():
    st.warning("未配置密钥：识别功能暂不可用。")

tab_signin, tab_audio = st.tabs(["签到表识别与核对", "会议录音转写与待办"])

with tab_signin:
    st.subheader("签到表核对（原图对照 + 人工修正）")
    conn = get_conn()
    acts = conn.execute("SELECT activity_id,title,start_time FROM activities ORDER BY activity_id").fetchall()
    conn.close()
    sel = st.selectbox("关联活动", ["%d - %s" % (a[0], a[1]) for a in acts])
    aid = int(sel.split(" - ")[0])
    start_time = next(a[2] for a in acts if a[0] == aid)
    up = st.file_uploader("上传签到表图片", type=["jpg", "jpeg", "png"])
    if up is not None:
        img_path = Path("data/app") / ("signin_" + up.name)
        img_path.parent.mkdir(parents=True, exist_ok=True)
        img_path.write_bytes(up.getvalue())
        if "signin_rows" not in st.session_state or st.button("重新识别"):
            if is_configured():
                try:
                    data = extract_signin(str(img_path))
                    conn = get_conn()
                    st.session_state["signin_rows"] = check_rows(conn, aid, data["rows"])
                    conn.close()
                except (LLMError, ValueError) as e:
                    st.error(str(e))
        if "signin_rows" in st.session_state:
            col1, col2 = st.columns([1, 2])
            with col1:
                st.image(str(img_path), use_container_width=True)
            with col2:
                rows = st.session_state["signin_rows"]
                st.caption("有问题的行已排在前面（状态非“正常”）")
                df = st.data_editor(rows, use_container_width=True, num_rows="dynamic")
                if st.button("确认写入到场情况"):
                    conn = get_conn()
                    rechecked = check_rows(conn, aid, df)
                    bad = [r for r in rechecked if r.get("status") != "正常"]
                    if bad:
                        st.error("仍有 %d 行存在问题，未写入" % len(bad))
                    else:
                        wconn = get_conn_manual()
                        for r in df:
                            t = str(r.get("sign_time", "")).strip()
                            late = is_late(t, start_time)
                            att = None if late is None else ("late" if late else "present")
                            wconn.execute(
                                "UPDATE registrations SET attendance=? WHERE activity_id=? "
                                "AND student_id=? AND status='registered'",
                                (att, aid, r.get("student_id")))
                        # 比较识别值与人工确认值，逐条记录修正
                        originals = {id(x): x for x in rows}
                        orig = originals.get(id(r), {})
                        for f in ["student_id", "name", "sign_time"]:
                            raw_v, new_v = str(orig.get(f, "")), str(r.get(f, ""))
                            if raw_v != new_v:
                                wconn.execute(
                                    "INSERT INTO corrections (activity_id,row_no,field,"
                                    "raw_value,corrected,corrected_by,ts) "
                                    "VALUES (?,?,?,?,?,?,datetime('now'))",
                                    (aid, r.get("seq", 0), f, raw_v, new_v, user["username"]))
                        wconn.commit()
                        wconn.close()
                        st.success("已写入到场情况")
                    conn.close()

with tab_audio:
    st.subheader("会议录音转写与待办提取")
    st.caption("接口限制：单次 ≤120 秒、16 位 PCM WAV、≤8MiB。长录音自动切分。")
    up2 = st.file_uploader("上传会议录音（WAV）", type=["wav"])
    if up2 is not None:
        wav_path = Path("data/app") / ("meeting_" + up2.name)
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        wav_path.write_bytes(up2.getvalue())
        if st.button("切分并转写") and is_configured():
            try:
                parts = split_wav(str(wav_path), "data/app/asr_parts")
                key = os.getenv("DEEPSEEK_API_KEY")
                texts = []
                for i, part in enumerate(parts):
                    try:
                        texts.append(transcribe(part, key))
                        st.write("片段 %d/%d 转写成功" % (i + 1, len(parts)))
                    except Exception as e:
                        st.warning("片段 %d 转写失败：%s（可单独重试）" % (i + 1, e))
                transcript = "\n".join(texts)
                st.session_state["transcript"] = transcript
            except ValueError as e:
                st.error(str(e))
    if st.session_state.get("transcript"):
        edited = st.text_area("转写稿（可修正人名、活动名后用于摘要）",
                              st.session_state["transcript"], height=200)
        if st.button("提取摘要与待办") and is_configured():
            try:
                data = extract_todos(edited)
                st.markdown("**会议主题**：" + data["topic"])
                st.write("**讨论要点**：", "；".join(data["points"]))
                st.write("**形成的决定**：", "；".join(data["decisions"]))
                st.markdown("**待办事项**")
                for t in data["todos"]:
                    with st.expander("%s ｜ 负责人：%s ｜ 截止：%s" % (
                            t["task"], t["owner"], t["deadline"])):
                        st.write("原句：" + t["quote"])
            except (LLMError, ValueError) as e:
                st.error(str(e))
