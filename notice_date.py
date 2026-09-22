"""
notice_date.py

Notice dates on these sites are usually Bengali-numeral strings like
"০৩-০৮-২০১৫" (day-month-year). This parses that into a real date, so we
can decide whether a notice is too old to bother saving.

If a date string doesn't parse (unexpected format, empty, garbage), we
deliberately do NOT treat it as old — better to keep a notice we can't
date than to silently throw away a real recent one due to a parsing gap.
"""

import datetime

BENGALI_DIGITS = "০১২৩৪৫৬৭৮৯"


def to_latin_digits(text: str) -> str:
    for i, ch in enumerate(BENGALI_DIGITS):
        text = text.replace(ch, str(i))
    return text


def parse_notice_date(date_str: str):
    """Returns a datetime.date, or None if it can't be parsed."""
    if not date_str:
        return None
    latin = to_latin_digits(date_str.strip())

    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.datetime.strptime(latin, fmt).date()
        except ValueError:
            continue
    return None


def is_notice_too_old(date_str: str, max_age_days: int = 365) -> bool:
    """True only if the date is confidently parsed AND older than
    max_age_days. Unparseable dates are kept (return False)."""
    parsed = parse_notice_date(date_str)
    if parsed is None:
        return False
    age = (datetime.date.today() - parsed).days
    return age > max_age_days


if __name__ == "__main__":
    tests = [
        "০৩-০৮-২০১৫",
        "২০-০৯-২০২৬",
        "invalid",
        "",
        "17-09-2026",
    ]
    for t in tests:
        parsed = parse_notice_date(t)
        old = is_notice_too_old(t)
        print(f"{t!r:20s} -> parsed={parsed}, too_old={old}")
