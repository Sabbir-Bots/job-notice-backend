import time
from datetime import datetime, timezone

import firebase_admin
from firebase_admin import credentials, db, messaging

from config import (
    FIREBASE_DB_URL,
    FIREBASE_CREDENTIALS_FILE,
    ALL_NOTICES_TOPIC,
    ADMIN_ALERTS_TOPIC,
    FAIL_THRESHOLD,
    RECENT_NOTICE_HOURS,
    BD_TIMEZONE,
)

cred = credentials.Certificate(FIREBASE_CREDENTIALS_FILE)
firebase_admin.initialize_app(cred, {"databaseURL": FIREBASE_DB_URL})


# ---------- Time helpers (PBS-এর মতোই) ----------
def utc_now():
    return datetime.now(timezone.utc)


def local_now_string():
    return utc_now().astimezone(BD_TIMEZONE).isoformat(timespec="seconds")


def unix_now():
    return int(time.time())


# ---------- Scanner run status (PBS-এর last_updated + scanner_status) ----------
def start_scanner_run():
    started_unix = unix_now()
    started_readable = local_now_string()

    db.reference("last_updated").set({
        "timestamp": started_readable,
        "unix": started_unix,
        "status": "running",
    })
    db.reference("scanner_status").update({
        "status": "running",
        "started_at": started_readable,
        "started_at_unix": started_unix,
    })
    return started_unix


def finish_scanner_run(started_unix, stats):
    finished_unix = unix_now()
    finished_readable = local_now_string()
    duration = max(0, finished_unix - started_unix)

    db.reference("last_updated").set({
        "timestamp": finished_readable,
        "unix": finished_unix,
        "status": "completed",
        "duration_seconds": duration,
    })
    db.reference("scanner_status").set({
        "status": "completed",
        "started_at_unix": started_unix,
        "finished_at": finished_readable,
        "finished_at_unix": finished_unix,
        "duration_seconds": duration,
        "total_sources": stats["total"],
        "success": stats["success"],
        "no_notice": stats["no_notice"],
        "new_notices": stats["new_notices"],
        "failed": stats["failed"],
        "skipped": stats["skipped"],
        "notifications_sent": stats["notifications_sent"],
        "notification_failures": stats["notification_failures"],
    })


# ---------- 72-hour recent-notice feed (PBS-এর today_latest_notice) ----------
def cleanup_expired_recent_notices():
    now = unix_now()
    recent_ref = db.reference("today_latest_notice")
    existing = recent_ref.get() or {}

    if not isinstance(existing, dict):
        print("⚠️ today_latest_notice format invalid; cleanup skipped.")
        return 0

    deleted = 0
    for key, value in list(existing.items()):
        if not isinstance(value, dict):
            continue
        try:
            expires_at = int(value.get("expires_at_unix"))
        except (TypeError, ValueError):
            continue
        if expires_at <= now:
            recent_ref.child(key).delete()
            deleted += 1

    print(f"🧹 72-hour cleanup: {deleted} টি expired notice deleted।")
    return deleted


def add_to_recent_notices(source_id, name_bn, name_en, serial, item):
    created_unix = unix_now()
    expires_unix = created_unix + (RECENT_NOTICE_HOURS * 60 * 60)

    payload = {
        "id": source_id,
        "pbs": source_id,  # legacy field name — Android side backward-compatibility
        "name_bn": name_bn,
        "name_en": name_en,
        "serial": serial,
        "notice_title": item.get("title", ""),
        "notice_link": item.get("link", ""),
        "notice_date": item.get("date", ""),
        "created_at": local_now_string(),
        "created_at_unix": created_unix,
        "expires_at_unix": expires_unix,
        "expires_after_hours": RECENT_NOTICE_HOURS,
    }
    try:
        db.reference("today_latest_notice").push(payload)
        return True
    except Exception as e:
        print(f"⚠️ 72-hour notice save failed: {e}")
        return False


# ---------- FCM (data-only, PBS-এর মতোই, শুধু single global topic) ----------
def send_push_notification(source_id, name_bn, name_en, title, link):
    message = messaging.Message(
        data={
            "id": source_id,
            "name_en": name_en,
            "title": f"🔔 {name_bn}",
            "body": title,
            "url": link,
            "source": name_bn,
            "click_action": "NOTICE_DETAILS",
        },
        topic=ALL_NOTICES_TOPIC,
    )
    try:
        response = messaging.send(message)
        print(f"📱 [{name_bn}] FCM পাঠানো হয়েছে। Message ID: {response}")
        return True
    except Exception as e:
        print(f"❌ [{name_bn}] FCM ব্যর্থ: {e}")
        return False


# ---------- Source health (নতুন সংযোজন — broken selector ধরার জন্য, আলাদা নোডে) ----------
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
    except Exception as e:
        print(f"Admin alert failed: {e}")


def update_source_health(source_id, source, ok):
    ref = db.reference(f"source_health/{source_id}")
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
            f"{consecutive_empty} বার পরপর কোনো নোটিশ পাওয়া যায়নি"
        )
        ref.update({"alerted": True})
