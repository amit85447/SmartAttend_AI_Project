import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
from datetime import time
from sqlalchemy import create_engine, event
from database.tables import metadata


@pytest.fixture()
def eng(tmp_path):
    e = create_engine(f"sqlite:///{tmp_path/'t.db'}", future=True)

    @event.listens_for(e, "connect")
    def _fk(dbapi, _):
        dbapi.execute("PRAGMA foreign_keys=ON")
    metadata.create_all(e)
    return e


@pytest.fixture()
def setup(eng):
    from services import employees as E
    loc = E.create_work_location("HQ", 12.9716, 77.5946, 150, eng)
    sched = E.create_schedule("General", time(9, 0), time(18, 0), 10, "0,1,2,3,4", loc, eng)
    return eng, sched, loc
