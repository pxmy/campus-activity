"""到场人数预测与活动分群。

要点：按时间先后切分 80/20，不随机打乱；基线与回归在同一检验集上比较；
聚类前标准化、固定随机种子；聚类结果只展示群体，不评价个人。
星期在历史数据中是 1—7 的数字，页面可能传入“周一”，统一在业务层归一化。
"""
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, silhouette_score
from sklearn.preprocessing import StandardScaler

# 页面下拉框的中文星期与历史数据数字编码的对应关系
WEEKDAY_CN = {"周一": 1, "周二": 2, "周三": 3, "周四": 4,
              "周五": 5, "周六": 6, "周日": 7}
WEEKDAY_COLS = ["weekday_%d" % i for i in range(1, 8)]


def normalize_weekday(value):
    """把中文星期或数字星期统一为 1—7 的整数；无法识别时抛出 ValueError。"""
    if isinstance(value, str):
        if value in WEEKDAY_CN:
            return WEEKDAY_CN[value]
        try:
            value = int(value)
        except ValueError as e:
            raise ValueError("无法识别的星期：" + value) from e
    value = int(value)
    if value not in range(1, 8):
        raise ValueError("星期须为 1—7：%s" % value)
    return value


def evaluate(history):
    """比较基线（同类平均到场率×报名人数）与线性回归的 MAE。

    history 每行一场已结束活动，按 start_time 升序；需要列：
    category, weekday, is_evening, signed, arrived。
    """
    history = history.sort_values("start_time").reset_index(drop=True)
    cut = int(len(history) * 0.8)
    train, test = history.iloc[:cut], history.iloc[cut:]

    rate = (train["arrived"].groupby(train["category"]).sum()
            / train["signed"].groupby(train["category"]).sum())
    overall = train["arrived"].sum() / train["signed"].sum()
    base_pred = test["signed"] * test["category"].map(rate).fillna(overall)

    cols = ["signed", "weekday", "is_evening", "category"]
    hist = history.copy()
    hist["weekday"] = hist["weekday"].map(normalize_weekday)
    X = pd.get_dummies(hist[cols], columns=["category", "weekday"], dtype=float)
    model = LinearRegression().fit(X.iloc[:cut], train["arrived"])
    reg_pred = model.predict(X.iloc[cut:])

    coefs = {}
    if "signed" in X.columns:
        coefs["signed"] = round(float(model.coef_[X.columns.get_loc("signed")]), 3)
    if "is_evening" in X.columns:
        coefs["is_evening"] = round(float(model.coef_[X.columns.get_loc("is_evening")]), 3)

    return {
        "n_train": len(train), "n_test": len(test),
        "baseline_mae": round(float(mean_absolute_error(test["arrived"], base_pred)), 2),
        "regression_mae": round(float(mean_absolute_error(test["arrived"], reg_pred)), 2),
        "coefs": coefs,
        "cat_rates": {str(k): round(float(v), 4) for k, v in rate.items()},
        "overall_rate": round(float(overall), 4),
        "winner": "baseline" if mean_absolute_error(test["arrived"], base_pred)
                  <= mean_absolute_error(test["arrived"], reg_pred) else "regression",
    }


def predict(history, category, weekday, is_evening, signed):
    """对一场新活动给出基线预测与回归预测。"""
    history = history.sort_values("start_time").reset_index(drop=True)
    rate = (history["arrived"].groupby(history["category"]).sum()
            / history["signed"].groupby(history["category"]).sum())
    overall = history["arrived"].sum() / history["signed"].sum()
    base = signed * rate.get(category, overall)
    cols = ["signed", "weekday", "is_evening", "category"]
    hist = history.copy()
    hist["weekday"] = hist["weekday"].map(normalize_weekday)
    X = pd.get_dummies(hist[cols], columns=["category", "weekday"], dtype=float)
    model = LinearRegression().fit(X, hist["arrived"])
    new = pd.DataFrame([{"signed": signed, "weekday": normalize_weekday(weekday),
                         "is_evening": int(is_evening), "category": category}])
    new = pd.get_dummies(new, columns=["category", "weekday"], dtype=float)
    new = new.reindex(columns=X.columns, fill_value=0.0)
    return {"baseline": round(float(base), 1), "regression": round(float(model.predict(new)[0]), 1)}


