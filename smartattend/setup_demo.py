"""One-command demo setup: creates the database tables, loads FAKE demo data, creates a demo admin.
Usage:  python setup_demo.py
Then:   streamlit run app.py     (login: admin / Demo#Pass123)
Do NOT run this on a database that holds real employees."""
from database.db import engine, init_db
from database.seed_synthetic import seed, SYNTH_PASSWORD
from services import auth
from sqlalchemy import select, func
from database.tables import employees

init_db()
eng = engine()
with eng.connect() as c:
    n = c.execute(select(func.count()).select_from(employees)).scalar()
if n:
    raise SystemExit("Database already has employees. Demo data was NOT loaded.")
print(seed(eng))
if not auth.has_any_admin(eng):
    auth.create_admin("admin", "Demo#Pass123", "superadmin", eng)
print("Done. Admin login: admin / Demo#Pass123   |   Demo employee passwords: " + SYNTH_PASSWORD + " (IDs EMP0001...)")
