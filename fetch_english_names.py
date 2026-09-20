"""
fetch_english_names.py

For every entry in sources.json, visits the office's OWN website and pulls
its real English name from the page itself — instead of machine-translating
the Bengali name. Most Bangladesh government sites (built on the same
national portal template) show their official English name somewhere on
the page even when the site defaults to Bengali: in the <title> tag, in a
language-switch link's text, or in the header/logo area.

Strategy per site (tries in this order, stops at first success):
  1. Fetch the base_url and check the <title> tag — many .gov.bd templates
     put the official English name directly in <title>, even on the
     Bengali-language homepage.
  2. Try common English-version URLs (?lang=en, /en, /site/view/header?lang=en)
     and re-check <title>.
  3. Look for a language-switch link on the page (often labeled "English" or
     "EN") and follow it, then check that page's <title>.
  4. If nothing usable is found, leave name_en blank (do NOT guess/translate).

A result only counts if it's mostly Latin characters (i.e., actually
English) — a Bengali <title> is rejected, not kept as a wrong "English" name.

Usage:
    pip install requests beautifulsoup4
    python fetch_english_names.py

Input / Output:
    sources.json   (read and updated in place — every entry gets name_en
                     where found; left blank where not found, never guessed)
"""

import json
import re
import time
import requests
from bs4 import BeautifulSoup

INPUT_FILE = "sources.json"
TIMEOUT_SEC = 12
DELAY_SEC = 1.0
SAVE_EVERY = 20

HEADERS_EN = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

# Common site suffixes that switch a national-portal-template site to English
LANG_URL_CANDIDATES = ["?lang=en", "/en", "/site/view/header?lang=en", "/?lang=en"]

# Junk we should strip off titles (site templates often append this)
TITLE_JUNK = [
    "Government of the People's Republic of Bangladesh",
    "-Government of the People's Republic of Bangladesh",
    "| Government of the People's Republic of Bangladesh",
]


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
    t = t.strip(" -|")
    return t.strip()


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
    """Look on the homepage for a link whose text/label suggests it switches
    to the English version of the site."""
    try:
        resp = requests.get(url, headers=HEADERS_EN, timeout=TIMEOUT_SEC,
                             allow_redirects=True, verify=False)
        if resp.status_code >= 400:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True).lower()
            if text in ("english", "en", "eng"):
                from urllib.parse import urljoin
                return urljoin(url, a["href"])
    except requests.exceptions.RequestException:
        return None
    return None


def get_english_name(base_url: str):
    # 1. title of homepage as-is
    title = get_title(base_url)
    if title and is_mostly_latin(title):
        return title, "homepage_title"

    # 2. common lang-switch URL patterns
    for suffix in LANG_URL_CANDIDATES:
        candidate_url = base_url.rstrip("/") + suffix
        title = get_title(candidate_url)
        if title and is_mostly_latin(title):
            return title, f"lang_url:{suffix}"
        time.sleep(0.3)

    # 3. follow an actual "English" link found on the page
    en_link = find_english_switch_link(base_url)
    if en_link:
        title = get_title(en_link)
        if title and is_mostly_latin(title):
            return title, "english_link"

    return None, None


def main():
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    total = len(data)
    found = 0
    not_found = []

    for i, entry in enumerate(data, start=1):
        if entry.get("name_en"):
            continue  # already has one, skip

        base_url = entry["base_url"]
        name_en, method = get_english_name(base_url)

        if name_en:
            entry["name_en"] = name_en
            found += 1
            print(f"[{i}/{total}] OK ({method}): {base_url} -> {name_en}")
        else:
            not_found.append(base_url)
            print(f"[{i}/{total}] not found: {base_url}")

        time.sleep(DELAY_SEC)

        if i % SAVE_EVERY == 0:
            with open(INPUT_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    with open(INPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print(f"Total       : {total}")
    print(f"Found       : {found}")
    print(f"Not found   : {len(not_found)}")
    print(f"{'='*50}")
    if not_found:
        print("\nThese need a manual look (no reliable English name found "
              "on the site itself):")
        for u in not_found:
            print(" ", u)


if __name__ == "__main__":
    main()
