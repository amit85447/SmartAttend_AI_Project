SMARTATTEND AI
AI-powered smart attendance and workforce analytics system
==========================================================

PART 0. WHAT THIS IS (plain words)
----------------------------------
A website that runs on your own computer. An employee opens it, takes a selfie, and shares their
phone/browser location. The system checks (1) it is really that employee's face (FaceNet deep
learning), (2) the face is live and not a photo of a photo (liveness checks), (3) they are at the
workplace (GPS and a radius around the office). Only if all three pass, attendance is saved in a
database. Then you get dashboards, machine learning predictions, Excel and PDF reports, and a
Power BI guide.

Be honest with yourself and interviewers about these limits:
 * A laptop webcam has no GPS. Real GPS comes from the browser "location" permission. Phones are
   accurate. Laptops often give rough locations, and the app will reject poor accuracy on purpose.
 * Camera and location in a browser need HTTPS, except on "localhost" (your own computer).
   To let employees use phones, you must host the app with an HTTPS address.
 * Liveness here is a smart check, not a certified bank-grade anti-spoofing product.
 * The demo data is FAKE (synthetic). Machine learning results on it only show the pipeline works.
 * The Power BI file (.pbix) is not included. It cannot be created outside Power BI Desktop.
   POWERBI_GUIDE.txt tells you every click and gives all DAX formulas.

PART 1. FIRST-TIME SETUP ON WINDOWS (zero experience needed)
------------------------------------------------------------
STEP 1. Install Python
  1. Open your browser, go to  https://www.python.org/downloads/windows/
  2. Download "Python 3.11.x" (Windows installer 64-bit). Python 3.10, 3.11 or 3.12 all work.
  3. Double-click the downloaded file.
  4. VERY IMPORTANT: on the first screen tick the box  "Add python.exe to PATH"  (bottom of the window).
  5. Click "Install Now". Wait. Click "Close".

STEP 2. Put the project folder somewhere simple
  Create the folder (if you used the installer file, this already happened):
  C:\smartattend
  Inside it you should see app.py, config.py, requirements.txt and folders like database and services.

STEP 3. Open a terminal INSIDE that folder
  1. Open File Explorer, go to C:\smartattend
  2. Click on the address bar at the top (where it says C:\smartattend), type  cmd  and press Enter.
  3. A black window opens. The text in it ends with  C:\smartattend>   That is correct.

STEP 4. Check Python works
  Type this and press Enter:
      python --version
  Success looks like:  Python 3.11.9   (any 3.10 to 3.12 number)
  If it says "'python' is not recognized", reinstall Python and tick "Add python.exe to PATH".

STEP 5. Create a private Python environment (keeps things tidy)
      python -m venv .venv
      .venv\Scripts\activate
  Success: the line now starts with  (.venv) C:\smartattend>
  (Every time you open a new terminal later, run  .venv\Scripts\activate  again first.)

STEP 6. Install the libraries (takes 5-15 minutes, about 2-3 GB because of PyTorch)
      python -m pip install --upgrade pip
      pip install -r requirements.txt
      pip install --no-deps facenet-pytorch
  Success: no red "ERROR" at the end. Warnings in yellow are fine.
  If it fails on torch: run  pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu  then repeat the first install command.

STEP 7. Load the FAKE demo data and create the demo admin
      python setup_demo.py
  Success looks like:  {'employees': 80, 'attendance_rows': ...}  then  Done. Admin login: admin / Demo#Pass123

STEP 8. Start the app
      streamlit run app.py
  Success: your browser opens http://localhost:8501 showing the SmartAttend AI login page.
  (If it does not open, copy that address into Chrome.)  Stop the app any time with Ctrl+C in the black window.
  Log in: tab Administrator, username  admin , password  Demo#Pass123

STEP 9. Run the tests (optional but impressive)
      pytest -q
  The first run downloads the FaceNet model (about 110 MB) and a public face dataset for the face tests.
  Tests that need the internet skip themselves if it is not available.

