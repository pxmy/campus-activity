"""工具调用助手测试：参数校验、权限、数据归属、日志。"""
import json
import sqlite3

from services.tools import call_tool, validate_args, TOOLS, get_score_distribution


def make_conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
    CREATE TABLE activities(activity_id INTEGER PRIMARY KEY, title TEXT, category TEXT,
        organizer_id INTEGER, venue_id INTEGER, start_time TEXT, end_time TEXT,
        signup_deadline TEXT, capacity INTEGER, status TEXT, description TEXT);
    CREATE TABLE registrations(reg_id INTEGER PRIMARY KEY, activity_id INTEGER,
        student_id TEXT, status TEXT, created_at TEXT, attendance TEXT,
        task_score INTEGER, feedback_at TEXT, practice_score INTEGER);
    CREATE TABLE tool_logs(log_id INTEGER PRIMARY KEY, ts TEXT, username TEXT, role TEXT,
        tool TEXT, args_json TEXT, ok INTEGER, message TEXT, duration_ms INTEGER);
    INSERT INTO activities VALUES(1,'AI讲座','讲座',1,1,'2026-12-01T14:00',
        '2026-12-01T16:00','2026-11-30T14:00',100,'finished','');
    INSERT INTO registrations VALUES
        (1,1,'S01','registered','2026-11-20T10:00','present',90,NULL,95),
        (2,1,'S02','registered','2026-11-20T10:00','present',70,NULL,75),
        (3,1,'S03','registered','2026-11-20T10:00','absent',100,NULL,0);
    """)
    return c


def admin():
    return {"username": "admin", "role": "admin", "user_id": 0}


def organizer_own():
    return {"username": "org", "role": "organizer", "user_id": 1}


def organizer_other():
    return {"username": "org2", "role": "organizer", "user_id": 2}


def student():
    return {"username": "stu", "role": "student", "user_id": 3, "student_id": "S01"}


def logs(conn):
    return conn.execute("SELECT * FROM tool_logs").fetchall()


def test_validate_ok():
    spec = TOOLS["get_activity_stats"]
    validate_args(spec, {"activity_id": 1})


def test_validate_string_rejected():
    spec = TOOLS["get_activity_stats"]
    try:
        validate_args(spec, {"activity_id": "1"})
        assert False
    except ValueError as e:
        assert "类型错误" in str(e)


def test_validate_unknown_param():
    spec = TOOLS["query_activities"]
    try:
        validate_args(spec, {"bad": 1})
        assert False
    except ValueError as e:
        assert "未定义" in str(e)


def test_validate_out_of_range():
    spec = TOOLS["query_activities"]
    try:
        validate_args(spec, {"limit": 999})
        assert False
    except ValueError as e:
        assert "超过" in str(e)


def test_normal_query():
    out = json.loads(call_tool(make_conn(), admin(), "get_score_distribution", '{"activity_id":1}'))
    assert out["ok"] is True
    assert out["result"]["90-100"] == 1
    assert out["result"]["0-9"] == 1  # absent 的 0 分归入此档


def test_student_denied():
    conn = make_conn()
    out = json.loads(call_tool(conn, student(), "get_score_distribution", '{"activity_id":1}'))
    assert out["ok"] is False
    assert "无权" in out["message"]
    assert len(logs(conn)) == 1


def test_organizer_other_denied():
    conn = make_conn()
    out = json.loads(call_tool(conn, organizer_other(), "get_score_distribution", '{"activity_id":1}'))
    assert out["ok"] is False
    assert "无权查看该活动" in out["message"]


def test_organizer_own_ok():
    out = json.loads(call_tool(make_conn(), organizer_own(), "get_score_distribution", '{"activity_id":1}'))
    assert out["ok"] is True


def test_bad_param_logged():
    conn = make_conn()
    out = json.loads(call_tool(conn, admin(), "get_score_distribution", '{"activity_id":"x"}'))
    assert out["ok"] is False
    assert len(logs(conn)) == 1
    assert logs(conn)[0]["ok"] == 0


def test_unknown_tool_logged():
    conn = make_conn()
    out = json.loads(call_tool(conn, admin(), "no_such_tool", "{}"))
    assert out["ok"] is False
    assert len(logs(conn)) == 1
