"""统计口径与指标：本文件不出现任何 streamlit 代码。

口径见 docs/统计口径.md。要点：
- 汇总比率用“分子之和 ÷ 分母之和”，不对比率取平均；
- 分母为 0 时返回 None（页面显示“—”）；
- 已取消报名不计入有效报名；已取消和草稿活动不计入统计；
- 到场含准时和迟到；完成为任务分≥60，到场未评定计入分母不计入分子。
"""
import pandas as pd


def activity_metrics(conn, filters):
    """按筛选条件返回每场活动一行的指标 DataFrame。

    filters 可含：date_from, date_to, category, college, organizer_id；缺省不限制。
    返回列：activity_id,title,capacity,signed,arrived,completed,ungraded,
    signup_rate,attendance_rate,completion_rate,avg_score。
    """
    sql = (
        "SELECT a.activity_id, a.title, a.capacity, a.category, a.start_time, "
        "  a.organizer_id, "
        "  COUNT(r.reg_id) AS signed, "
        "  COALESCE(SUM(r.attendance IN ('present','late')),0) AS arrived, "
        "  COALESCE(SUM(r.task_score >= 60),0) AS completed, "
        "  COALESCE(SUM(r.attendance IS NOT NULL AND r.task_score IS NULL),0) AS ungraded, "
        "  COUNT(r.practice_score) AS scored_n, "
        "  AVG(CASE WHEN r.practice_score IS NOT NULL THEN r.practice_score END) AS avg_score "
        "FROM activities a "
        "LEFT JOIN registrations r ON r.activity_id=a.activity_id "
        "  AND r.status='registered' "
        "WHERE a.status NOT IN ('cancelled','draft') "
    )
    args = []
    if filters.get("date_from"):
        sql += " AND a.start_time >= ?"; args.append(filters["date_from"])
    if filters.get("date_to"):
        sql += " AND a.start_time <= ?"; args.append(filters["date_to"])
    if filters.get("category"):
        sql += " AND a.category = ?"; args.append(filters["category"])
    if filters.get("organizer_id") is not None:
        sql += " AND a.organizer_id = ?"; args.append(filters["organizer_id"])
    if filters.get("college"):
        # 学院筛选：分子分母都只统计该学院学生，通过派生列实现
        sql += (" AND r.student_id IN (SELECT student_id FROM students WHERE college=?)")
        args.append(filters["college"])
    sql += " GROUP BY a.activity_id ORDER BY a.start_time"

    rows = conn.execute(sql, args).fetchall()
    data = []
    for r in rows:
        capacity, signed, arrived, completed = (
            r["capacity"], r["signed"], r["arrived"], r["completed"])
        avg = r["avg_score"]
        data.append({
            "activity_id": r["activity_id"], "title": r["title"],
            "capacity": capacity, "signed": signed, "arrived": arrived,
            "completed": completed,             "ungraded": r["ungraded"],
            "scored_n": r["scored_n"],
            "signup_rate": signed / capacity if capacity else None,
            "attendance_rate": arrived / signed if signed else None,
            "completion_rate": completed / arrived if arrived else None,
            "avg_score": None if avg is None else avg,
        })
    return pd.DataFrame(data, columns=[
        "activity_id", "title", "capacity", "signed", "arrived", "completed",
        "ungraded", "scored_n", "signup_rate", "attendance_rate",
        "completion_rate", "avg_score"])


def summary(df):
    """汇总：分子之和÷分母之和；分母为 0 返回 None。

    平均实践成绩按各活动已有成绩人数加权还原总分后相除，避免对平均值再取平均。
    """
    if df.empty:
        return {"activities": 0, "signed": 0, "signup_rate": None,
                "attendance_rate": None, "completion_rate": None, "avg_score": None}
    cap_sum = int(df["capacity"].sum())
    signed_sum = int(df["signed"].sum())
    arrived_sum = int(df["arrived"].sum())
    completed_sum = int(df["completed"].sum())
    total_score = float((df["avg_score"].fillna(0) * df["scored_n"]).sum())
    n_scored = int(df["scored_n"].sum())
    return {
        "activities": len(df),
        "signed": signed_sum,
        "signup_rate": signed_sum / cap_sum if cap_sum else None,
        "attendance_rate": arrived_sum / signed_sum if signed_sum else None,
        "completion_rate": completed_sum / arrived_sum if arrived_sum else None,
        "avg_score": total_score / n_scored if n_scored else None,
    }


