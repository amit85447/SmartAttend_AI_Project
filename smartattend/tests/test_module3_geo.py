from datetime import datetime, timedelta
import pytest
from sqlalchemy import select
import config
from database.tables import location_logs
from services import employees as E, geo
from services.geo import GpsFix, evaluate_fix
from utils.geo import haversine_m

HQ = (12.9716, 77.5946)
NOW = datetime(2026, 11, 24, 9, 0, 0)


def fix(lat=HQ[0], lon=HQ[1], acc=15, src="browser_gps", ts=None):
    return GpsFix(lat, lon, acc, (ts or NOW).timestamp() * 1000, src)


def test_haversine_known_distance():
    # Bengaluru -> Chennai is about 290 km
    assert 280_000 < haversine_m(12.9716, 77.5946, 13.0827, 80.2707) < 300_000
    assert haversine_m(*HQ, *HQ) == 0


def test_inside_and_outside():
    assert evaluate_fix(fix(), *HQ, 150, now=NOW).accepted
    far = evaluate_fix(fix(lat=HQ[0] + 0.01), *HQ, 150, now=NOW)   # ~1.1 km
    assert not far.accepted and not far.within_geofence and "Outside" in far.reason


def test_rejects_bad_sources_and_quality():
    assert not evaluate_fix(fix(src="ip_estimate"), *HQ, 150, now=NOW).accepted
    assert not evaluate_fix(fix(src="manual_admin"), *HQ, 150, now=NOW).accepted
    assert "poor_accuracy" in evaluate_fix(fix(acc=config.MAX_GPS_ACCURACY_M + 50), *HQ, 150, now=NOW).flags
    assert "zero_accuracy" in evaluate_fix(fix(acc=0), *HQ, 150, now=NOW).flags
    old = fix(ts=NOW - timedelta(minutes=10))
    assert "stale_fix" in evaluate_fix(old, *HQ, 150, now=NOW).flags
    assert "null_island" in evaluate_fix(fix(lat=0, lon=0), 0, 0, 150, now=NOW).flags


def test_impossible_jump_and_repeated_fix():
    prev = [{"latitude": 28.6, "longitude": 77.2, "accuracy_m": 15, "logged_at": NOW - timedelta(minutes=5)}]
    assert "impossible_jump" in evaluate_fix(fix(), *HQ, 150, prev, NOW).flags     # Delhi -> Bengaluru in 5 min
    same = [{"latitude": HQ[0], "longitude": HQ[1], "accuracy_m": 15, "logged_at": NOW - timedelta(days=d)} for d in (1, 2, 3)]
    assert "repeated_identical_fix" in evaluate_fix(fix(), *HQ, 150, same, NOW).flags


def test_verify_location_writes_log(setup):
    eng, sched, _ = setup
    i = E.register_employee("Asha Rao", "IT", "Analyst", "asha@x.com", None, sched, "Passw0rd!", eng=eng)
    assert geo.verify_location(i, fix(), now=NOW, eng=eng).accepted
    assert not geo.verify_location(i, fix(lat=HQ[0] + 0.02), now=NOW + timedelta(hours=1), eng=eng).accepted
    with eng.connect() as c:
        rows = c.execute(select(location_logs.c.result, location_logs.c.within_geofence)).all()
    assert [r[0] for r in rows] == ["accepted", "rejected"]
