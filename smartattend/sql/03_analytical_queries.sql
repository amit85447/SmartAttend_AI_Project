-- SmartAttend AI : analytical queries (MySQL 8). Each block starts with "-- Q<number>:" and ends with ";".

-- Q1: Department attendance rate (JOIN + GROUP BY)
SELECT d.name AS department,
       COUNT(*) AS scheduled_days,
       SUM(CASE WHEN a.status IN ('present','late') THEN 1 ELSE 0 END) AS present_days,
       ROUND(100.0 * SUM(CASE WHEN a.status IN ('present','late') THEN 1 ELSE 0 END) / COUNT(*), 2) AS attendance_pct
FROM attendance a
JOIN employees e ON e.employee_id = a.employee_id
JOIN departments d ON d.department_id = e.department_id
WHERE a.status IN ('present','late','absent')
GROUP BY d.name
ORDER BY attendance_pct DESC;

-- Q2: Monthly attendance with month-over-month change (CTE + window function LAG)
WITH monthly AS (
  SELECT DATE_FORMAT(att_date, '%Y-%m') AS ym,
         100.0 * SUM(CASE WHEN status IN ('present','late') THEN 1 ELSE 0 END) / COUNT(*) AS att_pct
  FROM attendance
  WHERE status IN ('present','late','absent')
  GROUP BY DATE_FORMAT(att_date, '%Y-%m')
)
SELECT ym, ROUND(att_pct, 2) AS att_pct,
       ROUND(att_pct - LAG(att_pct) OVER (ORDER BY ym), 2) AS change_vs_prev_month
FROM monthly
ORDER BY ym;

-- Q3: Top 10 most punctual employees (CTE + RANK window function)
WITH per_emp AS (
  SELECT e.emp_code, e.full_name,
         COUNT(*) AS days_present,
         SUM(CASE WHEN a.status = 'late' THEN 1 ELSE 0 END) AS late_days
  FROM attendance a JOIN employees e ON e.employee_id = a.employee_id
  WHERE a.status IN ('present','late')
  GROUP BY e.emp_code, e.full_name
  HAVING COUNT(*) >= 20
)
SELECT emp_code, full_name, days_present, late_days,
       ROUND(100.0 * late_days / days_present, 1) AS late_pct,
       RANK() OVER (ORDER BY 1.0 * late_days / days_present ASC) AS punctuality_rank
FROM per_emp
ORDER BY punctuality_rank
LIMIT 10;

-- Q4: Employees later than their own department average (correlated-free subquery)
SELECT e.emp_code, e.full_name, ROUND(AVG(a.late_minutes), 1) AS avg_late_min
FROM attendance a JOIN employees e ON e.employee_id = a.employee_id
WHERE a.status IN ('present','late')
GROUP BY e.emp_code, e.full_name, e.department_id
HAVING AVG(a.late_minutes) > (
  SELECT AVG(a2.late_minutes)
  FROM attendance a2 JOIN employees e2 ON e2.employee_id = a2.employee_id
  WHERE e2.department_id = e.department_id AND a2.status IN ('present','late'))
ORDER BY avg_late_min DESC
LIMIT 15;

-- Q5: 7-day moving attendance count (window frame)
WITH daily AS (
  SELECT att_date,
         SUM(CASE WHEN status IN ('present','late') THEN 1 ELSE 0 END) AS present_cnt
  FROM attendance WHERE status IN ('present','late','absent')
  GROUP BY att_date
)
SELECT att_date, present_cnt,
       ROUND(AVG(present_cnt) OVER (ORDER BY att_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 1) AS moving_avg_7d
FROM daily
ORDER BY att_date;

-- Q6: Longest absence streaks start (consecutive absent rows using ROW_NUMBER gap trick)
WITH absent AS (
  SELECT employee_id, att_date,
         ROW_NUMBER() OVER (PARTITION BY employee_id ORDER BY att_date) AS rn
  FROM attendance WHERE status = 'absent'
), grp AS (
  SELECT a.employee_id, a.att_date,
         ROW_NUMBER() OVER (PARTITION BY a.employee_id ORDER BY a.att_date) AS rn2,
         (SELECT COUNT(*) FROM attendance x
            WHERE x.employee_id = a.employee_id AND x.att_date <= a.att_date AND x.status <> 'absent') AS present_before
  FROM attendance a WHERE a.status = 'absent'
)
SELECT employee_id, present_before, COUNT(*) AS consecutive_absent_days, MIN(att_date) AS first_day
FROM grp
GROUP BY employee_id, present_before
HAVING COUNT(*) >= 2
ORDER BY consecutive_absent_days DESC, employee_id
LIMIT 10;

-- Q7: Check-in hour distribution
SELECT CAST(SUBSTR(CAST(check_in_ts AS CHAR), 12, 2) AS UNSIGNED) AS checkin_hour, COUNT(*) AS n
FROM attendance
WHERE check_in_ts IS NOT NULL
GROUP BY CAST(SUBSTR(CAST(check_in_ts AS CHAR), 12, 2) AS UNSIGNED)
ORDER BY checkin_hour;

-- Q8: GPS verification summary per workplace (3-table join)
SELECT wl.name AS workplace, ll.result,
       COUNT(*) AS logs, ROUND(AVG(ll.distance_m), 1) AS avg_distance_m, ROUND(AVG(ll.accuracy_m), 1) AS avg_accuracy_m
FROM location_logs ll
JOIN employees e ON e.employee_id = ll.employee_id
JOIN work_schedules ws ON ws.schedule_id = e.schedule_id
JOIN work_locations wl ON wl.location_id = ws.location_id
GROUP BY wl.name, ll.result
ORDER BY wl.name, ll.result;

-- Q9: Employees with rejected GPS attempts (EXISTS subquery)
SELECT e.emp_code, e.full_name
FROM employees e
WHERE EXISTS (SELECT 1 FROM location_logs l WHERE l.employee_id = e.employee_id AND l.result = 'rejected')
ORDER BY e.emp_code
LIMIT 20;

-- Q10: Running total of late minutes per employee (SUM window)
SELECT employee_id, att_date, late_minutes,
       SUM(late_minutes) OVER (PARTITION BY employee_id ORDER BY att_date) AS cumulative_late_min
FROM attendance
WHERE status IN ('present','late') AND employee_id = 1
ORDER BY att_date
LIMIT 20;
