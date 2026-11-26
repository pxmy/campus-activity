"""统计口径测试：手工构造小数据集并手算期望值。"""
import sqlite3

import pandas as pd

from services.stats import activity_metrics, summary


def make_conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
    CREATE TABLE students(student_id TEXT PRIMARY KEY, name TEXT, college TEXT,
                          class_name TEXT, grade INTEGER);
    INSERT INTO students VALUES
      ('S01','A','计算机学院','1班',2024),('S02','B','管理学院','1班',2024),
      ('S03','C','计算机学院','1班',2024),('S04','D','计算机学院','1班',2024);
    CREATE TABLE activities(
        activity_id INTEGER PRIMARY KEY, title TEXT, category TEXT, organizer_id INTEGER,
        venue_id INTEGER, start_time TEXT, end_time TEXT, signup_deadline TEXT,
        capacity INTEGER, status TEXT, description TEXT);
    -- 甲活动：10 人报名（只有 4 人有记录以便手算），到场 9 口径用容量算报名率
    INSERT INTO activities VALUES
      (1,'甲','讲座',1,1,'2026-10-01T14:00','2026-10-01T16:00','2026-09-30T14:00',10,'finished',''),
      (2,'乙','竞赛',1,1,'2026-10-02T14:00','2026-10-02T16:00','2026-10-01T14:00',200,'finished',''),
      (3,'草稿','讲座',1,1,'2026-10-03T14:00','2026-10-03T16:00','2026-10-02T14:00',50,'draft',''),
      (4,'取消','讲座',1,1,'2026-10-04T14:00','2026-10-04T16:00','2026-10-03T14:00',50,'cancelled','');
    CREATE TABLE registrations(
        reg_id INTEGER PRIMARY KEY, activity_id INTEGER, student_id TEXT, status TEXT,
        created_at TEXT, attendance TEXT, task_score INTEGER, feedback_at TEXT,
        practice_score INTEGER);
    -- 甲：S01 present 90, S02 late 70, S03 absent 0, S04 present 未评定
    INSERT INTO registrations VALUES
      (1,1,'S01','registered','2026-09-28T10:00','present',90,NULL,95),
      (2,1,'S02','registered','2026-09-28T10:00','late',70,NULL,75),
      (3,1,'S03','registered','2026-09-28T10:00','absent',0,NULL,0),
      (4,1,'S04','registered','2026-09-28T10:00','present',NULL,NULL,NULL),
      (5,1,'S01','cancelled','2026-09-28T10:00',NULL,NULL,NULL,NULL);
    -- 乙：S01 present 80（1 人报名，容量 200）
    INSERT INTO registrations VALUES
      (6,2,'S01','registered','2026-09-29T10:00','present',80,NULL,90);
    """)
    return c


def test_metrics_basic():
    df = activity_metrics(make_conn(), {})
    # 草稿和取消的活动不计入
    assert len(df) == 2
    a = df[df["activity_id"] == 1].iloc[0]
    assert a["capacity"] == 10
    assert a["signed"] == 4          # 取消的报名不计入
    assert a["arrived"] == 3         # present 2 + late 1
    assert a["completed"] == 2       # task_score>=60: 90,70
    assert a["ungraded"] == 1        # present 但未评定
    assert abs(a["signup_rate"] - 0.4) < 1e-9
    assert abs(a["attendance_rate"] - 0.75) < 1e-9
    assert abs(a["completion_rate"] - 2 / 3) < 1e-9


def test_summary_ratio_of_sums():
    df = activity_metrics(make_conn(), {})
    s = summary(df)
    # 报名率 = (4+1)/(10+200) = 5/210，不是 (0.4+0.005)/2
    assert abs(s["signup_rate"] - 5 / 210) < 1e-9
    # 到场率 = (3+1)/(4+1) = 4/5
    assert abs(s["attendance_rate"] - 0.8) < 1e-9
    # 完成率 = (2+1)/(3+1) = 3/4
    assert abs(s["completion_rate"] - 0.75) < 1e-9
    assert s["activities"] == 2
    assert s["signed"] == 5


def test_summary_weighted_avg():
    df = activity_metrics(make_conn(), {})
    s = summary(df)
    # 甲有成绩 3 人(95,75,0) 平均 56.667；乙 1 人 90；加权 = (170+90)/4 = 65
    assert abs(s["avg_score"] - 65.0) < 1e-6


def test_college_filter_affects_both_sides():
    conn = make_conn()
    df = activity_metrics(conn, {"college": "计算机学院"})
    a = df[df["activity_id"] == 1].iloc[0]
    # 计算机学院学生 S01,S03,S04 → 3 人有效报名（S02 管理学院被排除）
    assert a["signed"] == 3
    assert abs(a["signup_rate"] - 0.3) < 1e-9


def test_empty_summary():
    from pandas import DataFrame
    s = summary(DataFrame())
    assert s["signup_rate"] is None
    assert s["activities"] == 0


def test_zero_denominator_returns_none():
    c = make_conn()
    # 构造一场无报名的活动
    c.execute("INSERT INTO activities VALUES(9,'空','讲座',1,1,'2026-10-09T14:00',"
              "'2026-10-09T16:00','2026-10-08T14:00',30,'finished','')")
    c.commit()
    df = activity_metrics(c, {})
    a = df[df["activity_id"] == 9].iloc[0]
    assert pd.isna(a["attendance_rate"])  # pandas 把 None 存为 NaN
    assert a["signup_rate"] == 0.0
