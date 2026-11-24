"""Module 7: machine learning on attendance history (scikit-learn).

Leakage rules followed everywhere:
  * Every feature for day D is computed from days strictly BEFORE D (shift(1) before any rolling window).
  * Train/test splits are by TIME (earliest dates train, latest dates test). Never random shuffles.
  * Scalers/encoders are fitted inside sklearn Pipelines on training rows only.
Each task reports a naive baseline next to the models so you can see if the model adds anything.
Results are whatever the data gives; nothing is hard-coded.
"""
from __future__ import annotations
import json
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor, IsolationForest
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (accuracy_score, precision_score, recall_score, f1_score, roc_auc_score,
                             mean_absolute_error, classification_report)
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.tree import DecisionTreeClassifier

NUM = ["dow", "month", "tenure_days", "late_rate_5", "late_rate_20", "absent_rate_5", "absent_rate_20",
       "avg_arrival_5", "avg_arrival_20", "last_late", "last_absent", "days_since_absent", "is_monday", "is_friday"]
CAT = ["department"]


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """One row per employee per scheduled day with HISTORY-ONLY features."""
    d = df[df["status"].isin(["present", "late", "absent"])].sort_values(["emp_code", "att_date"]).copy()
    d["is_late"] = (d["status"] == "late").astype(float).where(d["status"] != "absent")
    d["is_absent"] = (d["status"] == "absent").astype(float)
    g = d.groupby("emp_code", group_keys=False)

    def hist(col, w, fn="mean"):
        return g[col].apply(lambda s: s.shift(1).rolling(w, min_periods=2).agg(fn))
    d["late_rate_5"], d["late_rate_20"] = hist("is_late", 5), hist("is_late", 20)
    d["absent_rate_5"], d["absent_rate_20"] = hist("is_absent", 5), hist("is_absent", 20)
    d["avg_arrival_5"], d["avg_arrival_20"] = hist("checkin_minute", 5), hist("checkin_minute", 20)
    d["last_late"] = g["is_late"].shift(1)
    d["last_absent"] = g["is_absent"].shift(1)
    d["_abs_date"] = d["att_date"].where(d["is_absent"] == 1)
    d["_last_abs"] = g["_abs_date"].apply(lambda s: s.shift(1).ffill())
    d["days_since_absent"] = (d["att_date"] - d["_last_abs"]).dt.days.fillna(365)
    d["dow"] = d["att_date"].dt.dayofweek
    d["month"] = d["att_date"].dt.month
    d["is_monday"], d["is_friday"] = (d["dow"] == 0).astype(int), (d["dow"] == 4).astype(int)
    first = g["att_date"].transform("min")
    d["tenure_days"] = (d["att_date"] - first).dt.days
    return d.dropna(subset=["late_rate_20", "absent_rate_20", "avg_arrival_20"]).drop(columns=["_abs_date", "_last_abs"])


def _fill_arrival(X):
    return X.fillna({"avg_arrival_5": X["avg_arrival_20"], "last_late": 0})


def _models():
    def pre(scale):
        steps = [("imp", SimpleImputer(strategy="median"))] + ([("sc", StandardScaler())] if scale else [])
        return ColumnTransformer([("num", Pipeline(steps), NUM),   # imputer fitted on TRAIN rows only
                                  ("cat", OneHotEncoder(handle_unknown="ignore"), CAT)])
    return {
        "LogisticRegression": Pipeline([("p", pre(True)), ("m", LogisticRegression(max_iter=1000, class_weight="balanced"))]),
        "DecisionTree": Pipeline([("p", pre(False)), ("m", DecisionTreeClassifier(max_depth=5, min_samples_leaf=40, class_weight="balanced", random_state=0))]),
        "RandomForest": Pipeline([("p", pre(False)), ("m", RandomForestClassifier(n_estimators=300, min_samples_leaf=20, class_weight="balanced_subsample", n_jobs=-1, random_state=0))]),
    }


def time_split(d: pd.DataFrame, frac=0.75):
    cut = d["att_date"].sort_values().iloc[int(len(d) * frac)]
    return d[d["att_date"] < cut], d[d["att_date"] >= cut], cut


