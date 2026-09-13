import json
import urllib3
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import MAX_WORKERS, GEMINI_API_KEY
from processor import process_source

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

gemini_client = None
if GEMINI_API_KEY:
    from google import genai
    gemini_client = genai.Client(api_key=GEMINI_API_KEY)


def main():
    with open("sources.json", "r", encoding="utf-8") as f:
        sources = json.load(f)

    active_sources = {
        sid: s for sid, s in sources.items()
        if s["type"] != "ai_fallback" or gemini_client is not None
    }
    skipped = len(sources) - len(active_sources)
    if skipped:
        print(f"Skipping {skipped} ai_fallback sources (no GEMINI_API_KEY)")

    print(f"Processing {len(active_sources)} sources with {MAX_WORKERS} workers...")

    completed = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(process_source, sid, s, gemini_client): sid
            for sid, s in active_sources.items()
        }
        for future in as_completed(futures):
            sid = futures[future]
            try:
                future.result()
                completed += 1
            except Exception as e:
                failed += 1
                print(f"Unhandled error processing {sid}: {e}")

    print(f"Done. Completed: {completed}, Failed: {failed}, Total: {len(active_sources)}")


if __name__ == "__main__":
    main()
