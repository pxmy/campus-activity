"""数据清洗：把历史报名/成绩文件分成“可入库数据”和“异常清单”。

约定：任何一行要么进入 clean_df，要么在 issues_df 中有“未入库”记录，不允许无声丢弃。
8 类问题各写成独立小函数，便于单独测试。
"""
import re
import unicodedata
from pathlib import Path

import pandas as pd

SOURCE_COLS = ["activity_id", "student_id", "attendance", "task_score", "feedback_at"]
ISSUE_COLS = ["source_file", "row_no", "field", "raw_value", "issue_type", "action"]


def read_csv_smart(path):
    """识别编码读取 CSV：优先 utf-8-sig，失败后用 gbk；都不行则抛 ValueError。"""
    path = Path(path)
    for enc in ("utf-8-sig", "gbk"):
        try:
            return pd.read_csv(path, encoding=enc, dtype=str)
        except UnicodeDecodeError:
            continue
    raise ValueError("无法识别文件编码，拒绝带着乱码入库：" + str(path))


def normalize_student_id(value):
    """把学号的全角数字转半角、去掉首尾空白。"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return unicodedata.normalize("NFKC", str(value)).strip()


def normalize_datetime(value):
    """把常见日期写法统一为 ISO 8601（YYYY-MM-DDTHH:MM）；无法解析返回 None。"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = unicodedata.normalize("NFKC", str(value)).strip()
    m = re.match(r"^(\d{4})[/.\-年](\d{1,2})[/.\-月](\d{1,2})日?"
                 r"(?:[ T](\d{1,2}):(\d{2}))?", s)
    if not m:
        return None
    y, mo, d, hh, mm = m.groups()
    hh, mm = hh or "00", mm or "00"
    return "%04d-%02d-%02dT%02d:%02d" % (int(y), int(mo), int(d), int(hh), int(mm))


def _is_blank(v):
    return v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == ""


def _add_issue(issues, source_file, row_no, field, raw_value, issue_type, action):
    issues.append({"source_file": source_file, "row_no": row_no, "field": field,
                   "raw_value": "" if raw_value is None else str(raw_value),
                   "issue_type": issue_type, "action": action})


def check_illegal(activity_id, attendance, task_score, feedback_at):
    """校验字段取值是否合法，返回 (是否合法, 字段名, 说明)。

    attendance ∈ {present,late,absent}；task_score 为空或 0-100 整数；
    feedback_at 为空或可规范化为日期。
    """
    if attendance not in ("present", "late", "absent"):
        return False, "attendance", "到场情况取值非法"
    if not _is_blank(task_score):
        try:
            n = int(str(task_score).strip())
            if not 0 <= n <= 100:
                return False, "task_score", "任务完成度越界"
        except ValueError:
            return False, "task_score", "任务完成度非整数"
    if not _is_blank(feedback_at) and normalize_datetime(feedback_at) is None:
        return False, "feedback_at", "反馈时间格式非法"
    return True, "", ""


def clean_scores(path, valid_activity_ids=None, valid_student_ids=None):
    """清洗成绩导入文件。

    参数 valid_activity_ids / valid_student_ids 为可迭代的合法编号集合；
    传 None 时跳过“引用不存在”检查（便于单元测试）。

    返回 (clean_df, issues_df)：
    - clean_df 列为 SOURCE_COLS，可直接入库；
    - issues_df 列为 ISSUE_COLS，row_no 为原始文件行号（表头为第 1 行）。
    """
    path = Path(path)
    source_name = path.name
    raw = read_csv_smart(path)
    issues = []
    records = []            # (row_no, dict) 通过基础校验的行
    drop_rows = set()       # 重复处理中需要剔除的行号
    seen = {}               # (activity_id, student_id) -> list of (row_no, record)

    for idx, row in raw.iterrows():
        row_no = idx + 2     # 表头第 1 行
        act_raw = row.get("activity_id", "")
        sid_raw = row.get("student_id", "")
        act = "" if _is_blank(act_raw) else str(act_raw).strip()
        sid = normalize_student_id(sid_raw)
        att = row.get("attendance", "")
        task = row.get("task_score", "")
        fb = row.get("feedback_at", "")

        # 关键字段缺失：活动编号 / 学号
        if not act:
            _add_issue(issues, source_name, row_no, "activity_id", act_raw,
                       "关键字段缺失", "未入库")
            continue
        if not sid:
            _add_issue(issues, source_name, row_no, "student_id", sid_raw,
                       "关键字段缺失", "未入库")
            continue

        # 格式不规范：学号含空格/全角、日期格式不统一；修复后继续
        if sid != str(sid_raw):
            _add_issue(issues, source_name, row_no, "student_id", sid_raw,
                       "格式不规范", "已修复")
        fb_norm = normalize_datetime(fb) if not _is_blank(fb) else None
        if not _is_blank(fb) and fb_norm is None:
            _add_issue(issues, source_name, row_no, "feedback_at", fb,
                       "非法值", "未入库")
            continue
        if not _is_blank(fb) and str(fb).strip() != fb_norm:
            _add_issue(issues, source_name, row_no, "feedback_at", fb,
                       "格式不规范", "已修复")

        # 非关键字段缺失：任务完成度为空 → 入库，成绩按“未评定”
        if _is_blank(task):
            _add_issue(issues, source_name, row_no, "task_score", task,
                       "非关键字段缺失", "入库-未评定")

        # 非法值校验（在 int 转换之前，避免 int("优") 抛异常）
        ok, field, desc = check_illegal(act, att, task, fb)
        if not ok:
            raw_val = {"attendance": att, "task_score": task,
                       "feedback_at": fb}.get(field, task)
            _add_issue(issues, source_name, row_no, field, raw_val,
                       "非法值", "未入库")
            continue

        task_value = None if _is_blank(task) else int(str(task).strip())

        # 引用不存在
        if valid_activity_ids is not None and act not in {str(x) for x in valid_activity_ids}:
            _add_issue(issues, source_name, row_no, "activity_id", act,
                       "引用不存在", "未入库")
            continue
        if valid_student_ids is not None and sid not in {str(x) for x in valid_student_ids}:
            _add_issue(issues, source_name, row_no, "student_id", sid,
                       "引用不存在", "未入库")
            continue

        rec = {"activity_id": act, "student_id": sid, "attendance": att,
               "task_score": task_value, "feedback_at": fb_norm}
        records.append((row_no, rec))
        seen.setdefault((act, sid), []).append((row_no, rec))

    # 重复处理：完全重复保留第一行，重复矛盾两行都不入库
    for key, group in seen.items():
        if len(group) < 2:
            continue
        first_rec = group[0][1]
        identical = all(r == first_rec for _, r in group[1:])
        if identical:
            for row_no, rec in group[1:]:
                drop_rows.add(row_no)
                _add_issue(issues, source_name, row_no, "student_id", rec["student_id"],
                           "完全重复", "未入库")
        else:
            for row_no, rec in group:
                drop_rows.add(row_no)
                _add_issue(issues, source_name, row_no, "task_score", rec["task_score"],
                           "重复且矛盾", "未入库")

    clean = [rec for row_no, rec in records if row_no not in drop_rows]
    clean_df = pd.DataFrame(clean, columns=SOURCE_COLS)
    issues_df = pd.DataFrame(issues, columns=ISSUE_COLS)
    return clean_df, issues_df


def count_unimported(issues_df):
    """统计“未入库”异常行数，供页面对账：读取 = 入库 + 未入库。"""
    if issues_df.empty:
        return 0
    return int((issues_df["action"] == "未入库").sum())