def _eval_classifier(d, target, baseline_col):
    d = d.copy()
    d[NUM] = d[NUM].apply(pd.to_numeric)
    d["last_late"] = d["last_late"].fillna(0); d["avg_arrival_5"] = d["avg_arrival_5"].fillna(d["avg_arrival_20"])
    tr, te, cut = time_split(d)
    X = lambda x: x[NUM + CAT]
    res = {"train_rows": len(tr), "test_rows": len(te), "split_date": str(cut.date()),
           "test_positive_rate": round(float(te[target].mean()), 4), "models": {}}
    base = te[baseline_col].fillna(0).astype(int)
    res["baseline_repeat_last_day"] = {"accuracy": round(accuracy_score(te[target], base), 4),
                                       "f1": round(f1_score(te[target], base, zero_division=0), 4)}
    fitted = {}
    for name, pipe in _models().items():
        pipe.fit(X(tr), tr[target])
        proba = pipe.predict_proba(X(te))[:, 1]
        pred = (proba >= 0.5).astype(int)
        res["models"][name] = {"accuracy": round(accuracy_score(te[target], pred), 4),
                               "precision": round(precision_score(te[target], pred, zero_division=0), 4),
                               "recall": round(recall_score(te[target], pred, zero_division=0), 4),
                               "f1": round(f1_score(te[target], pred, zero_division=0), 4),
                               "roc_auc": round(roc_auc_score(te[target], proba), 4)}
        fitted[name] = pipe
    rf = fitted["RandomForest"]
    names = NUM + list(rf.named_steps["p"].named_transformers_["cat"].get_feature_names_out(CAT))
    imp = pd.Series(rf.named_steps["m"].feature_importances_, index=names).sort_values(ascending=False)
    res["rf_top_features"] = {k: round(float(v), 4) for k, v in imp.head(6).items()}
    return res, fitted


def late_arrival_model(feat: pd.DataFrame):
    d = feat[feat["status"].isin(["present", "late"])].copy()
    d["y"] = (d["status"] == "late").astype(int)
    return _eval_classifier(d, "y", "last_late")


def absenteeism_model(feat: pd.DataFrame):
    d = feat.copy()
    d["y"] = d["is_absent"].astype(int)
    return _eval_classifier(d, "y", "last_absent")


def pattern_classification(df: pd.DataFrame):
    """Predict an employee's NEXT-month attendance pattern from THIS month's behaviour.
    Pattern labels are rule-defined from next month's late%/absent% (Punctual / Occasionally late /
    Chronically late / Frequent absentee); features come only from the current month."""
    d = df[df["status"].isin(["present", "late", "absent"])].copy()
    d["month"] = d["att_date"].dt.to_period("M")
    m = d.groupby(["emp_code", "month"]).agg(
        days=("status", "size"), late=("status", lambda s: (s == "late").sum()),
        absent=("status", lambda s: (s == "absent").sum()), arrival=("checkin_minute", "mean"),
        arrival_std=("checkin_minute", "std"), hours=("working_hours", "mean")).reset_index()
    m = m[m["days"] >= 10]
    m["late_pct"] = m["late"] / (m["days"] - m["absent"]).clip(lower=1)
    m["absent_pct"] = m["absent"] / m["days"]

    def label(r):
        if r.absent_pct >= 0.12:
            return "Frequent absentee"
        if r.late_pct >= 0.40:
            return "Chronically late"
        if r.late_pct >= 0.15:
            return "Occasionally late"
        return "Punctual"
    m["pattern"] = m.apply(label, axis=1)
    m = m.sort_values(["emp_code", "month"])
    m["next_pattern"] = m.groupby("emp_code")["pattern"].shift(-1)
    m["next_month"] = m.groupby("emp_code")["month"].shift(-1)
    m = m.dropna(subset=["next_pattern"])
    feats = ["late_pct", "absent_pct", "arrival", "arrival_std", "hours"]
    m[feats] = m[feats].fillna(m[feats].median())
    months = sorted(m["next_month"].unique())
    cut = months[int(len(months) * 0.7)]
    tr, te = m[m["next_month"] < cut], m[m["next_month"] >= cut]
    clf = RandomForestClassifier(n_estimators=300, min_samples_leaf=3, class_weight="balanced", random_state=0).fit(tr[feats], tr["next_pattern"])
    pred = clf.predict(te[feats])
    base = te["pattern"]                       # baseline: next month = this month's label
    return {"train_rows": len(tr), "test_rows": len(te), "test_from_month": str(cut),
            "class_counts_test": te["next_pattern"].value_counts().to_dict(),
            "random_forest_accuracy": round(accuracy_score(te["next_pattern"], pred), 4),
            "baseline_same_as_this_month_accuracy": round(accuracy_score(te["next_pattern"], base), 4),
            "report": classification_report(te["next_pattern"], pred, output_dict=True, zero_division=0)}, clf


