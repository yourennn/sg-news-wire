"""
SG News Wire scraper.

Runs automatically on GitHub (see .github/workflows/update-news.yml) and
writes docs/news.json, which the website (docs/index.html) loads.

You can also run it on your own computer to test:
    pip install -r requirements.txt
    python scraper.py

Titles and paragraphs are saved exactly as they appear on the source sites.
"""

import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import feedparser
import requests
from bs4 import BeautifulSoup

SGT = ZoneInfo("Asia/Singapore")
OUTPUT = Path(__file__).parent / "docs" / "news.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
TIMEOUT = 20
MAX_PARAGRAPHS = 10
WORKERS = 4  # articles fetched in parallel (kept small to be polite)

session = requests.Session()
session.headers.update(HEADERS)


def fetch_html(url):
    r = session.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    r.encoding = r.apparent_encoding if not r.encoding else r.encoding
    return r.text


def extract_paragraphs(soup, max_n=MAX_PARAGRAPHS):
    paragraphs = []
    for p in soup.find_all("p"):
        text = p.get_text(" ", strip=True)
        if len(text) > 20:
            paragraphs.append(text)
    return paragraphs[:max_n]


def to_iso_sgt(value):
    """Turn any date string we understand into ISO 8601 in Singapore time.
    Returns None if it can't be parsed."""
    if not value:
        return None
    dt = None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(value)  # RSS style: "Sat, 18 Jul 2026 22:20:19 +0800"
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=SGT)
    return dt.astimezone(SGT).isoformat(timespec="seconds")


# ==================================================================
# ZAOBAO
# ==================================================================

ZAOBAO_BASE = "https://www.zaobao.com.sg"
ZAOBAO_SECTIONS = ("新加坡", "国际")


def zaobao_section_cards(soup, section_name, limit=10):
    section_h2 = next(
        (h2 for h2 in soup.find_all("h2") if h2.get_text(strip=True) == section_name),
        None,
    )
    if section_h2 is None:
        return []

    container = section_h2.find_parent()
    while container is not None:
        if len(container.find_all("div", class_="card-content")) >= limit:
            break
        container = container.parent
    if container is None:
        return []

    rows = []
    for card in container.find_all("div", class_="card-content")[:limit]:
        h2 = card.find("h2", class_="card-header")
        link = card.find("a", href=True)
        if not h2 or not link:
            continue
        time_div = card.find("div", class_="text-brand-primary")
        url = urljoin(ZAOBAO_BASE, link["href"])
        rows.append({
            "source": "zaobao",
            "section": section_name,
            "time": time_div.get_text(strip=True) if time_div else "",
            "sort_time": None,
            "title": h2.get_text(strip=True),
            "url": url,
            "id": url,
            "paragraphs": [],
        })
    return rows


