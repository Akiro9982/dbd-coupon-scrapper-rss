#  Copyright (C) 2026 Kevin Escobar (Akiro9982)
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

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

IGNORED_TOKENS = {
    "ACTIVE", "INACTIVE", "NORMAL", "MODE", "SERVER", "BONUS", "COPY", "CODE",
    "LATEST", "NEWEST", "CODES", "RELEASED", "EXPIRES", "EXPIRED"
}


def fetch_page(url):
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text


def extract_new_section(soup):
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

    search_text = re.split(r"(?i)latest\s+expired\s+codes\s*:|expired\s+codes\s*:", search_text, maxsplit=1)[0]
    candidates = re.findall(r'"([A-Za-z0-9-]{4,})"', search_text)

    for raw in candidates:
        code = raw.strip().upper()
        if not code or code in IGNORED_TOKENS or code.isdigit():
            continue
        if re.fullmatch(r"(?:19|20)\d{2}", code):
            continue
        if not re.search(r"[A-Z]", code):
            continue
        if len(code) > 40:
            continue

        found[code] = False

    return found


def load_seen(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"active_codes": []}


def save_seen(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def build_feed(current_codes):
    now = datetime.now(timezone.utc)
    pubdate_str = now.strftime('%a, %d %b %Y %H:%M:%S GMT')
    guid_str = now.strftime('%Y%m%d%H%M%S')
    
    if not current_codes:
        description = "<p>No hay códigos activos en este momento.</p>"
    else:
        lines = "".join(f"<li><strong>{escape(c)}</strong></li>" for c in current_codes)
        description = f"<p>Códigos activos actualmente:</p><ul>{lines}</ul>"

    item = f"""
    <item>
      <title>Códigos Activos - {now.strftime('%Y-%m-%d')}</title>
      <description><![CDATA[{description}]]></description>
      <pubDate>{pubdate_str}</pubDate>
      <guid isPermaLink="false">dbd-active-{guid_str}</guid>
    </item>
    """

    rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>DBD Active Codes</title>
  <link>{escape(URL)}</link>
  <description>Lista actualizada de códigos activos para Dead by Daylight</description>
{item}
</channel>
</rss>
"""
    return rss


def main():
    html = fetch_page(URL)
    current = detect_codes(html)
    current_codes = sorted(current.keys())

    seen = load_seen(SEEN_FILE)
    last_active = seen.get("active_codes", [])

    if current_codes == last_active:
        print("Sin cambios en los códigos activos.")
        return

    rss_content = build_feed(current_codes)
    with open(FEED_FILE, "w", encoding="utf-8") as f:
        f.write(rss_content)

    feed_dir = os.path.dirname(os.path.abspath(FEED_FILE)) or os.getcwd()
    codes_txt = os.path.join(feed_dir, "codes.txt")
    codes_json = os.path.join(feed_dir, "codes.json")
    try:
        with open(codes_txt, "w", encoding="utf-8") as f:
            for c in current_codes:
                f.write(c + "\n")
        with open(codes_json, "w", encoding="utf-8") as f:
            json.dump(current_codes, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("No se pudieron guardar los archivos de códigos:", e)

    seen["active_codes"] = current_codes
    save_seen(SEEN_FILE, seen)

    print(f"Cambios detectados. Códigos activos actualmente: {current_codes}")


if __name__ == '__main__':
    main()