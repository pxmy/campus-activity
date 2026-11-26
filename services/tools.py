"""工具调用助手：工具登记、参数校验、权限控制、执行上限与调用日志。

所有工具都是只读的；需要改数据的操作不作为工具提供。
"""
import json
import time
from datetime import datetime

MAX_TOOL_STEPS = 5
MAX_LIMIT = 20

JSON_TYPES = {str: "string", int: "integer", bool: "boolean"}


def query_activities(conn, keyword="", status=None, limit=10):
    """按标题关键词和状态查询活动列表。"""
    sql = "SELECT activity_id, title, category, start_time, status FROM activities WHERE title LIKE ?"
    args = ["%" + str(keyword) + "%"]
    if status:
        sql += " AND status = ?"
        args.append(status)
    sql += " ORDER BY start_time DESC LIMIT ?"
    args.append(limit)
    cols = ["activity_id", "title", "category", "start_time", "status"]
    return [dict(zip(cols, r)) for r in conn.execute(sql, args).fetchall()]


def get_activity_stats(conn, activity_id):
    """查询某活动的报名率与到场率。"""
    row = conn.execute("SELECT title, capacity FROM activities WHERE activity_id=?",
                       (activity_id,)).fetchone()
    if row is None:
        raise ValueError("活动不存在")
    title, capacity = row["title"], row["capacity"]
    signed, arrived = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(attendance IN ('present','late')),0) "
        "FROM registrations WHERE activity_id=? AND status='registered'",
        (activity_id,)).fetchone()
    return {"title": title, "capacity": capacity, "signed": signed, "arrived": arrived,
            "signup_rate": round(signed / capacity, 4) if capacity else None,
            "attendance_rate": round(arrived / signed, 4) if signed else None}


