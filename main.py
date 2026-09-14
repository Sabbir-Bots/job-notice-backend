import json
import urllib3
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import MAX_WORKERS, GEMINI_API_KEY, RECENT_NOTICE_HOURS
from processor import process_source
from firebase_client import (
    start_scanner_run,
    finish_scanner_run,
    cleanup_expired_recent_notices,
    local_now_string,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

gemini_client = None
if GEMINI_API_KEY:
    from google import genai
    gemini_client = genai.Client(api_key=GEMINI_API_KEY)


def load_sources():
    with open("sources.json", "r", encoding="utf-8") as f:
        sources = json.load(f)

    if not sources:
        print("❌ sources.json খালি অথবা পড়া যায়নি।")
        return None

    for source_id, s in sources.items():
        if not s.get("base_url") or not s.get("notice_path") or not s.get("type"):
            print(f"❌ {source_id}: base_url/notice_path/type missing")
            return None

    print(f"✅ sources.json loaded: {len(sources)} entries।")
    return sources


def main():
    print()
    print("=" * 70)
    print("🚀 JOB NOTICE SCANNER STARTED")
    print("📡 FCM MODE: DATA-ONLY")
    print("🔥 Firebase: ENABLED")
    print(f"🕒 Recent notice retention: {RECENT_NOTICE_HOURS} hours")
    print("🇧🇩 Timezone: Asia/Dhaka (UTC+06:00)")
    print("=" * 70)
    print()

    sources = load_sources()
    if not sources:
        return

    active_sources = {
        sid: s for sid, s in sources.items()
        if s["type"] != "ai_fallback" or gemini_client is not None
    }
    skipped_count = len(sources) - len(active_sources)

    started_unix = start_scanner_run()
    cleanup_expired_recent_notices()

    stats = {
        "total": len(sources),
        "success": 0,
        "no_notice": 0,
        "new_notices": 0,
        "failed": 0,
        "skipped": skipped_count,
        "notifications_sent": 0,
        "notification_failures": 0,
    }

    print()
    print("=" * 70)
    print(f"[{local_now_string()}] স্ক্যানিং শুরু হয়েছে: মোট {len(sources)} টি অফিস...")
    print("=" * 70)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(process_source, sid, s, gemini_client): sid
            for sid, s in active_sources.items()
        }
        for future in as_completed(futures):
            sid = futures[future]
            try:
                result = future.result()
            except Exception as e:
                stats["failed"] += 1
                print(f"❌ [{sid}] unhandled error: {e}")
                continue

            outcome = result["outcome"]
            if outcome == "success":
                stats["success"] += 1
                stats["new_notices"] += result["new_history"]
                if result["notified"] is True:
                    stats["notifications_sent"] += 1
                elif result["notified"] is False:
                    stats["notification_failures"] += 1
            elif outcome == "no_notice":
                stats["no_notice"] += 1
            elif outcome == "failed":
                stats["failed"] += 1

    finish_scanner_run(started_unix, stats)

    print()
    print("=" * 70)
    print("📊 SCAN SUMMARY")
    print(f"Total sources          : {stats['total']}")
    print(f"Successful scans       : {stats['success']}")
    print(f"No notice              : {stats['no_notice']}")
    print(f"New history entries    : {stats['new_notices']}")
    print(f"Failed                 : {stats['failed']}")
    print(f"Skipped                : {stats['skipped']}")
    print(f"FCM sent               : {stats['notifications_sent']}")
    print(f"FCM failed             : {stats['notification_failures']}")
    print("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⛔ Scanner manually stopped.")
    except Exception as e:
        print(f"\n❌ Fatal scanner error: {e}")
        raise

    print()
    print("=" * 70)
    print("✅ সকল সাইটের স্ক্যানিং সম্পন্ন হয়েছে।")
    print("=" * 70)
