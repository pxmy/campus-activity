-- 校园活动与实践管理平台：核心数据结构（SQLite）
-- 依据指导书附录 D.1。保留各表主键与外键关系，教师下发的数据文件方可导入。
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT NOT NULL UNIQUE,
    role        TEXT NOT NULL CHECK (role IN ('student','organizer','admin')),
    student_id  TEXT REFERENCES students(student_id)
);

CREATE TABLE IF NOT EXISTS students (
    student_id  TEXT PRIMARY KEY,            -- 学号
    name        TEXT NOT NULL,
    college     TEXT NOT NULL,
    class_name  TEXT NOT NULL,
    grade       INTEGER NOT NULL             -- 入学年份
);

CREATE TABLE IF NOT EXISTS venues (
    venue_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    capacity    INTEGER NOT NULL CHECK (capacity > 0)
);

CREATE TABLE IF NOT EXISTS activities (
    activity_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    category        TEXT NOT NULL,           -- 讲座/竞赛/志愿服务/文体/实践
    organizer_id    INTEGER NOT NULL REFERENCES users(user_id),
    venue_id        INTEGER NOT NULL REFERENCES venues(venue_id),
    start_time      TEXT NOT NULL,           -- ISO 8601，如 2026-12-05T14:00
    end_time        TEXT NOT NULL,
    signup_deadline TEXT NOT NULL,
    capacity        INTEGER NOT NULL CHECK (capacity > 0),
    status          TEXT NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft','open','closed','finished','cancelled')),
    description     TEXT DEFAULT '',
    CHECK (start_time < end_time)
);

CREATE TABLE IF NOT EXISTS registrations (
    reg_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id     INTEGER NOT NULL REFERENCES activities(activity_id),
    student_id      TEXT NOT NULL REFERENCES students(student_id),
    status          TEXT NOT NULL DEFAULT 'registered'
                    CHECK (status IN ('registered','cancelled')),
    created_at      TEXT NOT NULL,
    attendance      TEXT CHECK (attendance IN ('present','late','absent')),
    task_score      INTEGER CHECK (task_score BETWEEN 0 AND 100),
    feedback_at     TEXT,
    practice_score  INTEGER
);

-- 同一学生对同一活动只允许一条有效报名（取消后可再次报名）
CREATE UNIQUE INDEX IF NOT EXISTS uq_active_reg
    ON registrations(activity_id, student_id) WHERE status = 'registered';

CREATE TABLE IF NOT EXISTS feedback (
    feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id INTEGER NOT NULL REFERENCES activities(activity_id),
    student_id  TEXT NOT NULL REFERENCES students(student_id),
    rating      INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_logs (
    log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    username    TEXT NOT NULL,
    role        TEXT NOT NULL,
    tool        TEXT NOT NULL,
    args_json   TEXT NOT NULL,
    ok          INTEGER NOT NULL,            -- 1 成功，0 被拒绝或出错
    message     TEXT NOT NULL,
    duration_ms INTEGER NOT NULL
);

-- 单元 6 反馈分类结果
CREATE TABLE IF NOT EXISTS feedback_topics (
    topic_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    feedback_id INTEGER NOT NULL REFERENCES feedback(feedback_id),
    topic       TEXT NOT NULL,
    sentiment   TEXT NOT NULL CHECK (sentiment IN ('正面','中性','负面')),
    UNIQUE(feedback_id, topic)
);

-- 单元 7 签到表人工修正记录
CREATE TABLE IF NOT EXISTS corrections (
    corr_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id INTEGER NOT NULL,
    row_no      INTEGER NOT NULL,
    field       TEXT NOT NULL,
    raw_value   TEXT,
    corrected   TEXT,
    corrected_by TEXT NOT NULL,
    ts          TEXT NOT NULL
);

-- 单元 8 工作流运行记录
CREATE TABLE IF NOT EXISTS workflow_runs (
    run_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    week        TEXT NOT NULL,
    ts          TEXT NOT NULL,
    steps_json  TEXT NOT NULL,
    all_ok      INTEGER NOT NULL,
    output_path TEXT
);
