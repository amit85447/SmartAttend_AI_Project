"""Central configuration. Every value can be overridden with an environment variable
or a .env file placed next to this file (see .env.example in README)."""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _f(name, default):
    return float(os.getenv(name, default))


# --- Database -------------------------------------------------------------
# MySQL (production):  mysql+pymysql://user:password@localhost:3306/smartattend
# SQLite (quick local test): sqlite:///smartattend_test.db
DB_URL = os.getenv("SMARTATTEND_DB_URL", f"sqlite:///{BASE_DIR / 'smartattend_dev.db'}")

# --- Storage (private folders; never mounted as static web files) ---------
EMPLOYEE_PHOTO_DIR = Path(os.getenv("EMPLOYEE_PHOTO_DIR", BASE_DIR / "employee_photos"))
ATTENDANCE_PHOTO_DIR = Path(os.getenv("ATTENDANCE_PHOTO_DIR", BASE_DIR / "attendance_photos"))
DATASET_DIR = BASE_DIR / "dataset"
EXPORT_DIR = BASE_DIR / "exports"

# --- Security -------------------------------------------------------------
# Fernet key used to encrypt embeddings and photos at rest. Generate once:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Losing this key makes stored biometrics unreadable. Keep it out of git.
ENCRYPTION_KEY = os.getenv("SMARTATTEND_KEY", "")
KEY_FILE = BASE_DIR / ".smartattend.key"   # auto-created on first run if no env key
MAX_FAILED_LOGINS = int(os.getenv("MAX_FAILED_LOGINS", 5))
LOCKOUT_MINUTES = int(os.getenv("LOCKOUT_MINUTES", 15))
MIN_PASSWORD_LENGTH = 8

# --- Face recognition -----------------------------------------------------
FACE_MODEL_NAME = "facenet-vggface2"          # InceptionResnetV1 pretrained on VGGFace2
FACE_MATCH_THRESHOLD = _f("FACE_MATCH_THRESHOLD", 0.60)   # cosine similarity; LFW test: 0.60 -> TAR 98.5%, FAR 0.0% (tune on your own staff)
FACE_MARGIN_OVER_OTHERS = _f("FACE_MARGIN", 0.05)         # must beat best other employee by this
MIN_FACE_PROB = _f("MIN_FACE_PROB", 0.95)                 # MTCNN detection confidence
MIN_ENROLL_IMAGES = int(os.getenv("MIN_ENROLL_IMAGES", 3))

# --- Liveness -------------------------------------------------------------
LIVENESS_REQUIRED = os.getenv("LIVENESS_REQUIRED", "1") == "1"
LIVENESS_THRESHOLD = _f("LIVENESS_THRESHOLD", 0.55)
HEAD_TURN_MIN_SHIFT = _f("HEAD_TURN_MIN_SHIFT", 0.06)   # normalised nose shift between frames

# --- GPS / geofence -------------------------------------------------------
MAX_GPS_ACCURACY_M = _f("MAX_GPS_ACCURACY_M", 100)      # reject fixes worse than this
MAX_FIX_AGE_S = _f("MAX_FIX_AGE_S", 60)                  # reject stale fixes
MAX_TRAVEL_SPEED_MPS = _f("MAX_TRAVEL_SPEED_MPS", 70)    # ~250 km/h, faster = suspicious jump

# --- Attendance rules -----------------------------------------------------
MIN_CHECKOUT_GAP_MIN = int(os.getenv("MIN_CHECKOUT_GAP_MIN", 5))
DATA_RETENTION_DAYS_PHOTOS = int(os.getenv("RETENTION_PHOTOS_DAYS", 180))
