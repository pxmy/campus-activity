"""页面 3：数据导入与文档生成。组织者/管理员可用。"""
from datetime import datetime
from pathlib import Path

import streamlit as st

from services.auth import require_role
from services.cleaning import clean_scores, count_unimported, read_csv_smart
from services.db import get_conn, get_conn_manual
from services.docgen import generate_proof, generate_roster

st.set_page_config(page_title="数据导入与文档生成", layout="wide")
st.title("数据导入与文档生成")
user = require_role("organizer", "admin")

tab_import, tab_doc = st.tabs(["清洗与导入", "生成名册与证明"])

with tab_import:
    st.subheader("导入成绩文件（signup_import / scores_import）")
    st.caption("原始数据只读不改；干净数据入库，问题数据进异常清单，一条不丢。")
    up = st.file_uploader("选择 CSV / Excel 文件", type=["csv", "xlsx"])
    if up is not None:
        tmp = Path("data/app") / ("upload_" + up.name)
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(up.getvalue())
        conn = get_conn()
        valid_acts = {str(r[0]) for r in conn.execute("SELECT activity_id FROM activities")}
        valid_stus = {str(r[0]) for r in conn.execute("SELECT student_id FROM students")}
        conn.close()
        try:
            clean, issues = clean_scores(tmp, valid_acts, valid_stus)
            read_n = len(read_csv_smart(tmp))
            c1, c2, c3 = st.columns(3)
            c1.metric("读取行数", read_n)
            c2.metric("可入库", len(clean))
            c3.metric("未入库异常", count_unimported(issues))
            st.write("**异常清单预览**")
            st.dataframe(issues, use_container_width=True)
            if st.button("确认写入数据库"):
                wconn = get_conn_manual()
                from services.rules import calc_practice_score
                for _, r in clean.iterrows():
                    wconn.execute(
                        "INSERT OR IGNORE INTO registrations "
                        "(activity_id,student_id,status,created_at,attendance,task_score,feedback_at,practice_score) "
                        "VALUES (?,?,'registered',?,?,?,?,?)",
                        (int(r["activity_id"]), r["student_id"], datetime.now().isoformat(timespec="seconds"),
                         r["attendance"], None if r["task_score"] is None else int(r["task_score"]),
                         r["feedback_at"], None))
                wconn.commit()
                wconn.close()
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                out = Path("outputs") / ("异常清单_%s.xlsx" % stamp)
                out.parent.mkdir(parents=True, exist_ok=True)
                issues.to_excel(out, index=False, engine="openpyxl")
                st.success("已写入 %d 条；异常清单：%s" % (len(clean), out))
        except ValueError as e:
            st.error(str(e))

with tab_doc:
    st.subheader("按模板生成名册与证明")
    conn = get_conn()
    acts = conn.execute("SELECT activity_id,title FROM activities ORDER BY activity_id").fetchall()
    conn.close()
    if not acts:
        st.info("请先创建活动。")
    else:
        sel = st.selectbox("活动", ["%d - %s" % (a[0], a[1]) for a in acts])
        aid = int(sel.split(" - ")[0])
        roster_tpl = st.text_input("名册模板路径", "templates/名册模板.docx")
        proof_tpl = st.text_input("证明模板路径", "templates/实践证明模板.docx")
        if st.button("生成名册"):
            try:
                conn = get_conn()
                p = generate_roster(conn, aid, roster_tpl, "outputs/名册_%d.docx" % aid)
                conn.close()
                st.success("已生成：" + p)
            except Exception as e:
                st.error(str(e))
        st.markdown("**批量生成证明（成绩合格及以上）**")
        conn = get_conn()
        rows = conn.execute(
            "SELECT student_id,practice_score FROM registrations WHERE activity_id=? "
            "AND status='registered' AND practice_score>=60", (aid,)).fetchall()
        conn.close()
        st.write("合格学生 %d 人" % len(rows))
        if st.button("生成全部证明"):
            import zipfile
            conn = get_conn()
            zpath = Path("outputs") / ("证明_%d.zip" % aid)
            zpath.parent.mkdir(parents=True, exist_ok=True)
            ok = 0
            with zipfile.ZipFile(zpath, "w") as z:
                for seq, r in enumerate(rows, 1):
                    try:
                        p = generate_proof(conn, aid, r[0], proof_tpl,
                                           "outputs/证明_%d_%s.docx" % (aid, r[0]), seq)
                        z.write(p, arcname=Path(p).name)
                        ok += 1
                    except Exception:
                        pass
            conn.close()
            st.success("已生成 %d 份证明：%s" % (ok, zpath))
