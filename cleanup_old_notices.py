"""
cleanup_old_notices.py

One-time (or periodic) cleanup for data that was already saved to Firebase
BEFORE the 1-year retention filter existed in processor.py. Goes through
every job_notices/{source_id}/notices_history entry, deletes anything
older than NOTICE_MAX_AGE_DAYS.

processor.py's own age filter only stops NEW old notices from being
saved going forward — it doesn't touch what's already there. This script
is what actually shrinks your current Firebase usage.

Usage:
    python cleanup_old_notices.py            # actually deletes
    python cleanup_old_notices.py --dry-run  # just reports what WOULD be
                                                deleted, deletes nothing
"""

import sys

from firebase_client import db
from config import NOTICE_MAX_AGE_DAYS
from notice_date import is_notice_too_old


def main():
    dry_run = "--dry-run" in sys.argv
    mode_label = "DRY RUN (কিছু মুছবে না)" if dry_run else "LIVE (সত্যিই মুছে দেবে)"
    print(f"Mode: {mode_label}")
    print(f"Cutoff: {NOTICE_MAX_AGE_DAYS} দিনের বেশি পুরনো notice মুছে যাবে\n")

    job_notices = db.reference("job_notices").get() or {}
    print(f"মোট source: {len(job_notices)}\n")

    total_checked = 0
    total_deleted = 0
    sources_touched = 0

    for source_id, source_data in job_notices.items():
        if not isinstance(source_data, dict):
            continue
        history = source_data.get("notices_history") or {}
        if not isinstance(history, dict) or not history:
            continue

        to_delete = []
        for notice_id, notice in history.items():
            if not isinstance(notice, dict):
                continue
            total_checked += 1
            notice_date = notice.get("notice_date", "")
            if is_notice_too_old(notice_date, NOTICE_MAX_AGE_DAYS):
                to_delete.append(notice_id)

        if to_delete:
            sources_touched += 1
            print(f"[{source_id}] {len(to_delete)}টা পুরনো notice "
                  f"({'delete হবে' if not dry_run else 'delete হতো'})")
            if not dry_run:
                history_ref = db.reference(f"job_notices/{source_id}/notices_history")
                for notice_id in to_delete:
                    history_ref.child(notice_id).delete()
            total_deleted += len(to_delete)

    print(f"\n{'='*50}")
    print(f"মোট চেক করা হয়েছে : {total_checked}")
    print(f"মোট {'delete হতো' if dry_run else 'delete হয়েছে'} : {total_deleted}")
    print(f"যেসব source-এ পুরনো notice পাওয়া গেছে : {sources_touched}")
    print(f"{'='*50}")
    if dry_run:
        print("\nএটা dry-run ছিল, কিছু মোছা হয়নি। সত্যিই মুছতে "
              "'python cleanup_old_notices.py' (--dry-run ছাড়া) চালান।")


if __name__ == "__main__":
    main()
