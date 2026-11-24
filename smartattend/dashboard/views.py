"""Module 11: all Streamlit pages. Each function renders one page."""
from __future__ import annotations
import io
from datetime import date, datetime, time, timedelta
import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
import config
from analytics import cleaning, eda, ml
from dashboard.theme import kpi
from database.db import engine, init_db
from database.tables import (departments, work_locations, work_schedules, holidays, audit_logs, face_profiles,
                             attendance, employees as emp_t, location_logs, attendance_photos)
from models import liveness
from reports import exporters, excel_workbook
from services import attendance as A, employees as E, face_service, retention, auth, audit, geo
from sqlalchemy import select, insert, delete, func, text
from utils.images import bytes_to_rgb
from utils.browser_gps import request_browser_gps


@st.cache_data(ttl=60, show_spinner=False)
def _clean_records(_key):
    df = A.records(eng=engine())
    if df.empty:
        return df, {}
    return cleaning.clean(df)


def _data():
    key = (config.DB_URL, int(datetime.now().timestamp() // 60))
    return _clean_records(key)


# ---------------------------------------------------------------- Overview
def overview():
    st.title("Overview")
    df, _ = _data()
    if df.empty:
        st.info("No attendance yet. Add a workplace and employees, or load demo data in Database Management.")
        return
    last = df["att_date"].max()
    day = st.date_input("Day", value=last.date(), max_value=last.date())
    today = df[df["att_date"] == pd.Timestamp(day)]
    sched = today[today.status.isin(["present", "late", "absent"])]
    pres, late = int(sched.status.isin(["present", "late"]).sum()), int((sched.status == "late").sum())
    c = st.columns(4)
    total = int(E.list_employees(engine()).query("status=='active'").shape[0])
    kpi(c[0], "Total employees", total)
    kpi(c[1], "Present", pres, f"{late} late")
    kpi(c[2], "Absent", int((sched.status == "absent").sum()))
    kpi(c[3], "Attendance %", f"{100*pres/max(len(sched),1):.1f}%")
    c = st.columns(3)
    kpi(c[0], "Avg working hours", f"{today['working_hours'].mean():.2f}" if today["working_hours"].notna().any() else "n/a")
    mo = eda.monthly(df)
    kpi(c[1], "Monthly growth", f"{mo['growth_pct_vs_prev_month'].iloc[-1]:+.2f} pts" if len(mo) > 1 else "n/a", "vs previous month")
    kpi(c[2], "Late arrivals (day)", late)
    d = eda.daily(df)
    st.plotly_chart(px.line(d, x="att_date", y="attendance_pct", title="Daily attendance %"), use_container_width=True)
    a, b = st.columns(2)
    a.plotly_chart(px.bar(eda.by_department(df), x="department", y="attendance_pct", title="Department attendance %"), use_container_width=True)
    b.plotly_chart(px.bar(eda.monthly(df), x="month", y="attendance_pct", title="Monthly attendance %"), use_container_width=True)


# ---------------------------------------------------------------- Employees
def employee_management():
    st.title("Employee Management")
    eng = engine()
    with eng.connect() as c:
        scheds = c.execute(select(work_schedules.c.schedule_id, work_schedules.c.name)).all()
    tab1, tab2 = st.tabs(["Register employee", "Directory and profiles"])
    with tab1:
        if not scheds:
            st.warning("Create a workplace and schedule first (Settings page).")
        else:
            with st.form("reg", clear_on_submit=True):
                c1, c2 = st.columns(2)
                name = c1.text_input("Full name"); dept = c2.text_input("Department")
                desig = c1.text_input("Designation"); email = c2.text_input("Email")
                phone = c1.text_input("Phone (optional)"); sched = c2.selectbox("Work schedule", scheds, format_func=lambda s: s[1])
                pw = st.text_input("Temporary password", type="password", help="8+ characters, letters and digits")
                if st.form_submit_button("Register"):
                    try:
                        i = E.register_employee(name, dept, desig, email, phone or None, sched[0], pw,
                                                actor=st.session_state["user"]["username"], eng=eng)
                        st.success(f"Registered. Employee ID: {E.get_employee(i, eng)['emp_code']}")
                    except Exception as e:
                        st.error(str(e))
    with tab2:
        df = E.list_employees(eng)
        st.dataframe(df, use_container_width=True, hide_index=True)
        if len(df):
            sel = st.selectbox("Edit profile", df["emp_code"] + " - " + df["full_name"])
            code = sel.split(" - ")[0]
            row = df[df["emp_code"] == code].iloc[0]
            with st.form("edit"):
                n = st.text_input("Name", row["full_name"]); d = st.text_input("Designation", row["designation"])
                ph = st.text_input("Phone", row["phone"] or ""); stt = st.selectbox("Status", ["active", "inactive"], index=0 if row["status"] == "active" else 1)
                if st.form_submit_button("Save changes"):
                    try:
                        E.update_profile(int(row["employee_id"]), actor=st.session_state["user"]["username"], eng=eng,
                                         full_name=n, designation=d, phone=ph or None, status=stt)
                        st.success("Saved")
                    except Exception as e:
                        st.error(str(e))


# ---------------------------------------------------------------- Face registration
def face_registration():
    st.title("Face Registration")
    st.caption("Biometric data is only collected after explicit consent. Embeddings are stored encrypted.")
    eng = engine()
    df = E.list_employees(eng)
    if df.empty:
        st.info("Register an employee first.")
        return
    sel = st.selectbox("Employee", df["emp_code"] + " - " + df["full_name"])
    row = df[df["emp_code"] == sel.split(" - ")[0]].iloc[0]
    emp_id = int(row["employee_id"])
    n_prof = len(face_service.load_embeddings(eng, emp_id).get(emp_id, []))
    st.write(f"Consent recorded: **{'yes' if row['biometric_consent'] else 'no'}**, enrolled face images: **{n_prof}**")
    consent = st.checkbox("The employee has been informed and gives explicit consent to store a face template for attendance verification.",
                          value=bool(row["biometric_consent"]))
    if consent != bool(row["biometric_consent"]) and st.button("Save consent decision"):
        E.set_consent(emp_id, consent, actor=st.session_state["user"]["username"], eng=eng)
        st.rerun()
    if not row["biometric_consent"]:
        st.warning("Enrolment is locked until consent is recorded.")
        return
    st.markdown(f"Provide **{config.MIN_ENROLL_IMAGES}+ clear photos** (different angles and lighting, one person, no sunglasses).")
    ups = st.file_uploader("Upload photos", type=["jpg", "jpeg", "png"], accept_multiple_files=True)
    cam = st.camera_input("...or take a photo with the webcam")
    imgs = [bytes_to_rgb(u.getvalue()) for u in ups]
    if cam is not None:
        imgs.append(bytes_to_rgb(cam.getvalue()))
    if imgs:
        st.image([i for i in imgs], width=110)
    if st.button("Enrol face images", disabled=len(imgs) < config.MIN_ENROLL_IMAGES):
        with st.spinner("Detecting faces and computing FaceNet embeddings..."):
            try:
                n = face_service.enroll(emp_id, imgs, actor=st.session_state["user"]["username"], eng=eng)
                st.success(f"Enrolled {n} face images.")
            except Exception as e:
                st.error(str(e))


# ---------------------------------------------------------------- Mark attendance
def mark_attendance():
    st.title("Mark Attendance")
    user, eng = st.session_state["user"], engine()
    if user["role"] == "employee":
        emp_id = user["employee_id"]
    else:
        df = E.list_employees(eng)
        sel = st.selectbox("Mark on behalf of (admin kiosk)", df["emp_code"] + " - " + df["full_name"])
        emp_id = int(df[df["emp_code"] == sel.split(" - ")[0]].iloc[0]["employee_id"])
        st.caption("The employee's own face and GPS are still required. Admin cannot bypass verification.")
    kind = st.radio("Action", ["check_in", "check_out"], horizontal=True, format_func=lambda k: "Check in" if k == "check_in" else "Check out")
    if "challenge" not in st.session_state:
        st.session_state["challenge"] = liveness.new_challenge()
    ch = st.session_state["challenge"]
    st.markdown("**Step 1. Location.** Your browser will ask permission to share your location.")
    fix, msg = request_browser_gps("gps_" + kind)
    st.write(("OK: " if fix else "") + msg)
    if fix:
        st.caption(f"Accuracy {fix.accuracy_m:.0f} m. Phones give accurate GPS; laptops often give a rough estimate and may be rejected.")
    st.markdown("**Step 2. Photo.** Look straight at the camera.")
    p1 = st.camera_input("Neutral photo", key="cam1_" + kind)
    st.markdown(f"**Step 3. Liveness.** Turn your head so your nose points toward the **{ch.upper()}** side of the picture, then take the second photo.")
    p2 = st.camera_input("Head-turn photo", key="cam2_" + kind)
    if st.button("Submit", type="primary", disabled=not (p1 and p2)):
        with st.spinner("Verifying face, liveness and location..."):
            res = A.mark(emp_id, kind, bytes_to_rgb(p1.getvalue()), bytes_to_rgb(p2.getvalue()), ch, fix, eng=eng)
        st.session_state["challenge"] = liveness.new_challenge()
        if res.ok:
            st.success(res.message)
            st.write(f"Face confidence {res.confidence:.2f}, liveness {res.liveness}, distance from workplace {res.distance_m} m")
        else:
            st.error(res.message)


# ---------------------------------------------------------------- Live records
def live_records():
    st.title("Live Attendance Records")
    df = A.records(date.today() - timedelta(days=30), eng=engine())
    if df.empty:
        st.info("No records yet.")
        return
    c1, c2 = st.columns(2)
    stt = c1.multiselect("Status", sorted(df["status"].unique()), default=list(df["status"].unique()))
    q = c2.text_input("Search name / code")
    f = df[df["status"].isin(stt)]
    if q:
        f = f[f["full_name"].str.contains(q, case=False) | f["emp_code"].str.contains(q, case=False)]
    st.dataframe(f.head(1000), use_container_width=True, hide_index=True)
    if st.button("Refresh"):
        st.rerun()


# ---------------------------------------------------------------- Location tracking
def location_tracking():
    import folium
    from streamlit_folium import st_folium  # optional; falls back to HTML embed
    st.title("Location Tracking")
    eng = engine()
    end = st.date_input("To", value=date.today()); start = st.date_input("From", value=end - timedelta(days=7))
    log = exporters.gps_log(eng, start, end)
    if log.empty:
        st.info("No GPS logs in this range.")
        return
    res = st.radio("Show", ["accepted", "rejected", "both"], horizontal=True)
    wp = st.selectbox("Workplace", sorted(log["workplace"].unique()))
    log = log[log["workplace"] == wp]
    show = log if res == "both" else log[log["result"] == res]
    show = show.head(1500)
    if show.empty:
        st.info("Nothing to show for this selection."); return
    m = folium.Map(location=[show["latitude"].astype(float).median(), show["longitude"].astype(float).median()], zoom_start=15)
    with eng.connect() as c:
        for r in c.execute(select(work_locations)).mappings():
            folium.Circle([float(r["latitude"]), float(r["longitude"])], radius=r["radius_m"], color="#4DA3FF", fill=True, fill_opacity=.1,
                          tooltip=f"{r['name']} geofence {r['radius_m']} m").add_to(m)
    for r in show.itertuples():
        folium.CircleMarker([float(r.latitude), float(r.longitude)], radius=3, color="#2ECC71" if r.result == "accepted" else "#FF5A5F",
                            tooltip=f"{r.emp_code} {r.logged_at:%Y-%m-%d %H:%M} dist {r.distance_m} m {r.spoof_flags}").add_to(m)
    st_folium(m, height=520, use_container_width=True)
    st.dataframe(eda.location_summary(log), hide_index=True, use_container_width=True)


# ---------------------------------------------------------------- Analytics
def analytics_page():
    st.title("Analytics")
    df, rep = _data()
    if df.empty:
        st.info("No data.")
        return
    t = st.tabs(["Trends", "Departments", "Punctuality", "Patterns and tests", "Data quality"])
    d = eda.daily(df)
    with t[0]:
        tr, s = eda.trend(d)
        st.plotly_chart(px.line(tr, x="att_date", y=["attendance_pct", "rolling_7d"], title="Daily attendance % with 7-day average"), use_container_width=True)
        st.json(s)
        st.dataframe(eda.monthly(df), hide_index=True, use_container_width=True)
    with t[1]:
        dep = eda.by_department(df)
        st.dataframe(dep, hide_index=True, use_container_width=True)
        st.plotly_chart(px.bar(dep, x="department", y=["late_pct"], title="Late % of present days"), use_container_width=True)
    with t[2]:
        p = eda.punctuality(df)
        st.dataframe(p, hide_index=True, use_container_width=True)
        st.plotly_chart(px.histogram(df[df.checkin_hour_float.notna()], x="checkin_hour_float", nbins=48, title="Check-in time distribution (hour)"), use_container_width=True)
    with t[3]:
        w = eda.weekday_pattern(df)
        hm = df[df.status.isin(["present", "late", "absent"])].copy()
        hm["wk"] = hm["att_date"].dt.strftime("%G-W%V"); hm["dow"] = hm["att_date"].dt.day_name()
        pivot = hm.assign(a=(hm.status == "absent").astype(int)).pivot_table(index="dow", columns="wk", values="a", aggfunc="mean")
        pivot = pivot.reindex(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
        st.plotly_chart(px.imshow(pivot, aspect="auto", title="Absence-rate heatmap (weekday x week)", color_continuous_scale="Reds"), use_container_width=True)
        st.dataframe(w, hide_index=True)
        st.json(eda.stat_tests(df))
    with t[4]:
        st.json(rep)


# ---------------------------------------------------------------- ML
def ml_page():
    st.title("Machine Learning Predictions")
    df, _ = _data()
    if df.empty or df["emp_code"].nunique() < 5 or df["att_date"].nunique() < 90:
        st.info("Need at least ~90 days of data for 5+ employees. Load synthetic demo data to try this page.")
        return
    st.caption("Models use only past days to predict a day, and are scored on the most recent 25% of dates. Baselines are shown for honesty.")
    if st.button("Train and evaluate all models", type="primary") or "ml_res" in st.session_state:
        if "ml_res" not in st.session_state:
            with st.spinner("Training..."):
                feat = ml.build_features(df)
                late, lf = ml.late_arrival_model(feat); absn, af = ml.absenteeism_model(feat)
                pat, _ = ml.pattern_classification(df); an, an_df = ml.anomaly_detection(df); fc, fdf = ml.forecast_attendance(eda.daily(df))
                st.session_state["ml_res"] = dict(late=late, absn=absn, pat=pat, an=an, an_df=an_df, fc=fc, fdf=fdf, feat=feat, lf=lf, af=af)
        r = st.session_state["ml_res"]
        for title, res in (("Late arrival prediction", r["late"]), ("Absenteeism prediction", r["absn"])):
            st.subheader(title)
            st.dataframe(pd.DataFrame(res["models"]).T, use_container_width=True)
            st.caption(f"Baseline (repeat yesterday): {res['baseline_repeat_last_day']}. Test positive rate {res['test_positive_rate']}. Split {res['split_date']}.")
            st.write("Top features:", res["rf_top_features"])
        st.subheader("Next-month pattern classification")
        st.write({k: v for k, v in r["pat"].items() if k != "report"})
        st.subheader("Anomaly detection (Isolation Forest)")
        st.write(r["an"]); st.dataframe(r["an_df"][r["an_df"]["is_anomaly"]].head(50), hide_index=True)
        st.subheader("14 working-day attendance forecast")
        st.write(r["fc"])
        st.plotly_chart(px.line(r["fdf"], x="date", y="forecast_attendance_pct", markers=True), use_container_width=True)
        st.subheader("Predict tomorrow for one employee")
        feat = r["feat"]
        codes = sorted(feat["emp_code"].unique())
        code = st.selectbox("Employee", codes)
        last = feat[feat["emp_code"] == code].iloc[-1:].copy()
        st.caption(f"Uses their history up to {last['att_date'].iloc[0].date()}; features for the next day are rolled from that history.")
        nxt = last.copy(); nxt["att_date"] = last["att_date"] + pd.offsets.BDay(1)
        nxt["dow"] = nxt["att_date"].dt.dayofweek; nxt["month"] = nxt["att_date"].dt.month
        nxt["is_monday"], nxt["is_friday"] = int(nxt["dow"].iloc[0] == 0), int(nxt["dow"].iloc[0] == 4)
        nxt["last_late"] = (last["status"] == "late").astype(float); nxt["last_absent"] = (last["status"] == "absent").astype(float)
        pl = r["lf"]["RandomForest"].predict_proba(nxt[ml.NUM + ml.CAT])[0, 1]
        pa = r["af"]["RandomForest"].predict_proba(nxt[ml.NUM + ml.CAT])[0, 1]
        c = st.columns(2); kpi(c[0], "P(late | present)", f"{pl:.0%}"); kpi(c[1], "P(absent)", f"{pa:.0%}")


# ---------------------------------------------------------------- Reports
def reports_page():
    st.title("Reports")
    eng = engine()
    name = st.selectbox("Report", exporters.REPORTS)
    c = st.columns(4)
    end = c[0].date_input("To", value=date.today()); start = c[1].date_input("From", value=end - timedelta(days=30))
    emps = E.list_employees(eng)
    code = c[2].selectbox("Employee", emps["emp_code"]) if name == "Employee report" and len(emps) else None
    dep = c[3].selectbox("Department", ["(all)"] + sorted(emps["department"].unique())) if name == "Department report" and len(emps) else None
    if st.button("Generate", type="primary"):
        try:
            df = exporters.build(name, start, end, code, None if dep in (None, "(all)") else dep, eng)
        except Exception as e:
            st.error(str(e)); return
        st.dataframe(df, hide_index=True, use_container_width=True)
        base = name.lower().replace(" ", "_")
        d1, d2, d3 = st.columns(3)
        d1.download_button("CSV", exporters.to_csv_bytes(df), f"{base}.csv", "text/csv")
        d2.download_button("Excel", exporters.to_excel_bytes(df, name), f"{base}.xlsx")
        d3.download_button("PDF", exporters.to_pdf_bytes(df, name, f"{start} to {end}"), f"{base}.pdf", "application/pdf")
    st.divider()
    st.subheader("Full Excel workbook (formulas, XLOOKUP, COUNTIFS, SUMIFS)")
    if st.button("Build workbook from database"):
        raw = A.records(eng=eng)
        buf = io.BytesIO()
        path = config.EXPORT_DIR / "SmartAttend_Report.xlsx"; config.EXPORT_DIR.mkdir(exist_ok=True)
        excel_workbook.build_workbook(raw, str(path), eng)
        st.download_button("Download workbook", path.read_bytes(), "SmartAttend_Report.xlsx")


# ---------------------------------------------------------------- Database
def database_management():
    st.title("Database Management")
    eng = engine()
    admin = st.session_state["user"]
    st.code(config.DB_URL.split("@")[-1] if "@" in config.DB_URL else config.DB_URL)
    with eng.connect() as c:
        counts = {t.name: c.execute(select(func.count()).select_from(t)).scalar() for t in
                  (departments, work_locations, work_schedules, emp_t, face_profiles, attendance, attendance_photos, location_logs, holidays, audit_logs)}
    st.dataframe(pd.DataFrame(counts.items(), columns=["table", "rows"]), hide_index=True)
    t1, t2, t3, t4 = st.tabs(["Privacy and retention", "Maintenance", "Audit log", "Demo data"])
    with t1:
        emps = E.list_employees(eng)
        if len(emps):
            sel = st.selectbox("Employee", emps["emp_code"] + " - " + emps["full_name"], key="pv")
            eid = int(emps[emps["emp_code"] == sel.split(" - ")[0]].iloc[0]["employee_id"])
            c1, c2 = st.columns(2)
            if c1.button("Delete face data and withdraw consent"):
                st.success(f"Deleted {retention.delete_biometrics(eid, admin['username'], eng)} face templates")
            if c2.button("Delete employee (anonymise, keep attendance rows)"):
                retention.delete_employee(eid, admin["username"], eng); st.success("Employee anonymised")
        days = st.number_input("Delete attendance photos older than (days)", 1, 3650, config.DATA_RETENTION_DAYS_PHOTOS)
        if st.button("Purge old photos"):
            st.success(f"Purged {retention.purge_old_photos(int(days), admin['username'], eng)} photos")
    with t2:
        d = st.date_input("Mark absentees for date", value=date.today() - timedelta(days=1))
        if st.button("Run automatic absent marking"):
            st.success(f"{A.mark_absentees(d, eng)} employees marked absent")
        st.caption("Schedule this nightly (README: Task Scheduler).")
    with t3:
        with eng.connect() as c:
            a = pd.DataFrame(c.execute(select(audit_logs).order_by(audit_logs.c.log_id.desc()).limit(300)).mappings().all())
        st.dataframe(a, hide_index=True, use_container_width=True)
    with t4:
        st.warning("Loads FAKE employees and attendance for testing into the CURRENT database. Use only on an empty/test database.")
        if counts["employees"] == 0 and st.button("Load synthetic demo data"):
            from database.seed_synthetic import seed
            st.write(seed(eng)); st.cache_data.clear(); st.rerun()
        if counts["employees"] > 0:
            st.caption("Demo data can only be loaded into a database with no employees.")


# ---------------------------------------------------------------- Settings
def settings_page():
    st.title("Settings")
    eng = engine()
    t1, t2, t3, t4 = st.tabs(["Workplaces / geofence", "Schedules", "Holidays", "Verification thresholds"])
    with t1:
        with eng.connect() as c:
            st.dataframe(pd.DataFrame(c.execute(select(work_locations)).mappings().all()), hide_index=True)
        with st.form("loc"):
            n = st.text_input("Name"); la = st.number_input("Latitude", -90.0, 90.0, 0.0, format="%.6f")
            lo = st.number_input("Longitude", -180.0, 180.0, 0.0, format="%.6f"); r = st.number_input("Radius (m)", 20, 5000, 150)
            st.caption("Tip: open Google Maps, right-click the office entrance, click the coordinates to copy them.")
            if st.form_submit_button("Add workplace"):
                try:
                    E.create_work_location(n, la, lo, int(r), eng); st.success("Added"); st.rerun()
                except Exception as e:
                    st.error(str(e))
    with t2:
        with eng.connect() as c:
            st.dataframe(pd.DataFrame(c.execute(select(work_schedules)).mappings().all()), hide_index=True)
            locs = c.execute(select(work_locations.c.location_id, work_locations.c.name)).all()
        with st.form("sch"):
            n = st.text_input("Schedule name"); s = st.time_input("Start", time(9, 0)); e_ = st.time_input("End", time(18, 0))
            g = st.number_input("Grace minutes", 0, 120, 10)
            days = st.multiselect("Working days", ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], default=["Mon", "Tue", "Wed", "Thu", "Fri"])
            loc = st.selectbox("Workplace", locs, format_func=lambda x: x[1]) if locs else None
            if st.form_submit_button("Add schedule") and loc:
                try:
                    E.create_schedule(n, s, e_, int(g), ",".join(str(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].index(x)) for x in days), loc[0], eng)
                    st.success("Added"); st.rerun()
                except Exception as ex:
                    st.error(str(ex))
    with t3:
        with eng.connect() as c:
            st.dataframe(pd.DataFrame(c.execute(select(holidays).order_by(holidays.c.holiday_date)).mappings().all()), hide_index=True)
        with st.form("hol"):
            d = st.date_input("Date"); n = st.text_input("Holiday name")
            if st.form_submit_button("Add holiday") and n:
                with eng.begin() as c:
                    c.execute(insert(holidays).values(holiday_date=d, name=n))
                st.rerun()
    with t4:
        st.write({"Face match threshold (cosine)": config.FACE_MATCH_THRESHOLD, "Liveness required": config.LIVENESS_REQUIRED,
                  "Liveness threshold": config.LIVENESS_THRESHOLD, "Max GPS accuracy (m)": config.MAX_GPS_ACCURACY_M,
                  "Max fix age (s)": config.MAX_FIX_AGE_S})
        st.caption("Change these in the .env file (see README), then restart the app. Verification cannot be switched off from the UI.")
