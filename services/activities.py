"""活动与报名的数据库操作：供页面调用，不在页面写 SQL。"""
from datetime import datetime

from services.db import get_conn, get_conn_manual
from services.rules import (RuleError, can_transition, cancel_registration,
                            find_venue_conflicts, register, validate_activity)

ROLE_CN = {"student": "学生", "organizer": "组织者", "admin": "管理员"}
STATUS_CN = {"draft": "草稿", "open": "报名中", "closed": "报名截止",
             "finished": "已结束", "cancelled": "已取消"}
ATT_CN = {"present": "准时", "late": "迟到", "absent": "缺席"}
# 界面选项用中文展示，提交时映射回英文码值存库（规则层只认英文）
ATT_REVERSE = {"准时": "present", "迟到": "late", "缺席": "absent"}
ATT_OPTIONS = ["未登记"] + list(ATT_CN.values())


def list_venues():
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM venues ORDER BY venue_id")]
    finally:
        conn.close()


def list_activities(organizer_id=None, role=None):
    """组织者只看自己的活动；管理员看全部；学生看非草稿活动。"""
    conn = get_conn()
    try:
        sql = "SELECT a.*, v.name AS venue_name FROM activities a JOIN venues v ON a.venue_id=v.venue_id"
        args = []
        where = []
        if role == "organizer":
            where.append("a.organizer_id=?"); args.append(organizer_id)
        elif role == "student":
            where.append("a.status IN ('open','closed','finished')")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY a.start_time"
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def get_activity(activity_id):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT a.*, v.name AS venue_name FROM activities a "
            "JOIN venues v ON a.venue_id=v.venue_id WHERE a.activity_id=?",
            (activity_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def save_activity(data, user):
    """新建或更新活动，含输入检查与场地冲突检查。返回 activity_id。"""
    conn = get_conn_manual()
    try:
        normalized = validate_activity(
            conn, data["title"], data["category"], data["venue_id"],
            data["start_time"], data["end_time"], data["signup_deadline"],
            data["capacity"], exclude_id=data.get("activity_id"))
        if data.get("activity_id"):
            conn.execute(
                "UPDATE activities SET title=?,category=?,venue_id=?,start_time=?,"
                "end_time=?,signup_deadline=?,capacity=?,description=? WHERE activity_id=?",
                (normalized["title"], normalized["category"], normalized["venue_id"],
                 normalized["start_time"], normalized["end_time"],
                 normalized["signup_deadline"], normalized["capacity"],
                 data.get("description", ""), data["activity_id"]))
            return data["activity_id"]
        cur = conn.execute(
            "INSERT INTO activities (title,category,organizer_id,venue_id,start_time,"
            "end_time,signup_deadline,capacity,status,description) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (normalized["title"], normalized["category"], user["user_id"],
             normalized["venue_id"], normalized["start_time"], normalized["end_time"],
             normalized["signup_deadline"], normalized["capacity"], "draft",
             data.get("description", "")))
        return cur.lastrowid
    finally:
        conn.close()


def change_status(activity_id, new_status):
    """变更活动状态，校验转换合法性。"""
    conn = get_conn_manual()
    try:
        old = conn.execute("SELECT status FROM activities WHERE activity_id=?",
                           (activity_id,)).fetchone()
        if old is None:
            raise RuleError("活动不存在")
        if not can_transition(old["status"], new_status):
            raise RuleError("不允许从“%s”转换到“%s”" % (old["status"], new_status))
        conn.execute("UPDATE activities SET status=? WHERE activity_id=?",
                     (new_status, activity_id))
    finally:
        conn.close()


def do_register(activity_id, student_id):
    conn = get_conn_manual()
    try:
        register(conn, activity_id, student_id)
    finally:
        conn.close()


def do_cancel_registration(activity_id, student_id):
    conn = get_conn_manual()
    try:
        cancel_registration(conn, activity_id, student_id)
    finally:
        conn.close()


def my_registrations(student_id):
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT r.*, a.title, a.start_time, a.end_time, a.status AS act_status "
            "FROM registrations r JOIN activities a ON r.activity_id=a.activity_id "
            "WHERE r.student_id=? AND r.status='registered' ORDER BY a.start_time",
            (student_id,)).fetchall()]
    finally:
        conn.close()


def activity_registrations(activity_id):
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT r.*, s.name, s.college, s.class_name FROM registrations r "
            "JOIN students s ON r.student_id=s.student_id "
            "WHERE r.activity_id=? AND r.status='registered' ORDER BY s.student_id",
            (activity_id,)).fetchall()]
    finally:
        conn.close()


def record_attendance(reg_id, attendance, task_score):
    """登记到场与任务完成度，并按规则重算成绩。"""
    from services.rules import calc_practice_score, score_level
    conn = get_conn_manual()
    try:
        row = conn.execute(
            "SELECT r.activity_id, r.feedback_at, a.end_time FROM registrations r "
            "JOIN activities a ON r.activity_id=a.activity_id WHERE r.reg_id=?",
            (reg_id,)).fetchone()
        score = calc_practice_score(attendance, task_score, row["feedback_at"], row["end_time"])
        conn.execute(
            "UPDATE registrations SET attendance=?, task_score=?, practice_score=? "
            "WHERE reg_id=?", (attendance, task_score, score, reg_id))
        return score, score_level(score)
    finally:
        conn.close()
