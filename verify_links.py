"""
verify_links.py

Checks every URL in bd_office_links.txt and separates them into:
  - alive_links.txt   -> only URLs that returned an actual successful HTTP
                          response (status < 400) on at least one retry
  - dead_links.txt    -> everything else (timeout, connection error, SSL
                          failure, 403/503, DNS failure) — grouped by reason
  - verified_links.csv -> full detail for every URL (result + reason)

Philosophy: if a link can't be reliably reached right now, a future
automated scan won't be able to reach it either — so "maybe it's just
temporarily blocked" is not good enough to keep it. Each URL gets 3
attempts (with a short pause between) before being marked dead, so a
one-off transient hiccup doesn't wrongly kill a real site — but SSL
errors, bot-protection blocks, and timeouts that persist across all 3
attempts DO count as dead.

Usage (locally or in GitHub Actions):
    pip install requests urllib3
    python verify_links.py

Input:
    bd_office_links.txt   (one URL per line, in the same folder)

Output:
    verified_links.csv    (url, result, note)
    alive_links.txt       (confirmed working — use this in your app)
    dead_links.txt        (could not be reached after 3 tries)
"""

import csv
import html
import socket
import threading
import time
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

INPUT_FILE = "bd_office_links.txt"
CSV_OUTPUT = "verified_links.csv"
ALIVE_OUTPUT = "alive_links.txt"
DEAD_OUTPUT = "dead_links.txt"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}
TIMEOUT_SEC = 12
MAX_WORKERS = 15  # keep modest — too high looks like a DDoS and gets you blocked faster

# Write results as they complete, so if the job gets killed/times out you
# still keep everything checked so far instead of losing all progress.
_write_lock = threading.Lock()


def clean_url(raw: str) -> str:
    url = raw.strip()
    if not url:
        return ""
    url = html.unescape(url)  # &amp; -> &
    return url


def dns_resolves(url: str) -> bool:
    """True if the hostname resolves to SOMETHING. False only means the
    domain genuinely does not exist / has no DNS record."""
    try:
        host = urlparse(url).hostname
        if not host:
            return False
        socket.setdefaulttimeout(8)
        socket.gethostbyname(host)
        return True
    except Exception:
        return False


def check_url(url: str):
    """Returns (url, result, note). result is 'alive' only if we got an
    actual successful HTTP response (status < 400) on at least one of
    several retries. Everything else (timeout, connection refused, SSL
    failure, 403/503, DNS failure) is 'dead' — if we can't reliably reach
    it now, a future automated scan won't be able to either."""

    if not dns_resolves(url):
        return (url, "dead", "dns_failure")

    attempts = 3
    last_reason = "unknown"
    for attempt in range(attempts):
        try:
            resp = requests.get(
                url, headers=HEADERS, timeout=TIMEOUT_SEC,
                allow_redirects=True, verify=False,  # cert issues alone shouldn't fail a real site
            )
            if resp.status_code < 400:
                return (url, "alive", f"HTTP {resp.status_code}")
            else:
                last_reason = f"http_{resp.status_code}"
        except requests.exceptions.SSLError:
            last_reason = "ssl_error"
        except requests.exceptions.Timeout:
            last_reason = "timeout"
        except requests.exceptions.ConnectionError:
            last_reason = "connection_error"
        except requests.exceptions.RequestException as e:
            last_reason = f"request_error: {str(e)[:60]}"

        if attempt < attempts - 1:
            time.sleep(2)  # brief pause before retrying — helps with transient blocks

    return (url, "dead", last_reason)


def main():
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        urls = [clean_url(line) for line in f if clean_url(line)]

    # de-duplicate while keeping order
    urls = list(dict.fromkeys(urls))
    print(f"Loaded {len(urls)} unique URLs from {INPUT_FILE}")
    print(f"Checking with {MAX_WORKERS} parallel workers (timeout {TIMEOUT_SEC}s each)...\n")

    csv_file = open(CSV_OUTPUT, "w", newline="", encoding="utf-8")
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(["url", "result", "note"])

    alive_file = open(ALIVE_OUTPUT, "w", encoding="utf-8")
    dead_file = open(DEAD_OUTPUT, "w", encoding="utf-8")

    alive_count = 0
    dead_count = 0
    checked = 0
    dead_reasons = {}  # reason -> count, for the final summary

    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(check_url, u): u for u in urls}
            for future in as_completed(futures):
                url = futures[future]
                try:
                    result_url, result, note = future.result()
                except Exception as e:
                    # Should not normally happen since check_url catches broadly,
                    # but guard anyway so one bad URL can't kill the whole run.
                    # Strict mode: if we couldn't even determine the result, don't
                    # guess "alive" — treat it as dead and flag it for review.
                    result_url, result, note = (url, "dead", f"checker_crashed: {e}")

                with _write_lock:
                    csv_writer.writerow([result_url, result, note])
                    csv_file.flush()
                    if result == "alive":
                        alive_file.write(result_url + "\n")
                        alive_file.flush()
                        alive_count += 1
                    else:
                        dead_file.write(result_url + "\n")
                        dead_file.flush()
                        dead_count += 1
                        # bucket by the reason prefix (before any ": " detail)
                        reason_key = note.split(":")[0]
                        dead_reasons[reason_key] = dead_reasons.get(reason_key, 0) + 1

                checked += 1
                if checked % 50 == 0 or checked == len(urls):
                    print(f"  checked {checked}/{len(urls)}  "
                          f"(alive: {alive_count}, dead: {dead_count})")
    finally:
        csv_file.close()
        alive_file.close()
        dead_file.close()

    print(f"\n{'='*50}")
    print(f"RESULT SUMMARY")
    print(f"{'='*50}")
    print(f"Total checked : {len(urls)}")
    print(f"Alive         : {alive_count}  ({alive_count*100//max(len(urls),1)}%)")
    print(f"Dead          : {dead_count}  ({dead_count*100//max(len(urls),1)}%)")
    if dead_reasons:
        print(f"\nDead breakdown by reason:")
        for reason, count in sorted(dead_reasons.items(), key=lambda x: -x[1]):
            print(f"  {reason:20s} : {count}")
    print(f"{'='*50}")
    print(f"\nUse {ALIVE_OUTPUT} in your app.")
    print(f"Review {DEAD_OUTPUT} / {CSV_OUTPUT} if you want to manually rescue any of the dead ones.")


if __name__ == "__main__":
    main()
