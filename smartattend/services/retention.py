"""Privacy controls: biometric deletion (right to erasure), photo retention purge, employee anonymisation."""
from datetime import datetime, timedelta
from pathlib import Path
from sqlalchemy import select, delete, update
import config
from database.db import engine
from database.tables import face_profiles, attendance_photos, attendance, employees
from services import audit


def _rm(path):
    p = Path(path)
    if p.exists():
        p.unlink()


def delete_biometrics(employee_id, actor="system", eng=None) -> int:
    """Delete all stored embeddings + enrolment images and withdraw consent."""
    eng = eng or engine()
    with eng.begin() as c:
        paths = [r[0] for r in c.execute(select(face_profiles.c.image_path).where(
            face_profiles.c.employee_id == employee_id)) if r[0]]
        n = c.execute(delete(face_profiles).where(face_profiles.c.employee_id == employee_id)).rowcount
        c.execute(update(employees).where(employees.c.employee_id == employee_id)
                  .values(biometric_consent=False, consent_at=None))
    for p in paths:
        _rm(p)
    audit.log("admin", actor, "biometrics_deleted", "employees", employee_id, {"profiles": n}, eng)
    return n


def purge_old_photos(days: int | None = None, actor="system", eng=None) -> int:
    """Delete attendance photo files + rows older than the retention period. Attendance rows are kept."""
    eng = eng or engine()
    cutoff = datetime.now() - timedelta(days=days if days is not None else config.DATA_RETENTION_DAYS_PHOTOS)
    with eng.begin() as c:
        rows = c.execute(select(attendance_photos.c.photo_id, attendance_photos.c.file_path)
                         .where(attendance_photos.c.captured_at < cutoff)).all()
        for pid, _ in rows:
            c.execute(delete(attendance_photos).where(attendance_photos.c.photo_id == pid))
    for _, p in rows:
        _rm(p)
    audit.log("system", actor, "photos_purged", "attendance_photos", None, {"count": len(rows), "cutoff": cutoff}, eng)
    return len(rows)


def delete_employee(employee_id, actor="system", eng=None):
    """Soft delete: removes biometrics, anonymises personal fields, keeps attendance rows for payroll/audit."""
    eng = eng or engine()
    delete_biometrics(employee_id, actor, eng)
    with eng.begin() as c:
        c.execute(update(employees).where(employees.c.employee_id == employee_id).values(
            status="deleted", full_name="[deleted]", email=f"deleted_{employee_id}@removed.invalid",
            phone=None, password_hash="!"))
    audit.log("admin", actor, "employee_deleted", "employees", employee_id, eng=eng)
