"""
clean_urls.py

Normalizes every URL in bd_office_links.txt down to just its base domain
(scheme + host), dropping any path, query string, or trailing slash. This
fixes the inconsistency where some entries are clean homepages
(https://mof.gov.bd/) and others are deep links to a specific page
(https://mof.gov.bd/pages/budget-mofs?filters=%7B...%7D) — after this,
every entry is a plain base URL like https://mof.gov.bd, safe to append
a notice-page path to.

Usage:
    python clean_urls.py

Input:
    bd_office_links.txt

Output:
    cleaned_base_urls.txt   (one base URL per line, de-duplicated)
"""

import html
from urllib.parse import urlparse

INPUT_FILE = "bd_office_links.txt"
OUTPUT_FILE = "cleaned_base_urls.txt"


def clean_to_base(raw: str):
    url = raw.strip()
    if not url:
        return None
    url = html.unescape(url)  # &amp; -> &

    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return None  # not a usable URL at all

    # Rebuild as scheme://host only — drops path, query string, fragment
    base = f"{parsed.scheme}://{parsed.netloc}"
    return base


def main():
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        raw_lines = [line for line in f if line.strip()]

    seen = set()
    cleaned = []
    dropped = 0

    for line in raw_lines:
        base = clean_to_base(line)
        if base is None:
            dropped += 1
            continue
        if base not in seen:
            seen.add(base)
            cleaned.append(base)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for url in cleaned:
            f.write(url + "\n")

    print(f"Read           : {len(raw_lines)} lines")
    print(f"Unusable/dropped: {dropped}")
    print(f"Unique base URLs: {len(cleaned)}  -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
