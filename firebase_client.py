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
    NOTIFICATION_MODE_PATH,
    DEFAULT_NOTIFICATION_MODE,
)

cred = credentials.Certificate(FIREBASE_CREDENTIALS_FILE)
firebase_admin.initialize_app(cred, {"databaseURL": FIREBASE_DB_URL})


# ---------- Time helpers ----------
def utc_now():
    return datetime.now(timezone.utc)


def local_now_string():
    return utc_now().astimezone(BD_TIMEZONE).isoformat(timespec="seconds")


def unix_now():
    return int(time.time())


# ---------- Scanner run status (last_updated + scanner_status) ----------
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


# ---------- Notification mode (নতুন) ----------
def get_notification_mode():
    """Reads notification_settings/mode from Firebase. Returns "job_only"
    or "all". Falls back to DEFAULT_NOTIFICATION_MODE if unset or invalid,
    so a typo or missing path never accidentally spams every notice.

    If the path doesn't exist yet, this WRITES the default value there —
    so after the first run, the node shows up in the Firebase console and
    you can flip it to "all" directly from there, instead of it silently
    only existing as an in-code fallback."""
    try:
        mode = db.reference(NOTIFICATION_MODE_PATH).get()
    except Exception as e:
        print(f"⚠️ notification mode read failed, using default: {e}")
        return DEFAULT_NOTIFICATION_MODE

    if mode not in ("job_only", "all"):
        if mode is not None:
            print(f"⚠️ unrecognized notification mode {mode!r}, using default")
        else:
            # path doesn't exist yet — create it so it's visible in console
            try:
                db.reference(NOTIFICATION_MODE_PATH).set(DEFAULT_NOTIFICATION_MODE)
                print(f"ℹ️ notification_settings/mode ছিল না, "
                      f"'{DEFAULT_NOTIFICATION_MODE}' বসিয়ে তৈরি করা হলো")
            except Exception as e:
                print(f"⚠️ notification_settings/mode তৈরি করা যায়নি: {e}")
        return DEFAULT_NOTIFICATION_MODE

    return mode


# ---------- 72-hour recent-notice feed (today_latest_notice) ----------
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


def add_to_recent_notices(notice_id, source_id, name_bn, name_en, serial, item, is_job):
    created_unix = unix_now()
    expires_unix = created_unix + (RECENT_NOTICE_HOURS * 60 * 60)

    payload = {
        "notice_id": notice_id,
        "id": source_id,
        "job": source_id,  # আগের PBS প্রজেক্টের "pbs" ফিল্ডের নতুন নাম — Android app এটা পড়ে
        "name_bn": name_bn,
        "name_en": name_en,
        "serial": serial,
        "notice_title": item.get("title", ""),
        "notice_link": item.get("link", ""),
        "notice_date": item.get("date", ""),
        "is_job_notice": is_job,
        "created_at": local_now_string(),
        "created_at_unix": created_unix,
        "expires_at_unix": expires_unix,
        "expires_after_hours": RECENT_NOTICE_HOURS,
    }
    try:
        # deterministic key (notice_id) instead of push() — re-scanning the
        # same notice overwrites the same entry instead of duplicating it
        db.reference("today_latest_notice").child(notice_id).set(payload)
        return True
    except Exception as e:
        print(f"⚠️ 72-hour notice save failed: {e}")
        return False


# ---------- FCM (data-only, single global topic) ----------
def send_push_notification(source_id, name_bn, name_en, title, link, is_job):
    message = messaging.Message(
        data={
            "id": source_id,
            "name_en": name_en,
            "title": f"🔔 {name_bn}",
            "body": title,
            "url": link,
            "source": name_bn,
            "is_job_notice": "true" if is_job else "false",
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
