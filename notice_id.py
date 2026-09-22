"""
notice_id.py

Builds a deterministic notice_id like "0149_6ecd8a21":
  - "0149" = the source's serial_num (from sources.json) — lets you look
    at any notice_id and immediately know which office it came from by
    checking sources.json for that serial_num.
  - "6ecd8a21" = first 8 hex chars of md5(title + link) — deterministic,
    so the SAME notice always produces the SAME id. If the scanner
    re-scrapes an unchanged notice later, this id matches what's already
    in Firebase and overwrites instead of creating a duplicate entry.
"""

import hashlib


def generate_notice_id(serial_num: str, title: str, link: str) -> str:
    raw = f"{title.strip()}|{link.strip()}"
    content_hash = hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]
    return f"{serial_num}_{content_hash}"
