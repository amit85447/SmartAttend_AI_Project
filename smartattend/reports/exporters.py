"""Module 10: the eight reports, each exportable as CSV, Excel and PDF."""
from __future__ import annotations
from datetime import date, timedelta
from io import BytesIO
import pandas as pd
from sqlalchemy import select
from analytics import cleaning, eda
from database.db import engine
from database.tables import location_logs, employees, work_schedules, work_locations
from services import attendance as A

REPORTS = ["Daily attendance", "Weekly attendance", "Monthly attendance", "Employee report", "Department report",
           "Late arrival report", "Absent employee report", "GPS verification report"]


def _clean(eng, start, end):
    df = A.records(start, end, eng)
    if df.empty:
        return df
    c, _ = cleaning.clean(df)
    return c


def gps_log(eng, start, end) -> pd.DataFrame:
    q = (select(location_logs.c.log_id, employees.c.emp_code, employees.c.full_name, location_logs.c.logged_at,
                location_logs.c.latitude, location_logs.c.longitude, location_logs.c.accuracy_m,
                location_logs.c.distance_m, location_logs.c.within_geofence, location_logs.c.spoof_flags,
                location_logs.c.source, location_logs.c.result, work_locations.c.name.label("workplace"))
         .join(employees, employees.c.employee_id == location_logs.c.employee_id)
         .join(work_schedules, work_schedules.c.schedule_id == employees.c.schedule_id)
         .join(work_locations, work_locations.c.location_id == work_schedules.c.location_id)
         .where(location_logs.c.logged_at >= pd.Timestamp(start)).where(location_logs.c.logged_at < pd.Timestamp(end) + pd.Timedelta(days=1)))
    df = pd.read_sql(q, eng)
    df.columns = [str(c) for c in df.columns]
    return df


def build(name: str, start: date, end: date, emp_code: str | None = None, department: str | None = None, eng=None) -> pd.DataFrame:
    eng = eng or engine()
    if name == "GPS verification report":
        return gps_log(eng, start, end)
    d = _clean(eng, start, end)
    if d.empty:
        return d
    cols = ["att_date", "emp_code", "full_name", "department", "status", "check_in_ts", "check_out_ts",
            "late_minutes", "working_hours", "face_conf_in"]
    if name == "Daily attendance":
        return d[d["att_date"] == pd.Timestamp(end)][cols].sort_values("emp_code")
    if name == "Weekly attendance":
        w = d[d["att_date"] >= pd.Timestamp(end) - pd.Timedelta(days=6)]
        return eda.punctuality(w, 1).merge(
            w[w.status.isin(["present", "late", "absent"])].groupby("emp_code").agg(absent_days=("status", lambda s: (s == "absent").sum())).reset_index(), on="emp_code", how="left")
    if name == "Monthly attendance":
        return eda.monthly(d) if (end - start).days > 40 else eda.daily(d)
    if name == "Employee report":
        if not emp_code:
            raise ValueError("Choose an employee")
        return d[d["emp_code"] == emp_code][cols].sort_values("att_date")
    if name == "Department report":
        x = d if not department else d[d["department"] == department]
        return eda.by_department(x) if not department else eda.punctuality(x, 1)
    if name == "Late arrival report":
        return d[d["status"] == "late"][cols].sort_values("late_minutes", ascending=False)
    if name == "Absent employee report":
        return d[d["status"] == "absent"][["att_date", "emp_code", "full_name", "department"]].sort_values(["att_date", "emp_code"])
    raise ValueError(name)


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def to_excel_bytes(df: pd.DataFrame, title: str) -> bytes:
    from openpyxl.utils import get_column_letter
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        out = df.copy()
        for c in out.select_dtypes(include=["datetimetz"]).columns:
            out[c] = out[c].dt.tz_localize(None)
        out.to_excel(xw, sheet_name=title[:30], index=False)
        ws = xw.sheets[title[:30]]
        for i, col in enumerate(out.columns, 1):
            ws.column_dimensions[get_column_letter(i)].width = min(40, max(12, len(str(col)) + 4))
        ws.freeze_panes = "A2"
    return buf.getvalue()


def to_pdf_bytes(df: pd.DataFrame, title: str, subtitle: str = "") -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=24, rightMargin=24, topMargin=28, bottomMargin=28)
    st = getSampleStyleSheet()
    els = [Paragraph(f"SmartAttend AI - {title}", st["Title"]), Paragraph(subtitle, st["Normal"]), Spacer(1, 10)]
    if df.empty:
        els.append(Paragraph("No records for this selection.", st["Normal"]))
    else:
        show = df.head(400).copy()
        for c in show.columns:
            if pd.api.types.is_datetime64_any_dtype(show[c]):
                show[c] = show[c].dt.strftime("%Y-%m-%d %H:%M").str.replace(" 00:00", "", regex=False)
        show = show.round(2).fillna("")
        data = [list(map(str, show.columns))] + show.astype(str).values.tolist()
        t = Table(data, repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3A5F")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                               ("FONTSIZE", (0, 0), (-1, -1), 7), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#EEF2F7")]),
                               ("GRID", (0, 0), (-1, -1), 0.25, colors.grey)]))
        els.append(t)
        if len(df) > 400:
            els.append(Paragraph(f"Showing first 400 of {len(df)} rows. Use CSV/Excel for the full data.", st["Italic"]))
    doc.build(els)
    return buf.getvalue()
