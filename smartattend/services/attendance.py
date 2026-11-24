"""Smart attendance (Module 4): check-in/out with face + liveness + GPS, late/working-hour maths,
duplicate prevention and automatic absent marking. Nothing is saved unless EVERY check passes."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, date, time, timedelta
import numpy as np
import pandas as pd
from sqlalchemy import select, insert, update
from sqlalchemy.exc import IntegrityError
import config
from database.db import engine
from database.tables import (attendance, attendance_photos, employees, work_schedules, holidays,
                             location_logs, departments)
from services import audit, employees as emp_svc, geo, face_service
from services.geo import GpsFix
from utils.images import rgb_to_jpeg_bytes, save_encrypted
from services.crypto import sha256_hex


@dataclass
class MarkResult:
    ok: bool
    message: str
    status: str | None = None
    confidence: float | None = None
    liveness: float | None = None
    distance_m: float | None = None
    late_minutes: int = 0
    working_hours: float | None = None
    reasons: list[str] = field(default_factory=list)


def get_schedule(employee_id, eng):
    with eng.connect() as c:
        return c.execute(select(work_schedules).join(
            employees, employees.c.schedule_id == work_schedules.c.schedule_id)
            .where(employees.c.employee_id == employee_id)).mappings().first()


def is_holiday(d: date, eng) -> str | None:
    with eng.connect() as c:
        return c.execute(select(holidays.c.name).where(holidays.c.holiday_date == d)).scalar()


def is_working_day(d: date, schedule) -> bool:
    return str(d.weekday()) in schedule["working_days"].split(",")


def compute_late(check_in: datetime, schedule) -> int:
    """Minutes after scheduled start, but 0 when inside the grace window."""
    start = datetime.combine(check_in.date(), schedule["start_time"])
    delta = (check_in - start).total_seconds() / 60
    return int(delta) if delta > schedule["grace_minutes"] else 0


def compute_hours(check_in: datetime, check_out: datetime) -> float:
    return round((check_out - check_in).total_seconds() / 3600, 2)


def _today_row(employee_id, d, eng):
    with eng.connect() as c:
        return c.execute(select(attendance).where((attendance.c.employee_id == employee_id)
                                                  & (attendance.c.att_date == d))).mappings().first()


def _reject(employee_id, kind, reasons, eng) -> MarkResult:
    audit.log("employee", employee_id, f"{kind}_rejected", "attendance", None, {"reasons": reasons}, eng)
    return MarkResult(False, "Not marked: " + "; ".join(reasons), reasons=reasons)


def mark(employee_id: int, kind: str, frame: np.ndarray, challenge_frame: np.ndarray | None,
         challenge: str | None, fix: GpsFix | None, now: datetime | None = None,
         eng=None, face_engine=None) -> MarkResult:
    """kind = 'check_in' | 'check_out'. `frame` is the neutral photo that is stored with the record."""
    assert kind in ("check_in", "check_out")
    eng = eng or engine()
    now = now or datetime.now()
    emp = emp_svc.get_employee(employee_id, eng)
    if not emp or emp["status"] != "active":
        return MarkResult(False, "Employee is not active")
    if not emp["biometric_consent"]:
        return MarkResult(False, "Biometric consent not recorded. Ask HR to record your consent first.")
    sched = get_schedule(employee_id, eng)
    today = now.date()
    h = is_holiday(today, eng)
    if h:
        return MarkResult(False, f"Today is a holiday ({h}). Attendance is closed.")
    if not is_working_day(today, sched):
        return MarkResult(False, "Today is not a working day for your schedule.")
    row = _today_row(employee_id, today, eng)
    if kind == "check_in" and row is not None:
        return MarkResult(False, "Duplicate: you have already checked in today.")
    if kind == "check_out":
        if row is None or row["check_in_ts"] is None:
            return MarkResult(False, "No check-in found for today. Check in first.")
        if row["check_out_ts"] is not None:
            return MarkResult(False, "Duplicate: you have already checked out today.")
        if (now - row["check_in_ts"]).total_seconds() < config.MIN_CHECKOUT_GAP_MIN * 60:
            return MarkResult(False, f"Too soon to check out (minimum {config.MIN_CHECKOUT_GAP_MIN} minutes after check-in).")

    reasons: list[str] = []
    # --- location (never skipped; a missing fix is a rejection) ---
    if fix is None:
        geo_res = None
        reasons.append("No GPS location received (allow location access in the browser)")
    else:
        geo_res = geo.verify_location(employee_id, fix, now=now, eng=eng)
        if not geo_res.accepted:
            reasons.append(geo_res.reason)
    # --- face + liveness (never skipped) ---
    fres = face_service.verify_live(employee_id, frame, challenge_frame, challenge, eng, face_engine)
    if not fres.ok:
        reasons.append(fres.reason)
    if reasons:
        return _reject(employee_id, kind, reasons, eng)

    jpg = rgb_to_jpeg_bytes(frame)
    path = save_encrypted(jpg, config.ATTENDANCE_PHOTO_DIR / str(today.year) / f"{today.month:02d}",
                          f"{emp['emp_code']}_{today:%Y%m%d}_{kind}_{now:%H%M%S}")
    try:
        with eng.begin() as c:
            if kind == "check_in":
                late = compute_late(now, sched)
                aid = c.execute(insert(attendance).values(
                    employee_id=employee_id, att_date=today, check_in_ts=now,
                    status="late" if late else "present", late_minutes=late,
                    face_conf_in=fres.confidence, liveness_in=fres.liveness_score,
                    verification_status="verified", source="app")).inserted_primary_key[0]
                out = MarkResult(True, "Checked in" + (f" ({late} min late)" if late else " on time"),
                                 "late" if late else "present", late_minutes=late)
            else:
                hours = compute_hours(row["check_in_ts"], now)
                aid = row["attendance_id"]
                c.execute(update(attendance).where(attendance.c.attendance_id == aid).values(
                    check_out_ts=now, working_hours=hours, face_conf_out=fres.confidence,
                    liveness_out=fres.liveness_score))
                out = MarkResult(True, f"Checked out. Worked {hours:.2f} h", row["status"], working_hours=hours)
            c.execute(insert(attendance_photos).values(attendance_id=aid, kind=kind, file_path=path,
                                                       sha256=sha256_hex(jpg), captured_at=now))
            if geo_res and geo_res.log_id:
                c.execute(update(location_logs).where(location_logs.c.log_id == geo_res.log_id).values(attendance_id=aid))
    except IntegrityError:
        return MarkResult(False, "Duplicate: attendance already recorded.")
    out.confidence, out.liveness = fres.confidence, fres.liveness_score
    out.distance_m = geo_res.distance_m if geo_res else None
    audit.log("employee", employee_id, f"{kind}_ok", "attendance", aid,
              {"conf": fres.confidence, "distance_m": out.distance_m}, eng)
    return out


def mark_absentees(for_date: date, eng=None) -> int:
    """Insert an 'absent' row for every active employee scheduled to work that day with no record.
    Call nightly (see README: Windows Task Scheduler / cron). Skips holidays, non-working days and
    employees who had not joined yet. Safe to run repeatedly."""
    eng = eng or engine()
    if is_holiday(for_date, eng):
        return 0
    n = 0
    with eng.begin() as c:
        emps = c.execute(select(employees.c.employee_id, employees.c.joined_on, work_schedules.c.working_days)
                         .join(work_schedules, work_schedules.c.schedule_id == employees.c.schedule_id)
                         .where(employees.c.status == "active")).all()
        have = {r[0] for r in c.execute(select(attendance.c.employee_id).where(attendance.c.att_date == for_date))}
        for emp_id, joined, wdays in emps:
            if emp_id in have or joined > for_date or str(for_date.weekday()) not in wdays.split(","):
                continue
            c.execute(insert(attendance).values(employee_id=emp_id, att_date=for_date, status="absent",
                                                late_minutes=0, verification_status="not_applicable",
                                                source="auto_absent"))
            n += 1
    audit.log("system", "scheduler", "absent_marked", "attendance", None, {"date": for_date, "count": n}, eng)
    return n


def records(start: date | None = None, end: date | None = None, eng=None) -> pd.DataFrame:
    """Attendance joined with employee and department names (used by dashboard, analytics, exports)."""
    q = (select(attendance.c.attendance_id, employees.c.emp_code, employees.c.full_name,
                departments.c.name.label("department"), attendance.c.att_date, attendance.c.check_in_ts,
                attendance.c.check_out_ts, attendance.c.status, attendance.c.late_minutes,
                attendance.c.working_hours, attendance.c.face_conf_in, attendance.c.face_conf_out,
                attendance.c.liveness_in, attendance.c.verification_status, attendance.c.source)
         .join(employees, employees.c.employee_id == attendance.c.employee_id)
         .join(departments, departments.c.department_id == employees.c.department_id))
    if start:
        q = q.where(attendance.c.att_date >= start)
    if end:
        q = q.where(attendance.c.att_date <= end)
    df = pd.read_sql(q.order_by(attendance.c.att_date.desc(), employees.c.emp_code), eng or engine())
    df.columns = [str(c) for c in df.columns]
    return df
