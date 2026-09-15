import re
import json
import requests
from bs4 import BeautifulSoup

from config import HEADERS, REQUEST_TIMEOUT, ACTION_WORDS, GEMINI_MODEL

DATE_PATTERN = re.compile(r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}")
FILE_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png", ".docx", ".doc", ".zip")


# ---------- national_portal: সরকারি "জাতীয় তথ্য বাতায়ন" টেমপ্লেট ----------
def parse_national_portal(source):
    url = source["base_url"].rstrip("/") + source["notice_path"]
    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, verify=False)
    soup = BeautifulSoup(resp.text, "html.parser")

    notices = []
    rows = soup.select("table tr") or soup.select("ul.notice-list li, .view-content .views-row")

    for row in rows:
        all_links = row.find_all("a", href=True)
        if not all_links:
            continue

        # ১. প্রথমে সরাসরি ফাইল লিংক (pdf/image/doc ইত্যাদি)
        link_tag = None
        for a in all_links:
            href_path = a["href"].split("?")[0].strip().lower()
            if href_path.endswith(FILE_EXTENSIONS):
                link_tag = a
                break

        # ২. না পেলে "দেখুন"/action-word লিংক
        if not link_tag:
            for a in all_links:
                if a.get_text(strip=True).lower() in ACTION_WORDS:
                    link_tag = a
                    break

        # ৩. তাও না পেলে শেষ লিংক
        if not link_tag:
            link_tag = all_links[-1]

        link = link_tag["href"]
        if link.startswith("/"):
            link = source["base_url"].rstrip("/") + link

        # title: row-এর সবচেয়ে লম্বা অর্থবহ টেক্সট সেল
        cells = row.find_all(["td", "th"])
        title = ""
        for cell in cells:
            text = cell.get_text(strip=True)
            if not text or text.lower() in ACTION_WORDS:
                continue
            if text.isdigit() or DATE_PATTERN.fullmatch(text):
                continue
            if len(text) > len(title):
                title = text

        if not title:
            continue

        row_text = row.get_text(" ", strip=True)
        date_match = DATE_PATTERN.search(row_text)
        date_str = date_match.group(0) if date_match else ""

        notices.append({"title": title, "link": link, "date": date_str})

    return notices


# ---------- css_selector: config-driven, কোড ছাড়া নতুন সাইট যোগ করা যায় ----------
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


# ---------- ai_fallback: bdjobs/chakri.com — Gemini দিয়ে parse ----------
def parse_ai_fallback(source, gemini_client):
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
            model=GEMINI_MODEL,
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
