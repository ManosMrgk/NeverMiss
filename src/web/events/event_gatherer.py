"""
Fast scraper for more.com (music) → for selected date range.
"""
from __future__ import annotations
import argparse, json, pathlib, re
from dataclasses import asdict
from datetime import date, datetime
from typing import List, Optional, Tuple, Dict, Any
import requests
from bs4 import BeautifulSoup

from models.events import Event
from events.event_utils.time_utils import (
    G_MONTHS_LABEL, athens_now, overlaps_range, parse_greek_date_or_range,
    parse_iso_date, range_bounds
)
from events.event_utils.logger import log, info, warn

BASE = "https://www.more.com/gr-el/tickets/music/"


SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "el-GR,el;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
})

NEXT_TEXTS = {"επόμενη", "next", "»", ">", "επομενη"}

def fetch_soup(url: str, *, debug: bool) -> BeautifulSoup:
    log(f"GET {url}", debug=debug)
    r = SESSION.get(url, timeout=25)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")

def find_next_url(soup: BeautifulSoup, current_url: str) -> Optional[str]:
    link = soup.find("a", rel=lambda v: v and "next" in v.lower())
    if link and link.get("href"):
        return requests.compat.urljoin(current_url, link["href"])

    for a in soup.select("a[href]"):
        t = (a.get_text(" ", strip=True) or "").lower()
        if t in NEXT_TEXTS:
            return requests.compat.urljoin(current_url, a["href"])

    pag = soup.select_one(".pagination, .pager, .paginator")
    if pag:
        active = pag.select_one(".active + li a[href], .current + a[href]")
        if active and active.get("href"):
            return requests.compat.urljoin(current_url, active["href"])
    return None

