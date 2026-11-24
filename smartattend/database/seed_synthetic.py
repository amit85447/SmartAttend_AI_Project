"""Synthetic TEST data generator. All names/emails/coordinates are invented. Nothing here is real
attendance. Patterns are generated from explicit, documented rules (below) so analytics and ML have
real structure to find; the ML code never sees those rules, only the resulting records.

Generating rules
  * Each employee has a personal punctuality offset (minutes vs. start time) and a personal absence rate.
  * Mondays/Fridays: later arrivals and higher absence. Monsoon months (Jul-Sep): extra delay for some.
  * Absence is sticky (higher chance the day after an absence) and sometimes comes as 1-3 day blocks.
  * Check-out = schedule end + noise; ~3% of days the employee forgets to check out (hours = NULL).
  * GPS = workplace coordinates + Gaussian jitter; ~1% of attempts are rejected (outside radius / poor accuracy).
  * Face confidence / liveness values are SIMULATED numbers here (no real camera was involved).

Run:  python -m database.seed_synthetic --employees 80 --days 200
"""
from __future__ import annotations
import argparse
from datetime import date, datetime, time, timedelta
import numpy as np
from sqlalchemy import insert, select
import bcrypt
from database.db import engine, init_db
from database.tables import (departments, work_locations, work_schedules, employees, attendance,
                             location_logs, holidays)
from utils.geo import EARTH_R

FIRST = ["Aarav", "Vivaan", "Aditya", "Ishaan", "Rohan", "Kabir", "Arjun", "Dev", "Neha", "Priya", "Ananya", "Diya",
         "Meera", "Riya", "Sneha", "Pooja", "Karan", "Nikhil", "Rahul", "Sanjay", "Kavya", "Isha", "Tanvi", "Varun",
         "Manish", "Deepa", "Rajesh", "Sunita", "Amit", "Anita", "Suresh", "Lakshmi", "Farhan", "Zoya", "Harpreet", "Simran"]
LAST = ["Sharma", "Verma", "Iyer", "Nair", "Reddy", "Patel", "Singh", "Gupta", "Khan", "Das", "Mehta", "Joshi",
        "Kapoor", "Bose", "Menon", "Rao", "Chopra", "Malhotra", "Kulkarni", "Pillai"]
DEPTS = {"Engineering": ["Software Engineer", "Senior Engineer", "QA Engineer"],
         "Sales": ["Sales Executive", "Account Manager"], "HR": ["HR Executive", "Recruiter"],
         "Finance": ["Accountant", "Financial Analyst"], "Operations": ["Operations Associate", "Supervisor"],
         "Support": ["Support Agent", "Team Lead"]}
LOCATIONS = [("Bengaluru HQ", 12.971599, 77.594566, 150), ("Pune Branch", 18.520430, 73.856743, 150)]
HOLIDAYS = [(date(2026, 8, 15), "Independence Day"), (date(2026, 10, 2), "Gandhi Jayanti"),
            (date(2026, 10, 20), "Company holiday (sample)"), (date(2026, 11, 9), "Company holiday (sample)")]
SYNTH_PASSWORD = "Synth#Pass1"


def _jitter(lat, lon, sd_m, rng):
    dn, de = rng.normal(0, sd_m, 2)
    return lat + np.degrees(dn / EARTH_R), lon + np.degrees(de / (EARTH_R * np.cos(np.radians(lat))))