STEP 10. Build the datasets, charts, Excel workbook and ML results
      python run_analytics.py
  Success: folders  dataset\  and  excel\  fill with CSV, Excel, PNG charts and ml_results.json.

PART 2. MYSQL SETUP (beginner level)
------------------------------------
The demo works without MySQL (it uses a small file database). For the real project use MySQL.
  1. Go to  https://dev.mysql.com/downloads/installer/  and download "MySQL Installer" (the larger file is fine).
  2. Run it. Choose "Developer Default" or "Server only". Click Next until it asks for a root password.
  3. Choose a root password and WRITE IT DOWN. Keep the default port 3306. Finish the installer.
  4. Open the Start menu, type "MySQL 8.0 Command Line Client", open it, type the root password, press Enter.
     You should see the prompt  mysql>
  5. Create the database and tables. In the Start menu command line client type:
        source C:/smartattend/sql/01_schema_mysql.sql
     (use forward slashes). Success: lines like "Query OK, 0 rows affected" and no ERROR.
  6. Create a dedicated user (replace the password):
        CREATE USER 'smartattend'@'localhost' IDENTIFIED BY 'ChooseAStrongPassword1';
        GRANT ALL PRIVILEGES ON smartattend.* TO 'smartattend'@'localhost';
        FLUSH PRIVILEGES;
  7. Tell the app to use MySQL. In C:\smartattend copy the file  .env.example  to  .env  (File Explorer: copy, paste, rename;
     if you cannot see ".env.example", enable View > Show > File name extensions and Hidden items).
     Open .env in Notepad, put a # in front of the SQLite line, and remove the # from the MySQL line, e.g.
        SMARTATTEND_DB_URL=mysql+pymysql://smartattend:ChooseAStrongPassword1@localhost:3306/smartattend
  8. Create the encryption key:  python make_key.py   -> copy the long text into .env as  SMARTATTEND_KEY=that-text
     BACK THIS KEY UP. Without it saved face data cannot be read.
  9. Run  python setup_demo.py  (demo data) or just  streamlit run app.py  and use the "First-time setup" screen.
 10. Sample analytic queries: sql/03_analytical_queries.sql (open in MySQL Workbench or paste into the client).
 11. For Power BI also run  source C:/smartattend/sql/02_views_for_powerbi.sql
 Note: the Python code and the SQL files were tested here on SQLite because no MySQL server was available in the
 build environment. The schema file is plain MySQL 8 and matches the Python models (a test checks column names),
 but run the schema once on your machine and tell me if MySQL shows any error.

PART 3. USING THE APP (real use, not demo)
------------------------------------------
 1. Start with an empty database (do NOT run setup_demo.py). Open the app, create the admin on the first-time screen.
 2. Settings > Workplaces: add your office name, latitude, longitude and radius (150 m is a good start).
    Get coordinates: Google Maps, right-click the office entrance, click the numbers to copy.
 3. Settings > Schedules: start time, end time, grace minutes, working days, choose the workplace.
 4. Settings > Holidays: add holidays (attendance is closed those days).
 5. Employee Management > Register employee (gets an ID like EMP0001 and a temporary password).
 6. Face Registration: tick the consent box (the employee must truly agree), upload 3+ clear photos, click Enrol.
 7. The employee logs in on the "Employee" tab and opens Mark Attendance:
      a. Allow location when the browser asks.
      b. Take a straight photo.
      c. Take the second photo with the head turned toward the side the screen asks for.
      d. Submit. The result shows the face confidence and distance from the workplace.
 8. Database Management > "Run automatic absent marking" each day, or schedule it (below).

Webcam: Chrome/Edge will ask "Allow camera". Click Allow. If you clicked Block before, click the camera icon in the address bar and
        change it. GPS: the same for location. Windows: Settings > Privacy > Camera and Location must be ON for the browser.
