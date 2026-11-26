"""数据清洗测试：8 类问题各一个测试 + 行数对账。"""
import csv
from pathlib import Path

import pytest

from services.cleaning import (
    clean_scores, count_unimported, normalize_student_id, normalize_datetime,
)


def write_csv(tmp_path, rows, encoding="utf-8", name="scores_import.csv"):
    p = tmp_path / name
    with p.open("w", encoding=encoding, newline="") as f:
        w = csv.writer(f)
        w.writerow(["activity_id", "student_id", "attendance", "task_score", "feedback_at"])
        w.writerows(rows)
    return p


HEAD = "1"


def test_format_normalization(tmp_path):
    p = write_csv(tmp_path, [[HEAD, " ２０２４０００１ ", "present", "85", "2026/12/8 10:00"]])
    clean, issues = clean_scores(p)
    assert clean.iloc[0]["student_id"] == "20240001"
    assert clean.iloc[0]["feedback_at"] == "2026-12-08T10:00"
    assert set(issues["issue_type"]) == {"格式不规范"}


def test_key_field_missing(tmp_path):
    p = write_csv(tmp_path, [[HEAD, "", "present", "85", ""], ["", "S002", "present", "85", ""]])
    clean, issues = clean_scores(p)
    assert len(clean) == 0
    assert (issues["issue_type"] == "关键字段缺失").sum() == 2


def test_nonkey_missing_kept_as_ungraded(tmp_path):
    p = write_csv(tmp_path, [[HEAD, "S001", "present", "", ""]])
    clean, issues = clean_scores(p)
    assert len(clean) == 1
    assert clean.iloc[0]["task_score"] is None
    assert "非关键字段缺失" in set(issues["issue_type"])


def test_exact_duplicate(tmp_path):
    row = [HEAD, "S001", "present", "85", ""]
    p = write_csv(tmp_path, [row, row])
    clean, issues = clean_scores(p)
    assert len(clean) == 1
    assert "完全重复" in set(issues["issue_type"])


def test_conflicting_duplicate(tmp_path):
    p = write_csv(tmp_path, [[HEAD, "S001", "present", "85", ""],
                             [HEAD, "S001", "present", "99", ""]])
    clean, issues = clean_scores(p)
    assert len(clean) == 0
    assert (issues["issue_type"] == "重复且矛盾").sum() == 2


def test_illegal_values(tmp_path):
    p = write_csv(tmp_path, [[HEAD, "S001", "来了", "85", ""],
                             [HEAD, "S002", "present", "105", ""],
                             [HEAD, "S003", "present", "优", ""]])
    clean, issues = clean_scores(p)
    assert len(clean) == 0
    assert (issues["issue_type"] == "非法值").sum() == 3


def test_broken_reference(tmp_path):
    p = write_csv(tmp_path, [[HEAD, "9999", "present", "85", ""],
                             [HEAD, "S999", "present", "85", ""]])
    clean, issues = clean_scores(p, valid_activity_ids={"1"}, valid_student_ids={"S001"})
    assert len(clean) == 0
    assert (issues["issue_type"] == "引用不存在").sum() == 2


def test_encoding_gbk(tmp_path):
    p = write_csv(tmp_path, [[HEAD, "S001", "present", "85", ""]], encoding="gbk")
    clean, issues = clean_scores(p)
    assert len(clean) == 1


def test_row_number_is_original(tmp_path):
    p = write_csv(tmp_path, [[HEAD, "", "present", "85", ""]])
    clean, issues = clean_scores(p)
    assert issues.iloc[0]["row_no"] == 2  # 表头第 1 行


def test_row_balance(tmp_path):
    rows = [[HEAD, "S001", "present", "85", ""],
            [HEAD, "", "present", "85", ""],
            [HEAD, "S002", "来了", "85", ""]]
    p = write_csv(tmp_path, rows)
    clean, issues = clean_scores(p)
    assert len(rows) == len(clean) + count_unimported(issues)


def test_no_silent_drop(tmp_path):
    """每一行要么入库，要么在 issues 有未入库记录。"""
    rows = [[HEAD, "S001", "present", "85", ""],
            [HEAD, "S001", "present", "85", ""],
            [HEAD, "S003", "present", "105", ""]]
    p = write_csv(tmp_path, rows)
    clean, issues = clean_scores(p)
    assert len(rows) == len(clean) + count_unimported(issues)