def seed(eng=None, n_employees=80, days=200, end: date = date(2026, 11, 23), seed_value=42) -> dict:
    eng = eng or engine()
    init_db(str(eng.url))
    rng = np.random.default_rng(seed_value)
    pw = bcrypt.hashpw(SYNTH_PASSWORD.encode(), bcrypt.gensalt(rounds=10)).decode()
    with eng.begin() as c:
        dept_ids = {}
        for d in DEPTS:
            dept_ids[d] = c.execute(insert(departments).values(name=d)).inserted_primary_key[0]
        loc_ids = [c.execute(insert(work_locations).values(name=n, latitude=la, longitude=lo, radius_m=r)).inserted_primary_key[0]
                   for n, la, lo, r in LOCATIONS]
        sched_ids = [c.execute(insert(work_schedules).values(
            name=f"General 9-18 ({LOCATIONS[i][0]})", start_time=time(9, 0), end_time=time(18, 0), grace_minutes=10,
            working_days="0,1,2,3,4", location_id=loc_ids[i])).inserted_primary_key[0] for i in range(2)]
        for hd, name in HOLIDAYS:
            c.execute(insert(holidays).values(holiday_date=hd, name=name))

    start = end - timedelta(days=days - 1)
    emp_rows, profile = [], {}
    dept_names = list(DEPTS)
    for i in range(n_employees):
        dept = dept_names[int(rng.choice(len(dept_names), p=[.30, .18, .08, .12, .17, .15]))]
        loc_idx = int(rng.random() < 0.3)
        joined = start - timedelta(days=int(rng.integers(30, 900)))
        if i >= n_employees - 6:                       # a few recent joiners (no history before join date)
            joined = start + timedelta(days=int(rng.integers(20, days - 30)))
        name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        emp_rows.append(dict(emp_code=f"EMP{i+1:04d}", full_name=name, department_id=dept_ids[dept],
                             designation=str(rng.choice(DEPTS[dept])), email=f"emp{i+1:04d}@synthetic.example",
                             phone=f"+9190000{i+1:05d}", schedule_id=sched_ids[loc_idx], password_hash=pw,
                             biometric_consent=False, status="active", joined_on=joined))
        profile[i + 1] = dict(off=rng.normal(-3, 9), sd=rng.uniform(4, 14), p_abs=rng.beta(2, 45) + 0.005,
                              monsoon=rng.random() < 0.4, loc=loc_idx, fwd=rng.random() < 0.03,
                              early_leaver=rng.random() < 0.1)
    with eng.begin() as c:
        c.execute(insert(employees), emp_rows)
        emp_id = {r[1]: r[0] for r in c.execute(select(employees.c.employee_id, employees.c.emp_code))}
    hol = {h for h, _ in HOLIDAYS}

    att_rows, loc_rows, key = [], [], []
    for i, e in enumerate(emp_rows, 1):
        p, eid = profile[i], emp_id[e["emp_code"]]
        la0, lo0, rad = LOCATIONS[p["loc"]][1], LOCATIONS[p["loc"]][2], LOCATIONS[p["loc"]][3]
        absent_left, prev_absent = 0, False
        for k in range(days):
            d = start + timedelta(days=k)
            if d.weekday() > 4 or d in hol or d < e["joined_on"]:
                continue
            dow_mult = 1.7 if d.weekday() in (0, 4) else 1.0
            p_abs = min(0.6, p["p_abs"] * dow_mult * (2.5 if prev_absent else 1.0))
            if absent_left > 0 or rng.random() < p_abs:
                if absent_left == 0 and rng.random() < 0.25:
                    absent_left = int(rng.integers(1, 3))
                elif absent_left > 0:
                    absent_left -= 1
                prev_absent = True
                att_rows.append(dict(employee_id=eid, att_date=d, status="absent", late_minutes=0,
                                     verification_status="not_applicable", source="auto_absent"))
                key.append((eid, d, None, None))
                continue
            prev_absent = False
            off = p["off"] + (4 if d.weekday() == 0 else 2 if d.weekday() == 4 else 0)
            if p["monsoon"] and d.month in (7, 8, 9):
                off += 5
            off = off + rng.normal(0, p["sd"])
            if rng.random() < 0.02:
                off += rng.uniform(40, 120)               # rare big delay (outlier)
            cin = datetime.combine(d, time(9, 0)) + timedelta(minutes=float(off))
            late = int((cin - datetime.combine(d, time(9, 0))).total_seconds() / 60)
            late = late if late > 10 else 0
            cout = None
            if not (p["fwd"] and rng.random() < 0.5) and rng.random() > 0.03:
                shift = -rng.uniform(30, 90) if (p["early_leaver"] and rng.random() < .4) else rng.normal(10, 30)
                cout = datetime.combine(d, time(18, 0)) + timedelta(minutes=float(shift))
                if cout <= cin + timedelta(hours=2):
                    cout = cin + timedelta(hours=8)
            hours = round((cout - cin).total_seconds() / 3600, 2) if cout else None
            att_rows.append(dict(employee_id=eid, att_date=d, check_in_ts=cin, check_out_ts=cout,
                                 status="late" if late else "present", late_minutes=late, working_hours=hours,
                                 face_conf_in=round(float(np.clip(rng.normal(.82, .06), .62, .99)), 4),
                                 face_conf_out=None if cout is None else round(float(np.clip(rng.normal(.82, .06), .62, .99)), 4),
                                 liveness_in=round(float(np.clip(rng.normal(.8, .07), .56, .99)), 4),
                                 liveness_out=None if cout is None else round(float(np.clip(rng.normal(.8, .07), .56, .99)), 4),
                                 verification_status="verified", source="app"))
            key.append((eid, d, cin, cout))
            for ts in (cin, cout):
                if ts is None:
                    continue
                la, lo = _jitter(la0, lo0, 14, rng)
                loc_rows.append(dict(_emp=eid, _d=d, employee_id=eid, logged_at=ts, latitude=round(la, 6), longitude=round(lo, 6),
                                     accuracy_m=round(float(rng.uniform(5, 45)), 2), within_geofence=True,
                                     spoof_flags="", source="browser_gps", result="accepted"))
            if rng.random() < 0.01:                       # a rejected attempt (outside radius or poor accuracy)
                if rng.random() < .6:
                    la, lo = _jitter(la0, lo0, 900, rng); acc = float(rng.uniform(5, 40))
                else:
                    la, lo = _jitter(la0, lo0, 40, rng); acc = float(rng.uniform(150, 600))
                loc_rows.append(dict(_emp=eid, _d=d, employee_id=eid, logged_at=cin - timedelta(minutes=2), latitude=round(la, 6),
                                     longitude=round(lo, 6), accuracy_m=round(acc, 2), within_geofence=acc > 100,
                                     spoof_flags="poor_accuracy" if acc > 100 else "", source="browser_gps", result="rejected"))
    cols = ["employee_id", "att_date", "check_in_ts", "check_out_ts", "status", "late_minutes", "working_hours",
            "face_conf_in", "face_conf_out", "liveness_in", "liveness_out", "verification_status", "source"]
    att_rows = [{k: r.get(k) for k in cols} for r in att_rows]     # same keys in every row (bulk insert)
    with eng.begin() as c:
        for i in range(0, len(att_rows), 2000):
            c.execute(insert(attendance), att_rows[i:i + 2000])
        amap = {(r[1], r[2]): r[0] for r in c.execute(select(attendance.c.attendance_id, attendance.c.employee_id, attendance.c.att_date))}
        locs = []
        for r in loc_rows:
            r = dict(r); r["attendance_id"] = amap.get((r.pop("_emp"), r.pop("_d")))
            la0, lo0, rad = None, None, None
            locs.append(r)
        # distance to the employee's own workplace
        w = {r[0]: (float(r[1]), float(r[2])) for r in c.execute(
            select(employees.c.employee_id, work_locations.c.latitude, work_locations.c.longitude)
            .join(work_schedules, work_schedules.c.schedule_id == employees.c.schedule_id)
            .join(work_locations, work_locations.c.location_id == work_schedules.c.location_id))}
        from utils.geo import haversine_m
        for r in locs:
            r["distance_m"] = round(haversine_m(r["latitude"], r["longitude"], *w[r["employee_id"]]), 2)
            if r["result"] == "accepted":
                r["within_geofence"] = r["distance_m"] <= 150
        for i in range(0, len(locs), 2000):
            c.execute(insert(location_logs), locs[i:i + 2000])
    return {"employees": n_employees, "attendance_rows": len(att_rows), "location_logs": len(locs),
            "from": str(start), "to": str(end)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--employees", type=int, default=80)
    ap.add_argument("--days", type=int, default=200)
    a = ap.parse_args()
    print(seed(n_employees=a.employees, days=a.days))
