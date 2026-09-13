import os
import json
import re
import hashlib
import requests
import urllib3
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
import firebase_admin
from firebase_admin import credentials, db, messaging
from google import genai

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------- Setup ----------
FIREBASE_DB_URL = os.environ["FIREBASE_DB_URL"]
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

cred = credentials.Certificate("firebase_credentials.json")
firebase_admin.initialize_app(cred, {"databaseURL": FIREBASE_DB_URL})

gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JobNoticeBot/1.0)"}
ALL_NOTICES_TOPIC = "all_job_notices"
ADMIN_ALERTS_TOPIC = "admin_alerts"
FAIL_THRESHOLD = 3       # এতবার পরপর খালি ফলাফল পেলে অ্যাডমিন অ্যালার্ট যাবে
MAX_WORKERS = 20         # একসাথে কতগুলো সাইট স্ক্র্যাপ হবে
REQUEST_TIMEOUT = 15     # সেকেন্ড — স্লো/মৃত সাইটে বেশিক্ষণ আটকে থাকবে না


# ---------- Parser: national_portal (govt sites, same টেমপ্লেট) ----------
def parse_national_portal(source):
    url = source["base_url"].rstrip("/") + source["notice_path"]
    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, verify=False)
    soup = BeautifulSoup(resp.text, "html.parser")

    notices = []
    rows = soup.select("table tr") or soup.select("ul.notice-list li, .view-content .views-row")

    date_pattern = re.compile(r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}")

    for row in rows:
        link_tag = row.find("a", href=True)
        if not link_tag:
            continue
        title = link_tag.get_text(strip=True)
        if not title:
            continue
        link = link_tag["href"]
        if link.startswith("/"):
            link = source["base_url"].rstrip("/") + link

        row_text = row.get_text(" ", strip=True)
        date_match = date_pattern.search(row_text)
        date_str = date_match.group(0) if date_match else ""

        notices.append({"title": title, "link": link, "date": date_str})

    return notices


# ---------- Parser: css_selector (config-driven, কোড ছাড়া নতুন সাইট যোগ করা যায়) ----------
def parse_css_selector(source):
    url = source["base_url"].rstrip("/") + source["notice_path"]
    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, verify=False)
    soup = BeautifulSoup(resp.text, "html.parser")

    sel = source["selectors"]
    notices = []
    for item in soup.select(sel["item"]):
        title_tag = item.select_one(sel["title"])
        link_tag = item.select_one(sel["link"])
        date_tag = item.select_one(sel.get("date", "")) if sel.get("date") else None

        if not title_tag or not link_tag:
            continue

        link = link_tag.get("href", "")
        if link.startswith("/"):
            link = source["base_url"].rstrip("/") + link

        notices.append({
            "title": title_tag.get_text(strip=True),
            "link": link,
            "date": date_tag.get_text(strip=True) if date_tag else "",
        })
    return notices


# ---------- Parser: ai_fallback (bdjobs/chakri.com — বর্তমানে স্কিপ করা, টেমপ্লেট হিসেবে রাখা) ----------
def parse_ai_fallback(source):
    url = source["base_url"].rstrip("/") + source["notice_path"]
    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, verify=False)
    soup = BeautifulSoup(resp.text, "html.parser")

    for tag in soup(["script", "style", "svg", "img"]):
        tag.decompose()
    text_html = str(soup)[:15000]

    prompt = f"""
নিচের HTML থেকে চাকরির বিজ্ঞাপনগুলো বের করো।
শুধুমাত্র একটা JSON array রিটার্ন করো, প্রতিটা আইটেমে থাকবে: title, link, date (পাওয়া না গেলে খালি স্ট্রিং)।
কোনো অতিরিক্ত ব্যাখ্যা, মার্কডাউন, কোড ফেন্স ছাড়া শুধু raw JSON দাও।

HTML:
{text_html}
"""
    try:
        result = gemini_client.models.generate_content(
            model="gemini-flash-latest",
            contents=prompt,
        )
        raw = result.text.strip()
        raw = re.sub(r"^```json|```$", "", raw).strip()
        items = json.loads(raw)
        notices = []
        for item in items:
            link = item.get("link", "")
            if link.startswith("/"):
                link = source["base_url"].rstrip("/") + link
            notices.append({
                "title": item.get("title", "").strip(),
                "link": link,
                "date": item.get("date", "").strip(),
            })
        return notices
    except Exception as e:
        print(f"AI fallback parse failed: {e}")
        return []


PARSERS = {
    "national_portal": parse_national_portal,
    "css_selector": parse_css_selector,
    "ai_fallback": parse_ai_fallback,
}


# ---------- Firebase + FCM ----------
def notice_hash(title):
    return hashlib.md5(title.encode("utf-8")).hexdigest()


def send_fcm(source, notice):
    message = messaging.Message(
        data={
            "name_en": source["name_en"],
            "name_bn": source["name_bn"],
            "title": notice["title"],
            "link": notice["link"],
            "date": notice["date"],
        },
        topic=ALL_NOTICES_TOPIC,
    )
    try:
        messaging.send(message)
        print(f"FCM sent to {ALL_NOTICES_TOPIC}")
    except Exception as e:
        print(f"FCM send failed: {e}")


def send_admin_alert(source_id, source, reason):
    message = messaging.Message(
        data={
            "type": "source_broken",
            "source_id": source_id,
            "name_en": source["name_en"],
            "reason": reason,
        },
        topic=ADMIN_ALERTS_TOPIC,
    )
    try:
        messaging.send(message)
        print(f"Admin alert sent for {source_id}")
    except Exception as e:
        print(f"Admin alert failed: {e}")


def update_source_health(source_id, source, ok):
    ref = db.reference(f"job_sources/{source_id}/status")
    status = ref.get() or {}
    consecutive_empty = status.get("consecutive_empty", 0)
    alerted = status.get("alerted", False)

    if ok:
        ref.update({"consecutive_empty": 0, "alerted": False})
        return

    consecutive_empty += 1
    ref.update({"consecutive_empty": consecutive_empty})

    if consecutive_empty >= FAIL_THRESHOLD and not alerted:
        send_admin_alert(
            source_id, source,
            f"{consecutive_empty} বার পরপর কোনো নোটিশ পাওয়া যায়নি — "
            f"selector ভেঙে গেছে বা সাইট রিডিজাইন হয়েছে"
        )
        ref.update({"alerted": True})


def process_source(source_id, source):
    parser = PARSERS.get(source["type"])
    if not parser:
        print(f"No parser for type: {source['type']}")
        return

    try:
        notices = parser(source)
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
    ref = db.reference(f"job_notices/{source_id}")
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


def main():
    with open("sources.json", "r", encoding="utf-8") as f:
        sources = json.load(f)

    active_sources = {
        sid: s for sid, s in sources.items() if s["type"] != "ai_fallback"
    }
    skipped = len(sources) - len(active_sources)
    if skipped:
        print(f"Skipping {skipped} ai_fallback sources (disabled for now)")

    print(f"Processing {len(active_sources)} sources with {MAX_WORKERS} workers...")

    completed = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(process_source, sid, s): sid
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
