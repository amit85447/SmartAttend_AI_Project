"""GPS verification, geofencing and basic anti-spoofing.

Rules (all enforced, none silently skipped):
  * Only browser GPS fixes (user granted permission) are accepted. IP-based or manual locations are
    stored for audit but are never accepted for attendance.
  * Fix accuracy must be <= MAX_GPS_ACCURACY_M, fix must be fresh, coordinates must be valid.
  * Distance to the work location (haversine) must be <= the geofence radius.
  * Spoof flags: impossible jump since the previous fix, identical coordinates AND accuracy repeated
    across several logs (real GPS jitters), (0,0) "null island", zero/absurdly perfect accuracy.
Limits: software checks cannot prove a phone is not running a mock-location app. Treat flags as risk
signals and review the GPS verification report.
"""
from __future__ import annotations
import time as _time
from dataclasses import dataclass, field
from datetime import datetime
from sqlalchemy import select, insert, desc
import config
from database.db import engine
from database.tables import location_logs, work_locations, work_schedules, employees
from services import audit
from utils.geo import haversine_m


@dataclass
class GpsFix:
    latitude: float
    longitude: float
    accuracy_m: float
    timestamp_ms: float | None = None      # browser timestamp (ms since epoch)
    source: str = "browser_gps"            # browser_gps | manual_admin | ip_estimate


@dataclass
class GeoResult:
    accepted: bool
    distance_m: float | None
    within_geofence: bool
    flags: list[str] = field(default_factory=list)
    reason: str = ""
    log_id: int | None = None


def _previous_logs(employee_id, eng, n=3):
    with eng.connect() as c:
        return c.execute(select(location_logs).where(location_logs.c.employee_id == employee_id)
                         .where(location_logs.c.source == "browser_gps")
                         .order_by(desc(location_logs.c.logged_at)).limit(n)).mappings().all()


def evaluate_fix(fix: GpsFix, target_lat, target_lon, radius_m, previous: list | None = None,
                 now: datetime | None = None) -> GeoResult:
    """Pure function (no DB) so it is easy to unit-test."""
    now = now or datetime.now()
    flags: list[str] = []
    if fix.source != "browser_gps":
        return GeoResult(False, None, False, ["not_gps_source"],
                         "Only real device GPS can mark attendance (IP/manual location is not accepted)")
    if not (-90 <= fix.latitude <= 90 and -180 <= fix.longitude <= 180):
        return GeoResult(False, None, False, ["invalid_coordinates"], "Invalid coordinates")
    if abs(fix.latitude) < 0.001 and abs(fix.longitude) < 0.001:
        flags.append("null_island")
    dist = haversine_m(fix.latitude, fix.longitude, target_lat, target_lon)
    within = dist <= radius_m
    if fix.accuracy_m is None or fix.accuracy_m <= 0:
        flags.append("zero_accuracy")
    elif fix.accuracy_m > config.MAX_GPS_ACCURACY_M:
        flags.append("poor_accuracy")
    if fix.timestamp_ms is not None:
        age = abs(now.timestamp() - fix.timestamp_ms / 1000.0)
        if age > config.MAX_FIX_AGE_S:
            flags.append("stale_fix")
    prev = previous or []
    if prev:
        p = prev[0]
        dt = (now - p["logged_at"]).total_seconds()
        if dt > 0:
            speed = haversine_m(float(p["latitude"]), float(p["longitude"]), fix.latitude, fix.longitude) / dt
            if speed > config.MAX_TRAVEL_SPEED_MPS and dt < 6 * 3600:
                flags.append("impossible_jump")
    if len(prev) >= 3 and all(round(float(p["latitude"]), 6) == round(fix.latitude, 6) and
                              round(float(p["longitude"]), 6) == round(fix.longitude, 6) and
                              float(p["accuracy_m"]) == float(fix.accuracy_m) for p in prev):
        flags.append("repeated_identical_fix")
    reasons = {
        "null_island": "Location looks invalid (0,0)", "zero_accuracy": "GPS accuracy not reported",
        "poor_accuracy": f"GPS accuracy too low (worse than {config.MAX_GPS_ACCURACY_M:.0f} m). Move outdoors or use a phone",
        "stale_fix": "GPS reading is too old, refresh the location", "impossible_jump": "Location jumped impossibly fast",
        "repeated_identical_fix": "Same exact GPS reading repeated, which real GPS does not do"}
    if flags:
        return GeoResult(False, round(dist, 2), within, flags, "; ".join(reasons[f] for f in flags))
    if not within:
        return GeoResult(False, round(dist, 2), False, [],
                         f"Outside the workplace radius ({dist:.0f} m away, allowed {radius_m} m)")
    return GeoResult(True, round(dist, 2), True, [], "Location verified")


def get_work_location(employee_id, eng=None):
    with (eng or engine()).connect() as c:
        return c.execute(select(work_locations).join_from(
            employees, work_schedules, employees.c.schedule_id == work_schedules.c.schedule_id).join(
            work_locations, work_locations.c.location_id == work_schedules.c.location_id)
            .where(employees.c.employee_id == employee_id)).mappings().first()


def verify_location(employee_id, fix: GpsFix, attendance_id=None, now=None, eng=None) -> GeoResult:
    """Evaluate a fix against the employee's workplace and always write a location log."""
    eng = eng or engine()
    loc = get_work_location(employee_id, eng)
    if loc is None:
        return GeoResult(False, None, False, ["no_workplace"], "No workplace/geofence is configured for this employee")
    now = now or datetime.now()
    res = evaluate_fix(fix, float(loc["latitude"]), float(loc["longitude"]), loc["radius_m"],
                       _previous_logs(employee_id, eng), now)
    lat = max(-90, min(90, fix.latitude)); lon = max(-180, min(180, fix.longitude))
    with eng.begin() as c:
        ins = c.execute(insert(location_logs).values(
            employee_id=employee_id, attendance_id=attendance_id, logged_at=now, latitude=lat, longitude=lon,
            accuracy_m=fix.accuracy_m or 0, distance_m=res.distance_m, within_geofence=res.within_geofence,
            spoof_flags=",".join(res.flags), source=fix.source if fix.source in ("browser_gps", "manual_admin", "ip_estimate") else "manual_admin",
            result="accepted" if res.accepted else "rejected"))
        res.log_id = ins.inserted_primary_key[0]
    if not res.accepted:
        audit.log("employee", employee_id, "location_rejected", "location_logs", None,
                  {"flags": res.flags, "distance_m": res.distance_m}, eng)
    return res
