"""Attendance rules. Face verification is replaced by a stub here so the BUSINESS RULES (late, hours,
duplicates, holidays, absent marking, rejection when GPS/face fail) are tested exactly and fast.
The real FaceNet path is covered in test_module2_face.py."""
from datetime import datetime, date, time
import numpy as np
import pytest
from sqlalchemy import select, func
from database.tables import attendance, attendance_photos, location_logs, holidays
from services import employees as E, attendance as A, face_service
from services.face_service import VerifyResult
from services.geo import GpsFix

HQ = (12.9716, 77.5946)
IMG = np.zeros((50, 50, 3), np.uint8)
MON = date(2026, 11, 23)    # Monday


def at(h, m, d=MON):
    return datetime.combine(d, time(h, m))


def gps(now):
    return GpsFix(HQ[0], HQ[1], 12, now.timestamp() * 1000)


@pytest.fixture()
def emp(setup, monkeypatch, tmp_path):
    import config
    monkeypatch.setattr(config, "ATTENDANCE_PHOTO_DIR", tmp_path / "ap")
    monkeypatch.setattr(config, "KEY_FILE", tmp_path / "k.key")
    eng, sched, _ = setup
    i = E.register_employee("Asha Rao", "IT", "Analyst", "asha@x.com", None, sched, "Passw0rd!", eng=eng,
                            joined_on=date(2026, 1, 1))
    E.set_consent(i, True, eng=eng)
    return eng, i


def stub(monkeypatch, ok=True, reason="Face verified"):
    monkeypatch.setattr(face_service, "verify_live",
                        lambda *a, **k: VerifyResult(ok, 0.83 if ok else 0.2, 0.9 if ok else None, reason))


def mark(eng, i, kind, now, fix="auto"):
    f = gps(now) if fix == "auto" else fix
    return A.mark(i, kind, IMG, IMG, "left", f, now, eng)


def test_on_time_late_and_hours(emp, monkeypatch):
    eng, i = emp
    stub(monkeypatch)
    r = mark(eng, i, "check_in", at(9, 5))
    assert r.ok and r.status == "present" and r.late_minutes == 0       # inside 10-min grace
    r = mark(eng, i, "check_out", at(17, 35))
    assert r.ok and r.working_hours == 8.5
    with eng.connect() as c:
        assert c.execute(select(func.count()).select_from(attendance_photos)).scalar() == 2
        row = c.execute(select(attendance)).mappings().first()
        assert float(row["face_conf_in"]) == pytest.approx(0.83) and row["verification_status"] == "verified"
        assert c.execute(select(location_logs.c.attendance_id)).scalars().all() == [row["attendance_id"]] * 2


def test_late_minutes(emp, monkeypatch):
    eng, i = emp
    stub(monkeypatch)
    r = mark(eng, i, "check_in", at(9, 42))
    assert r.status == "late" and r.late_minutes == 42


def test_duplicates_blocked(emp, monkeypatch):
    eng, i = emp
    stub(monkeypatch)
    assert mark(eng, i, "check_in", at(9, 0)).ok
    assert "Duplicate" in mark(eng, i, "check_in", at(9, 10)).message
    assert "Too soon" in mark(eng, i, "check_out", at(9, 2)).message
    assert mark(eng, i, "check_out", at(18, 0)).ok
    assert "Duplicate" in mark(eng, i, "check_out", at(18, 30)).message


def test_checkout_without_checkin(emp, monkeypatch):
    eng, i = emp
    stub(monkeypatch)
    assert "No check-in" in mark(eng, i, "check_out", at(18, 0)).message


def test_face_failure_saves_nothing(emp, monkeypatch):
    eng, i = emp
    stub(monkeypatch, ok=False, reason="Face not recognised (unknown or unverified)")
    r = mark(eng, i, "check_in", at(9, 0))
    assert not r.ok and "not recognised" in r.message
    with eng.connect() as c:
        assert c.execute(select(func.count()).select_from(attendance)).scalar() == 0


def test_location_failures_never_bypassed(emp, monkeypatch):
    eng, i = emp
    stub(monkeypatch)
    assert "No GPS" in mark(eng, i, "check_in", at(9, 0), fix=None).message
    far = GpsFix(HQ[0] + 0.02, HQ[1], 10, at(9, 0).timestamp() * 1000)
    assert "Outside" in mark(eng, i, "check_in", at(9, 0), fix=far).message
    ip = GpsFix(HQ[0], HQ[1], 10, at(9, 0).timestamp() * 1000, "ip_estimate")
    assert not mark(eng, i, "check_in", at(9, 0), fix=ip).ok
    with eng.connect() as c:
        assert c.execute(select(func.count()).select_from(attendance)).scalar() == 0


def test_holiday_weekend_consent(emp, monkeypatch):
    eng, i = emp
    stub(monkeypatch)
    with eng.begin() as c:
        c.execute(holidays.insert().values(holiday_date=MON, name="Test Holiday"))
    assert "holiday" in mark(eng, i, "check_in", at(9, 0)).message
    sat = date(2026, 11, 28)
    assert "not a working day" in mark(eng, i, "check_in", at(9, 0, sat)).message
    E.set_consent(i, False, eng=eng)
    assert "consent" in mark(eng, i, "check_in", at(9, 0, date(2026, 11, 24))).message


def test_auto_absent(emp, monkeypatch):
    eng, i = emp
    stub(monkeypatch)
    tue = date(2026, 11, 24)
    assert A.mark_absentees(tue, eng) == 1
    assert A.mark_absentees(tue, eng) == 0                    # idempotent
    assert A.mark_absentees(date(2026, 11, 28), eng) == 0     # Saturday
    mark(eng, i, "check_in", at(9, 0, date(2026, 11, 25)))
    assert A.mark_absentees(date(2026, 11, 25), eng) == 0     # present, not absent
    df = A.records(eng=eng)
    assert set(df["status"]) == {"absent", "present"}
