"""
translate_names.py

Fills in name_en for every entry in sources.json missing one, by machine-
translating name_bn -> English. Built for accuracy/completeness over speed:
  - Tries Google Translate (via deep-translator) first, 3 attempts with backoff
  - If Google fails every time, falls back to MyMemory Translate (a second,
    independent translation service) as a second attempt
  - Caches every unique name_bn -> name_en so repeats are never re-translated
  - Saves progress to disk every 20 entries, so an interrupted run loses
    almost nothing and can just be re-run (already-filled entries are skipped)
  - Prints a clear final report of anything that STILL failed, so you know
    exactly what (if anything) needs a manual look

Usage:
    pip install deep-translator
    python translate_names.py

Input / Output:
    sources.json   (read and updated in place)
"""

import json
import time
from deep_translator import GoogleTranslator, MyMemoryTranslator

INPUT_FILE = "sources.json"
MAX_ATTEMPTS = 3
RETRY_DELAY_SEC = 3
SAVE_EVERY = 20

google = GoogleTranslator(source="bn", target="en")
mymemory = MyMemoryTranslator(source="bn-IN", target="en-GB")


def translate_one(text: str) -> str:
    """Try Google Translate up to MAX_ATTEMPTS times, then MyMemory as a
    fallback. Returns '' only if every attempt on both services failed."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = google.translate(text)
            if result and result.strip():
                return result.strip()
        except Exception as e:
            print(f"    Google attempt {attempt}/{MAX_ATTEMPTS} failed for "
                  f"'{text}': {e}")
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_DELAY_SEC)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = mymemory.translate(text)
            if result and result.strip():
                return result.strip()
        except Exception as e:
            print(f"    MyMemory attempt {attempt}/{MAX_ATTEMPTS} failed for "
                  f"'{text}': {e}")
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_DELAY_SEC)

    return ""


def save(data):
    with open(INPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    cache = {}
    total = len(data)
    newly_translated = 0
    already_had = 0
    still_failed = []

    for i, entry in enumerate(data, start=1):
        if entry.get("name_en"):
            already_had += 1
            continue

        name_bn = entry.get("name_bn", "")
        if not name_bn:
            continue

        if name_bn in cache:
            entry["name_en"] = cache[name_bn]
        else:
            print(f"[{i}/{total}] translating: {name_bn}")
            en = translate_one(name_bn)
            cache[name_bn] = en
            entry["name_en"] = en
            if en:
                newly_translated += 1
            else:
                still_failed.append(name_bn)
                print(f"    !! still failed after all retries: {name_bn}")
            time.sleep(0.5)

        if i % SAVE_EVERY == 0:
            save(data)
            print(f"  -- progress saved at {i}/{total} --")

    save(data)

    print(f"\n{'='*50}")
    print(f"Total entries        : {total}")
    print(f"Already had name_en  : {already_had}")
    print(f"Newly translated     : {newly_translated}")
    print(f"Still blank (failed) : {len(still_failed)}")
    print(f"{'='*50}")
    if still_failed:
        print("\nThese need a manual look (or just re-run the script — it")
        print("only processes entries still missing name_en, so re-running")
        print("is safe and cheap):")
        for n in still_failed:
            print(" ", n)


if __name__ == "__main__":
    main()
