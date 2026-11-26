"""到场人数预测与活动分群。

要点：按时间先后切分 80/20，不随机打乱；基线与回归在同一检验集上比较；
聚类前标准化、固定随机种子；聚类结果只展示群体，不评价个人。
"""
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, silhouette_score
from sklearn.preprocessing import StandardScaler


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
    X = pd.get_dummies(history[cols], columns=["category", "weekday"], dtype=float)
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
    X = pd.get_dummies(history[cols], columns=["category", "weekday"], dtype=float)
    model = LinearRegression().fit(X, history["arrived"])
    new = pd.DataFrame([{"signed": signed, "weekday": weekday,
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
