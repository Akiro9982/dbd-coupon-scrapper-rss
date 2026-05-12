import os
import re
import json
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup
from html import escape

# Config
URL = "https://dbdcoupons.com/?"
# Guardar archivos en la misma carpeta que este script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SEEN_FILE = os.path.join(BASE_DIR, "seen_codes.json")
FEED_FILE = os.path.join(BASE_DIR, "feed.xml")
HISTORY_LIMIT = 50

EXPIRE_KEYWORDS = ["expir", "caduc", "expired", "agotad", "ended", "ended on"]
IGNORED_TOKENS = {
    "ACTIVE", "INACTIVE", "NORMAL", "MODE", "SERVER", "BONUS", "COPY", "CODE",
    "LATEST", "NEWEST", "CODES", "RELEASED", "EXPIRES", "EXPIRED"
}


def fetch_page(url):
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text


def extract_new_section(soup):
    # Prefer the explicit section "Newest Active Codes" and stop at "Latest Expired Codes"
    start_keywords = ["newest active codes", "newest codes", "new active codes"]
    stop_keywords = ["latest expired codes", "expired codes"]

    for htag in ["h1", "h2", "h3", "h4", "h5", "h6"]:
        for hdr in soup.find_all(htag):
            header_text = hdr.get_text(" ", strip=True).lower()
            if not any(k in header_text for k in start_keywords):
                continue

            parts = []
            for sib in hdr.next_siblings:
                sib_name = getattr(sib, "name", None)
                if sib_name and sib_name.lower().startswith("h"):
                    sib_text = sib.get_text(" ", strip=True).lower()
                    if any(k in sib_text for k in stop_keywords):
                        break
                if len(parts) > 120:
                    break
                try:
                    text = sib.get_text(" ", strip=True)
                except Exception:
                    text = str(sib)
                if text:
                    parts.append(text)

            section_text = "\n".join(parts)
            if section_text.strip():
                return section_text

    # Fallback: try an element with class/name hints related to newest/active coupons
    selectors = [".newest-active-codes", "#new-dbd-codes", ".new-coupons", ".latest", ".recent", "#new-coupons", ".coupons-new"]
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            return el.get_text(" ", strip=True)
    return ""


def detect_codes(html, prefer_new_section=True):
    soup = BeautifulSoup(html, "html.parser")
    found = {}

    search_text = None
    if prefer_new_section:
        search_text = extract_new_section(soup)
    if not search_text:
        return found

    # Keep only the "new/active" block if "expired" block is embedded in the same text chunk
    search_text = re.split(r"(?i)latest\s+expired\s+codes\s*:|expired\s+codes\s*:", search_text, maxsplit=1)[0]

    # Strict mode: only codes inside quotes within the newest-active section.
    candidates = re.findall(r'"([A-Za-z0-9-]{4,})"', search_text)

    for raw in candidates:
        code = raw.strip().upper()
        if not code:
            continue
        if code in IGNORED_TOKENS:
            continue
        if code.isdigit():
            continue
        # Avoid years and similar numeric-only tokens
        if re.fullmatch(r"(?:19|20)\d{2}", code):
            continue
        # Require at least one letter to avoid date fragments
        if not re.search(r"[A-Z]", code):
            continue
        if len(code) > 40:
            continue

        # We only track newest active codes in this parser
        found[code] = False

    return found  # dict: code -> expired(bool)


def load_seen(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"codes": {}, "history": []}


def save_seen(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def make_rss(entry_title, new_codes, expired_codes, pubdate=None):
    if pubdate is None:
        pubdate = datetime.now(timezone.utc)

    def make_section(title, codes):
        if not codes:
            return f"<p><strong>{escape(title)}</strong><br/>(ninguno)</p>"
        lines = "".join(f"<p>Código: {escape(c)}</p>" for c in codes)
        return f"<p><strong>{escape(title)}</strong></p>" + lines

    description = make_section("Códigos nuevos:", new_codes) + make_section("Expirados:", expired_codes)

    item = f"""
    <item>
      <title>{escape(entry_title)}</title>
      <description><![CDATA[{description}]]></description>
      <pubDate>{pubdate.strftime('%a, %d %b %Y %H:%M:%S GMT')}</pubDate>
    </item>
    """

    return item


def build_feed(history_items):
    items_xml = "\n".join(history_items)
    rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>DBD Coupons Feed</title>
  <link>{escape(URL)}</link>
  <description>Feed de cambios (códigos nuevos / expirados) desde dbdcoupons.com</description>
{items_xml}
</channel>
</rss>
"""
    return rss


def main():
    html = fetch_page(URL)
    current = detect_codes(html)  # dict code->expired

    seen = load_seen(SEEN_FILE)
    seen_codes = seen.get("codes", {})

    new_codes = []
    expired_codes = []

    now = datetime.now(timezone.utc).isoformat()

    # Compare
    for code, expired in current.items():
        if code not in seen_codes:
            new_codes.append(code)
            seen_codes[code] = {"first_seen": now, "expired": expired, "last_seen": now}
        else:
            # if status changed to expired
            if expired and not seen_codes[code].get("expired", False):
                expired_codes.append(code)
            # update last seen and expired flag
            seen_codes[code]["last_seen"] = now
            seen_codes[code]["expired"] = seen_codes[code].get("expired", False) or expired

    # Keep ordering stable
    new_codes.sort()
    expired_codes.sort()

    # If there are no new or expired codes, do not modify any files
    if not new_codes and not expired_codes:
        print("Sin cambios detectados.")
        return

    # Append history entry
    entry_title = f"Actualización {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
    item_xml = make_rss(entry_title, new_codes, expired_codes, datetime.now(timezone.utc))
    history = seen.get("history", [])
    history.insert(0, {"time": now, "title": entry_title, "new": new_codes, "expired": expired_codes, "item_xml": item_xml})
    # trim history
    history = history[:HISTORY_LIMIT]

    # Save seen
    seen["codes"] = seen_codes
    seen["history"] = history
    save_seen(SEEN_FILE, seen)

    # Build feed from history items
    items = [h["item_xml"] for h in history]
    rss = build_feed(items)
    with open(FEED_FILE, "w", encoding="utf-8") as f:
        f.write(rss)

    # Guardar lista de códigos (en la misma carpeta que el feed)
    feed_dir = os.path.dirname(os.path.abspath(FEED_FILE)) or os.getcwd()
    codes_txt = os.path.join(feed_dir, "codes.txt")
    codes_json = os.path.join(feed_dir, "codes.json")
    current_codes = sorted(current.keys())
    try:
        with open(codes_txt, "w", encoding="utf-8") as f:
            for c in current_codes:
                f.write(c + "\n")
        with open(codes_json, "w", encoding="utf-8") as f:
            json.dump(current_codes, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("No se pudieron guardar los archivos de códigos:", e)

    # Print summary
    if new_codes:
        print("Nuevos códigos:", new_codes)
    if expired_codes:
        print("Expirados detectados:", expired_codes)


if __name__ == '__main__':
    main()