def zaobao_published_time(soup):
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            payload = json.loads(script.string or "")
        except Exception:
            continue
        for obj in payload if isinstance(payload, list) else [payload]:
            if isinstance(obj, dict):
                for key in ("datePublished", "dateModified", "uploadDate"):
                    if obj.get(key):
                        return obj[key]
    for attrs in (
        {"property": "article:published_time"},
        {"name": "article:published_time"},
        {"itemprop": "datePublished"},
        {"name": "publish-date"},
        {"property": "og:updated_time"},
        {"property": "article:modified_time"},
        {"name": "date"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            return tag["content"]
    time_tag = soup.find("time", attrs={"datetime": True})
    return time_tag["datetime"] if time_tag else None


def zaobao_fill_article(row):
    try:
        soup = BeautifulSoup(fetch_html(row["url"]), "html.parser")
        row["paragraphs"] = extract_paragraphs(soup)
        row["sort_time"] = to_iso_sgt(zaobao_published_time(soup))
    except Exception as e:
        print(f"  ! zaobao article failed: {row['url']} ({e})")
    return row


def infer_dates_from_page_order(rows, now):
    """For rows with only 'HH:MM', work out the date from page order
    (newest first): if the clock goes UP as we move down, we crossed
    midnight into the previous day. Uses Singapore time, not the server's."""
    current_date = now.date()
    prev_minutes = None
    for row in rows:
        m = re.match(r"^(\d{1,2}):(\d{2})$", row.get("time", "").strip())
        if not m:
            continue
        minutes = int(m.group(1)) * 60 + int(m.group(2))
        if prev_minutes is None and minutes > now.hour * 60 + now.minute + 5:
            current_date -= timedelta(days=1)  # newest item is "later" than now => yesterday
        elif prev_minutes is not None and minutes > prev_minutes:
            current_date -= timedelta(days=1)
        prev_minutes = minutes
        if not row.get("sort_time"):
            dt = datetime(current_date.year, current_date.month, current_date.day,
                          int(m.group(1)), int(m.group(2)), tzinfo=SGT)
            row["sort_time"] = dt.isoformat(timespec="seconds")


def fetch_zaobao(cache, limit=10):
    soup = BeautifulSoup(fetch_html(f"{ZAOBAO_BASE}/realtime"), "html.parser")
    now = datetime.now(SGT)
    articles = []
    for section in ZAOBAO_SECTIONS:
        rows = zaobao_section_cards(soup, section, limit=limit)
        print(f"[zaobao] {section}: {len(rows)} headlines")
        todo = reuse_cached(rows, cache)
        print(f"[zaobao] {section}: fetching {len(todo)} new articles")
        with ThreadPoolExecutor(WORKERS) as pool:
            list(pool.map(zaobao_fill_article, todo))
        infer_dates_from_page_order(rows, now)
        articles.extend(rows)
    return articles


# ==================================================================
# 8WORLD
# ==================================================================

RSS_URL = "https://www.8world.com/api/v1/rss-outbound-feed?_format=xml"

# 8world URL path -> section label shown in the website
TAG_LABELS = {
    "singapore": "新加坡",
    "world": "国际",
    "southeast-asia": "东南亚",
    "greater-china": "中港台",
    "china": "中国",
    "sports": "体育",
    "entertainment": "娱乐",
    "e-news": "娱乐",
    "business": "财经",
    "finance": "财经",
    "lifestyle": "生活",
    "bodysos": "健康",
    "health": "健康",
    "omg": "趣闻",
}


def eightworld_fill_article(row):
    try:
        soup = BeautifulSoup(fetch_html(row["url"]), "html.parser")
        paragraphs = extract_paragraphs(soup)
        if not paragraphs:
            meta = soup.find("meta", attrs={"name": "description"})
            if meta and meta.get("content"):
                text = meta["content"].strip()
                paragraphs = [s.strip() + "。" for s in text.split("。") if s.strip()][:MAX_PARAGRAPHS]
        row["paragraphs"] = paragraphs
    except Exception as e:
        print(f"  ! 8world article failed: {row['url']} ({e})")
    return row


def fetch_8world(cache, limit_per_tag=10):
    feed = feedparser.parse(session.get(RSS_URL, timeout=TIMEOUT).content)
    rows, counts = [], {}
    for item in feed.entries:
        url = item.get("link", "")
        if not url:
            continue
        tag = url.replace("https://www.8world.com/", "").split("/")[0]
        counts[tag] = counts.get(tag, 0) + 1
        if counts[tag] > limit_per_tag:
            continue
        published = item.get("published", "")
        rows.append({
            "source": "8world",
            "section": TAG_LABELS.get(tag, tag),
            "time": published,
            "sort_time": to_iso_sgt(published),
            "title": item.get("title", ""),
            "url": url,
            "id": url,
            "paragraphs": [],
        })
    print(f"[8world] {len(rows)} headlines")
    todo = reuse_cached(rows, cache)
    print(f"[8world] fetching {len(todo)} new articles")
    with ThreadPoolExecutor(WORKERS) as pool:
        list(pool.map(eightworld_fill_article, todo))
    return rows


# ==================================================================
# MAIN
# ==================================================================

def load_previous():
    """Last run's articles. On GitHub each run starts on a fresh machine, so we
    download the news.json currently on the live website (SITE_URL is set by
    the workflow). Falls back to a local docs/news.json when testing."""
    site = os.environ.get("SITE_URL", "").rstrip("/")
    if site:
        try:
            r = session.get(f"{site}/news.json", params={"t": int(time.time())}, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
            arts = data["articles"] if isinstance(data, dict) else data
            print(f"Loaded {len(arts)} previous articles from the live site")
            return arts
        except Exception as e:
            print(f"Could not load previous news from the live site ({e})")
    try:
        data = json.loads(OUTPUT.read_text(encoding="utf-8"))
        return data["articles"] if isinstance(data, dict) else data
    except Exception:
        return []


def reuse_cached(rows, cache):
    """Fill rows we already scraped last time; return the rows still to fetch."""
    todo = []
    for row in rows:
        old = cache.get(row["url"])
        if old and old.get("paragraphs"):
            row["paragraphs"] = old["paragraphs"]
            row["sort_time"] = row.get("sort_time") or old.get("sort_time")
        else:
            todo.append(row)
    return todo


def main():
    started = time.time()
    previous = load_previous()
    cache = {a.get("url"): a for a in previous if a.get("url")}
    sources = {}
    all_articles = []

    for name, fetcher in (("zaobao", fetch_zaobao), ("8world", fetch_8world)):
        try:
            got = fetcher(cache)
            if not got:
                raise RuntimeError("no articles found (page layout may have changed)")
            all_articles.extend(got)
            sources[name] = {"ok": True, "count": len(got)}
        except Exception as e:
            # Keep the last good articles from this source instead of losing them.
            kept = [a for a in previous if a.get("source") == name]
            all_articles.extend(kept)
            sources[name] = {"ok": False, "count": len(kept), "error": str(e)[:200]}
            print(f"!! {name} failed: {e} -- kept {len(kept)} previous articles")

    if not any(s["ok"] for s in sources.values()):
        print("!! Both sources failed. Leaving the existing news.json untouched.")
        sys.exit(1)

    all_articles.sort(key=lambda a: a.get("sort_time") or "", reverse=True)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({
        "generated_at": datetime.now(SGT).isoformat(timespec="seconds"),
        "sources": sources,
        "articles": all_articles,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\nSaved {len(all_articles)} articles to {OUTPUT} in {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