def anomaly_detection(df: pd.DataFrame, contamination=0.01):
    """Isolation Forest on per-record features, with each person's own norm removed (arrival deviation)."""
    d = df[df["status"].isin(["present", "late"]) & df["checkin_minute"].notna()].copy()
    d["arrival_dev"] = d["checkin_minute"] - d.groupby("emp_code")["checkin_minute"].transform("median")
    d["hours_f"] = d["working_hours"].fillna(d["working_hours_imputed"]) if "working_hours_imputed" in d else d["working_hours"]
    cols = ["arrival_dev", "hours_f", "face_conf_in", "liveness_in"]
    cols = [c for c in cols if c in d and d[c].notna().mean() > 0.5]
    X = d[cols].astype(float)
    X = X.fillna(X.median())
    iso = IsolationForest(n_estimators=300, contamination=contamination, random_state=0).fit(X)
    d["anomaly_score"] = -iso.score_samples(X)
    d["is_anomaly"] = iso.predict(X) == -1
    out = d.sort_values("anomaly_score", ascending=False)
    flagged = out[out["is_anomaly"]]
    # Proxy check (not ground truth): how many flagged days are arrivals >45 min later than the person's usual?
    proxy = float((flagged["arrival_dev"] > 45).mean()) if len(flagged) else float("nan")
    summary = {"records_scored": len(d), "flagged": int(len(flagged)), "features_used": cols,
               "share_of_flagged_with_arrival_over_45min_later_than_usual": round(proxy, 3)}
    return summary, out[["emp_code", "full_name", "department", "att_date", "check_in_ts", "working_hours",
                         "arrival_dev", "anomaly_score", "is_anomaly"]]


def forecast_attendance(daily_df: pd.DataFrame, horizon=14):
    """Forecast daily attendance % `horizon` working days ahead using only features known `horizon` days earlier."""
    s = daily_df.set_index("att_date")["attendance_pct"].astype(float)
    d = pd.DataFrame({"y": s})
    d["dow"] = d.index.dayofweek
    d["month"] = d.index.month
    d["lag_h"] = s.shift(horizon)
    d["lag_h5"] = s.shift(horizon + 5)
    d["roll20_h"] = s.shift(horizon).rolling(20, min_periods=10).mean()
    d = d.dropna()
    cut = int(len(d) * 0.8)
    tr, te = d.iloc[:cut], d.iloc[cut:]
    X = ["dow", "month", "lag_h", "lag_h5", "roll20_h"]
    rf = RandomForestRegressor(n_estimators=300, min_samples_leaf=5, random_state=0).fit(tr[X], tr["y"])
    ridge = Ridge(alpha=1.0).fit(tr[X], tr["y"])
    naive = te["lag_h5"]                         # seasonal-naive-ish baseline: value 1 week before lag
    mean_base = np.full(len(te), tr["y"].mean())
    metrics = {"horizon_working_days": horizon, "test_days": len(te),
               "MAE_random_forest": round(mean_absolute_error(te["y"], rf.predict(te[X])), 3),
               "MAE_ridge": round(mean_absolute_error(te["y"], ridge.predict(te[X])), 3),
               "MAE_baseline_train_mean": round(mean_absolute_error(te["y"], mean_base), 3),
               "MAE_baseline_naive_lag": round(mean_absolute_error(te["y"], naive), 3)}
    # forecast the next `horizon` working days after the last observed date
    full = pd.concat([tr, te])
    rf = RandomForestRegressor(n_estimators=300, min_samples_leaf=5, random_state=0).fit(full[X], full["y"])
    future_dates = pd.bdate_range(s.index.max() + pd.Timedelta(days=1), periods=horizon)
    allv = s.reindex(s.index.union(future_dates))
    rows = []
    pos = {dt: i for i, dt in enumerate(allv.index)}
    for dt in future_dates:
        i = pos[dt]
        lag_h = allv.iloc[i - horizon] if i - horizon >= 0 else np.nan
        lag_h5 = allv.iloc[i - horizon - 5] if i - horizon - 5 >= 0 else np.nan
        roll = allv.iloc[max(0, i - horizon - 19): i - horizon + 1].mean()
        rows.append({"date": dt, "dow": dt.dayofweek, "month": dt.month, "lag_h": lag_h, "lag_h5": lag_h5, "roll20_h": roll})
    F = pd.DataFrame(rows).dropna()
    F["forecast_attendance_pct"] = rf.predict(F[X]).round(2)
    return metrics, F[["date", "forecast_attendance_pct"]]


def run_all(df_clean: pd.DataFrame, daily_df: pd.DataFrame, out_json=None) -> dict:
    feat = build_features(df_clean)
    late, _ = late_arrival_model(feat)
    absn, _ = absenteeism_model(feat)
    pat, _ = pattern_classification(df_clean)
    anom, _ = anomaly_detection(df_clean)
    fc, _ = forecast_attendance(daily_df)
    res = {"late_arrival": late, "absenteeism": absn, "pattern_classification": pat, "anomaly_detection": anom, "forecast": fc}
    if out_json:
        with open(out_json, "w") as f:
            json.dump(res, f, indent=2, default=str)
    return res