def cluster_students(features, k=3, seed=42):
    """按参与特征聚类。features 每行一名学生，列：报名次数、到场率、平均成绩、类别数。

    参与次数 < 2 的学生由调用方另行归为“参与较少”，不参与聚类。
    返回 (带簇标签的 DataFrame, 各簇特征均值, 轮廓系数)。
    """
    cols = ["signup_count", "attendance_rate", "avg_score", "category_count"]
    X = features[cols].fillna(0)
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)
    km = KMeans(n_clusters=k, random_state=seed, n_init=10)
    labels = km.fit_predict(Xs)
    out = features.copy()
    out["cluster"] = labels
    centers = out.groupby("cluster")[cols].mean()
    score = float(silhouette_score(Xs, labels)) if len(set(labels)) > 1 else None
    return out, centers, score


def name_clusters(centers, overall):
    """按各簇特征均值给簇起名并写一句描述，避免出现重名。

    centers 为 cluster_students 返回的各簇均值，overall 为全体学生各特征均值。
    命名依据到场率与相对报名次数，描述用通俗语言概括四个特征的均值。
    返回 (簇号→名称, 簇号→描述)。
    """
    names, descriptions, used = {}, {}, {}
    for cid, row in centers.iterrows():
        signup_ratio = (row["signup_count"] / overall["signup_count"]
                        if overall["signup_count"] else 1.0)
        rate = row["attendance_rate"]
        if rate < 0.5 and signup_ratio >= 0.9:
            base = "报名多到场少型"
        elif rate < 0.5:
            base = "低到场型"
        elif signup_ratio > 1.15 and rate >= 0.65:
            base = "高频稳定型"
        elif signup_ratio < 0.85 and rate >= 0.65:
            base = "低频稳定型"
        elif rate >= 0.65:
            base = "稳定参与型"
        else:
            base = "中间型"
        used[base] = used.get(base, 0) + 1
        name = base if used[base] == 1 else "%s%d" % (base, used[base])
        names[int(cid)] = name
        descriptions[int(cid)] = (
            "报名 %.1f 次、到场率 %.0f%%、平均成绩 %.1f 分、参加 %.1f 类活动。"
            % (row["signup_count"], rate * 100, row["avg_score"], row["category_count"]))
    return names, descriptions


def student_features(conn):
    """从报名表汇总每名学生的参与特征，并分离参与次数少于 2 次的学生。

    返回 (可聚类的特征 DataFrame, 参与较少 DataFrame)，两者都含 student_id 与四项特征。
    """
    cols = ["student_id", "signup_count", "attendance_rate", "avg_score", "category_count"]
    rows = conn.execute(
        "SELECT r.student_id, COUNT(*) AS signup_count, "
        "COALESCE(SUM(r.attendance IN ('present','late'))*1.0/COUNT(*),0) AS attendance_rate, "
        "AVG(CASE WHEN r.practice_score IS NOT NULL THEN r.practice_score END) AS avg_score, "
        "COUNT(DISTINCT a.category) AS category_count "
        "FROM registrations r JOIN activities a ON r.activity_id=a.activity_id "
        "WHERE r.status='registered' GROUP BY r.student_id").fetchall()
    data = pd.DataFrame([dict(zip(cols, r)) for r in rows], columns=cols)
    if data.empty:
        return data, data.copy()
    few = data[data["signup_count"] < 2].reset_index(drop=True)
    features = data[data["signup_count"] >= 2].reset_index(drop=True)
    return features, few


def cluster_diagnostics(features, ks=(3, 4, 5), seed=42):
    """对一组候选簇数返回轮廓系数与各簇人数，供页面对比选择。"""
    cols = ["signup_count", "attendance_rate", "avg_score", "category_count"]
    Xs = StandardScaler().fit_transform(features[cols].fillna(0))
    out = []
    for k in ks:
        km = KMeans(n_clusters=k, random_state=seed, n_init=10)
        labels = km.fit_predict(Xs)
        out.append({
            "k": k,
            "silhouette": round(float(silhouette_score(Xs, labels)), 3),
            "sizes": sorted(pd.Series(labels).value_counts().tolist(), reverse=True),
        })
    return out
