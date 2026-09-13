import os

# ---------- Environment ----------
FIREBASE_DB_URL = os.environ["FIREBASE_DB_URL"]
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
FIREBASE_CREDENTIALS_FILE = "firebase_credentials.json"

# ---------- HTTP ----------
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JobNoticeBot/1.0)"}
REQUEST_TIMEOUT = 15  # সেকেন্ড — স্লো/মৃত সাইটে বেশিক্ষণ আটকে থাকবে না

# ---------- FCM Topics ----------
ALL_NOTICES_TOPIC = "all_job_notices"
ADMIN_ALERTS_TOPIC = "admin_alerts"

# ---------- Health tracking ----------
FAIL_THRESHOLD = 3  # এতবার পরপর খালি ফলাফল পেলে অ্যাডমিন অ্যালার্ট যাবে

# ---------- Concurrency ----------
MAX_WORKERS = 20  # একসাথে কতগুলো সাইট স্ক্র্যাপ হবে

# ---------- Parsing ----------
ACTION_WORDS = {"দেখুন", "বিস্তারিত", "view", "details", "download", "ডাউনলোড"}
GEMINI_MODEL = "gemini-flash-latest"
