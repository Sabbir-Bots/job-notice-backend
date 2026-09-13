import hashlib
import firebase_admin
from firebase_admin import credentials, db, messaging

from config import (
    FIREBASE_DB_URL,
    FIREBASE_CREDENTIALS_FILE,
    ALL_NOTICES_TOPIC,
    ADMIN_ALERTS_TOPIC,
    FAIL_THRESHOLD,
)

# ---------- Init (module load হওয়ার সময় একবারই চলে) ----------
cred = credentials.Certificate(FIREBASE_CREDENTIALS_FILE)
firebase_admin.initialize_app(cred, {"databaseURL": FIREBASE_DB_URL})


def notice_hash(title):
    return hashlib.md5(title.encode("utf-8")).hexdigest()


def send_fcm(source, notice):
    message = messaging.Message(
        data={
            "name_en": source["name_en"],
            "name_bn": source["name_bn"],
            "title": notice["title"],
            "link": notice["link"],
            "date": notice["date"],
        },
        topic=ALL_NOTICES_TOPIC,
    )
    try:
        messaging.send(message)
        print(f"FCM sent to {ALL_NOTICES_TOPIC}")
    except Exception as e:
        print(f"FCM send failed: {e}")


def send_admin_alert(source_id, source, reason):
    message = messaging.Message(
        data={
            "type": "source_broken",
            "source_id": source_id,
            "name_en": source["name_en"],
            "reason": reason,
        },
        topic=ADMIN_ALERTS_TOPIC,
    )
    try:
        messaging.send(message)
        print(f"Admin alert sent for {source_id}")
    except Exception as e:
        print(f"Admin alert failed: {e}")


def update_source_health(source_id, source, ok):
    ref = db.reference(f"job_sources/{source_id}/status")
    status = ref.get() or {}
    consecutive_empty = status.get("consecutive_empty", 0)
    alerted = status.get("alerted", False)

    if ok:
        ref.update({"consecutive_empty": 0, "alerted": False})
        return

    consecutive_empty += 1
    ref.update({"consecutive_empty": consecutive_empty})

    if consecutive_empty >= FAIL_THRESHOLD and not alerted:
        send_admin_alert(
            source_id, source,
            f"{consecutive_empty} বার পরপর কোনো নোটিশ পাওয়া যায়নি — "
            f"selector ভেঙে গেছে বা সাইট রিডিজাইন হয়েছে"
        )
        ref.update({"alerted": True})


def get_notice_ref(source_id):
    return db.reference(f"job_notices/{source_id}")
