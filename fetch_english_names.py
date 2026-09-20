"""
fetch_english_names.py

For every entry in sources.json, visits the office's OWN website and pulls
its real English name from the page itself — instead of machine-translating
the Bengali name.

Strategy per site (tries in this order, stops at first success):
  1. Fetch the base_url and check the <title> tag.
  2. Try common English-version URL patterns (?lang=en, /en, etc.) and
     re-check <title>.
  3. Look for an "English" language-switch link on the page and follow it.
  4. If nothing usable is found, leave name_en blank (never guessed/translated).

Runs sites in PARALLEL (like your other scripts) so ~969 sites finish in a
reasonable time instead of hours. Prints progress immediately (flush=True)
so GitHub Actions logs update live instead of appearing stuck.

Usage:
    pip install requests beautifulsoup4
    python fetch_english_names.py

Input / Output:
    sources.json   (read and updated in place)
"""

import json
import re
import time
import threading
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

INPUT_FILE = "sources.json"
TIMEOUT_SEC = 8          # shorter timeout — a slow site isn't worth waiting 12s x5 for
MAX_WORKERS = 20
SAVE_EVERY = 25

HEADERS_EN = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

LANG_URL_CANDIDATES = ["?lang=en", "/en", "/?lang=en"]  # trimmed to the 3 most common

TITLE_JUNK = [
    "Government of the People's Republic of Bangladesh",
    "-Government of the People's Republic of Bangladesh",
    "| Government of the People's Republic of Bangladesh",
]

_write_lock = threading.Lock()
_print_lock = threading.Lock()


def log(msg):
    with _print_lock:
        print(msg, flush=True)


def is_mostly_latin(text: str) -> bool:
    if not text or not text.strip():
        return False
    latin_chars = len(re.findall(r"[A-Za-z]", text))
    bengali_chars = len(re.findall(r"[\u0980-\u09FF]", text))
    return latin_chars > 0 and latin_chars >= bengali_chars


def clean_title(title: str) -> str:
    t = title.strip()
    for junk in TITLE_JUNK:
        t = t.replace(junk, "")
    return t.strip(" -|").strip()


def get_title(url: str):
    try:
        resp = requests.get(url, headers=HEADERS_EN, timeout=TIMEOUT_SEC,
                             allow_redirects=True, verify=False)
        if resp.status_code >= 400:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        if soup.title and soup.title.string:
            return clean_title(soup.title.string)
    except requests.exceptions.RequestException:
        return None
    return None


def find_english_switch_link(url: str):
    try:
        resp = requests.get(url, headers=HEADERS_EN, timeout=TIMEOUT_SEC,
                             allow_redirects=True, verify=False)
        if resp.status_code >= 400:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True).lower()
            if text in ("english", "en", "eng"):
                return urljoin(url, a["href"])
    except requests.exceptions.RequestException:
        return None
    return None


def get_english_name(base_url: str):
    title = get_title(base_url)
    if title and is_mostly_latin(title):
        return title, "homepage_title"

    for suffix in LANG_URL_CANDIDATES:
        candidate_url = base_url.rstrip("/") + suffix
        title = get_title(candidate_url)
        if title and is_mostly_latin(title):
            return title, f"lang_url:{suffix}"

    en_link = find_english_switch_link(base_url)
    if en_link:
        title = get_title(en_link)
        if title and is_mostly_latin(title):
            return title, "english_link"

    return None, None


def process_entry(entry):
    base_url = entry["base_url"]
    name_en, method = get_english_name(base_url)
    return entry, name_en, method


def save(data):
    with open(INPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    todo = [e for e in data if not e.get("name_en")]
    total = len(data)
    log(f"Total entries: {total}, already have name_en: {total - len(todo)}, "
        f"to process: {len(todo)}")
    log(f"Running with {MAX_WORKERS} parallel workers, {TIMEOUT_SEC}s timeout...\n")

    found = 0
    not_found = []
    checked = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_entry, e): e for e in todo}
        for future in as_completed(futures):
            entry, name_en, method = future.result()
            checked += 1

            with _write_lock:
                if name_en:
                    entry["name_en"] = name_en
                    found += 1
                    log(f"[{checked}/{len(todo)}] OK ({method}): "
                        f"{entry['base_url']} -> {name_en}")
                else:
                    not_found.append(entry["base_url"])
                    log(f"[{checked}/{len(todo)}] not found: {entry['base_url']}")

                if checked % SAVE_EVERY == 0:
                    save(data)
                    log(f"  -- progress saved at {checked}/{len(todo)} --")

    save(data)

    log(f"\n{'='*50}")
    log(f"Total       : {total}")
    log(f"Found       : {found}")
    log(f"Not found   : {len(not_found)}")
    log(f"{'='*50}")
    if not_found:
        log("\nThese need a manual look (no reliable English name found on "
            "the site itself):")
        for u in not_found:
            log(f"  {u}")


if __name__ == "__main__":
    main()
