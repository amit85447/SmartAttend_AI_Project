"""Employee management: registration, profile, consent, soft delete, department/schedule/location setup."""
import re
from datetime import datetime, date, time
from sqlalchemy import select, insert, update, func
from database.db import engine
from database.tables import employees, departments, work_schedules, work_locations
from services import audit
from services.auth import hash_password

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ValidationError(Exception):
    pass


def get_or_create_department(name: str, eng=None) -> int:
    eng = eng or engine()
    name = name.strip()
    if not name:
        raise ValidationError("Department name required")
    with eng.begin() as c:
        row = c.execute(select(departments.c.department_id).where(departments.c.name == name)).first()
        if row:
            return row[0]
        return c.execute(insert(departments).values(name=name)).inserted_primary_key[0]


def create_work_location(name, lat, lon, radius_m=150, eng=None) -> int:
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValidationError("Invalid coordinates")
    with (eng or engine()).begin() as c:
        return c.execute(insert(work_locations).values(name=name, latitude=lat, longitude=lon,
                                                       radius_m=radius_m)).inserted_primary_key[0]


def create_schedule(name, start: time, end: time, grace=10, working_days="0,1,2,3,4",
                    location_id=None, eng=None) -> int:
    if end <= start:
        raise ValidationError("End time must be after start time")
    with (eng or engine()).begin() as c:
        return c.execute(insert(work_schedules).values(
            name=name, start_time=start, end_time=end, grace_minutes=grace,
            working_days=working_days, location_id=location_id)).inserted_primary_key[0]


def next_emp_code(eng=None) -> str:
    with (eng or engine()).connect() as c:
        n = c.execute(select(func.count()).select_from(employees)).scalar() or 0
    return f"EMP{n + 1:04d}"


def register_employee(full_name, department, designation, email, phone, schedule_id, password,
                      joined_on: date | None = None, emp_code: str | None = None,
                      actor="system", eng=None) -> int:
    eng = eng or engine()
    if len(full_name.strip()) < 2:
        raise ValidationError("Name too short")
    if not EMAIL_RE.match(email):
        raise ValidationError("Invalid email")
    if phone and not re.fullmatch(r"\+?\d[\d\s-]{6,17}", phone):
        raise ValidationError("Invalid phone number")
    dept_id = get_or_create_department(department, eng)
    code = emp_code or next_emp_code(eng)
    with eng.begin() as c:
        dup = c.execute(select(employees.c.employee_id).where(
            (employees.c.email == email) | (employees.c.emp_code == code))).first()
        if dup:
            raise ValidationError("Employee ID or email already exists")
        emp_id = c.execute(insert(employees).values(
            emp_code=code, full_name=full_name.strip(), department_id=dept_id, designation=designation,
            email=email.lower(), phone=phone, schedule_id=schedule_id, password_hash=hash_password(password),
            biometric_consent=False, status="active", joined_on=joined_on or date.today())).inserted_primary_key[0]
    audit.log("admin", actor, "employee_registered", "employees", emp_id, {"emp_code": code}, eng)
    return emp_id


def update_profile(employee_id, actor="system", eng=None, **fields):
    allowed = {"full_name", "designation", "phone", "schedule_id", "status", "email"}
    bad = set(fields) - allowed
    if bad:
        raise ValidationError(f"Cannot update: {bad}")
    if "email" in fields and not EMAIL_RE.match(fields["email"]):
        raise ValidationError("Invalid email")
    if "department" in fields:
        pass
    eng = eng or engine()
    with eng.begin() as c:
        c.execute(update(employees).where(employees.c.employee_id == employee_id).values(**fields))
    audit.log("admin", actor, "employee_updated", "employees", employee_id, fields, eng)


def set_consent(employee_id, consent: bool, actor="system", eng=None):
    """Record explicit biometric consent. Face enrolment is refused without it."""
    eng = eng or engine()
    with eng.begin() as c:
        c.execute(update(employees).where(employees.c.employee_id == employee_id).values(
            biometric_consent=consent, consent_at=datetime.now() if consent else None))
    audit.log("employee" if actor == "self" else "admin", actor, "consent_granted" if consent else "consent_withdrawn",
              "employees", employee_id, eng=eng)


def has_consent(employee_id, eng=None) -> bool:
    with (eng or engine()).connect() as c:
        return bool(c.execute(select(employees.c.biometric_consent).where(
            employees.c.employee_id == employee_id)).scalar())


def list_employees(eng=None, include_deleted=False):
    import pandas as pd
    q = (select(employees.c.employee_id, employees.c.emp_code, employees.c.full_name,
                departments.c.name.label("department"), employees.c.designation, employees.c.email,
                employees.c.phone, employees.c.status, employees.c.biometric_consent, employees.c.joined_on)
         .join(departments, departments.c.department_id == employees.c.department_id))
    if not include_deleted:
        q = q.where(employees.c.status != "deleted")
    return pd.read_sql(q.order_by(employees.c.emp_code), (eng or engine()))


def get_employee(employee_id, eng=None):
    with (eng or engine()).connect() as c:
        return c.execute(select(employees).where(employees.c.employee_id == employee_id)).mappings().first()