def clean_text(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _get_attr(el, sel: str, attr: str) -> Optional[str]:
    if not el: return None
    node = el.select_one(sel)
    if not node: return None
    v = node.get(attr)
    if not v: return None
    v = v.strip()
    if v.startswith("/"):
        v = requests.compat.urljoin("https://www.more.com", v)
    return v

def _get_text(el, sel: str) -> Optional[str]:
    if not el: return None
    node = el.select_one(sel)
    if not node: return None
    return clean_text(node.get_text(" ", strip=True))

def parse_cards(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    """
    Collect raw card data from the listing DOM (server-rendered).
    """
    cards = soup.select('#play_results article[itemtype="http://schema.org/Event"]')
    out: List[Dict[str, Any]] = []
    for art in cards:
        style = (art.get("style") or "").lower()
        hidden = "display:none" in style.replace(" ", "") or "display: none" in style

        url = _get_attr(art, 'meta[itemprop="url"]', 'content') \
              or _get_attr(art, 'a#ItemLink', 'href') \
              or _get_attr(art, 'a.play-template__main', 'href')

        image = _get_attr(art, 'meta[itemprop="image"]', 'content') \
                or _get_attr(art, 'img.lazy', 'data-original') \
                or _get_attr(art, 'img', 'src')

        start_iso = _get_attr(art, 'meta[itemprop="startDate"]', 'content') \
                    or art.get("data-date") \
                    or art.get("data-date-time")

        title = _get_text(art, 'h3.playinfo__title') \
                or _get_text(art, '[itemprop="name"]') \
                or "(untitled)"

        venue = _get_text(art, 'span#PlayVenue') \
                or _get_text(art, '[itemprop="location"] [itemprop="name"]')

        city = None
        loc_addr = art.select_one('[itemprop="addressLocality"]')
        if loc_addr:
            city = (loc_addr.get("content") or clean_text(loc_addr.get_text())) or None

        region = None
        loc_reg = art.select_one('[itemprop="addressRegion"]')
        if loc_reg:
            region = (loc_reg.get("content") or clean_text(loc_reg.get_text())) or None

        pill = _get_text(art, '.playinfo__date')

        out.append({
            "hidden": hidden,
            "url": url,
            "image": image,
            "start_iso": start_iso,
            "title": title,
            "venue": venue,
            "city": city,
            "region": region,
            "pill": pill,
        })
    return out

def collect_events_from_soup(
    soup: BeautifulSoup,
    range_a: datetime,
    range_b: datetime,
    *,
    location_only: bool,
    location_title: str,
    debug: bool
) -> List[Event]:
    items = parse_cards(soup)
    out: List[Event] = []
    fallback_year = range_a.year

    for it in items:
        if it.get("hidden"):
            continue

        url = it.get("url")
        if not url:
            continue

        title = it.get("title") or "(untitled)"
        image = it.get("image")

        start_iso_raw = it.get("start_iso")
        start_dt: Optional[datetime] = parse_iso_date(start_iso_raw) if start_iso_raw else None
        end_dt: Optional[datetime] = start_dt

        if not start_dt:
            s, e = parse_greek_date_or_range(it.get("pill") or "", fallback_year=fallback_year)
            start_dt, end_dt = s, e

        venue = it.get("venue")
        city = it.get("city")
        region = it.get("region")

        if location_only and (region or "").strip() != location_title:
            continue

        if not overlaps_range(start_dt, end_dt, range_a, range_b):
            continue

        if start_dt or end_dt:
            chosen = max(start_dt or end_dt, range_a)
            if chosen > range_b:
                chosen = range_a
            start_iso_out = f"{chosen.year:04d}-{chosen.month:02d}-{chosen.day:02d}"
        else:
            start_iso_out = None

        out.append(Event(
            title=title,
            url=url,
            start_date=start_iso_out,
            venue=venue,
            city=city,
            region=region,
            image=image
        ))

    log(f"collected {len(out)} events after filtering (this page)", debug=debug)
    return out

def scrape_more(
    location_only: bool,
    start_date_str: Optional[str],
    days: int,
    headful: bool,                  # kept for CLI compatibility
    engine: str,                    # kept for CLI compatibility
    max_location_reloads: int,      # kept for CLI compatibility
    debug: bool,
    use_fast_mode: bool,            # kept for CLI compatibility
    location_code: Optional[str] = ".area1",    # kept for CLI compatibility
    location_title: str = "Αττική",
    debug_dump: Optional[str] = ".more_list_debug.html"
) -> List[Event]:
    if start_date_str:
        sd = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    else:
        sd = athens_now().date()

    range_a, range_b = range_bounds(sd, days)

    url = BASE
    max_pages = 30
    page_count = 0
    all_events: List[Event] = []
    seen_urls = set()

    while url and page_count < max_pages:
        page_count += 1
        soup = fetch_soup(url, debug=debug)

        if page_count == 1 and debug_dump:
            try:
                pathlib.Path(debug_dump).write_text(str(soup), encoding="utf-8")
            except Exception:
                pass

        items = collect_events_from_soup(
            soup, range_a, range_b,
            location_only=location_only,
            location_title=location_title,
            debug=debug
        )

        fresh = [e for e in items if e.url not in seen_urls]
        for e in fresh:
            seen_urls.add(e.url)
        all_events.extend(fresh)

        nxt = find_next_url(soup, url)
        if not nxt:
            break
        url = nxt

    all_events.sort(key=lambda e: (e.start_date or "9999-99-99", e.title or ""))
    if not all_events and debug_dump:
        warn(f"0 events found; first page saved to {debug_dump} for inspection.", debug=debug)
    return all_events


def print_table(items: List[Event]):
    cols = [12, 28, 64, 80]
    def trunc(s: str, n: int) -> str:
        s = (s or "").replace("\n"," ").strip()
        return s if len(s) <= n else s[:n-1] + "…"
    header = ("When", "Venue", "Title", "URL")
    sep = "-+-".join("-"*n for n in cols)
    print(" | ".join(h.ljust(w) for h,w in zip(header, cols)))
    print(sep)
    for e in items:
        print(" | ".join([
            trunc(e.start_date or "", cols[0]).ljust(cols[0]),
            trunc(e.venue or "", cols[1]).ljust(cols[1]),
            trunc(e.title or "", cols[2]).ljust(cols[2]),
            trunc(e.url or "", cols[3]).ljust(cols[3]),
        ]))

def main(argv=None) -> int:
    now = athens_now()
    ap = argparse.ArgumentParser(description="Scrape more.com (music) → Attica for current month (fast)")
    ap.add_argument("--start", type=str, default=None, help="Start date YYYY-MM-DD (default: today in Europe/Athens)")
    ap.add_argument("--location_code", type=str, default="", help="Unused in bs4 mode; kept for CLI compatibility")
    ap.add_argument("--location_title", type=str, default="Αττική", help="Location title for filtering (default: 'Αττική')")
    ap.add_argument("--days", type=int, default=1, help="Number of days (inclusive)")
    ap.add_argument("--location-only", action="store_true", default=True)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--headful", action="store_true", help="Ignored in bs4 mode")
    ap.add_argument("--engine", choices=["firefox","chromium"], default="chromium", help="Ignored in bs4 mode")
    ap.add_argument("--debug", action="store_true", help="verbose debug logs on stderr")
    ap.add_argument("--max-location-reloads", type=int, default=1, help="Ignored in bs4 mode")
    ap.add_argument("--fast", action="store_true", help="Ignored in bs4 mode (bs4 is already fast)")
    ap.add_argument("--out", type=pathlib.Path, default=None, help="Output path for --json")
    args = ap.parse_args(argv)

    items = scrape_more(
        location_only=args.location_only,
        start_date_str=args.start, days=args.days,
        headful=args.headful, engine=args.engine,
        max_location_reloads=args.max_location_reloads,
        debug=args.debug,
        use_fast_mode=args.fast,
        location_code=args.location_code,
        location_title=args.location_title,
    )
    if args.json:
        base = args.start or now.strftime("%Y-%m-%d")
        default_name = f"more-{base}-{args.days}{('-'+args.location_title) if args.location_only else ''}.json"
        out_path = args.out or pathlib.Path(default_name)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        data = [asdict(e) for e in items]
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        info(f"Saved {len(items)} event(s) to {out_path.resolve()}")
    else:
        print_table(items)
        info(f"{len(items)} event(s).")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
