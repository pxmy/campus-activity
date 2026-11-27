"""单元5测试：时间切分、星期编码、聚类标准化与稳定性。"""
import sqlite3

import pandas as pd
import pytest

from services.ml import (cluster_diagnostics, cluster_students, evaluate,
                         name_clusters, normalize_weekday, predict,
                         student_features)


def make_history(n=20):
    """构造按时间升序的历史活动：到场人数恰好为报名的 70%。"""
    rows = []
    for i in range(n):
        rows.append({
            "activity_id": 1000 + i,
            "category": "讲座" if i % 2 == 0 else "竞赛",
            "start_time": "2025-01-%02dT10:00" % (i + 1),
            "weekday": (i % 7) + 1,
            "is_evening": i % 2,
            "signed": 100 + i,
            "arrived": int(round((100 + i) * 0.7)),
        })
    return pd.DataFrame(rows)


def test_evaluate_time_split_and_mae():
    h = make_history(20)
    r = evaluate(h)
    assert r["n_train"] == 16 and r["n_test"] == 4  # 前80%/后20%
    # 到场率恒定 0.7，两种方法的 MAE 都应接近 0
    assert r["baseline_mae"] < 0.6
    assert r["regression_mae"] < 0.6
    assert r["winner"] in ("baseline", "regression")


def test_evaluate_sorts_by_time_not_input_order():
    h = make_history(20)
    shuffled = h.sample(frac=1, random_state=7).reset_index(drop=True)
    # 打乱输入顺序不改变结果，因为 evaluate 内部按 start_time 排序
    assert evaluate(shuffled) == evaluate(h)


def test_predict_weekday_cn_equals_digit():
    h = make_history(20)
    assert predict(h, "讲座", "周一", 0, 120) == predict(h, "讲座", 1, 0, 120)
    assert predict(h, "讲座", "周日", 1, 120) == predict(h, "讲座", 7, 1, 120)


def test_normalize_weekday_rejects_invalid():
    assert normalize_weekday("周三") == 3
    assert normalize_weekday(5) == 5
    with pytest.raises(ValueError):
        normalize_weekday("周八")
    with pytest.raises(ValueError):
        normalize_weekday(9)


def make_features(n=40):
    rows = []
    for i in range(n):
        rows.append({
            "student_id": "S%03d" % i,
            "signup_count": 2 + (i % 8),
            "attendance_rate": [0.9, 0.8, 0.3, 0.5][i % 4],
            "avg_score": [88.0, 75.0, 40.0, 65.0][i % 4],
            "category_count": 2 + (i % 4),
        })
    return pd.DataFrame(rows)


def test_cluster_uses_fixed_seed_and_standardization():
    f = make_features(40)
    out1, centers1, sil1 = cluster_students(f, k=3, seed=42)
    out2, centers2, sil2 = cluster_students(f, k=3, seed=42)
    assert (out1["cluster"].tolist() == out2["cluster"].tolist())  # 固定种子可复现
    assert sil1 == sil2
    assert 0 < sil1 <= 1
    # 不同量纲的特征都参与聚类：均值和方差差异巨大仍能得到有意义的分簇
    assert set(out1["cluster"].unique()) == {0, 1, 2}


def test_cluster_diagnostics_three_candidates():
    f = make_features(40)
    diag = cluster_diagnostics(f, ks=(3, 4, 5), seed=42)
    assert [d["k"] for d in diag] == [3, 4, 5]
    for d in diag:
        assert 0 < d["silhouette"] <= 1
        assert sum(d["sizes"]) == len(f)


def test_name_clusters_has_distinct_names():
    f = make_features(40)
    _, centers, _ = cluster_students(f, k=3, seed=42)
    overall = f[["signup_count", "attendance_rate", "avg_score", "category_count"]].mean()
    names, desc = name_clusters(centers, overall)
    assert len(names) == 3 and len(set(names.values())) == 3  # 不重名
    for cid in names:
        assert names[cid] and desc[cid]  # 每个簇有名称和描述


def test_student_features_excludes_low_participation():
    c = sqlite3.connect(":memory:")
    c.executescript("""
    CREATE TABLE registrations(student_id TEXT, status TEXT, attendance TEXT,
                               practice_score INTEGER, activity_id INTEGER);
    CREATE TABLE activities(activity_id INTEGER, category TEXT);
    INSERT INTO activities VALUES(1,'讲座'),(2,'竞赛');
    INSERT INTO registrations VALUES
      ('S1','registered','present',90,1),('S1','registered','late',80,2),
      ('S2','registered','absent',0,1),
      ('S3','registered','present',70,1);
    """)
    feats, few = student_features(c)
    assert len(feats) == 1 and len(few) == 2  # S1 报名2次参与聚类，S2/S3 各1次归为参与较少
    assert feats.iloc[0]["signup_count"] == 2
    assert abs(feats.iloc[0]["attendance_rate"] - 1.0) < 1e-9
