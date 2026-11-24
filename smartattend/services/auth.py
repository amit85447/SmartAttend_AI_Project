"""Authentication: bcrypt hashing, lockout after repeated failures, admin and employee logins."""
from datetime import datetime, timedelta
import bcrypt
from sqlalchemy import select, update, insert
import config
from database.db import engine
from database.tables import admin_users, employees
from services import audit


class AuthError(Exception):
    pass


def validate_password(pw: str):
    if len(pw) < config.MIN_PASSWORD_LENGTH:
        raise AuthError(f"Password must be at least {config.MIN_PASSWORD_LENGTH} characters")
    if pw.isalpha() or pw.isdigit():
        raise AuthError("Password must mix letters and digits or symbols")


def hash_password(pw: str) -> str:
    validate_password(pw)
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except ValueError:
        return False


def create_admin(username: str, password: str, role: str = "hr", eng=None):
    eng = eng or engine()
    with eng.begin() as c:
        c.execute(insert(admin_users).values(username=username, password_hash=hash_password(password),
                                             role=role, is_active=True, failed_attempts=0))
    audit.log("system", "setup", "admin_created", "admin_users", username, {"role": role}, eng)


def has_any_admin(eng=None) -> bool:
    with (eng or engine()).connect() as c:
        return c.execute(select(admin_users.c.admin_id).limit(1)).first() is not None


def _locked(until):
    return until is not None and until > datetime.now()


def login_admin(username: str, password: str, eng=None) -> dict:
    eng = eng or engine()
    failure = None
    with eng.begin() as c:
        row = c.execute(select(admin_users).where(admin_users.c.username == username)).mappings().first()
        if not row or not row["is_active"]:
            failure = ("Invalid username or password", False)
        elif _locked(row["locked_until"]):
            failure = ("Account temporarily locked. Try again later.", False)
        elif not verify_password(password, row["password_hash"]):
            fails = row["failed_attempts"] + 1
            vals = {"failed_attempts": fails}
            if fails >= config.MAX_FAILED_LOGINS:
                vals.update(locked_until=datetime.now() + timedelta(minutes=config.LOCKOUT_MINUTES), failed_attempts=0)
            c.execute(update(admin_users).where(admin_users.c.admin_id == row["admin_id"]).values(**vals))
            failure = ("Invalid username or password", True)
        else:
            c.execute(update(admin_users).where(admin_users.c.admin_id == row["admin_id"])
                      .values(failed_attempts=0, locked_until=None, last_login=datetime.now()))
    if failure:                       # audit after the transaction closes (avoids nested writes)
        if failure[1]:
            audit.log("admin", username, "login_failed", eng=eng)
        raise AuthError(failure[0])
    audit.log("admin", username, "login_ok", eng=eng)
    return {"role": "admin", "admin_id": row["admin_id"], "username": username, "admin_role": row["role"]}


# Employee lockout is kept in-table via a lightweight in-memory counter per process.
_emp_fails: dict[str, tuple[int, datetime | None]] = {}


def login_employee(emp_code: str, password: str, eng=None) -> dict:
    eng = eng or engine()
    fails, until = _emp_fails.get(emp_code, (0, None))
    if _locked(until):
        raise AuthError("Account temporarily locked. Try again later.")
    with eng.connect() as c:
        row = c.execute(select(employees).where(employees.c.emp_code == emp_code)).mappings().first()
    if not row or row["status"] != "active" or not verify_password(password, row["password_hash"]):
        fails += 1
        until = datetime.now() + timedelta(minutes=config.LOCKOUT_MINUTES) if fails >= config.MAX_FAILED_LOGINS else None
        _emp_fails[emp_code] = (0 if until else fails, until)
        audit.log("employee", emp_code, "login_failed", eng=eng)
        raise AuthError("Invalid employee ID or password")
    _emp_fails.pop(emp_code, None)
    audit.log("employee", emp_code, "login_ok", eng=eng)
    return {"role": "employee", "employee_id": row["employee_id"], "emp_code": emp_code, "name": row["full_name"]}
