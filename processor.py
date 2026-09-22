from parsers import parse_national_portal, parse_css_selector, parse_ai_fallback
from firebase_client import (
    db,
    local_now_string,
    unix_now,
    add_to_recent_notices,
    send_push_notification,
    update_source_health,
)
from config import MAX_NOTICES_PER_SOURCE
from notice_id import generate_notice_id
from job_classifier import is_job_notice


def get_source_ref(source_id):
    return db.reference(f"job_notices/{source_id}")


def _run_parser(source, gemini_client):
    parser_type = source["type"]
    if parser_type == "national_portal":
        return parse_national_portal(source)
    if parser_type == "css_selector":
        return parse_css_selector(source)
    if parser_type == "ai_fallback":
        return parse_ai_fallback(source, gemini_client)
    raise ValueError(f"Unknown parser type: {parser_type}")


def process_source(source_id, source, gemini_client=None, notification_mode="job_only"):
    name_bn = source.get("name_bn", "")
    name_en = source.get("name_en", "")
    serial = source.get("serial_num", "")
    result = {"outcome": None, "new_history": 0, "notified": None}

    try:
        notices = _run_parser(source, gemini_client)
    except Exception as e:
        print(f"❌ [{name_bn}] স্ক্যান করতে গিয়ে সমস্যা হয়েছে: {e}")
        update_source_health(source_id, source, ok=False)
        result["outcome"] = "failed"
        return result

    notices = notices[:MAX_NOTICES_PER_SOURCE]

    if not notices:
        print(f"⚠️ [{name_bn}] কোনো notice পাওয়া যায়নি।")
        update_source_health(source_id, source, ok=False)
        result["outcome"] = "no_notice"
        return result

    update_source_health(source_id, source, ok=True)

    ref = get_source_ref(source_id)
    last_saved_title = ref.child("last_title").get()
    latest = notices[0]
    notice_title, notice_link, notice_date = latest["title"], latest["link"], latest["date"]
    latest_is_job_for_node = is_job_notice(notice_title)

    # ---------- মূল নোড আপডেট ----------
    ref.child("id").set(source_id)
    ref.child("pbs").set(source_id)  # legacy field name, Android পাশের জন্য
    ref.child("name_bn").set(name_bn)
    ref.child("name_en").set(name_en)
    ref.child("serial").set(serial)
    ref.child("pbs_url").set(source["base_url"].rstrip("/") + source["notice_path"])
    ref.child("last_title").set(notice_title)
    ref.child("last_pdf").set(notice_link)
    ref.child("last_notice_date").set(notice_date)
    ref.child("last_is_job_notice").set(latest_is_job_for_node)
    ref.child("last_scanned_at").set(local_now_string())
    ref.child("last_scanned_at_unix").set(unix_now())

    # ---------- HISTORY (কখনো মোছা হবে না, শুধু নতুন title যোগ হবে) ----------
    history_ref = ref.child("notices_history")
    existing_history = history_ref.get() or {}
    existing_titles = set()
    if isinstance(existing_history, dict):
        for value in existing_history.values():
            if isinstance(value, dict):
                old_title = value.get("notice_title")
                if old_title:
                    existing_titles.add(old_title)

    newly_added_history = []
    for item in notices:
        item_title = item["title"]
        if item_title not in existing_titles:
            notice_id = generate_notice_id(serial, item_title, item["link"])
            item_is_job = is_job_notice(item_title)
            history_ref.child(notice_id).set({
                "notice_id": notice_id,
                "id": source_id,
                "pbs": source_id,
                "name_bn": name_bn,
                "name_en": name_en,
                "serial": serial,
                "notice_title": item_title,
                "notice_link": item["link"],
                "notice_date": item["date"],
                "is_job_notice": item_is_job,
                "added_at": local_now_string(),
                "added_at_unix": unix_now(),
            })
            existing_titles.add(item_title)
            item["notice_id"] = notice_id
            item["is_job_notice"] = item_is_job
            newly_added_history.append(item)

    result["new_history"] = len(newly_added_history)

    # ---------- ৭২-ঘণ্টা recent feed ----------
    for item in newly_added_history:
        add_to_recent_notices(
            item["notice_id"], source_id, name_bn, name_en, serial, item, item["is_job_notice"]
        )

    # ---------- FCM (শুধু top/সর্বশেষ notice বদলালে) ----------
    if notice_title != last_saved_title:
        latest_is_job = latest_is_job_for_node
        should_notify = (notification_mode == "all") or (
            notification_mode == "job_only" and latest_is_job
        )
        print(f"🆕 [{name_bn}] নতুন নোটিশ পাওয়া গেছে! Title: {notice_title} "
              f"(job_notice={latest_is_job}, mode={notification_mode})")
        if should_notify:
            result["notified"] = send_push_notification(
                source_id, name_bn, name_en, notice_title, notice_link, latest_is_job
            )
        else:
            print(f"🔕 [{name_bn}] mode='{notification_mode}' অনুযায়ী FCM পাঠানো হয়নি "
                  f"(general notice, job-only mode চালু আছে)।")
            result["notified"] = None
    else:
        print(f"✓ [{name_bn}] কোনো নতুন notice নেই।")

    result["outcome"] = "success"
    return result
