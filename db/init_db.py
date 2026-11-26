"""建库并写入演示数据。可重复运行而不报错、不产生重复数据。

用法：python db/init_db.py
数据源：优先读取 data/raw/students.csv（教师下发名单），若不存在则用内置演示名单。
生成文件：data/app.db
"""
import csv
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "db" / "schema.sql"
DB_PATH = ROOT / os.getenv("DB_PATH", "data/app.db")

VENUES = [
    ("博学报告厅", 200),
    ("笃行楼301", 80),
    ("体育馆", 500),
]

DEMO_USERS = [
    ("admin", "admin"),
    ("org_zhang", "organizer"),
    ("org_li", "organizer"),
    ("stu_001", "student"),
    ("stu_002", "student"),
    ("stu_003", "student"),
]


def _demo_students():
    """内置演示学生名单（学号、姓名、学院、班级、年级），全部为虚构数据。"""
    colleges = ["计算机学院", "管理学院", "机械学院"]
    data = []
    for i in range(1, 61):
        sid = "2024%04d" % i
        name = "演示学生%02d" % i
        college = colleges[(i - 1) % 3]
        data.append((sid, name, college, "班级%d" % ((i - 1) % 3 + 1), 2024))
    return data


def load_students(conn):
    """从 CSV 或内置名单导入学生，用 INSERT OR IGNORE 保证幂等。返回导入条数。"""
    src = ROOT / "data" / "raw" / "students.csv"
    rows = []
    if src.exists():
        with src.open(encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                rows.append((r["student_id"], r["name"], r["college"],
                             r["class_name"], int(r["grade"])))
    else:
        rows = _demo_students()
    before = conn.total_changes
    conn.executemany(
        "INSERT OR IGNORE INTO students (student_id,name,college,class_name,grade) "
        "VALUES (?,?,?,?,?)", rows)
    return conn.total_changes - before


def seed_users(conn):
    """写入演示用户；学生用户绑定到已有学号。幂等。"""
    student_ids = [r[0] for r in conn.execute("SELECT student_id FROM students").fetchall()]
    for i, (username, role) in enumerate(DEMO_USERS):
        sid = student_ids[i] if role == "student" and i < len(student_ids) else None
        conn.execute(
            "INSERT OR IGNORE INTO users (username, role, student_id) VALUES (?,?,?)",
            (username, role, sid))


def seed_activities(conn):
    """写入若干不同状态的演示活动，覆盖报名中、已结束等场景。幂等。"""
    org_ids = [r[0] for r in conn.execute(
        "SELECT user_id FROM users WHERE role='organizer'").fetchall()]
    if not org_ids:
        return
    now = datetime.now()
    acts = [
        ("AI 技术前沿讲座", "讲座", org_ids[0], 1,
         now + timedelta(days=5), now + timedelta(days=5, hours=2), 120, "open"),
        ("校园志愿服务招募", "志愿服务", org_ids[0], 2,
         now + timedelta(days=10), now + timedelta(days=10, hours=3), 60, "open"),
        ("程序设计竞赛", "竞赛", org_ids[-1], 3,
         now - timedelta(days=10),
         now - timedelta(days=10) + timedelta(hours=3), 200, "finished"),
        ("文体活动：趣味运动会", "文体", org_ids[-1], 3,
         now + timedelta(days=20), now + timedelta(days=20, hours=4), 300, "draft"),
    ]
    for title, cat, org, venue, start, end, cap, status in acts:
        exists = conn.execute("SELECT 1 FROM activities WHERE title=?", (title,)).fetchone()
        if exists:
            continue
        conn.execute(
            "INSERT INTO activities (title,category,organizer_id,venue_id,start_time,"
            "end_time,signup_deadline,capacity,status,description) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (title, cat, org, venue,
             start.isoformat(timespec="minutes"), end.isoformat(timespec="minutes"),
             (start - timedelta(days=1)).isoformat(timespec="minutes"),
             cap, status, "演示活动：" + title))


def main():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        n_stu = load_students(conn)
        conn.executemany(
            "INSERT OR IGNORE INTO venues (name, capacity) VALUES (?,?)", VENUES)
        seed_users(conn)
        seed_activities(conn)
        conn.commit()
        print("数据库初始化完成：%s" % DB_PATH)
        print("新增学生记录：%d" % n_stu)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