def get_score_distribution(conn, activity_id):
    """查询某活动实践成绩各分数段人数（每 10 分一档）。"""
    rows = conn.execute(
        "SELECT practice_score FROM registrations WHERE activity_id=? "
        "AND status='registered' AND practice_score IS NOT NULL", (activity_id,)).fetchall()
    dist = {"0-9": 0, "10-19": 0, "20-29": 0, "30-39": 0, "40-49": 0,
            "50-59": 0, "60-69": 0, "70-79": 0, "80-89": 0, "90-100": 0}
    for r in rows:
        s = r["practice_score"]
        key = "90-100" if s >= 90 else "%d-%d" % (s // 10 * 10, s // 10 * 10 + 9)
        dist[key] += 1
    return dist


def get_my_registrations(conn, student_id):
    """查询本人报名记录（凭 student_id，学生可用）。"""
    rows = conn.execute(
        "SELECT r.activity_id, a.title, a.status, r.attendance, r.practice_score "
        "FROM registrations r JOIN activities a ON r.activity_id=a.activity_id "
        "WHERE r.student_id=? AND r.status='registered' ORDER BY a.start_time DESC LIMIT ?",
        (student_id, MAX_LIMIT)).fetchall()
    return [dict(r) for r in rows]


TOOLS = {
    "query_activities": {
        "func": query_activities,
        "roles": {"student", "organizer", "admin"},
        "description": "按标题关键词和状态查询活动列表",
        "params": {
            "keyword": {"type": str, "required": False, "max_len": 30},
            "status": {"type": str, "required": False,
                       "enum": ["draft", "open", "closed", "finished", "cancelled"]},
            "limit": {"type": int, "required": False, "min": 1, "max": MAX_LIMIT},
        },
    },
    "get_activity_stats": {
        "func": get_activity_stats,
        "roles": {"organizer", "admin"},
        "description": "查询某活动的报名率与到场率",
        "params": {"activity_id": {"type": int, "required": True, "min": 1}},
    },
    "get_score_distribution": {
        "func": get_score_distribution,
        "roles": {"organizer", "admin"},
        "description": "查询某活动实践成绩分布（每 10 分一档）",
        "params": {"activity_id": {"type": int, "required": True, "min": 1}},
    },
    "get_my_registrations": {
        "func": get_my_registrations,
        "roles": {"student"},
        "description": "查询本人报名记录",
        "params": {"student_id": {"type": str, "required": True, "max_len": 20}},
    },
}


def tool_schemas(role):
    """生成当前角色有权使用的工具说明。"""
    out = []
    for name, spec in TOOLS.items():
        if role not in spec["roles"]:
            continue
        props = {}
        for p, rule in spec["params"].items():
            props[p] = {"type": JSON_TYPES[rule["type"]]}
            if "enum" in rule:
                props[p]["enum"] = rule["enum"]
        out.append({"type": "function", "function": {
            "name": name, "description": spec["description"],
            "parameters": {"type": "object", "properties": props,
                           "required": [p for p, r in spec["params"].items()
                                        if r["required"]]}}})
    return out


def validate_args(spec, args):
    """逐项校验模型给出的参数；发现问题时抛 ValueError。"""
    if not isinstance(args, dict):
        raise ValueError("参数必须是 JSON 对象")
    unknown = set(args) - set(spec["params"])
    if unknown:
        raise ValueError("存在未定义的参数：" + "、".join(sorted(unknown)))
    for name, rule in spec["params"].items():
        if name not in args:
            if rule["required"]:
                raise ValueError("缺少必填参数：" + name)
            continue
        value = args[name]
        if type(value) is not rule["type"]:  # 不用 isinstance：True 也是 int
            raise ValueError("参数 " + name + " 类型错误")
        if "min" in rule and value < rule["min"]:
            raise ValueError("参数 " + name + " 小于允许的最小值")
        if "max" in rule and value > rule["max"]:
            raise ValueError("参数 " + name + " 超过允许的最大值")
        if "max_len" in rule and len(value) > rule["max_len"]:
            raise ValueError("参数 " + name + " 过长")
        if "enum" in rule and value not in rule["enum"]:
            raise ValueError("参数 " + name + " 不在允许的取值范围内")


def _check_ownership(spec, conn, user, name, args):
    """数据归属检查：组织者只能查自己发布的活动。"""
    if "activity_id" not in args:
        return
    if user["role"] != "organizer":
        return
    row = conn.execute("SELECT organizer_id FROM activities WHERE activity_id=?",
                       (args["activity_id"],)).fetchone()
    if row is None:
        return
    if row["organizer_id"] != user.get("user_id"):
        raise PermissionError("无权查看该活动")


def call_tool(conn, user, name, args_json):
    """执行一次工具调用并写日志；无论成功失败都返回可交给模型的字符串。"""
    started = time.time()
    ok, message, result = 0, "", None
    try:
        spec = TOOLS.get(name)
        if spec is None:
            raise ValueError("不存在名为 " + name + " 的工具")
        if user["role"] not in spec["roles"]:
            raise PermissionError("当前角色无权使用工具 " + name)
        args = json.loads(args_json or "{}")
        validate_args(spec, args)
        _check_ownership(spec, conn, user, name, args)
        result = spec["func"](conn, **args)
        ok, message = 1, "ok"
    except (ValueError, PermissionError) as e:
        message = str(e)
    conn.execute(
        "INSERT INTO tool_logs (ts,username,role,tool,args_json,ok,message,duration_ms) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (datetime.now().isoformat(timespec="seconds"), user["username"], user["role"],
         name, (args_json or "")[:500], ok, message, int((time.time() - started) * 1000)))
    conn.commit()
    return json.dumps({"ok": bool(ok), "result": result, "message": message},
                      ensure_ascii=False)


def run_assistant(client, conn, user, question, model="deepseek-flash"):
    """带工具的问答循环，最多 MAX_TOOL_STEPS 轮。模型不直接接触数据库。"""
    messages = [
        {"role": "system", "content": "你是校园活动平台的助手，只能依据工具返回的数据作答；"
         "工具返回失败时如实告知用户，不得编造数据。"},
        {"role": "user", "content": question},
    ]
    tools = tool_schemas(user["role"])
    for _ in range(MAX_TOOL_STEPS):
        resp = client.chat.completions.create(model=model, messages=messages, tools=tools)
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return msg.content
        messages.append(msg)
        for tc in msg.tool_calls:
            output = call_tool(conn, user, tc.function.name, tc.function.arguments)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": output})
    return "本次提问需要的操作步骤超过上限，已停止。请把问题拆小后重试。"
