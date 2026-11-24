-- Views used by Power BI (import these 4 views instead of raw tables). MySQL 8.
USE smartattend;

CREATE OR REPLACE VIEW vw_attendance_fact AS
SELECT a.attendance_id, a.att_date, e.emp_code, e.full_name, d.name AS department, e.designation,
       a.status, a.late_minutes, a.working_hours,
       HOUR(a.check_in_ts) + MINUTE(a.check_in_ts) / 60 AS checkin_hour,
       a.check_in_ts, a.check_out_ts, a.face_conf_in, a.liveness_in,
       CASE WHEN a.status IN ('present','late') THEN 1 ELSE 0 END AS is_present,
       CASE WHEN a.status = 'late' THEN 1 ELSE 0 END AS is_late,
       CASE WHEN a.status = 'absent' THEN 1 ELSE 0 END AS is_absent
FROM attendance a
JOIN employees e ON e.employee_id = a.employee_id AND e.status <> 'deleted'
JOIN departments d ON d.department_id = e.department_id
WHERE a.status IN ('present','late','absent');

CREATE OR REPLACE VIEW vw_employees AS
SELECT e.emp_code, e.full_name, d.name AS department, e.designation, e.status, e.joined_on
FROM employees e JOIN departments d ON d.department_id = e.department_id WHERE e.status <> 'deleted';

CREATE OR REPLACE VIEW vw_locations AS
SELECT l.log_id, e.emp_code, l.logged_at, l.latitude, l.longitude, l.accuracy_m, l.distance_m,
       l.within_geofence, l.result, wl.name AS workplace
FROM location_logs l
JOIN employees e ON e.employee_id = l.employee_id
JOIN work_schedules ws ON ws.schedule_id = e.schedule_id
JOIN work_locations wl ON wl.location_id = ws.location_id;

CREATE OR REPLACE VIEW vw_holidays AS SELECT holiday_date, name FROM holidays;
