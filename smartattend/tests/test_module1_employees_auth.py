import pytest
from sqlalchemy import select, text
from database.tables import face_profiles, audit_logs, employees
from services import employees as E, auth, retention


def test_register_and_duplicate(setup):
    eng, sched, _ = setup
    i = E.register_employee("Asha Rao", "IT", "Analyst", "asha@x.com", "+919876543210", sched, "Passw0rd!", eng=eng)
    assert i == 1
    with pytest.raises(E.ValidationError):
        E.register_employee("Asha Two", "IT", "Analyst", "asha@x.com", None, sched, "Passw0rd!", eng=eng)
    assert E.list_employees(eng).shape[0] == 1


def test_validation(setup):
    eng, sched, _ = setup
    with pytest.raises(E.ValidationError):
        E.register_employee("A", "IT", "x", "bad", None, sched, "Passw0rd!", eng=eng)
    with pytest.raises(auth.AuthError):
        E.register_employee("Valid Name", "IT", "x", "v@x.com", None, sched, "short", eng=eng)


def test_password_hashed_and_login(setup):
    eng, sched, _ = setup
    E.register_employee("Asha Rao", "IT", "Analyst", "asha@x.com", None, sched, "Passw0rd!", eng=eng)
    with eng.connect() as c:
        h = c.execute(select(employees.c.password_hash)).scalar()
    assert h.startswith("$2") and "Passw0rd" not in h
    assert auth.login_employee("EMP0001", "Passw0rd!", eng)["name"] == "Asha Rao"
    with pytest.raises(auth.AuthError):
        auth.login_employee("EMP0001", "wrong-pass1", eng)


def test_admin_lockout(eng):
    auth.create_admin("boss", "Str0ngPass!", "superadmin", eng)
    for _ in range(5):
        with pytest.raises(auth.AuthError):
            auth.login_admin("boss", "bad-pass-1", eng)
    with pytest.raises(auth.AuthError, match="locked"):
        auth.login_admin("boss", "Str0ngPass!", eng)


def test_consent_and_delete(setup):
    eng, sched, _ = setup
    i = E.register_employee("Asha Rao", "IT", "Analyst", "asha@x.com", None, sched, "Passw0rd!", eng=eng)
    assert not E.has_consent(i, eng)
    E.set_consent(i, True, eng=eng)
    assert E.has_consent(i, eng)
    with eng.begin() as c:
        c.execute(face_profiles.insert().values(employee_id=i, embedding_enc=b"x", embedding_dim=1, model_name="m"))
    assert retention.delete_biometrics(i, eng=eng) == 1
    assert not E.has_consent(i, eng)
    retention.delete_employee(i, eng=eng)
    assert E.get_employee(i, eng)["status"] == "deleted"
    with eng.connect() as c:
        acts = [r[0] for r in c.execute(select(audit_logs.c.action))]
    assert "employee_deleted" in acts and "consent_granted" in acts


def test_fk_enforced(eng):
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        with eng.begin() as c:
            c.execute(text("INSERT INTO face_profiles(employee_id,embedding_enc,embedding_dim,model_name) VALUES (99,'x',1,'m')"))


def test_python_tables_match_mysql_ddl():
    """Every table/column in the SQLAlchemy models must exist in sql/01_schema_mysql.sql."""
    import re
    from pathlib import Path
    from database.tables import metadata
    ddl = (Path(__file__).resolve().parents[1] / "sql" / "01_schema_mysql.sql").read_text()
    blocks = dict(re.findall(r"CREATE TABLE (\w+) \((.*?)\n\) ENGINE", ddl, re.S))
    assert set(blocks) == set(metadata.tables)
    for name, t in metadata.tables.items():
        for col in t.columns:
            assert re.search(rf"\b{col.name}\b", blocks[name]), f"{name}.{col.name} missing in DDL"
