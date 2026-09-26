import os
from zoneinfo import ZoneInfo

# ---------- Environment ----------
FIREBASE_DB_URL = os.environ["FIREBASE_DB_URL"]
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
FIREBASE_CREDENTIALS_FILE = "firebase_credentials.json"

# ---------- HTTP ----------
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
REQUEST_TIMEOUT = 12
REQUEST_DELAY_SECONDS = 1

# ---------- FCM ----------
ALL_NOTICES_TOPIC = "all_job_notices"
ADMIN_ALERTS_TOPIC = "admin_alerts"


# ---------- Notice retention (নতুন) ----------
# Notices older than this are not saved at all (keeps Firebase small).
# Applies at scan time going forward — does NOT clean up old data already
# saved before this was added; use cleanup_old_notices.py for that.
NOTICE_MAX_AGE_DAYS = 365

# ---------- Health tracking ----------
FAIL_THRESHOLD = 3

# ---------- Concurrency ----------
MAX_WORKERS = 20

# ---------- Notice retention ----------
MAX_NOTICES_PER_SOURCE = 10   # প্রতি স্ক্যানে টেবিল থেকে সর্বোচ্চ কতগুলো item নেওয়া হবে
RECENT_NOTICE_HOURS = 72      # today_latest_notice ফিডের এক্সপায়ারি

# ---------- Timezone ----------
BD_TIMEZONE = ZoneInfo("Asia/Dhaka")

# ---------- Parsing ----------
ACTION_WORDS = {"দেখুন", "বিস্তারিত", "view", "details", "download", "ডাউনলোড"}
GEMINI_MODEL = "gemini-flash-latest"
