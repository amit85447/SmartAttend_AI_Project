"""Module 8: Excel workbook built from the application's real data (database -> workbook).

Sheets: README, Raw, Cleaned, Employees (lookup), Dept_Summary (COUNTIFS/SUMIFS formulas),
Employee_Monthly (COUNTIFS/SUMIFS + XLOOKUP formulas, conditional formatting), Daily (formulas),
Pivot_Guide. Formulas are live Excel formulas, so numbers recalculate when data changes.
Honest note: openpyxl cannot create native PivotTables. The formula summary sheets give the same
numbers, and Pivot_Guide has the 6 clicks to add a real PivotTable on the Cleaned table.
XLOOKUP needs Excel 2021 / Microsoft 365."""
from __future__ import annotations
from datetime import date
import pandas as pd
from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule, ColorScaleRule, FormulaRule
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo
from analytics import cleaning, eda
from services import attendance as A, employees as E

HDR = PatternFill("solid", fgColor="1F3A5F")


def _write(ws, df, table_name=None):
    df = df.copy()
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            df[c] = df[c].dt.tz_localize(None) if getattr(df[c].dt, "tz", None) else df[c]
    ws.append(list(df.columns))
    for row in df.itertuples(index=False):
        ws.append([None if (isinstance(v, float) and pd.isna(v)) or v is pd.NaT or (v is pd.NA) else (v.to_pydatetime() if isinstance(v, pd.Timestamp) else v) for v in row])
    for i, col in enumerate(df.columns, 1):
        ws.cell(1, i).font = Font(bold=True, color="FFFFFF"); ws.cell(1, i).fill = HDR
        ws.column_dimensions[get_column_letter(i)].width = max(12, min(30, len(str(col)) + 4))
        if "ts" in str(col):
            for r in range(2, len(df) + 2):
                ws.cell(r, i).number_format = "yyyy-mm-dd hh:mm"
        elif str(col) == "att_date":
            for r in range(2, len(df) + 2):
                ws.cell(r, i).number_format = "yyyy-mm-dd"
    ws.freeze_panes = "A2"
    if table_name and len(df):
        t = Table(displayName=table_name, ref=f"A1:{get_column_letter(len(df.columns))}{len(df) + 1}")
        t.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
        ws.add_table(t)


