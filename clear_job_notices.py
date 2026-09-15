import os
import firebase_admin
from firebase_admin import credentials, db

cred = credentials.Certificate("firebase_credentials.json")
firebase_admin.initialize_app(cred, {"databaseURL": os.environ["FIREBASE_DB_URL"]})

# Site Resources ব্যতীত সবকিছু ফ্রেশ করা হচ্ছে
NODES_TO_CLEAR = [
    "job_notices",
    "today_latest_notice",
    "scanner_status",
    "source_health",
    "last_updated",
]

for node in NODES_TO_CLEAR:
    db.reference(node).delete()
    print(f"✅ {node} মুছে ফেলা হয়েছে।")

print("🎉 Site Resources ব্যতীত সব নোড ফ্রেশ — পরের scan থেকে সম্পূর্ণ নতুন ডেটা তৈরি হবে।")
