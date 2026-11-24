"""SQLAlchemy Core table definitions. They mirror sql/01_schema_mysql.sql and work on MySQL and SQLite."""
from sqlalchemy import (MetaData, Table, Column, Integer, BigInteger, String, Date, DateTime, Time,
                        Numeric, Boolean, ForeignKey, UniqueConstraint, Index, LargeBinary, Text,
                        CheckConstraint, Enum, func)

metadata = MetaData()
BigPK = BigInteger().with_variant(Integer, "sqlite")   # SQLite needs INTEGER for autoincrement

departments = Table("departments", metadata,
    Column("department_id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(80), nullable=False, unique=True),
    Column("created_at", DateTime, nullable=False, server_default=func.now()))

work_locations = Table("work_locations", metadata,
    Column("location_id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(100), nullable=False, unique=True),
    Column("latitude", Numeric(9, 6), nullable=False),
    Column("longitude", Numeric(9, 6), nullable=False),
    Column("radius_m", Integer, nullable=False, default=150),
    CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_lat"),
    CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_lon"),
    CheckConstraint("radius_m BETWEEN 20 AND 5000", name="ck_radius"))

work_schedules = Table("work_schedules", metadata,
    Column("schedule_id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(80), nullable=False, unique=True),
    Column("start_time", Time, nullable=False),
    Column("end_time", Time, nullable=False),
    Column("grace_minutes", Integer, nullable=False, default=10),
    Column("working_days", String(20), nullable=False, default="0,1,2,3,4"),
    Column("location_id", Integer, ForeignKey("work_locations.location_id")))

employees = Table("employees", metadata,
    Column("employee_id", Integer, primary_key=True, autoincrement=True),
    Column("emp_code", String(20), nullable=False, unique=True),
    Column("full_name", String(120), nullable=False),
    Column("department_id", Integer, ForeignKey("departments.department_id"), nullable=False),
    Column("designation", String(80), nullable=False),
    Column("email", String(150), nullable=False, unique=True),
    Column("phone", String(20)),
    Column("schedule_id", Integer, ForeignKey("work_schedules.schedule_id"), nullable=False),
    Column("password_hash", String(255), nullable=False),
    Column("biometric_consent", Boolean, nullable=False, default=False),
    Column("consent_at", DateTime),
    Column("status", Enum("active", "inactive", "deleted", name="emp_status"), nullable=False, default="active"),
    Column("joined_on", Date, nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Index("ix_emp_dept", "department_id"), Index("ix_emp_status", "status"))

face_profiles = Table("face_profiles", metadata,
    Column("profile_id", Integer, primary_key=True, autoincrement=True),
    Column("employee_id", Integer, ForeignKey("employees.employee_id", ondelete="CASCADE"), nullable=False),
    Column("embedding_enc", LargeBinary, nullable=False),
    Column("embedding_dim", Integer, nullable=False),
    Column("model_name", String(40), nullable=False),
    Column("image_path", String(300)),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Index("ix_fp_emp", "employee_id"))

attendance = Table("attendance", metadata,
    Column("attendance_id", BigPK, primary_key=True, autoincrement=True),
    Column("employee_id", Integer, ForeignKey("employees.employee_id"), nullable=False),
    Column("att_date", Date, nullable=False),
    Column("check_in_ts", DateTime),
    Column("check_out_ts", DateTime),
    Column("status", Enum("present", "late", "absent", "holiday", "weekend", name="att_status"), nullable=False),
    Column("late_minutes", Integer, nullable=False, default=0),
    Column("working_hours", Numeric(5, 2)),
    Column("face_conf_in", Numeric(5, 4)), Column("face_conf_out", Numeric(5, 4)),
    Column("liveness_in", Numeric(5, 4)), Column("liveness_out", Numeric(5, 4)),
    Column("verification_status", Enum("verified", "rejected", "not_applicable", name="ver_status"),
           nullable=False, default="verified"),
    Column("source", Enum("app", "auto_absent", name="att_source"), nullable=False, default="app"),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    UniqueConstraint("employee_id", "att_date", name="uq_att_emp_day"),
    Index("ix_att_date", "att_date"), Index("ix_att_status", "status"))

attendance_photos = Table("attendance_photos", metadata,
    Column("photo_id", BigPK, primary_key=True, autoincrement=True),
    Column("attendance_id", BigInteger, ForeignKey("attendance.attendance_id", ondelete="CASCADE"), nullable=False),
    Column("kind", Enum("check_in", "check_out", name="photo_kind"), nullable=False),
    Column("file_path", String(300), nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("captured_at", DateTime, nullable=False),
    UniqueConstraint("attendance_id", "kind", name="uq_ap"))

location_logs = Table("location_logs", metadata,
    Column("log_id", BigPK, primary_key=True, autoincrement=True),
    Column("employee_id", Integer, ForeignKey("employees.employee_id"), nullable=False),
    Column("attendance_id", BigInteger, ForeignKey("attendance.attendance_id", ondelete="SET NULL")),
    Column("logged_at", DateTime, nullable=False),
    Column("latitude", Numeric(9, 6), nullable=False),
    Column("longitude", Numeric(9, 6), nullable=False),
    Column("accuracy_m", Numeric(8, 2), nullable=False),
    Column("distance_m", Numeric(10, 2)),
    Column("within_geofence", Boolean, nullable=False),
    Column("spoof_flags", String(200), nullable=False, default=""),
    Column("source", Enum("browser_gps", "manual_admin", "ip_estimate", name="loc_source"),
           nullable=False, default="browser_gps"),
    Column("result", Enum("accepted", "rejected", name="loc_result"), nullable=False),
    Index("ix_ll_emp_time", "employee_id", "logged_at"))

holidays = Table("holidays", metadata,
    Column("holiday_date", Date, primary_key=True),
    Column("name", String(100), nullable=False))

admin_users = Table("admin_users", metadata,
    Column("admin_id", Integer, primary_key=True, autoincrement=True),
    Column("username", String(60), nullable=False, unique=True),
    Column("password_hash", String(255), nullable=False),
    Column("role", Enum("superadmin", "hr", name="admin_role"), nullable=False, default="hr"),
    Column("is_active", Boolean, nullable=False, default=True),
    Column("failed_attempts", Integer, nullable=False, default=0),
    Column("locked_until", DateTime),
    Column("last_login", DateTime))

audit_logs = Table("audit_logs", metadata,
    Column("log_id", BigPK, primary_key=True, autoincrement=True),
    Column("ts", DateTime, nullable=False, server_default=func.now()),
    Column("actor_type", Enum("admin", "employee", "system", name="actor_type"), nullable=False),
    Column("actor_id", String(40), nullable=False),
    Column("action", String(60), nullable=False),
    Column("entity", String(40)), Column("entity_id", String(40)),
    Column("details", Text),
    Index("ix_audit_ts", "ts"), Index("ix_audit_actor", "actor_type", "actor_id"))
