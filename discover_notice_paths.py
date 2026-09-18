"""
discover_notice_paths.py

For every base URL in bd_office_links.txt (or final_source_list.txt),
tries a list of common notice/circular path suffixes used by Bangladesh's
National Web Portal template (the same pattern your PBS project already
found: /site/notices, /pages/notices, etc.) and picks whichever one
actually returns a real notice-looking page.

This produces a sources.json in the same shape as your PBS project's
sources.json (id, base_url, notice_url, match_reason), so it should plug
into your existing processor.py / parsers.py pipeline with minimal changes.

Usage:
    pip install requests urllib3
    python discover_notice_paths.py

Input:
    final_source_list.txt   (one base URL per line)
    -> change INPUT_FILE below if you want to run it on bd_office_links.txt
       or alive_links.txt instead

Output:
    sources.json         -> [{id, base_url, notice_url, match_reason}, ...]
    unmatched.txt        -> base URLs where NONE of the candidate paths worked
                             (these need a manual look, same as bdjobs/chakri.com
                             were deferred in your project before)
"""

import csv
import html
import json
import re
import socket
import threading
import time
from urllib.parse import urlparse, urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

INPUT_FILE = "cleaned_base_urls.txt"
SOURCES_OUTPUT = "sources.json"
UNMATCHED_OUTPUT = "unmatched.txt"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}
TIMEOUT_SEC = 12
MAX_WORKERS = 15

# Candidate path suffixes to try, in priority order — first one that looks
# like a real notice page wins. Extend this list as you discover more
# patterns (same way you found /pages/notices for the PBS project).
CANDIDATE_PATHS = [
    "/site/notices",
    "/pages/notices",
    "/site/view/notice",
    "/site/view/notices",
    "/bn/site/notices",
    "/site/all_offices_notice",
    "/pages/all-notice",
    "/notices",
]

# If the fetched page's text contains any of these, we consider it a real
# notice/circular listing page (not a generic homepage or a 404).
NOTICE_KEYWORDS = [
    "নোটিশ", "বিজ্ঞপ্তি", "নিয়োগ বিজ্ঞপ্তি", "সার্কুলার",
    "notice", "circular", "job notice", "recruitment",
]

_write_lock = threading.Lock()


def clean_url(raw: str) -> str:
    url = raw.strip()
    if not url:
        return ""
    return html.unescape(url)


def looks_like_notice_page(text: str) -> bool:
    lowered = text.lower()
    return any(kw.lower() in lowered for kw in NOTICE_KEYWORDS)


def try_fetch(url: str):
    """Returns response text on success (status<400), else None."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT_SEC,
                             allow_redirects=True, verify=False)
        if resp.status_code < 400:
            return resp.text
    except requests.exceptions.RequestException:
        pass
    return None


def discover_for_site(base_url: str):
    """Returns dict with base_url, notice_url, match_reason — or None if
    nothing matched (goes into unmatched.txt)."""

    base_url = base_url.rstrip("/")

    for path in CANDIDATE_PATHS:
        candidate_url = base_url + path
        text = try_fetch(candidate_url)
        if text and looks_like_notice_page(text):
            return {
                "base_url": base_url,
                "notice_url": candidate_url,
                "match_reason": f"path_matches:{path}",
            }
        time.sleep(0.3)  # be polite between attempts on the same host

    # Last resort: check if the homepage itself already mentions notices
    # (some smaller offices just list notices right on the homepage)
    text = try_fetch(base_url)
    if text and looks_like_notice_page(text):
        return {
            "base_url": base_url,
            "notice_url": base_url,
            "match_reason": "homepage_has_notices",
        }

    return None


def main():
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        urls = [clean_url(line) for line in f if clean_url(line)]
    urls = list(dict.fromkeys(urls))

    print(f"Loaded {len(urls)} base URLs from {INPUT_FILE}")
    print(f"Trying {len(CANDIDATE_PATHS)} candidate paths per site "
          f"with {MAX_WORKERS} parallel workers...\n")

    matched = []
    unmatched = []
    checked = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(discover_for_site, u): u for u in urls}
        for future in as_completed(futures):
            base_url = futures[future]
            try:
                result = future.result()
            except Exception as e:
                result = None
                print(f"  [error] {base_url} -> {e}")

            with _write_lock:
                if result:
                    result["id"] = str(len(matched) + 1)
                    matched.append(result)
                else:
                    unmatched.append(base_url)

            checked += 1
            if checked % 25 == 0 or checked == len(urls):
                print(f"  checked {checked}/{len(urls)}  "
                      f"(matched: {len(matched)}, unmatched: {len(unmatched)})")

    with open(SOURCES_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(matched, f, ensure_ascii=False, indent=2)

    with open(UNMATCHED_OUTPUT, "w", encoding="utf-8") as f:
        for u in unmatched:
            f.write(u + "\n")

    print(f"\n{'='*50}")
    print(f"Matched (in {SOURCES_OUTPUT})   : {len(matched)}")
    print(f"Unmatched (in {UNMATCHED_OUTPUT}) : {len(unmatched)}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
