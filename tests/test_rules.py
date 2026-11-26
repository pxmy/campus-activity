"""业务规则测试：成绩计算 ≥12 条，规则总计 ≥25 条。

遵循指导书：先写测试再实现。特别覆盖 round(82.5)=82 的银行家舍入陷阱。
"""
import sqlite3

import pytest

from services.rules import (
    RuleError, calc_practice_score, cancel_registration, can_transition,
    find_venue_conflicts, overlaps, register, score_level, validate_activity,
)

END = "2026-12-05T16:00"


# ---------- 成绩计算（16 条） ----------
@pytest.mark.parametrize("attendance,task,feedback,expected,desc", [
    ("present", 90, "2026-12-06T10:00", 95, "三项都得分"),
    ("present", 85, None, 83, "40+42.5=82.5 四舍五入为 83（round 陷阱）"),
    ("late", 85, "2026-12-08T16:00", 83, "迟到，反馈恰在期限上"),
    ("late", 85, "2026-12-08T16:01", 73, "超期 1 分钟不得反馈分"),
    ("absent", 100, "2026-12-06T10:00", 0, "缺席直接记 0"),
    ("present", None, None, None, "到场但任务未评定"),
    (None, None, None, None, "未登记到场"),
    ("present", 0, None, 40, "任务分 0"),
    ("present", 100, None, 90, "任务分 100"),
    ("present", 100, "2026-12-08T16:00", 100, "满分 40+50+10"),
    ("late", 0, None, 30, "迟到任务分 0"),
    ("late", 100, "2026-12-08T16:00", 90, "迟到满分 30+50+10"),
    ("present", 85, "2026-12-05T16:00", 93, "活动结束时刻即提交，得反馈分 40+42.5+10=92.5→93"),
    ("present", 85, "2026-12-08T15:59", 93, "期限前一分钟，得反馈分"),
    ("present", 1, None, 41, "任务分 1，40.5 四舍五入为 41"),
    ("present", 59, None, 70, "40+29.5=69.5 四舍五入为 70"),
])
def test_calc_practice_score(attendance, task, feedback, expected, desc):
    assert calc_practice_score(attendance, task, feedback, END) == expected, desc


@pytest.mark.parametrize("att,task", [
    ("present", 101), ("late", -1), ("present", 1000),
])
def test_task_score_out_of_range(att, task):
    with pytest.raises(ValueError):
        calc_practice_score(att, task, None, END)


def test_score_level():
    assert [score_level(s) for s in [95, 85, 65, 50, None]] == \
        ["优秀", "良好", "合格", "不合格", "未评定"]


def test_score_level_boundaries():
    assert score_level(90) == "优秀"
    assert score_level(80) == "良好"
    assert score_level(60) == "合格"
    assert score_level(59) == "不合格"


# ---------- 时间段重叠 ----------
def test_overlap_true():
    assert overlaps("14:00", "16:00", "15:00", "17:00") is True


def test_overlap_touching_false():
    assert overlaps("14:00", "16:00", "16:00", "18:00") is False


def test_overlap_disjoint():
    assert overlaps("14:00", "15:00", "16:00", "17:00") is False


def test_overlap_contained():
    assert overlaps("14:00", "18:00", "15:00", "16:00") is True


# ---------- 场地冲突（用内存库） ----------
@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:", isolation_level=None)
    c.row_factory = sqlite3.Row
    c.executescript("""
    PRAGMA foreign_keys=ON;
    CREATE TABLE venues(venue_id INTEGER PRIMARY KEY, name TEXT, capacity INTEGER);
    CREATE TABLE activities(
        activity_id INTEGER PRIMARY KEY, title TEXT, category TEXT,
        organizer_id INTEGER, venue_id INTEGER, start_time TEXT, end_time TEXT,
        signup_deadline TEXT, capacity INTEGER,
        status TEXT, description TEXT);
    INSERT INTO venues VALUES(1,'报告厅',200);
    INSERT INTO activities VALUES
      (1,'已有活动','讲座',1,1,'2026-12-05T14:00','2026-12-05T16:00',
       '2026-12-04T14:00',100,'open',''),
      (2,'已取消活动','讲座',1,1,'2026-12-05T15:00','2026-12-05T17:00',
       '2026-12-04T14:00',100,'cancelled','');
    """)
    yield c
    c.close()


def test_conflict_detected(conn):
    got = find_venue_conflicts(conn, 1, "2026-12-05T15:00", "2026-12-05T17:00")
    assert [r["activity_id"] for r in got] == [1]


def test_conflict_touching_ok(conn):
    got = find_venue_conflicts(conn, 1, "2026-12-05T16:00", "2026-12-05T18:00")
    assert got == []


def test_conflict_exclude_self(conn):
    got = find_venue_conflicts(conn, 1, "2026-12-05T14:00", "2026-12-05T16:00",
                               exclude_id=1)
    assert got == []


def test_validate_activity_rejects_conflict(conn):
    with pytest.raises(RuleError, match="场地时间冲突"):
        validate_activity(conn, "新活动", "讲座", 1,
                          "2026-12-05T15:00", "2026-12-05T17:00",
                          "2026-12-04T14:00", 50)