Phones: run the app on a server with HTTPS (for example behind Cloudflare Tunnel, Caddy or a cloud host). Then employees open the address
        on their phone. Without HTTPS the phone browser blocks camera and location.

Schedule nightly absent marking and reports (Windows Task Scheduler):
  Create two small text files named  absent.bat  with:
      cd /d C:\smartattend
      .venv\Scripts\python.exe -c "from datetime import date,timedelta; from services.attendance import mark_absentees; mark_absentees(date.today()-timedelta(days=1))"
  In Task Scheduler choose Create Basic Task > Daily 23:55 > Start a program > pick absent.bat.
  Do the same with  python run_analytics.py  to refresh the dataset files for Power BI.

PART 4. PRIVACY AND SECURITY (what is built in)
-----------------------------------------------
 * Passwords: bcrypt hashes, minimum strength rules, lock after 5 wrong tries for 15 minutes.
 * Face templates and all photos are encrypted on disk and in the database (Fernet, key in .env). They are never served as public files.
 * Face enrolment is refused unless consent is recorded. Consent can be withdrawn and templates deleted (Database Management).
 * Retention: purge attendance photos older than N days. Employee deletion anonymises personal fields and keeps attendance rows.
 * Admin-only pages. Employees can only mark their own attendance. Admin cannot bypass face or GPS checks.
 * Every login, enrolment, rejection, deletion is written to the audit log.
 * Verification failures save nothing and are logged. IP location is never accepted as GPS.
 * Limit: software cannot prove a phone is not using a "fake GPS" app. Spoof flags are risk signals; review the GPS report.
 * Follow your local privacy law (in India: the DPDP Act). Face data is sensitive: tell employees what you store and why.

PART 5. FOLDER MAP
------------------
 app.py                      Streamlit app entry (login + navigation)
 config.py                   settings (thresholds, folders, security)
 setup_demo.py               loads fake demo data + admin
 run_analytics.py            builds datasets, charts, Excel workbook, ML results
 make_key.py                 makes the encryption key
 requirements.txt  .env.example  .gitignore  .streamlit/config.toml
 database/tables.py db.py seed_synthetic.py        tables (SQLAlchemy), connection, fake data generator
 models/face_model.py liveness.py                  FaceNet (PyTorch) + MTCNN detector, liveness checks
 services/auth.py employees.py face_service.py geo.py attendance.py retention.py audit.py crypto.py
 analytics/cleaning.py eda.py ml.py                Module 6 and 7
 reports/exporters.py excel_workbook.py            Module 8 and 10
 dashboard/theme.py views.py                       Module 11 pages
 utils/geo.py images.py browser_gps.py
 sql/01_schema_mysql.sql 02_views_for_powerbi.sql 03_analytical_queries.sql
 powerbi/POWERBI_GUIDE.txt                         Power BI steps + DAX
 excel/  dataset/                                  generated by run_analytics.py
 employee_photos/ attendance_photos/               encrypted images (private)
 tests/                                            pytest suites per module
 docs/                                             architecture and testing notes

PART 6. WHERE EACH PIECE NEEDS EXTRA HARDWARE OR A BROWSER
----------------------------------------------------------
 Webcam/phone camera: needed for Mark Attendance and Face Registration (browser permission).
 GPS: phone browser (accurate) or laptop (rough). Needs HTTPS or localhost.
 MySQL: a MySQL 8 server. Power BI: Windows PC with Power BI Desktop. Excel: Excel 2021 or Microsoft 365 for XLOOKUP.
 GPU: not needed. FaceNet runs on CPU in about a second per photo.

PART 7. HOW TO TALK ABOUT THIS IN INTERVIEWS (honest)
-----------------------------------------------------
 Say what is real: FaceNet embeddings with cosine matching measured on a public dataset (see docs/TESTING.txt), encrypted storage,
 geofencing with spoof flags, time-based ML evaluation with baselines and no leakage. Say what is limited: heuristic liveness,
 synthetic demo data, no .pbix shipped. Honest limits impress more than inflated claims.