def score_distribution(conn, filters):
    """按筛选条件返回实践成绩分布，每 10 分一档，另有 100 分档与“未评定”档。

    与指标口径保持一致：只统计有效报名、排除取消/草稿活动，学院筛选只计该学院学生。
    返回 DataFrame 两列：分数段、人数；档位顺序固定，空档也保留（人数为 0）。
    """
    sql = (
        "SELECT r.practice_score AS score FROM registrations r "
        "JOIN activities a ON r.activity_id=a.activity_id "
        "WHERE r.status='registered' AND a.status NOT IN ('cancelled','draft') "
    )
    args = []
    if filters.get("date_from"):
        sql += " AND a.start_time >= ?"; args.append(filters["date_from"])
    if filters.get("date_to"):
        sql += " AND a.start_time <= ?"; args.append(filters["date_to"])
    if filters.get("category"):
        sql += " AND a.category = ?"; args.append(filters["category"])
    if filters.get("organizer_id") is not None:
        sql += " AND a.organizer_id = ?"; args.append(filters["organizer_id"])
    if filters.get("college"):
        sql += " AND r.student_id IN (SELECT student_id FROM students WHERE college=?)"
        args.append(filters["college"])

    labels = ["%d-%d" % (lo, lo + 9) for lo in range(0, 100, 10)] + ["100", "未评定"]
    counts = {label: 0 for label in labels}
    for row in conn.execute(sql, args).fetchall():
        s = row["score"]
        if s is None:
            counts["未评定"] += 1
        elif s >= 100:
            counts["100"] += 1
        else:
            counts["%d-%d" % (s // 10 * 10, s // 10 * 10 + 9)] += 1
    return pd.DataFrame([{"分数段": label, "人数": counts[label]} for label in labels])


def filter_options(conn):
    """返回看板筛选项的可选值：活动类别列表与学院列表。"""
    categories = [r[0] for r in conn.execute(
        "SELECT DISTINCT category FROM activities WHERE category IS NOT NULL ORDER BY category").fetchall()]
    colleges = [r[0] for r in conn.execute(
        "SELECT DISTINCT college FROM students WHERE college IS NOT NULL ORDER BY college").fetchall()]
    return {"categories": categories, "colleges": colleges}


def display_frame(df):
    """把指标表转成页面展示用的中文表：比率显示为一位小数百分比，分母为 0 显示“—”。

    页面明细表与导出文件都调用本函数，保证两处数值完全一致。
    """
    show = df[["title", "capacity", "signed", "arrived", "completed", "ungraded",
               "signup_rate", "attendance_rate", "completion_rate", "avg_score"]].copy()
    for col in ["signup_rate", "attendance_rate", "completion_rate"]:
        show[col] = show[col].apply(lambda v: "—" if pd.isna(v) else "%.1f%%" % (v * 100))
    show["avg_score"] = show["avg_score"].apply(
        lambda v: "—" if pd.isna(v) else round(v, 1))
    return show.rename(columns={
        "title": "活动名称", "capacity": "名额", "signed": "有效报名", "arrived": "到场",
        "completed": "完成", "ungraded": "未评定", "signup_rate": "报名率",
        "attendance_rate": "到场率", "completion_rate": "完成率",
        "avg_score": "平均实践成绩"})


def export_frame(df, path):
    """导出 DataFrame：CSV 用带 BOM 的 UTF-8（Excel 打开中文正常），Excel 用 openpyxl。"""
    path = str(path)
    if path.lower().endswith(".csv"):
        df.to_csv(path, index=False, encoding="utf-8-sig")
    else:
        df.to_excel(path, index=False, engine="openpyxl")
    return path
