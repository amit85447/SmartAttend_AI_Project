"""Builds every dataset/report file from the CURRENT database.
Usage: python run_analytics.py
Creates: dataset/attendance_raw_export.csv (+ messy copy for cleaning demo), dataset/attendance_clean.csv,
         dataset/attendance_clean.xlsx, dataset/ml_results.json, dataset/forecast_14d.csv,
         dataset/anomalies.csv, excel/SmartAttend_Report.xlsx, dataset/cleaning_report.json,
         dataset/charts/*.png and dataset/maps/locations.html"""
import json
import config
from analytics import cleaning, eda, ml
from database.db import engine
from reports import excel_workbook, exporters
from services import attendance as A

eng = engine()
config.DATASET_DIR.mkdir(exist_ok=True)
(config.BASE_DIR / "excel").mkdir(exist_ok=True)
raw = A.records(eng=eng)
if raw.empty:
    raise SystemExit("No attendance data. Run setup_demo.py first (or mark real attendance).")
raw.to_csv(config.DATASET_DIR / "attendance_raw_export.csv", index=False)
messy, injected = cleaning.inject_problems(raw)           # synthetic demonstration of the cleaning step
messy.to_csv(config.DATASET_DIR / "attendance_messy_for_cleaning_demo.csv", index=False)
clean, rep = cleaning.clean(messy)
rep["injected_problems_for_demo"] = injected
json.dump(rep, open(config.DATASET_DIR / "cleaning_report.json", "w"), indent=2, default=str)
clean.to_csv(config.DATASET_DIR / "attendance_clean.csv", index=False)
clean.assign(**{c: clean[c].dt.tz_localize(None) for c in clean.select_dtypes("datetimetz").columns}).to_excel(
    config.DATASET_DIR / "attendance_clean.xlsx", index=False)
daily = eda.daily(clean)
res = ml.run_all(clean, daily, config.DATASET_DIR / "ml_results.json")
feat = ml.build_features(clean)
_, fdf = ml.forecast_attendance(daily); fdf.to_csv(config.DATASET_DIR / "forecast_14d.csv", index=False)
_, an = ml.anomaly_detection(clean); an[an["is_anomaly"]].to_csv(config.DATASET_DIR / "anomalies.csv", index=False)
excel_workbook.build_workbook(messy, str(config.BASE_DIR / "excel" / "SmartAttend_Report.xlsx"), eng)

# charts (Matplotlib/Seaborn) and map (Folium)
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, seaborn as sns
ch = config.DATASET_DIR / "charts"; ch.mkdir(exist_ok=True)
fig, ax = plt.subplots(figsize=(10, 4)); tr, s = eda.trend(daily)
ax.plot(tr["att_date"], tr["attendance_pct"], alpha=.4); ax.plot(tr["att_date"], tr["rolling_7d"], lw=2)
ax.set_title("Daily attendance % (7-day average)"); fig.tight_layout(); fig.savefig(ch / "daily_trend.png", dpi=130); plt.close(fig)
dep = eda.by_department(clean); fig, ax = plt.subplots(figsize=(8, 4)); sns.barplot(data=dep, x="department", y="attendance_pct", ax=ax)
ax.set_title("Attendance % by department"); fig.tight_layout(); fig.savefig(ch / "department.png", dpi=130); plt.close(fig)
fig, ax = plt.subplots(figsize=(8, 4)); sns.histplot(clean["checkin_hour_float"].dropna(), bins=40, ax=ax)
ax.set_title("Check-in time distribution"); fig.tight_layout(); fig.savefig(ch / "checkin_hist.png", dpi=130); plt.close(fig)
wd = eda.weekday_pattern(clean); fig, ax = plt.subplots(figsize=(7, 4)); sns.barplot(data=wd, x="weekday", y="absent_pct", ax=ax)
ax.set_title("Absence % by weekday"); fig.tight_layout(); fig.savefig(ch / "weekday_absence.png", dpi=130); plt.close(fig)
import folium
log = exporters.gps_log(eng, clean["att_date"].min().date(), clean["att_date"].max().date())
if len(log):
    (config.DATASET_DIR / "maps").mkdir(exist_ok=True)
    m = folium.Map(location=[float(log.latitude.median()), float(log.longitude.median())], zoom_start=5)
    for wp, g in log.groupby("workplace"):
        g = g.sample(min(len(g), 400), random_state=0)
        for r in g.itertuples():
            folium.CircleMarker([float(r.latitude), float(r.longitude)], radius=2, color="green" if r.result == "accepted" else "red").add_to(m)
    m.save(str(config.DATASET_DIR / "maps" / "locations.html"))
print("Cleaning report:", rep)
print("ML summary written to dataset/ml_results.json")
