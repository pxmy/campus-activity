"""业务规则：报名校验、场地时间冲突检查、实践成绩计算、活动状态转换。

规则以 docs/业务规则.md 为准，本文件是全项目唯一的规则实现处。
"""
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

FEEDBACK_DAYS = 3  # 活动结束后几天内（含）提交反馈可得分

# 活动状态允许的转换（谁触发由页面层校验角色）
STATUS_TRANSITIONS = {
    "draft": {"open", "cancelled"},
    "open": {"closed", "cancelled"},
    "closed": {"finished", "cancelled"},
    "finished": set(),
    "cancelled": set(),
}


class RuleError(Exception):
    """业务规则不满足时抛出，message 可直接显示给用户。"""


def overlaps(start_a, end_a, start_b, end_b):
    """两个时间段是否重叠。首尾相接（14:00-16:00 与 16:00-18:00）不算重叠。"""
    return start_a < end_b and start_b < end_a


def find_venue_conflicts(conn, venue_id, start_time, end_time, exclude_id=None):
    """返回与给定时间段冲突的活动列表；已取消的活动不参与检查。"""
    rows = conn.execute(
        "SELECT activity_id, title, start_time, end_time FROM activities "
        "WHERE venue_id = ? AND status != 'cancelled' AND activity_id IS NOT ?",
        (venue_id, exclude_id),
    ).fetchall()
    return [dict(r) for r in rows if overlaps(start_time, end_time, r["start_time"], r["end_time"])]


def validate_activity(conn, title, category, venue_id, start_time, end_time,
                      signup_deadline, capacity, exclude_id=None):
    """活动保存前的输入检查，返回规范化后的字段字典；不满足则抛 RuleError。

    检查：标题非空、时间合法且结束晚于开始、截止不晚于开始、名额为正整数且不超过场地容量、
    场地时间不冲突。
    """
    if not title or not title.strip():
        raise RuleError("活动标题不能为空")
    if not start_time or not end_time:
        raise RuleError("开始时间和结束时间不能为空")
    if not start_time < end_time:
        raise RuleError("结束时间必须晚于开始时间")
    if signup_deadline and signup_deadline > start_time:
        raise RuleError("报名截止时间不能晚于活动开始时间")
    if not isinstance(capacity, int) or capacity <= 0:
        raise RuleError("名额必须为正整数")
    venue = conn.execute("SELECT capacity FROM venues WHERE venue_id=?", (venue_id,)).fetchone()
    if venue is None:
        raise RuleError("场地不存在")
    if capacity > venue["capacity"]:
        raise RuleError("活动名额不能超过场地容量（%d）" % venue["capacity"])
    conflicts = find_venue_conflicts(conn, venue_id, start_time, end_time, exclude_id)
    if conflicts:
        detail = "；".join("%s（%s—%s）" % (c["title"], c["start_time"], c["end_time"])
                          for c in conflicts)
        raise RuleError("场地时间冲突：" + detail)
    return dict(title=title.strip(), category=category, venue_id=venue_id,
                start_time=start_time, end_time=end_time,
                signup_deadline=signup_deadline, capacity=capacity)


def can_transition(old, new):
    """活动状态转换是否合法。"""
    return new in STATUS_TRANSITIONS.get(old, set())


def register(conn, activity_id, student_id, now=None):
    """学生报名。依次检查：活动状态、截止时间、重复报名、人数上限。

    conn 应为 isolation_level=None 的连接，检查与写入在同一事务内完成。
    """
    now = now or datetime.now().isoformat(timespec="minutes")
    act = conn.execute(
        "SELECT status, signup_deadline, capacity FROM activities WHERE activity_id = ?",
        (activity_id,),
    ).fetchone()
    if act is None:
        raise RuleError("活动不存在")
    status, deadline, capacity = act["status"], act["signup_deadline"], act["capacity"]
    if status != "open":
        raise RuleError("活动当前不在报名阶段")
    if now > deadline:
        raise RuleError("已超过报名截止时间")
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        dup = conn.execute(
            "SELECT 1 FROM registrations WHERE activity_id = ? AND student_id = ? "
            "AND status = 'registered'", (activity_id, student_id),
        ).fetchone()
        if dup:
            raise RuleError("你已报名该活动，请勿重复报名")
        count = conn.execute(
            "SELECT COUNT(*) FROM registrations WHERE activity_id = ? "
            "AND status = 'registered'", (activity_id,),
        ).fetchone()[0]
        if count >= capacity:
            raise RuleError("报名人数已满")
        conn.execute(
            "INSERT INTO registrations (activity_id, student_id, created_at) VALUES (?,?,?)",
            (activity_id, student_id, now),
        )


def cancel_registration(conn, activity_id, student_id, now=None):
    """取消报名：把有效报名改为 cancelled；活动开始后不允许取消。"""
    now = now or datetime.now().isoformat(timespec="minutes")
    act = conn.execute("SELECT start_time FROM activities WHERE activity_id=?",
                       (activity_id,)).fetchone()
    if act is None:
        raise RuleError("活动不存在")
    if now >= act["start_time"]:
        raise RuleError("活动已开始，不能取消报名")
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT reg_id FROM registrations WHERE activity_id=? AND student_id=? "
            "AND status='registered'", (activity_id, student_id),
        ).fetchone()
        if row is None:
            raise RuleError("没有找到有效的报名记录")
        conn.execute("UPDATE registrations SET status='cancelled' WHERE reg_id=?",
                     (row["reg_id"],))


def calc_practice_score(attendance, task_score, feedback_at, activity_end):
    """按课程给定规则计算实践成绩，返回 0-100 整数；不具备条件时返回 None。

    出勤分：present 40 / late 30 / absent 记 0；
    任务分：task_score × 0.5；
    反馈分：活动结束后 3 天内（含第 3 天同一时刻）提交得 10；
    合计用 Decimal 四舍五入取整，避免银行家舍入。
    """
    if attendance is None:
        return None
    if attendance == "absent":
        return 0
    if task_score is None:
        return None
    if not 0 <= task_score <= 100:
        raise ValueError("任务完成度必须在 0-100 之间")
    total = Decimal(40 if attendance == "present" else 30)
    total += Decimal(task_score) * Decimal("0.5")
    if feedback_at:
        limit = datetime.fromisoformat(activity_end) + timedelta(days=FEEDBACK_DAYS)
        if datetime.fromisoformat(feedback_at) <= limit:
            total += 10
    return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def score_level(score):
    """把成绩映射为等级。"""
    if score is None:
        return "未评定"
    if score >= 90:
        return "优秀"
    if score >= 80:
        return "良好"
    if score >= 60:
        return "合格"
    return "不合格"
