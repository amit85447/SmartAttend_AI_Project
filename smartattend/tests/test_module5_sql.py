"""Run every analytical query. MySQL syntax is transpiled to SQLite (sqlglot) so it can be executed here
without a MySQL server. This validates logic and syntax shape, not MySQL-specific behaviour."""
import re
from pathlib import Path
import pytest
import sqlglot
from sqlalchemy import text
from database import seed_synthetic


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    from sqlalchemy import create_engine
    e = create_engine(f"sqlite:///{tmp_path_factory.mktemp('d')/'s.db'}", future=True)
    seed_synthetic.seed(e, n_employees=25, days=90)
    return e


def queries():
    sql = (Path(__file__).resolve().parents[1] / "sql" / "03_analytical_queries.sql").read_text()
    parts = re.split(r"^-- (Q\d+):.*$", sql, flags=re.M)
    return [(parts[i], parts[i + 1].strip().rstrip(";")) for i in range(1, len(parts), 2)]


@pytest.mark.parametrize("name,q", queries())
def test_query_runs_and_returns_rows(seeded, name, q):
    lite = sqlglot.transpile(q, read="mysql", write="sqlite")[0]
    with seeded.connect() as c:
        rows = c.execute(text(lite)).fetchall()
    assert len(rows) > 0, name


def test_q1_matches_pandas(seeded):
    import pandas as pd
    from services import attendance as A
    q = dict(queries())["Q1"]
    with seeded.connect() as c:
        got = {r[0]: r[3] for r in c.execute(text(sqlglot.transpile(q, read="mysql", write="sqlite")[0]))}
    df = A.records(eng=seeded)
    df = df[df.status.isin(["present", "late", "absent"])]
    exp = (df.assign(p=df.status.isin(["present", "late"])).groupby("department")["p"].mean() * 100).round(2).to_dict()
    for k, v in exp.items():
        assert got[k] == pytest.approx(v, abs=0.01)
