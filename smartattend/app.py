"""SmartAttend AI - Streamlit entry point.  Run:  streamlit run app.py"""
import streamlit as st

st.set_page_config(page_title="SmartAttend AI", page_icon="🕒", layout="wide")

import config
from database.db import engine, init_db
from dashboard import theme, views
from services import auth

init_db()
st.session_state.setdefault("theme", "dark")
st.session_state.setdefault("user", None)
theme.apply(st.session_state["theme"])

ADMIN_PAGES = {"Overview": views.overview, "Employee Management": views.employee_management,
               "Face Registration": views.face_registration, "Mark Attendance": views.mark_attendance,
               "Live Attendance Records": views.live_records, "Location Tracking": views.location_tracking,
               "Analytics": views.analytics_page, "Machine Learning Predictions": views.ml_page,
               "Reports": views.reports_page, "Database Management": views.database_management,
               "Settings": views.settings_page}
EMPLOYEE_PAGES = {"Mark Attendance": views.mark_attendance}


def login_screen():
    st.title("SmartAttend AI")
    st.caption("AI-powered smart attendance and workforce analytics")
    if not auth.has_any_admin():
        st.subheader("First-time setup: create the administrator account")
        with st.form("first"):
            u = st.text_input("Admin username"); p = st.text_input("Password (8+ chars, letters and digits)", type="password")
            if st.form_submit_button("Create admin"):
                try:
                    auth.create_admin(u, p, "superadmin"); st.success("Admin created. Log in now."); st.rerun()
                except Exception as e:
                    st.error(str(e))
        return
    t1, t2 = st.tabs(["Administrator", "Employee"])
    with t1, st.form("a"):
        u = st.text_input("Username"); p = st.text_input("Password", type="password")
        if st.form_submit_button("Log in as admin"):
            try:
                st.session_state["user"] = auth.login_admin(u, p); st.rerun()
            except auth.AuthError as e:
                st.error(str(e))
    with t2, st.form("e"):
        c = st.text_input("Employee ID (e.g. EMP0001)"); p = st.text_input("Password ", type="password")
        if st.form_submit_button("Log in as employee"):
            try:
                st.session_state["user"] = auth.login_employee(c.strip(), p); st.rerun()
            except auth.AuthError as e:
                st.error(str(e))


user = st.session_state["user"]
if not user:
    login_screen()
    st.stop()

pages = ADMIN_PAGES if user["role"] == "admin" else EMPLOYEE_PAGES
user.setdefault("username", user.get("emp_code"))
with st.sidebar:
    st.markdown("### SmartAttend AI")
    st.caption(f"Signed in: {user['username']} ({user['role']})")
    page = st.radio("Navigate", list(pages), label_visibility="collapsed")
    mode = st.toggle("Light theme", value=st.session_state["theme"] == "light")
    if mode != (st.session_state["theme"] == "light"):
        st.session_state["theme"] = "light" if mode else "dark"; st.rerun()
    if st.button("Log out"):
        st.session_state["user"] = None; st.rerun()
pages[page]()
