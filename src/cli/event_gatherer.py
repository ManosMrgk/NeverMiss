"""
Fast scraper for more.com (music) → for selected date range.
"""
from __future__ import annotations
import argparse, json, pathlib
from dataclasses import asdict
from datetime import date, datetime
from typing import List, Optional, Tuple, Dict, Any
from playwright.sync_api import sync_playwright, Page, BrowserContext, Route, Request
from models.events import Event
from utils.time_utils import G_MONTHS_LABEL, athens_now, overlaps_range, parse_greek_date_or_range, parse_iso_date, range_bounds
from utils.logger import log, info, warn

BASE = "https://www.more.com/gr-el/tickets/music/"


# ---------- page utils ----------
TRACKER_SUBSTR = (
    "doubleclick", "googletagmanager", "google-analytics", "facebook", "hotjar", "segment",
    "adsystem", "optimizely", "taboola", "criteo", "quantserve", "scorecardresearch",
)

def should_block(req: Request) -> bool:
    rt = req.resource_type
    url = req.url.lower()
    if rt in ("image", "media", "font"):
        return True
    if any(s in url for s in TRACKER_SUBSTR):
        return True
    return False

def install_blocking(ctx: BrowserContext, *, debug: bool):
    def _route(route: Route, req: Request):
        if should_block(req):
            route.abort()
        else:
            route.continue_()
    ctx.route("**/*", _route)
    log("request blocking enabled", debug=debug)


