"""单元7 多模态资料处理的离线测试：不调用真实图像/语音接口。"""
import json
import sqlite3
import wave

import pytest

from services import media


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
    CREATE TABLE students(student_id TEXT PRIMARY KEY, name TEXT);
    CREATE TABLE activities(activity_id INTEGER PRIMARY KEY, title TEXT, start_time TEXT);
    CREATE TABLE registrations(reg_id INTEGER PRIMARY KEY, activity_id INTEGER,
        student_id TEXT, status TEXT, attendance TEXT);
    CREATE TABLE corrections(corr_id INTEGER PRIMARY KEY AUTOINCREMENT,
        activity_id INTEGER, row_no INTEGER, field TEXT, raw_value TEXT,
        corrected TEXT, corrected_by TEXT, ts TEXT);
    INSERT INTO students VALUES('2024010101','甲'),('2024010102','乙'),
        ('2024010103','丙'),('2024010104','丁');
    INSERT INTO activities VALUES(1,'讲座','2026-09-12T14:00');
    """)
    for sid in ('2024010101', '2024010102', '2024010103'):
        c.execute("INSERT INTO registrations(activity_id,student_id,status) "
                  "VALUES(1,?,'registered')", (sid,))
    c.commit()
    return c


# ---------- 4.7.1 签到表字段提取与校验 ----------

def test_time_validation_rejects_impossible_values():
    assert media._valid_time("14:00")
    assert media._valid_time("9:05")
    for bad in ("25:99", "99:99", "24:00", "14:60", "9:5", "", "十四点"):
        assert not media._valid_time(bad), bad


def test_student_id_format_is_ten_digits():
    assert media.is_valid_student_id("2024010101")
    for bad in ("123", "2024abc101", "20240101011", ""):
        assert not media.is_valid_student_id(bad), bad


def test_extract_signin_clears_unreadable_values(tmp_path):
    img = tmp_path / "sheet.png"
    img.write_bytes(b"fake image")
    data = {"activity_name": "讲座", "date": "2026-09-12", "rows": [
        {"seq": 1, "student_id": "2024abc101", "name": "甲", "sign_time": "25:99", "signed": "是"},
        {"seq": 2, "student_id": "2024010102", "name": "乙", "sign_time": "14:05", "signed": "是"},
    ]}
    got = media.extract_signin(str(img), llm_call=lambda *a, **k: data)
    assert got["rows"][0]["student_id"] == ""  # 非法学号填空
    assert got["rows"][0]["sign_time"] == ""    # 非法时间填空
    assert got["rows"][1]["sign_time"] == "14:05"


def test_extract_signin_rejects_missing_rows(tmp_path):
    img = tmp_path / "x.png"
    img.write_bytes(b"x")
    with pytest.raises(ValueError, match="缺少 rows"):
        media.extract_signin(str(img), llm_call=lambda *a, **k: {"activity_name": "x"})


def test_check_rows_statuses(conn):
    rows = [
        {"seq": 1, "student_id": "2024010101", "name": "甲", "sign_time": "14:01"},
        {"seq": 2, "student_id": "2024010102", "name": "张三", "sign_time": "14:02"},  # 姓名不符
        {"seq": 3, "student_id": "9999999999", "name": "某人", "sign_time": "14:03"},  # 不存在
        {"seq": 4, "student_id": "2024010104", "name": "丁", "sign_time": "14:04"},    # 未报名
        {"seq": 5, "student_id": "", "name": "", "sign_time": ""},                     # 空值
        {"seq": 6, "student_id": "2024010101", "name": "甲", "sign_time": "14:05"},    # 重复
    ]
    out = media.check_rows(conn, 1, rows)
    byseq = {r["seq"]: r["status"] for r in out}
    assert byseq[1] == "正常"
    assert byseq[2] == "姓名不符"
    assert byseq[3] == "学号不存在"
    assert byseq[4] == "未报名该活动"
    assert byseq[5] == "学号不存在"
    assert byseq[6] == "同一学号重复出现"  # 重复优先
    assert out[0]["status"] != "正常"       # 异常行排前面


def test_check_rows_rejects_too_few_rows(conn):
    rows = [{"seq": 1, "student_id": "2024010101", "name": "甲"}]
    with pytest.raises(ValueError, match="相差过大"):
        media.check_rows(conn, 1, rows, expected_count=10)


def test_field_error_summary(conn):
    rows = [{"seq": 1, "student_id": "2024010101", "name": "甲"},
            {"seq": 2, "student_id": "9999999999", "name": "乙"}]
    out = media.check_rows(conn, 1, rows)
    assert media.extract_field_errors(out) == {"学号不存在": 1}


def test_late_is_program_decision():
    assert media.is_late("14:01", "2026-09-12T14:00") is True
    assert media.is_late("14:00", "2026-09-12T14:00") is False   # 严格晚于才算
    assert media.is_late("13:59", "2026-09-12T14:00") is False
    assert media.is_late("", "2026-09-12T14:00") is None
    assert media.is_late("25:99", "2026-09-12T14:00") is None


def test_apply_signin_writes_attendance_and_corrections(conn):
    raw = [{"seq": 1, "student_id": "2024010101", "name": "甲", "sign_time": "14:00"},
           {"seq": 2, "student_id": "2024010102", "name": "乙", "sign_time": "14:00"}]
    edited = [{"seq": 1, "student_id": "2024010101", "name": "甲", "sign_time": "14:01"},
              {"seq": 2, "student_id": "2024010102", "name": "乙", "sign_time": "14:00"}]
    r = media.apply_signin(conn, 1, edited, raw, "2026-09-12T14:00", "admin")
    assert r == {"written": 2, "corrections": 1}
    att = {x[0]: x[1] for x in conn.execute(
        "SELECT student_id,attendance FROM registrations")}
    assert att["2024010101"] == "late"     # 人工改成 14:01 → 迟到
    assert att["2024010102"] == "present"
    corr = conn.execute("SELECT field,raw_value,corrected FROM corrections").fetchone()
    assert (corr["field"], corr["raw_value"], corr["corrected"]) == (
        "sign_time", "14:00", "14:01")


def test_export_corrections_bom(conn, tmp_path):
    conn.execute("INSERT INTO corrections(activity_id,row_no,field,raw_value,corrected,"
                 "corrected_by,ts) VALUES(1,1,'name','甲(错)','甲','admin',datetime('now'))")
    conn.commit()
    p = media.export_corrections(conn, 1, str(tmp_path / "修正记录.csv"))
    assert open(p, "rb").read(3) == b"\xef\xbb\xbf"  # 带 BOM
    assert "人工修正值" in open(p, encoding="utf-8-sig").read()


# ---------- 4.7.2 录音切分与转写 ----------

def make_wav(path, seconds=5, rate=16000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * (seconds * rate))


def test_split_wav_returns_segments_with_time_range(tmp_path):
    p = tmp_path / "meeting.wav"
    make_wav(p, seconds=5)
    parts = media.split_wav(str(p), str(tmp_path / "parts"), seconds=2)
    assert len(parts) == 3
    assert [(x["start"], x["end"]) for x in parts] == [
        (0, 2.0), (2, 4.0), (4, 5.0)]
    for x in parts:
        with wave.open(x["path"], "rb") as w:
            assert w.getsampwidth() == 2


def test_validate_wav_rejects_stereo_and_large_file(tmp_path):
    p = tmp_path / "stereo.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00" * 100)
    with pytest.raises(ValueError, match="单声道"):
        media.validate_wav(str(p))


def test_join_transcript_marks_failed_segment(tmp_path):
    parts = [{"index": 0, "start": 0, "end": 110.0, "text": "第一句。"},
             {"index": 1, "start": 110, "end": 200.0, "text": "", "error": "timeout"}]
    joined = media.join_transcript(parts)
    assert "0.0-110.0s" in joined
    assert "此段转写失败，待重试" in joined
    assert media.transcript_body(parts) == "第一句。"


def test_transcribe_reports_missing_text(monkeypatch, tmp_path):
    p = tmp_path / "p.wav"
    p.write_bytes(b"x")

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"unexpected": "no text"}

    monkeypatch.setattr(media.requests, "post", lambda *a, **k: Resp())
    with pytest.raises(ValueError, match="缺少 text"):
        media.transcribe(str(p), "fake-key")


# ---------- 4.7.3 待办提取 ----------

def test_extract_todos_keeps_unspecified_and_checks_quote():
    transcript = "请李浩在十一月二十八日前提交场地确认单。另外还要整理清单，没说负责人。"
    data = {"topic": "筹备会", "points": ["场地"], "decisions": ["扩容"], "todos": [
        {"task": "提交确认单", "owner": "李浩", "deadline": "11月28日",
         "quote": "请李浩在十一月二十八日前提交场地确认单。"},
        {"task": "整理清单", "owner": "", "deadline": "", "quote": "没说负责人。"},
    ]}
    got = media.extract_todos(transcript, llm_chat_json=lambda *a, **k: data)
    assert got["todos"][1]["owner"] == "未明确"   # 不编造
    assert got["todos"][1]["deadline"] == "未明确"
    assert media.locate_quote(transcript, got["todos"][0]["quote"]) == 0


def test_extract_todos_rejects_fabricated_quote():
    data = {"topic": "筹备会", "points": [], "decisions": [], "todos": [
        {"task": "虚构任务", "owner": "某同学", "deadline": "明天",
         "quote": "这句话在转写稿里根本不存在，是模型自己编出来的内容。"},
    ]}
    with pytest.raises(ValueError, match="不在转写稿中"):
        media.extract_todos("真实的转写稿很短。", llm_chat_json=lambda *a, **k: data)


def test_extract_todos_rejects_missing_quote():
    data = {"topic": "筹备会", "points": [], "decisions": [],
            "todos": [{"task": "任务", "owner": "未明确", "deadline": "未明确", "quote": ""}]}
    with pytest.raises(ValueError, match="缺少转写稿原句"):
        media.extract_todos("任意转写稿内容", llm_chat_json=lambda *a, **k: data)