def test_validate_activity_rejects_capacity_over_venue(conn):
    with pytest.raises(RuleError, match="场地容量"):
        validate_activity(conn, "新活动", "讲座", 1,
                          "2026-12-10T15:00", "2026-12-10T17:00",
                          "2026-12-09T14:00", 300)


def test_validate_activity_ok(conn):
    got = validate_activity(conn, "新活动", "讲座", 1,
                            "2026-12-05T16:00", "2026-12-05T18:00",
                            "2026-12-04T14:00", 100)
    assert got["title"] == "新活动"


# ---------- 报名（事务与三项检查） ----------
@pytest.fixture
def reg_conn():
    c = sqlite3.connect(":memory:", isolation_level=None)
    c.row_factory = sqlite3.Row
    c.executescript("""
    PRAGMA foreign_keys=ON;
    CREATE TABLE students(student_id TEXT PRIMARY KEY, name TEXT, college TEXT,
                          class_name TEXT, grade INTEGER);
    CREATE TABLE users(user_id INTEGER PRIMARY KEY, username TEXT, role TEXT,
                       student_id TEXT REFERENCES students(student_id));
    CREATE TABLE venues(venue_id INTEGER PRIMARY KEY, name TEXT, capacity INTEGER);
    CREATE TABLE activities(
        activity_id INTEGER PRIMARY KEY, title TEXT, category TEXT,
        organizer_id INTEGER REFERENCES users(user_id), venue_id INTEGER REFERENCES venues,
        start_time TEXT, end_time TEXT, signup_deadline TEXT, capacity INTEGER,
        status TEXT, description TEXT);
    CREATE TABLE registrations(
        reg_id INTEGER PRIMARY KEY, activity_id INTEGER REFERENCES activities,
        student_id TEXT REFERENCES students,
        status TEXT NOT NULL DEFAULT 'registered', created_at TEXT,
        attendance TEXT, task_score INTEGER, feedback_at TEXT, practice_score INTEGER);
    CREATE UNIQUE INDEX uq_active_reg ON registrations(activity_id,student_id)
        WHERE status='registered';
    INSERT INTO students VALUES('S001','张三','计算机学院','1班',2024);
    INSERT INTO students VALUES('S002','李四','计算机学院','1班',2024);
    INSERT INTO users VALUES(1,'org','organizer',NULL);
    INSERT INTO venues VALUES(1,'报告厅',200);
    INSERT INTO activities VALUES
      (1,'报名中','讲座',1,1,'2026-12-05T14:00','2026-12-05T16:00',
       '2026-12-04T14:00',1,'open',''),
      (2,'草稿','讲座',1,1,'2026-12-06T14:00','2026-12-06T16:00',
       '2026-12-05T14:00',10,'draft','');
    """)
    yield c
    c.close()


def test_register_ok(reg_conn):
    register(reg_conn, 1, "S001", now="2026-12-01T10:00")
    n = reg_conn.execute("SELECT COUNT(*) FROM registrations WHERE status='registered'").fetchone()[0]
    assert n == 1


def test_register_duplicate(reg_conn):
    register(reg_conn, 1, "S001", now="2026-12-01T10:00")
    with pytest.raises(RuleError, match="请勿重复报名"):
        register(reg_conn, 1, "S001", now="2026-12-01T10:01")


def test_register_full(reg_conn):
    register(reg_conn, 1, "S001", now="2026-12-01T10:00")
    with pytest.raises(RuleError, match="报名人数已满"):
        register(reg_conn, 1, "S002", now="2026-12-01T10:01")


def test_register_not_open(reg_conn):
    with pytest.raises(RuleError, match="不在报名阶段"):
        register(reg_conn, 2, "S001", now="2026-12-01T10:00")


def test_register_after_deadline(reg_conn):
    with pytest.raises(RuleError, match="已超过报名截止时间"):
        register(reg_conn, 1, "S001", now="2026-12-04T15:00")


def test_cancel_then_reregister(reg_conn):
    register(reg_conn, 1, "S001", now="2026-12-01T10:00")
    cancel_registration(reg_conn, 1, "S001", now="2026-12-02T10:00")
    register(reg_conn, 1, "S001", now="2026-12-03T10:00")
    n = reg_conn.execute("SELECT COUNT(*) FROM registrations WHERE status='registered'").fetchone()[0]
    assert n == 1


def test_cancel_after_start_rejected(reg_conn):
    register(reg_conn, 1, "S001", now="2026-12-01T10:00")
    with pytest.raises(RuleError, match="活动已开始"):
        cancel_registration(reg_conn, 1, "S001", now="2026-12-05T15:00")


# ---------- 状态转换 ----------
def test_status_transitions():
    assert can_transition("draft", "open") is True
    assert can_transition("open", "closed") is True
    assert can_transition("closed", "finished") is True
    assert can_transition("draft", "finished") is False
    assert can_transition("finished", "open") is False
    assert can_transition("cancelled", "open") is False
