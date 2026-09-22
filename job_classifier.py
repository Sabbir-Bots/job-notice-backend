"""
job_classifier.py

Decides whether a notice title is a job/recruitment notice ("নিয়োগ
বিজ্ঞপ্তি") or a general notice (tender, event, circular, etc.).

This is intentionally simple (keyword match on the title) rather than an
AI call — calling Gemini for every single notice on every scan would be
slow and add cost, and title keywords catch the vast majority of real
recruitment notices reliably.

If you find real job notices slipping through uncaught, add more phrases
to JOB_KEYWORDS — that's the only tuning this needs.
"""

JOB_KEYWORDS = [
    # Bengali — most common phrasing in real notices
    "নিয়োগ বিজ্ঞপ্তি",
    "নিয়োগ বিজ্ঞপ্তী",
    "নিয়োগ সংক্রান্ত",
    "নিয়োগ প্রজ্ঞাপন",
    "নিয়োগ পরীক্ষা",
    "নিয়োগের বিজ্ঞপ্তি",
    "শূন্য পদ",
    "শুন্য পদ",
    "পদ পূরণ",
    "চাকরির বিজ্ঞপ্তি",
    "চাকুরির বিজ্ঞপ্তি",
    "চাকরি বিজ্ঞপ্তি",
    "লোক নিয়োগ",
    "জনবল নিয়োগ",
    "কর্মচারী নিয়োগ",
    "কর্মকর্তা নিয়োগ",
    "প্রার্থী আহ্বান",
    "আবেদন আহ্বান",
    "পদের জন্য আবেদন",
    "নিয়োগ",  # broad catch-all, kept last so more specific phrases still
               # match first in readability — matching logic doesn't care
               # about order, this just documents intent

    # English
    "job circular",
    "recruitment notice",
    "recruitment circular",
    "vacancy announcement",
    "vacant post",
    "walk-in interview",
    "walk in interview",
    "job notice",
    "appointment notice",
    "recruitment",
]


def is_job_notice(title: str) -> bool:
    """True if the notice title looks like a recruitment/job notice."""
    if not title:
        return False
    lowered = title.lower()
    return any(kw.lower() in lowered for kw in JOB_KEYWORDS)


if __name__ == "__main__":
    tests = [
        ("সহকারী পরিচালক পদে নিয়োগ বিজ্ঞপ্তি ২০২৬", True),
        ("দরপত্র বিজ্ঞপ্তি: অফিস সংস্কার কাজ", False),
        ("Recruitment Circular for Assistant Programmer", True),
        ("বার্ষিক সাধারণ সভার নোটিশ", False),
        ("১০টি শূন্য পদে জনবল নিয়োগ", True),
    ]
    for title, expected in tests:
        got = is_job_notice(title)
        status = "OK" if got == expected else "MISMATCH"
        print(f"[{status}] {title!r} -> {got} (expected {expected})")
