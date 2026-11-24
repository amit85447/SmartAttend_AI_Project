import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from analytics import cleaning, eda, ml
from database import seed_synthetic
from services import attendance as A


@pytest.fixture(scope="module")
def raw(tmp_path_factory):
    e = create_engine(f"sqlite:///{tmp_path_factory.mktemp('d')/'s.db'}", future=True)
    seed_synthetic.seed(e, n_employees=40, days=200)
    return A.records(eng=e)


def test_cleaning_removes_exactly_the_injected_problems(raw):
    messy, log = cleaning.inject_problems(raw)
    clean, rep = cleaning.clean(messy)
    assert rep["exact_duplicates_removed"] == log["duplicate_rows_added"]
    assert rep["rows_out"] == len(raw)
    assert rep["checkout_not_after_checkin"] == log["checkout_before_checkin"]
    assert rep["missing_department"] == log["missing_department"]
    assert rep["hours_recomputed_from_timestamps"] == log["impossible_hours_outliers"]
    assert set(clean["status"].dropna()) <= {"present", "late", "absent"}
    assert clean["department"].str.strip().eq(clean["department"]).all()


def test_eda_numbers_are_consistent(raw):
    clean, _ = cleaning.clean(raw)
    d = eda.daily(clean)
    assert (d["present"] + d["absent"] == d["scheduled"]).all()
    assert d["attendance_pct"].between(0, 100).all()
    assert eda.by_department(clean)["scheduled"].sum() == d["scheduled"].sum()


def test_features_use_only_the_past(raw):
    """Changing a FUTURE day's status must not change that earlier day's features."""
    clean, _ = cleaning.clean(raw)
    f1 = ml.build_features(clean)
    emp = f1["emp_code"].iloc[0]
    sub = clean[clean.emp_code == emp].sort_values("att_date")
    cutoff = sub["att_date"].iloc[len(sub) // 2]
    mod = clean.copy()
    mask = (mod.emp_code == emp) & (mod.att_date > cutoff)
    mod.loc[mask, ["status", "checkin_minute"]] = ["absent", np.nan]
    f2 = ml.build_features(mod)
    a = f1[(f1.emp_code == emp) & (f1.att_date <= cutoff)].set_index("att_date")[ml.NUM]
    b = f2[(f2.emp_code == emp) & (f2.att_date <= cutoff)].set_index("att_date")[ml.NUM]
    pd.testing.assert_frame_equal(a, b)


def test_ml_pipeline_runs_and_time_split(raw):
    clean, _ = cleaning.clean(raw)
    res = ml.run_all(clean, eda.daily(clean))
    la = res["late_arrival"]
    assert la["train_rows"] > 500 and la["test_rows"] > 200
    for m in la["models"].values():
        assert 0 <= m["roc_auc"] <= 1
    assert res["forecast"]["MAE_random_forest"] > 0
    assert res["anomaly_detection"]["flagged"] > 0
