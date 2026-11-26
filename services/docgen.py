"""办公文档生成：按 Word 模板填充生成名册与实践证明。

文档内容由模板加数据库数据生成，不交给大模型撰写。
"""
import re
import zipfile
from datetime import datetime
from pathlib import Path

from docx import Document

from services.rules import score_level


def _iter_paragraphs(doc):
    """遍历文档正文所有段落（含表格单元格内的段落）。"""
    for p in doc.paragraphs:
        yield p
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    yield p


def replace_placeholders(doc, mapping):
    """把模板中的 {{key}} 占位符替换为实际值。

    Word 可能把一个占位符拆到多个 run，先在段落级拼接文本再整体替换，
    避免逐 run 替换失败。返回替换后的文档。
    """
    for p in _iter_paragraphs(doc):
        text = "".join(run.text for run in p.runs)
        if "{{" not in text:
            continue
        new_text = text
        for key, value in mapping.items():
            new_text = new_text.replace("{{%s}}" % key, str(value))
        if new_text != text:
            if p.runs:
                p.runs[0].text = new_text
                for run in p.runs[1:]:
                    run.text = ""
    return doc


def assert_no_placeholder(doc):
    """重新读取并检查是否残留 {{，残留则抛 ValueError。"""
    for p in _iter_paragraphs(doc):
        if "{{" in "".join(run.text for run in p.runs):
            raise ValueError("生成文档仍残留占位符，请检查模板：" +
                             "".join(run.text for run in p.runs)[:80])


def proof_no(year, activity_id, seq):
    """证明编号：年份—活动编号—三位序号；同一学生同一活动序号固定则编号固定。"""
    return "%d—%d—%03d" % (year, activity_id, seq)


def generate_roster(conn, activity_id, template_path, output_path):
    """按活动生成名册：一个文档，表格中每名有效报名学生一行，含到场情况。"""
    template_path, output_path = Path(template_path), Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(
        "SELECT s.student_id, s.name, s.college, s.class_name, r.attendance, "
        "r.practice_score FROM registrations r JOIN students s "
        "ON r.student_id=s.student_id WHERE r.activity_id=? AND r.status='registered' "
        "ORDER BY s.student_id", (activity_id,)
    ).fetchall()
    act = conn.execute("SELECT title,start_time FROM activities WHERE activity_id=?",
                       (activity_id,)).fetchone()
    doc = Document(str(template_path))
    replace_placeholders(doc, {
        "活动名称": act["title"], "活动时间": act["start_time"],
        "活动编号": activity_id, "人数": len(rows),
    })
    table = doc.tables[0] if doc.tables else doc.add_table(rows=1, cols=5)
    headers = ["学号", "姓名", "学院", "到场情况", "实践成绩"]
    for j, h in enumerate(headers):
        table.rows[0].cells[j].text = h
    for r in rows:
        cells = table.add_row().cells
        cells[0].text = r["student_id"]
        cells[1].text = r["name"]
        cells[2].text = r["college"]
        cells[3].text = {"present": "准时", "late": "迟到", "absent": "缺席"}.get(
            r["attendance"], "未登记")
        cells[4].text = "" if r["practice_score"] is None else str(r["practice_score"])
    assert_no_placeholder(doc)
    doc.save(str(output_path))
    return str(output_path)


def generate_proof(conn, activity_id, student_id, template_path, output_path, seq=1):
    """为一名成绩合格及以上的学生生成实践证明；不合格时抛 ValueError。"""
    row = conn.execute(
        "SELECT s.name, s.college, r.practice_score FROM registrations r "
        "JOIN students s ON r.student_id=s.student_id "
        "WHERE r.activity_id=? AND r.student_id=? AND r.status='registered'",
        (activity_id, student_id),
    ).fetchone()
    if row is None or row["practice_score"] is None:
        raise ValueError("该学生尚无实践成绩")
    score = row["practice_score"]
    level = score_level(score)
    if score < 60:
        raise ValueError("成绩不合格，不生成证明")
    act = conn.execute("SELECT title,start_time FROM activities WHERE activity_id=?",
                       (activity_id,)).fetchone()
    year = datetime.fromisoformat(act["start_time"]).year
    doc = Document(str(template_path))
    replace_placeholders(doc, {
        "姓名": row["name"], "学号": student_id, "学院": row["college"],
        "活动名称": act["title"], "活动时间": act["start_time"],
        "实践成绩": score, "等级": level, "证明编号": proof_no(year, activity_id, seq),
    })
    assert_no_placeholder(doc)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    return str(output_path)
