"""Module 6b: exploratory analysis. Rates use only scheduled working days (present+late+absent)."""
from __future__ import annotations
import numpy as np
import pandas as pd
from scipy import stats


def _flags(d):
    d = d[d["status"].isin(["present", "late", "absent"])].copy()
    d["is_present"] = d["status"].isin(["present", "late"]).astype(int)
    d["is_late"] = (d["status"] == "late").astype(int)
    d["is_absent"] = (d["status"] == "absent").astype(int)
    return d


def daily(df):
    d = _flags(df)
    g = d.groupby("att_date").agg(scheduled=("is_present", "size"), present=("is_present", "sum"),
                                  late=("is_late", "sum"), absent=("is_absent", "sum"),
                                  avg_hours=("working_hours", "mean"))
    g["attendance_pct"] = (100 * g["present"] / g["scheduled"]).round(2)
    g["late_pct_of_present"] = (100 * g["late"] / g["present"].replace(0, np.nan)).round(2)
    return g.reset_index()


def monthly(df):
    d = _flags(df)
    d["month"] = d["att_date"].dt.to_period("M").astype(str)
    g = d.groupby("month").agg(scheduled=("is_present", "size"), present=("is_present", "sum"),
                               late=("is_late", "sum"), absent=("is_absent", "sum"), avg_hours=("working_hours", "mean"))
    g["attendance_pct"] = (100 * g["present"] / g["scheduled"]).round(2)
    g["growth_pct_vs_prev_month"] = g["attendance_pct"].diff().round(2)
    return g.reset_index()


def by_department(df):
    d = _flags(df)
    g = d.groupby("department").agg(scheduled=("is_present", "size"), present=("is_present", "sum"),
                                    late=("is_late", "sum"), absent=("is_absent", "sum"), avg_hours=("working_hours", "mean"),
                                    avg_checkin_hour=("checkin_hour_float", "mean"))
    g["attendance_pct"] = (100 * g["present"] / g["scheduled"]).round(2)
    g["late_pct"] = (100 * g["late"] / g["present"].replace(0, np.nan)).round(2)
    return g.round(2).reset_index().sort_values("attendance_pct", ascending=False)


def punctuality(df, min_days=20):
    d = _flags(df)
    p = d[d["is_present"] == 1]
    g = p.groupby(["emp_code", "full_name", "department"]).agg(
        days_present=("is_present", "size"), late_days=("is_late", "sum"),
        avg_late_min=("late_minutes", "mean"), checkin_std_min=("checkin_minute", "std"),
        avg_hours=("working_hours", "mean")).reset_index()
    g["late_pct"] = (100 * g["late_days"] / g["days_present"]).round(1)
    g = g[g["days_present"] >= min_days]
    g["punctuality_rank"] = g["late_pct"].rank(method="min").astype(int)
    return g.round(2).sort_values("punctuality_rank")


def weekday_pattern(df):
    d = _flags(df)
    d["weekday"] = d["att_date"].dt.day_name()
    g = d.groupby("weekday").agg(scheduled=("is_present", "size"), absent=("is_absent", "sum"), late=("is_late", "sum"))
    g["absent_pct"] = (100 * g["absent"] / g["scheduled"]).round(2)
    return g.reindex(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]).reset_index()


def trend(daily_df):
    """Linear trend of daily attendance % (slope per week) with p-value, and 7-day rolling mean."""
    y = daily_df["attendance_pct"].to_numpy(float)
    x = np.arange(len(y))
    r = stats.linregress(x, y)
    out = daily_df[["att_date", "attendance_pct"]].copy()
    out["rolling_7d"] = out["attendance_pct"].rolling(7, min_periods=3).mean()
    return out, {"slope_pct_points_per_week": round(r.slope * 5, 4), "p_value": round(r.pvalue, 4), "r2": round(r.rvalue ** 2, 4)}


def stat_tests(df):
    """Do departments differ in attendance? Does weekday matter for absence? (chi-square / Kruskal-Wallis)."""
    d = _flags(df)
    out = {}
    ct = pd.crosstab(d["department"], d["is_absent"])
    chi2, p, dof, _ = stats.chi2_contingency(ct)
    out["absence_vs_department_chi2"] = {"chi2": round(chi2, 3), "dof": int(dof), "p_value": round(p, 5)}
    ct = pd.crosstab(d["att_date"].dt.dayofweek, d["is_absent"])
    chi2, p, dof, _ = stats.chi2_contingency(ct)
    out["absence_vs_weekday_chi2"] = {"chi2": round(chi2, 3), "dof": int(dof), "p_value": round(p, 5)}
    groups = [g["checkin_minute"].dropna() for _, g in d[d["is_present"] == 1].groupby("department")]
    h, p = stats.kruskal(*groups)
    out["checkin_time_vs_department_kruskal"] = {"H": round(h, 3), "p_value": round(p, 5)}
    return out


def location_summary(loc: pd.DataFrame):
    """loc = location_logs joined with workplace name. Rejected attempts show failed GPS checks."""
    g = loc.groupby(["workplace", "result"]).agg(logs=("log_id", "size"), median_distance_m=("distance_m", "median"),
                                                  p95_distance_m=("distance_m", lambda s: s.quantile(.95)),
                                                  median_accuracy_m=("accuracy_m", "median")).round(1).reset_index()
    return g