def accept_and_clear_overlays(page: Page, *, debug: bool):
    # Try common cookie buttons; then nuke overlays via JS to avoid layout jank.
    candidates = [
        "#onetrust-accept-btn-handler", ".cc-btn.cc-allow", ".cc-allow",
        "text=Αποδοχή", "text=Συμφωνώ", "text=OK", "text=Accept all",
        "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    ]
    for sel in candidates:
        try:
            btn = page.locator(sel).first
            if btn.is_visible():
                btn.click(timeout=600)
                page.wait_for_timeout(120)
                break
        except Exception:
            pass
    try:
        page.evaluate("""
            () => {
              const hide = (sel) => { const n = document.querySelector(sel); if (n) { n.style.display='none'; n.style.pointerEvents='none'; }};
              ['.cc-overlay','.cc-window','.cc-bar__right','#CybotCookiebotDialog','.sp-message-container','.sp_veil']
                .forEach(hide);
              const b=document.body; if (b) b.style.overflow='auto';
            }
        """)
    except Exception:
        pass


def safe_click(l, *, debug: bool, timeout=1600) -> bool:
    try:
        l.click(timeout=timeout)
        return True
    except Exception:
        pass
    try:
        l.click(force=True, timeout=800)
        return True
    except Exception:
        pass
    try:
        l.evaluate("(el)=>el.click()")
        return True
    except Exception:
        return False


def wait_ready(page: Page, *, debug: bool):
    page.wait_for_selector("#ui-page", timeout=20000)
    page.wait_for_selector("#play_results", timeout=20000)
    log("base UI ready", debug=debug)


def fast_lazy_scroll(page: Page, *, debug: bool, pause_ms: int = 180, max_rounds: int = 50, stable_rounds: int = 3):
    """Rapidly scrolls until card count and document height are stable."""
    log("starting lazy-load scroll…", debug=debug)
    last_count = -1
    last_h = -1
    stable = 0
    for r in range(max_rounds):
        # Scroll to bottom in JS (faster than wheel)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(pause_ms)
        count = page.locator('#play_results article[itemtype="http://schema.org/Event"]').count()
        h = page.evaluate("document.body.scrollHeight")
        if count == last_count and h == last_h and count > 0:
            stable += 1
        else:
            stable = 0
        if stable >= stable_rounds:
            break
        last_count, last_h = count, h
    log(f"scroll finished with {last_count} cards", debug=debug)

# ---------- filters (UI) ----------

def try_open_location_dropdown(page: Page, *, debug: bool) -> bool:
    trigger = page.locator(".locationDropDown").first
    if not trigger.is_visible():
        trigger = page.locator("#LocationFilter").first
    return safe_click(trigger, debug=debug)


def select_location(page: Page, *, max_reload: int, debug: bool, location_code: str = ".area1") -> bool:
    for attempt in range(max_reload + 1):
        accept_and_clear_overlays(page, debug=debug)
        try_open_location_dropdown(page, debug=debug)
        try:
            if not page.locator("#location-cities.mm-opened").is_visible():
                page.locator('a[aria-owns="location-cities"]').first.click(timeout=800)
        except Exception:
            pass
        if not location_code or location_code.strip() == "":
            location_code = ".area1"  # default to Attica
        location = page.locator('ul.mm-listview a[data-filter="'+location_code+'"]').first
        if location.count() > 0 and location.is_visible():
            if safe_click(location, debug=debug):
                page.keyboard.press("Escape")
                page.wait_for_timeout(100)
                return True
        if attempt < max_reload:
            page.reload(wait_until="domcontentloaded")
            wait_ready(page, debug=debug)
    return False

def set_date_range_filters(page: Page, start_d: date, end_d: date, *, debug: bool):
    accept_and_clear_overlays(page, debug=debug)
    safe_click(page.locator(".datesDropDown").first, debug=debug)
    try:
        page.locator('.dropdown-menu.daterange-filters .ranges li[data-range-key="Συγκεκριμένο διάστημα"]').click(timeout=800)
    except Exception:
        pass

    def go_to_month(target: date):
        month_name = G_MONTHS_LABEL[target.month]
        left_header = page.locator('.daterangepicker .calendar.left .month').first
        right_next = page.locator('.daterangepicker .calendar.right .next.available').first
        for _ in range(24): # cap navigation hops
            try:
                txt = (left_header.text_content() or "").strip()
                if (month_name in txt) and (str(target.year) in txt):
                    return True
            except Exception:
                pass
            try:
                right_next.click(timeout=400)
            except Exception:
                page.keyboard.press("ArrowRight")
            page.wait_for_timeout(50)
        return False


    def pick_day(side: str, day: int) -> bool:
        try:
            cell = page.locator(f'.daterangepicker .calendar.{side} td.available', has_text=str(day)).first
            return safe_click(cell, debug=debug)
        except Exception:
            return False


    # Pick start
    if go_to_month(start_d):
        pick_day('left', start_d.day) or pick_day('right', start_d.day)
    else:
        warn("Could not navigate to start month; continuing.")


    # Pick end (may be same or later month)
    if end_d.month != start_d.month or end_d.year != start_d.year:
        go_to_month(end_d)
    pick_day('left', end_d.day) or pick_day('right', end_d.day)
    page.keyboard.press("Escape")

# ---------- scraping ----------

# Vectorized extraction (single JS roundtrip)
JS_EXTRACT = """
() => Array.from(document.querySelectorAll('#play_results article[itemtype="http://schema.org/Event"]')).map(art => {
  const style = (art.getAttribute('style')||'').toLowerCase();
  const hidden = style.includes('display: none') || style.includes('display:none');
  const pickAttr = (sel, attr) => { const el = art.querySelector(sel); const v = el && el.getAttribute(attr); return v ? v.trim() : null };
  const pickText = (sel) => { const el = art.querySelector(sel); const v = el && el.textContent; return v ? v.trim() : null };
  let url = pickAttr('meta[itemprop="url"]','content') || pickAttr('a#ItemLink','href') || pickAttr('a.play-template__main','href');
  if (url && url.startsWith('/')) url = 'https://www.more.com' + url;
  let image = pickAttr('meta[itemprop="image"]','content') || pickAttr('img.lazy','data-original') || pickAttr('img','src');
  if (image && image.startsWith('/')) image = 'https://www.more.com' + image;
  const start_iso = pickAttr('meta[itemprop="startDate"]','content') || art.getAttribute('data-date') || art.getAttribute('data-date-time');
  const title = pickText('h3.playinfo__title') || pickText('[itemprop="name"]') || '(untitled)';
  const venue = pickText('span#PlayVenue') || pickText('[itemprop="location"] [itemprop="name"]');
  const city = pickAttr('[itemprop="addressLocality"]','content');
  const region = pickAttr('[itemprop="addressRegion"]','content');
  const pill = pickText('.playinfo__date');
  return { hidden, url, image, start_iso, title, venue, city, region, pill };
})
"""

def collect_events(page: Page, range_a: datetime, range_b: datetime, *, location_only: bool, location_title: str = "Αττική", debug: bool) -> List[Event]:
    items: List[Dict[str, Any]] = page.evaluate(JS_EXTRACT)
    out: List[Event] = []
    for it in items:
        if it.get('hidden'):
            continue
        url = it.get('url')
        if not url:
            continue
        title = it.get('title') or '(untitled)'
        image = it.get('image')
        start_iso = it.get('start_iso')
        start_dt: Optional[datetime] = parse_iso_date(start_iso) if start_iso else None
        end_dt: Optional[datetime] = start_dt
        if not start_dt:
            s, e = parse_greek_date_or_range(it.get('pill') or '', fallback_year=y)
            start_dt, end_dt = s, e
        venue = it.get('venue')
        city = it.get('city')
        region = it.get('region')
        if location_only and (region or '').strip() != location_title:
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
        out.append(Event(title=title, url=url, start_date=start_iso_out, venue=venue, city=city, region=region, image=image))
    log(f"collected {len(out)} events after filtering", debug=debug)
    return out

# ---------- browser ----------

def make_context(pw, engine: str, headful: bool, *, debug: bool) -> Tuple[BrowserContext, Page]:
    # chromium is a bit faster & supports headless=new flags better
    if engine == "firefox":
        browser = pw.firefox.launch(headless=not headful)
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:129.0) Gecko/20100101 Firefox/129.0"
    else:
        browser = pw.chromium.launch(headless=not headful, args=([] if headful else ["--headless=new","--disable-dev-shm-usage"]))
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
    ctx = browser.new_context(
        locale="el-GR",
        timezone_id="Europe/Athens",
        ignore_https_errors=True,
        user_agent=ua,
        viewport={"width": 1440, "height": 900},
    )
    # Lower default timeout for snappier failures
    ctx.set_default_timeout(20000)
    install_blocking(ctx, debug=debug)
    page = ctx.new_page()
    log(f"context ready (engine={engine}, headful={headful})", debug=debug)
    return ctx, page