def build_workbook(raw: pd.DataFrame, path: str, eng=None):
    clean, rep = cleaning.clean(raw)
    clean = clean.copy()
    clean["month"] = clean["att_date"].dt.strftime("%Y-%m")
    for c in ("missing_checkout", "outlier_hours", "outlier_arrival"):
        clean[c] = clean[c].astype(int)
    keep = ["att_date", "month", "emp_code", "full_name", "department", "status", "check_in_ts", "check_out_ts",
            "late_minutes", "working_hours", "checkin_hour_float", "missing_checkout", "outlier_hours", "outlier_arrival"]
    cl = clean[keep].copy()
    cl["att_date"] = cl["att_date"].dt.tz_localize(None) if getattr(cl["att_date"].dt, "tz", None) else cl["att_date"]
    wb = Workbook()
    ws = wb.active; ws.title = "README"
    lines = ["SmartAttend AI - Excel report (generated from the application database)", f"Generated: {date.today()}", "",
             "Raw          : attendance exactly as exported", "Cleaned      : after Python cleaning (see counts below)",
             "Employees    : lookup table used by XLOOKUP", "Dept_Summary : COUNTIFS / SUMIFS by department",
             "Employee_Monthly : per employee per month, COUNTIFS + SUMIFS + XLOOKUP, attendance %, conditional formatting",
             "Daily        : per-day totals with formulas", "Pivot_Guide  : how to add a native PivotTable", "", "Cleaning report:"]
    lines += [f"  {k}: {v}" for k, v in rep.items()]
    for ln in lines:
        ws.append([ln])
    ws["A1"].font = Font(bold=True, size=14); ws.column_dimensions["A"].width = 100
    _write(wb.create_sheet("Raw"), raw)
    _write(wb.create_sheet("Cleaned"), cl, "tblCleaned")
    n = len(cl) + 1
    emps = E.list_employees(eng)[["emp_code", "full_name", "department", "designation", "email", "status"]]
    _write(wb.create_sheet("Employees"), emps, "tblEmployees")
    rng = lambda col: f"Cleaned!${col}$2:${col}${n}"       # A date, B month, C code, E dept, F status, I late, J hours
    # Dept summary
    d = wb.create_sheet("Dept_Summary")
    d.append(["Department", "Scheduled days", "Present (incl. late)", "Late", "Absent", "Attendance %", "Late % of present", "Avg hours"])
    depts = sorted(clean["department"].unique())
    for i, dep in enumerate(depts, 2):
        d.append([dep, f'=C{i}+E{i}', f'=COUNTIFS({rng("E")},A{i},{rng("F")},"present")+D{i}',
                  f'=COUNTIFS({rng("E")},A{i},{rng("F")},"late")', f'=COUNTIFS({rng("E")},A{i},{rng("F")},"absent")',
                  f'=IFERROR(C{i}/B{i},0)', f'=IFERROR(D{i}/C{i},0)', f'=IFERROR(AVERAGEIFS({rng("J")},{rng("E")},A{i}),0)'])
        d.cell(i, 6).number_format = d.cell(i, 7).number_format = "0.0%"; d.cell(i, 8).number_format = "0.00"
    for c in range(1, 9):
        d.cell(1, c).font = Font(bold=True, color="FFFFFF"); d.cell(1, c).fill = HDR; d.column_dimensions[get_column_letter(c)].width = 20
    d.conditional_formatting.add(f"F2:F{len(depts)+1}", ColorScaleRule(start_type="min", start_color="F8696B", mid_type="percentile", mid_value=50, mid_color="FFEB84", end_type="max", end_color="63BE7B"))
    # Employee x month
    em = wb.create_sheet("Employee_Monthly")
    em.append(["Month", "Emp code", "Name (XLOOKUP)", "Department (XLOOKUP)", "Present days", "Late days", "Absent days",
               "Attendance %", "Hours worked (SUMIFS)", "Avg late min (late days)"])
    pairs = clean.groupby(["month", "emp_code"]).size().reset_index()[["month", "emp_code"]].sort_values(["month", "emp_code"])
    for i, (m, ec) in enumerate(pairs.itertuples(index=False), 2):
        em.append([m, ec, f'=_xlfn.XLOOKUP(B{i},Employees!$A:$A,Employees!$B:$B,"?")', f'=_xlfn.XLOOKUP(B{i},Employees!$A:$A,Employees!$C:$C,"?")',
                   f'=COUNTIFS({rng("B")},A{i},{rng("C")},B{i},{rng("F")},"present")+F{i}',
                   f'=COUNTIFS({rng("B")},A{i},{rng("C")},B{i},{rng("F")},"late")',
                   f'=COUNTIFS({rng("B")},A{i},{rng("C")},B{i},{rng("F")},"absent")',
                   f'=IFERROR(E{i}/(E{i}+G{i}),0)', f'=SUMIFS({rng("J")},{rng("B")},A{i},{rng("C")},B{i})',
                   f'=IFERROR(AVERAGEIFS({rng("I")},{rng("B")},A{i},{rng("C")},B{i},{rng("F")},"late"),0)'])
        em.cell(i, 8).number_format = "0.0%"; em.cell(i, 9).number_format = "0.0"; em.cell(i, 10).number_format = "0.0"
    last = len(pairs) + 1
    for c in range(1, 11):
        em.cell(1, c).font = Font(bold=True, color="FFFFFF"); em.cell(1, c).fill = HDR; em.column_dimensions[get_column_letter(c)].width = 22
    em.freeze_panes = "A2"; em.auto_filter.ref = f"A1:J{last}"
    em.conditional_formatting.add(f"H2:H{last}", CellIsRule(operator="lessThan", formula=["0.85"], fill=PatternFill("solid", bgColor="F8CBAD")))
    em.conditional_formatting.add(f"H2:H{last}", CellIsRule(operator="greaterThanOrEqual", formula=["0.95"], fill=PatternFill("solid", bgColor="C6E0B4")))
    em.conditional_formatting.add(f"F2:F{last}", ColorScaleRule(start_type="min", start_color="FFFFFF", end_type="max", end_color="F4B183"))
    # Daily
    dl = wb.create_sheet("Daily")
    dl.append(["Date", "Present (incl. late)", "Late", "Absent", "Attendance %"])
    for i, dt in enumerate(sorted(cl["att_date"].unique()), 2):
        dl.append([pd.Timestamp(dt).to_pydatetime(), f'=COUNTIFS({rng("A")},A{i},{rng("F")},"present")+C{i}',
                   f'=COUNTIFS({rng("A")},A{i},{rng("F")},"late")', f'=COUNTIFS({rng("A")},A{i},{rng("F")},"absent")',
                   f'=IFERROR(B{i}/(B{i}+D{i}),0)'])
        dl.cell(i, 1).number_format = "yyyy-mm-dd"; dl.cell(i, 5).number_format = "0.0%"
    for c in range(1, 6):
        dl.cell(1, c).font = Font(bold=True, color="FFFFFF"); dl.cell(1, c).fill = HDR; dl.column_dimensions[get_column_letter(c)].width = 20
    pg = wb.create_sheet("Pivot_Guide")
    for ln in ["Add a native PivotTable (Excel desktop):", "1. Open sheet Cleaned, click any cell inside the table.",
               "2. Insert > PivotTable > New Worksheet.", "3. Rows: department. Columns: status. Values: Count of emp_code.",
               "4. Add a Slicer: PivotTable Analyze > Insert Slicer > month.", "5. Values > Show Values As > % of Row Total for attendance mix.",
               "6. Refresh after new data: Data > Refresh All."]:
        pg.append([ln])
    pg.column_dimensions["A"].width = 80
    wb.save(path)
    return rep
