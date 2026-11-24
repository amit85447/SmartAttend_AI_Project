"""Module 6a: data cleaning with Pandas/NumPy. Every step is counted in a report. Nothing is silently
dropped: bad values are flagged or set to NaN, duplicates are removed and counted."""
from __future__ import annotations
import numpy as np
import pandas as pd

STATUS_OK = {"present", "late", "absent", "holiday", "weekend"}


def inject_problems(df: pd.DataFrame, seed: int = 7) -> tuple[pd.DataFrame, dict]:
    """Make a deliberately MESSY copy of clean records so the cleaning pipeline can be demonstrated and
    tested against known counts. Used to build dataset/raw_attendance_export.csv (synthetic only)."""
    rng = np.random.default_rng(seed)
    d = df.copy()
    log = {}
    n = len(d)
    d["department"] = d["department"].astype(object)
    d["status"] = d["status"].astype(object)
    idx = rng.choice(n, int(.02 * n), replace=False)
    d.loc[idx, "department"] = d.loc[idx, "department"].str.upper() + " "; log["messy_department_text"] = len(idx)
    idx = rng.choice(n, int(.02 * n), replace=False)
    d.loc[idx, "status"] = d.loc[idx, "status"].str.capitalize(); log["messy_status_case"] = len(idx)
    idx = rng.choice(n, int(.01 * n), replace=False)
    d.loc[idx, "department"] = None; log["missing_department"] = len(idx)
    ok = d.index[d["check_out_ts"].notna() & d["check_in_ts"].notna()]
    idx = rng.choice(ok, int(.01 * n), replace=False)
    d.loc[idx, "check_out_ts"] = d.loc[idx, "check_in_ts"] - pd.Timedelta(hours=2); log["checkout_before_checkin"] = len(idx)
    idx = rng.choice(ok.difference(idx), int(.005 * n), replace=False)
    d.loc[idx, "working_hours"] = rng.uniform(19, 40, len(idx)).round(2); log["impossible_hours_outliers"] = len(idx)
    dup = d.sample(int(.015 * n), random_state=seed); log["duplicate_rows_added"] = len(dup)
    d = pd.concat([d, dup], ignore_index=True)
    return d.sample(frac=1, random_state=seed).reset_index(drop=True), log


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    d = df.copy()
    rep: dict = {"rows_in": len(d)}
    for col in ("full_name", "emp_code", "department", "status"):
        if col in d:
            d[col] = d[col].astype("string").str.strip()
    d["department"] = d["department"].str.title()
    d["status"] = d["status"].str.lower()
    for col in ("att_date", "check_in_ts", "check_out_ts"):
        d[col] = pd.to_datetime(d[col], errors="coerce")
    d["att_date"] = d["att_date"].dt.normalize()
    # --- duplicates: exact copies, then same employee+date (keep the most complete row)
    before = len(d)
    d = d.drop_duplicates()
    rep["exact_duplicates_removed"] = before - len(d)
    before = len(d)
    d["_complete"] = d[["check_in_ts", "check_out_ts", "working_hours"]].notna().sum(axis=1)
    d = d.sort_values("_complete", ascending=False).drop_duplicates(["emp_code", "att_date"]).drop(columns="_complete")
    rep["same_employee_day_duplicates_removed"] = before - len(d)
    # --- invalid values
    bad_status = ~d["status"].isin(STATUS_OK)
    rep["invalid_status_set_to_missing"] = int(bad_status.sum())
    d.loc[bad_status, "status"] = pd.NA
    bad_order = d["check_out_ts"].notna() & d["check_in_ts"].notna() & (d["check_out_ts"] <= d["check_in_ts"])
    rep["checkout_not_after_checkin"] = int(bad_order.sum())
    d.loc[bad_order, ["check_out_ts", "working_hours"]] = [pd.NaT, np.nan]
    # recompute hours from timestamps when both exist (single source of truth)
    calc = (d["check_out_ts"] - d["check_in_ts"]).dt.total_seconds() / 3600
    mismatch = calc.notna() & d["working_hours"].notna() & ((calc - d["working_hours"].astype(float)).abs() > 0.05)
    rep["hours_recomputed_from_timestamps"] = int(mismatch.sum())
    d["working_hours"] = calc.round(2).where(calc.notna(), d["working_hours"].astype(float))
    # --- missing values
    present = d["status"].isin(["present", "late"])
    d["missing_checkout"] = present & d["check_out_ts"].isna()
    rep["missing_checkout_flagged"] = int(d["missing_checkout"].sum())
    rep["missing_department"] = int(d["department"].isna().sum())
    d["department"] = d["department"].fillna("Unknown")
    # Imputed hours kept in a SEPARATE column so real measurements are never overwritten.
    med = d[present].groupby("emp_code")["working_hours"].transform("median")
    d["working_hours_imputed"] = d["working_hours"].where(d["working_hours"].notna() | ~present, med)
    rep["hours_imputed_with_employee_median"] = int((d["working_hours_imputed"].notna() & d["working_hours"].isna()).sum())
    # --- features
    d["checkin_minute"] = d["check_in_ts"].dt.hour * 60 + d["check_in_ts"].dt.minute
    d["checkin_hour_float"] = d["checkin_minute"] / 60
    # --- outliers (flagged, not removed): IQR rule on hours, robust z-score on arrival minute
    d["outlier_hours"] = flag_iqr(d["working_hours"])
    d["outlier_arrival"] = flag_robust_z(d["checkin_minute"])
    rep["outlier_hours_flagged"] = int(d["outlier_hours"].sum())
    rep["outlier_arrival_flagged"] = int(d["outlier_arrival"].sum())
    rep["rows_out"] = len(d)
    return d.sort_values(["att_date", "emp_code"]).reset_index(drop=True), rep


def flag_iqr(s: pd.Series, k: float = 1.5) -> pd.Series:
    q1, q3 = s.quantile(.25), s.quantile(.75)
    iqr = q3 - q1
    return ((s < q1 - k * iqr) | (s > q3 + k * iqr)).fillna(False)


def flag_robust_z(s: pd.Series, thr: float = 3.5) -> pd.Series:
    med = s.median()
    mad = (s - med).abs().median() or 1.0
    return ((0.6745 * (s - med) / mad).abs() > thr).fillna(False)