# ---------- driver ----------

def scrape_more(location_only: bool, start_date_str: Optional[str], days: int,
                headful: bool, engine: str,
                max_location_reloads: int,
                debug: bool,
                use_fast_mode: bool,
                location_code: Optional[str] = ".area1",
                location_title: str = "Αττική",
                debug_dump: Optional[str] = ".more_list_debug.html") -> List[Event]:
    if start_date_str:
        sd = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    else:
        sd = athens_now().date()
    a, b = range_bounds(sd, days)
    with sync_playwright() as p:
        ctx, page = make_context(p, engine, headful, debug=debug)
        log(f"goto {BASE}", debug=debug)
        page.goto(BASE, wait_until="domcontentloaded", timeout=20000)
        accept_and_clear_overlays(page, debug=debug)
        wait_ready(page, debug=debug)

        if not use_fast_mode and location_only:
            ok = select_location(page, max_reload=max_location_reloads, debug=debug, location_code=location_code)
            if not ok:
                warn("Proceeding without UI Location filter (will DOM-filter by region).")

        if not use_fast_mode:
            set_date_range_filters(page, sd, (a + (b - a)).date(), debug=debug)

        # Load all cards quickly
        fast_lazy_scroll(page, debug=debug)

        events = collect_events(page, a, b, location_only=location_only, location_title=location_title, debug=debug)

        if not events and debug_dump:
            try:
                pathlib.Path(debug_dump).write_text(page.content(), encoding="utf-8")
                warn(f"0 events; saved page to {debug_dump} for inspection.")
            except Exception:
                pass
        ctx.close()
        return events

# ---------- CLI ----------

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
            trunc(e.title, cols[2]).ljust(cols[2]),
            trunc(e.url, cols[3]).ljust(cols[3]),
        ]))


def main(argv=None) -> int:
    now = athens_now()
    ap = argparse.ArgumentParser(description="Scrape more.com (music) → Attica for current month (fast)")
    ap.add_argument("--start", type=str, default=None, help="Start date YYYY-MM-DD (default: today in Europe/Athens)")
    ap.add_argument("--location_code", type=str, default="", help="Optional location code to filter events (default: Attica's code)")
    ap.add_argument("--location_title", type=str, default="Αττική", help="Location title for filtering (default: 'Αττική')")
    ap.add_argument("--days", type=int, default=1, help="Number of days (inclusive)")
    ap.add_argument("--location-only", action="store_true", default=True)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--engine", choices=["firefox","chromium"], default="chromium")
    ap.add_argument("--debug", action="store_true", help="verbose debug logs on stderr")
    ap.add_argument("--max-location-reloads", type=int, default=1)
    ap.add_argument("--fast", action="store_true", help="Skip UI filters; rely on DOM filters only (much faster)")
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
        if args.start:
            base = args.start
        else:
            base = now.strftime("%Y-%m-%d")
        default_name = f"more-{base}-{args.days}{'-'+args.location_title if args.location_only else ''}.json"
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
