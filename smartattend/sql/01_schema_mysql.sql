-- SmartAttend AI : MySQL 8.0+ schema (InnoDB, utf8mb4)
-- Run:  mysql -u root -p < sql/01_schema_mysql.sql
CREATE DATABASE IF NOT EXISTS smartattend CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE smartattend;

CREATE TABLE departments (
  department_id INT AUTO_INCREMENT PRIMARY KEY,
  name          VARCHAR(80) NOT NULL UNIQUE,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE work_locations (
  location_id   INT AUTO_INCREMENT PRIMARY KEY,
  name          VARCHAR(100) NOT NULL UNIQUE,
  latitude      DECIMAL(9,6) NOT NULL,
  longitude     DECIMAL(9,6) NOT NULL,
  radius_m      INT NOT NULL DEFAULT 150,
  CONSTRAINT ck_lat CHECK (latitude BETWEEN -90 AND 90),
  CONSTRAINT ck_lon CHECK (longitude BETWEEN -180 AND 180),
  CONSTRAINT ck_radius CHECK (radius_m BETWEEN 20 AND 5000)
) ENGINE=InnoDB;

CREATE TABLE work_schedules (
  schedule_id   INT AUTO_INCREMENT PRIMARY KEY,
  name          VARCHAR(80) NOT NULL UNIQUE,
  start_time    TIME NOT NULL,
  end_time      TIME NOT NULL,
  grace_minutes INT NOT NULL DEFAULT 10,
  working_days  VARCHAR(20) NOT NULL DEFAULT '0,1,2,3,4',   -- Mon=0 ... Sun=6
  location_id   INT NULL,
  CONSTRAINT fk_ws_loc FOREIGN KEY (location_id) REFERENCES work_locations(location_id)
) ENGINE=InnoDB;

CREATE TABLE employees (
  employee_id     INT AUTO_INCREMENT PRIMARY KEY,
  emp_code        VARCHAR(20) NOT NULL UNIQUE,              -- e.g. EMP0001
  full_name       VARCHAR(120) NOT NULL,
  department_id   INT NOT NULL,
  designation     VARCHAR(80) NOT NULL,
  email           VARCHAR(150) NOT NULL UNIQUE,
  phone           VARCHAR(20),
  schedule_id     INT NOT NULL,
  password_hash   VARCHAR(255) NOT NULL,                    -- bcrypt
  biometric_consent TINYINT(1) NOT NULL DEFAULT 0,
  consent_at      DATETIME NULL,
  status          ENUM('active','inactive','deleted') NOT NULL DEFAULT 'active',
  joined_on       DATE NOT NULL,
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_emp_dept FOREIGN KEY (department_id) REFERENCES departments(department_id),
  CONSTRAINT fk_emp_sched FOREIGN KEY (schedule_id) REFERENCES work_schedules(schedule_id),
  INDEX ix_emp_dept (department_id),
  INDEX ix_emp_status (status)
) ENGINE=InnoDB;

CREATE TABLE face_profiles (
  profile_id    INT AUTO_INCREMENT PRIMARY KEY,
  employee_id   INT NOT NULL,
  embedding_enc BLOB NOT NULL,                              -- Fernet-encrypted float32 vector
  embedding_dim INT NOT NULL,
  model_name    VARCHAR(40) NOT NULL,
  image_path    VARCHAR(300) NULL,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_fp_emp FOREIGN KEY (employee_id) REFERENCES employees(employee_id) ON DELETE CASCADE,
  INDEX ix_fp_emp (employee_id)
) ENGINE=InnoDB;

CREATE TABLE attendance (
  attendance_id   BIGINT AUTO_INCREMENT PRIMARY KEY,
  employee_id     INT NOT NULL,
  att_date        DATE NOT NULL,
  check_in_ts     DATETIME NULL,
  check_out_ts    DATETIME NULL,
  status          ENUM('present','late','absent','holiday','weekend') NOT NULL,
  late_minutes    INT NOT NULL DEFAULT 0,
  working_hours   DECIMAL(5,2) NULL,
  face_conf_in    DECIMAL(5,4) NULL,
  face_conf_out   DECIMAL(5,4) NULL,
  liveness_in     DECIMAL(5,4) NULL,
  liveness_out    DECIMAL(5,4) NULL,
  verification_status ENUM('verified','rejected','not_applicable') NOT NULL DEFAULT 'verified',
  source          ENUM('app','auto_absent') NOT NULL DEFAULT 'app',
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_att_emp FOREIGN KEY (employee_id) REFERENCES employees(employee_id),
  CONSTRAINT uq_att_emp_day UNIQUE (employee_id, att_date),   -- duplicate prevention
  INDEX ix_att_date (att_date),
  INDEX ix_att_status (status)
) ENGINE=InnoDB;

CREATE TABLE attendance_photos (
  photo_id      BIGINT AUTO_INCREMENT PRIMARY KEY,
  attendance_id BIGINT NOT NULL,
  kind          ENUM('check_in','check_out') NOT NULL,
  file_path     VARCHAR(300) NOT NULL,                      -- private folder, encrypted at rest
  sha256        CHAR(64) NOT NULL,
  captured_at   DATETIME NOT NULL,
  CONSTRAINT fk_ap_att FOREIGN KEY (attendance_id) REFERENCES attendance(attendance_id) ON DELETE CASCADE,
  CONSTRAINT uq_ap UNIQUE (attendance_id, kind)
) ENGINE=InnoDB;

CREATE TABLE location_logs (
  log_id        BIGINT AUTO_INCREMENT PRIMARY KEY,
  employee_id   INT NOT NULL,
  attendance_id BIGINT NULL,
  logged_at     DATETIME NOT NULL,
  latitude      DECIMAL(9,6) NOT NULL,
  longitude     DECIMAL(9,6) NOT NULL,
  accuracy_m    DECIMAL(8,2) NOT NULL,
  distance_m    DECIMAL(10,2) NULL,
  within_geofence TINYINT(1) NOT NULL,
  spoof_flags   VARCHAR(200) NOT NULL DEFAULT '',
  source        ENUM('browser_gps','manual_admin','ip_estimate') NOT NULL DEFAULT 'browser_gps',
  result        ENUM('accepted','rejected') NOT NULL,
  CONSTRAINT fk_ll_emp FOREIGN KEY (employee_id) REFERENCES employees(employee_id),
  CONSTRAINT fk_ll_att FOREIGN KEY (attendance_id) REFERENCES attendance(attendance_id) ON DELETE SET NULL,
  INDEX ix_ll_emp_time (employee_id, logged_at)
) ENGINE=InnoDB;

CREATE TABLE holidays (
  holiday_date DATE PRIMARY KEY,
  name         VARCHAR(100) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE admin_users (
  admin_id        INT AUTO_INCREMENT PRIMARY KEY,
  username        VARCHAR(60) NOT NULL UNIQUE,
  password_hash   VARCHAR(255) NOT NULL,
  role            ENUM('superadmin','hr') NOT NULL DEFAULT 'hr',
  is_active       TINYINT(1) NOT NULL DEFAULT 1,
  failed_attempts INT NOT NULL DEFAULT 0,
  locked_until    DATETIME NULL,
  last_login      DATETIME NULL
) ENGINE=InnoDB;

CREATE TABLE audit_logs (
  log_id     BIGINT AUTO_INCREMENT PRIMARY KEY,
  ts         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  actor_type ENUM('admin','employee','system') NOT NULL,
  actor_id   VARCHAR(40) NOT NULL,
  action     VARCHAR(60) NOT NULL,
  entity     VARCHAR(40) NULL,
  entity_id  VARCHAR(40) NULL,
  details    TEXT NULL,
  INDEX ix_audit_ts (ts),
  INDEX ix_audit_actor (actor_type, actor_id)
) ENGINE=InnoDB;
