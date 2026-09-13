from parsers import parse_national_portal, parse_css_selector, parse_ai_fallback
from firebase_client import (
    notice_hash,
    send_fcm,
    update_source_health,
    get_notice_ref,
)


def _run_parser(source, gemini_client):
    parser_type = source["type"]
    if parser_type == "national_portal":
        return parse_national_portal(source)
    if parser_type == "css_selector":
        return parse_css_selector(source)
    if parser_type == "ai_fallback":
        return parse_ai_fallback(source, gemini_client)
    raise ValueError(f"Unknown parser type: {parser_type}")


def process_source(source_id, source, gemini_client=None):
    try:
        notices = _run_parser(source, gemini_client)
    except Exception as e:
        print(f"Scrape failed for {source_id}: {e}")
        update_source_health(source_id, source, ok=False)
        return

    if not notices:
        print(f"No notices found for {source_id}")
        update_source_health(source_id, source, ok=False)
        return

    update_source_health(source_id, source, ok=True)

    latest = notices[0]
    ref = get_notice_ref(source_id)
    last_hash = ref.child("last_hash").get()
    current_hash = notice_hash(latest["title"])

    ref.update({
        "last_hash": current_hash,
        "last_title": latest["title"],
        "last_link": latest["link"],
        "last_date": latest["date"],
        "name_en": source["name_en"],
        "name_bn": source["name_bn"],
    })

    if current_hash != last_hash:
        send_fcm(source, latest)
        print(f"New notice for {source_id}: {latest['title']}")
    else:
        print(f"No change for {source_id}")
