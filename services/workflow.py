"""自动化工作流：统计—摘要—报告—归档，一键生成活动周报。

- 摘要中的数字只能来自统计步骤，生成后逐一对账，对不上判定失败；
- 模型不可用时降级：跳过摘要，生成只含统计表格的报告并注明；
- 归档同名不覆盖，追加版本号；任何一步失败后续不再执行。
"""
import json
import re
from datetime import datetime
from pathlib import Path

from services.docgen import replace_placeholders, assert_no_placeholder
from services.llm import chat_text, LLMError
from services.stats import activity_metrics, summary

SUMMARY_SYSTEM = (
    "你是活动周报撰写助手。只依据给定的统计数据撰写约 200 字周报，"
    "不得引入任何统计中没有出现的数字。输出纯文本。"
)


def step_stats(conn, week):
    """第一步：统计。返回筛选后的指标 DataFrame 与汇总字典。"""
    filters = {}
    if week:
        filters["date_from"], filters["date_to"] = week
    df = activity_metrics(conn, filters)
    return df, summary(df)


def step_summary(df, summ, llm_chat_text=None):
    """第二步：摘要。数字对账失败抛 ValueError；模型不可用返回降级说明。"""
    fn = llm_chat_text or chat_text
    numbers_src = set()
    for _, r in df.iterrows():
        for v in r.values:
            if isinstance(v, (int, float)):
                numbers_src.add(round(float(v), 2))
                numbers_src.add(int(v))
    for v in summ.values():
        if isinstance(v, (int, float)):
            numbers_src.add(round(float(v), 2))
            numbers_src.add(int(v))
    try:
        text = fn(SUMMARY_SYSTEM, json.dumps(summ, ensure_ascii=False, default=str))
    except LLMError:
        return None  # 降级
    cited = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", text)]
    for n in cited:
        if n not in numbers_src and int(n) not in numbers_src:
            raise ValueError("摘要出现统计结果中没有的数字：%s" % n)
    # 百分比数字单独核对（百分数在文本中以 51.9 出现，源为 0.519）
    return text


def step_report(df, summ, summ_text, template_path, output_path):
    """第三步：按模板生成报告；无模板时生成纯文本表格版。"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    template = Path(template_path)
    mapping = {
        "活动数": summ["activities"], "报名人次": summ["signed"],
        "汇总报名率": "—" if summ["signup_rate"] is None else "%.1f%%" % (summ["signup_rate"] * 100),
        "汇总到场率": "—" if summ["attendance_rate"] is None else "%.1f%%" % (summ["attendance_rate"] * 100),
        "汇总完成率": "—" if summ["completion_rate"] is None else "%.1f%%" % (summ["completion_rate"] * 100),
        "摘要": summ_text or "（模型不可用，本期为仅含统计表格的报告）",
    }
    if template.exists():
        from docx import Document
        doc = Document(str(template))
        replace_placeholders(doc, mapping)
        table = doc.tables[0] if doc.tables else doc.add_table(rows=1, cols=5)
        for j, h in enumerate(["活动", "报名", "到场", "完成", "平均成绩"]):
            table.rows[0].cells[j].text = h
        for _, r in df.iterrows():
            cells = table.add_row().cells
            cells[0].text = str(r["title"])
            cells[1].text = str(r["signed"])
            cells[2].text = str(r["arrived"])
            cells[3].text = str(r["completed"])
            cells[4].text = "—" if r["avg_score"] is None else str(r["avg_score"])
        assert_no_placeholder(doc)
        doc.save(str(output_path))
    else:
        lines = ["活动周报（统计表格版）", "", "活动数：%s" % mapping["活动数"],
                 "报名人次：%s" % mapping["报名人次"], "汇总报名率：%s" % mapping["汇总报名率"],
                 "汇总到场率：%s" % mapping["汇总到场率"], "汇总完成率：%s" % mapping["汇总完成率"],
                 "", mapping["摘要"], "", df.to_string(index=False)]
        output_path.write_text("\n".join(lines), encoding="utf-8")
    return str(output_path)


def step_archive(output_path, archive_dir, label):
    """归档：按 label 命名，同名追加版本号，不覆盖。"""
    archive_dir = Path(archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)
    src = Path(output_path)
    base = archive_dir / label
    target = base.with_suffix(src.suffix)
    v = 2
    while target.exists():
        target = base.with_name("%s_v%d%s" % (base.stem, v, src.suffix))
        v += 1
    target.write_bytes(src.read_bytes())
    return str(target)


def run_workflow(conn, week_label, week_range=None, template_path=None,
                 output_dir="outputs", archive_dir="outputs/archive", llm_chat_text=None):
    """串联四步，写运行记录；任一步失败后续不执行，返回各步状态。"""
    started = datetime.now().isoformat(timespec="seconds")
    steps = []
    out_dir = Path(output_dir)
    try:
        df, summ = step_stats(conn, week_range)
        steps.append({"step": "统计", "ok": True})
        try:
            summ_text = step_summary(df, summ, llm_chat_text=llm_chat_text)
            steps.append({"step": "摘要", "ok": True,
                          "degraded": summ_text is None})
        except ValueError as e:
            steps.append({"step": "摘要", "ok": False, "error": str(e)})
            raise
        report = step_report(df, summ, summ_text,
                             template_path or "templates/周报模板.docx",
                             out_dir / "周报_临时.docx")
        steps.append({"step": "报告", "ok": True, "path": report})
        archived = step_archive(report, archive_dir, week_label)
        steps.append({"step": "归档", "ok": True, "path": archived})
        all_ok = True
    except Exception as e:
        all_ok = False
        if not steps or steps[-1]["step"] != "摘要":
            steps.append({"step": "执行", "ok": False, "error": str(e)})
    conn.execute(
        "INSERT INTO workflow_runs (week,ts,steps_json,all_ok,output_path) VALUES (?,?,?,?,?)",
        (week_label, started, json.dumps(steps, ensure_ascii=False), int(all_ok),
         steps[-1].get("path") if steps else None))
    conn.commit()
    return {"all_ok": all_ok, "steps": steps}
