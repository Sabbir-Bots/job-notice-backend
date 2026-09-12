import os
import json
import re
import hashlib
import requests
import urllib3
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


# ---------- Parser: national_portal (govt sites, bof.gov.bd style) ----------
def parse_national_portal(source):
    url = source["base_url"].rstrip("/") + source["notice_path"]
    resp = requests.get(url, headers=HEADERS, timeout=20, verify=False)
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


# ---------- Parser: ai_fallback (bdjobs, chakri.com style) ----------
def parse_ai_fallback(source):
    url = source["base_url"].rstrip("/") + source["notice_path"]
    resp = requests.get(url, headers=HEADERS, timeout=20, verify=False)
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


def process_source(source_id, source):
    parser = PARSERS.get(source["type"])
    if not parser:
        print(f"No parser for type: {source['type']}")
        return

    try:
        notices = parser(source)
    except Exception as e:
        print(f"Scrape failed for {source_id}: {e}")
        return

    if not notices:
        print(f"No notices found for {source_id}")
        return

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

    for source_id, source in sources.items():
        print(f"Processing: {source_id}")
        process_source(source_id, source)


if __name__ == "__main__":
    main()
