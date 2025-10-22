"""
Generates a beautiful HTML newsletter of upcoming events using the recommendations
from event_selector.get_recommended_events().

Sections:
- This week (omitted if today is Friday)
- This weekend
- Next week
- Coming soon (from two weeks out up to 30 days from today)

Usage:
    python generate_newsletter.py --out newsletter.html --days 30
    # optional: --start 2025-10-16 (ISO date)

Requires:
- event_selector.py (as provided)
- models.events.Event (dataclass with fields: title, url, start_date, venue, city, region, image)
"""

from __future__ import annotations
import argparse
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional
from zoneinfo import ZoneInfo
from event_selector import get_recommended_events
from models.events import Event
from event_utils.time_utils import local_tz, next_monday, next_sunday, parse_event_dt, start_of_week, upcoming_weekend_bounds


def bucket_events(events: List[Event], today: date) -> Dict[str, List[Event]]:
    """
    Buckets events by:
      - this_week (Mon..Thu from today; omitted entirely if today is Fri)
      - this_weekend (Fri..Sun this week)
      - next_week (Mon..Sun next week)
      - coming_soon (from Monday two weeks out .. today+30d)

    Note:
      - We only include events with a valid parsable start_date.
      - “This week” is the remaining weekdays up to Thursday (Mon–Thu).
    """
    # Resolve date window anchors
    mon_this = start_of_week(today)
    thu_this = mon_this + timedelta(days=3)
    fri_this, sun_this = upcoming_weekend_bounds(today)
    mon_next = next_monday(today)
    sun_next = next_sunday(today)
    mon_two_weeks = mon_next + timedelta(days=7)
    thirty_days_out = today + timedelta(days=30)

    weekday = today.weekday()  # Mon=0 .. Sun=6

    def in_range(d: date, start: date, end: date) -> bool:
        return start <= d <= end

    this_week: List[Event] = []
    this_weekend: List[Event] = []
    next_week: List[Event] = []
    coming_soon: List[Event] = []

    for ev in events:
        dt = parse_event_dt(ev)
        if not dt:
            continue  # skip undated/unparsable
        d = dt.date()

        # This week (Mon..Thu)
        if weekday != 4:  # NOT Friday
            start_bound = max(today, mon_this)
            if in_range(d, start_bound, thu_this):
                this_week.append(ev)
                continue

        # This weekend
        if in_range(d, fri_this, sun_this):
            this_weekend.append(ev)
            continue

        # Next week
        if in_range(d, mon_next, sun_next):
            next_week.append(ev)
            continue

        # Coming soon: two weeks out (Mon) up to 30 days from today
        if in_range(d, mon_two_weeks, thirty_days_out):
            coming_soon.append(ev)
            continue

    # Sort each bucket by start_date asc
    key_dt = lambda e, _tz=local_tz(): parse_event_dt(e) or datetime.max.replace(tzinfo=_tz)
    for bucket in (this_week, this_weekend, next_week, coming_soon):
        bucket.sort(key=key_dt)

    return {
        "this_week": this_week,
        "this_weekend": this_weekend,
        "next_week": next_week,
        "coming_soon": coming_soon,
    }


# -------------------------- HTML rendering --------------------------

def fmt_event_date(ev: Event) -> str:
    dt = parse_event_dt(ev)
    if not dt:
        return "Date TBA"
    return dt.strftime("%a, %d %b %Y • %H:%M")


def event_card(ev: Event) -> str:
    img = ev.image or ""
    has_img = bool(img)

    banner = (
        f'''
        <div class="thumb-banner">
          <div class="thumb-banner__ratio"></div>
          <img src="{img}" alt="" class="thumb-banner__img" />
        </div>
        ''' if has_img else
        '''
        <div class="thumb-banner thumb-banner--placeholder">
          <div class="thumb-banner__ratio"></div>
          <div class="thumb-banner__icon">🎵</div>
        </div>
        '''
    )

    loc_bits = [x for x in [ev.venue, ev.city, ev.region] if x]
    location = " · ".join(loc_bits) if loc_bits else "Location TBA"

    return f"""
    <a class="card" href="{ev.url}" target="_blank" rel="noopener noreferrer">
      {banner}
      <div class="meta">
        <div class="date">{fmt_event_date(ev)}</div>
        <div class="title">{ev.title}</div>
        <div class="where">{location}</div>
      </div>
    </a>
    """

def section_block(title: str, events: List[Event]) -> str:
    if not events:
        return f"""
        <section>
          <h2>{title}</h2>
          <div class="empty">No events in this section.</div>
        </section>
        """
    cards = "\n".join(event_card(e) for e in events)
    return f"""
    <section>
      <h2>{title}</h2>
      <div class="grid">
        {cards}
      </div>
    </section>
    """


def render_html(buckets: Dict[str, List[Event]], today: date) -> str:
    weekday = today.weekday()  # 4 = Friday
    # Build sections respecting the "omit This week if Friday" rule
    sections_html = []

    if weekday != 4:
        sections_html.append(section_block("This week", buckets["this_week"]))

    sections_html.append(section_block("This weekend", buckets["this_weekend"]))
    sections_html.append(section_block("Next week", buckets["next_week"]))
    sections_html.append(section_block("Coming soon", buckets["coming_soon"]))

    sections = "\n".join(sections_html)
    today_str = today.strftime("%A, %d %B %Y")

    # Inline CSS (email-friendly, avoids external refs)
    # Uses simple, robust styles and a responsive card grid.
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>NeverMiss Newsletter</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {{
    --bg: #0b1020;
    --panel: #111936;
    --muted: #9fb0d6;
    --text: #e8eeff;
    --accent: #7aa2ff;
    --card: #0f1a3a;
    --card-hover: #12204a;
    --shadow: rgba(0,0,0,0.35);
  }}
  body {{
    margin: 0; padding: 0;
    background: radial-gradient(1200px 800px at 20% -10%, #1b2450 0%, #0b1020 60%, #090e1b 100%) fixed;
    color: var(--text);
    font: 16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, "Helvetica Neue", Arial, "Apple Color Emoji","Segoe UI Emoji";
  }}
  .container {{
    max-width: 960px; margin: 0 auto; padding: 32px 20px 56px;
  }}
  header {{
    text-align: center; margin-bottom: 24px;
  }}
  header h1 {{
    margin: 0 0 6px; font-size: 28px; letter-spacing: 0.3px;
  }}
  header .sub {{
    color: var(--muted); font-size: 14px;
  }}
  section {{
    background: linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.02));
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 14px;
    padding: 18px;
    margin: 18px 0 26px;
    box-shadow: 0 8px 30px var(--shadow);
  }}
  h2 {{
    font-size: 18px; margin: 0 0 12px; letter-spacing: 0.2px; color: var(--accent);
  }}
  .empty {{
    color: var(--muted);
    padding: 14px;
    background: rgba(255,255,255,0.03);
    border-radius: 10px;
    border: 1px dashed rgba(255,255,255,0.08);
  }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 16px;
   }}
   .card {{
    display: block;
    text-decoration: none; color: inherit;
    background: var(--card);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 16px;
    overflow: hidden; /* for the banner radius */
    transition: transform .15s ease, background .15s ease, box-shadow .15s ease;
    box-shadow: 0 6px 22px rgba(0,0,0,0.28);
    }}
    .card:hover {{
    background: var(--card-hover);
    transform: translateY(-2px);
    box-shadow: 0 10px 28px rgba(0,0,0,0.35);
    }}

    .thumb-banner {{
    position: relative;
    width: 100%;
    background: #0c1636;
    border-bottom: 1px solid rgba(255,255,255,0.06);
    /* modern: maintain 16:9 without the hack below (many webmail clients support this now) */
    aspect-ratio: 16 / 9;
    }}
    .thumb-banner__img {{
    position: absolute; inset: 0;
    width: 100%; height: 100%;
    object-fit: cover; display: block;
    }}

    .thumb-banner__ratio {{
    display: none; /* hidden when aspect-ratio works */
    }}
    @supports not (aspect-ratio: 16 / 9) {{
        .thumb-banner {{ aspect-ratio: auto; }}
        .thumb-banner__ratio {{
            display: block;
            width: 100%;
            padding-top: 56.25%; /* 16:9 */
        }}
        .thumb-banner__img,
        .thumb-banner--placeholder .thumb-banner__icon {{
            position: absolute; left: 0; top: 0; right: 0; bottom: 0;
        }}
    }}

    .thumb-banner--placeholder {{
    display: grid; place-items: center;
    color: var(--muted);
    }}
    .thumb-banner__icon {{
    font-size: 42px; opacity: 0.9;
    }}

    .meta {{
    padding: 12px 12px 14px;
    min-width: 0; display: grid; gap: 6px;
    }}
    .meta .date {{
    color: var(--muted); font-size: 12px;
    }}
    .meta .title {{
    font-weight: 600; font-size: 16px; line-height: 1.35;
    }}
    .meta .where {{
    color: var(--muted); font-size: 13px;
    }}

  footer {{
    color: var(--muted);
    text-align: center;
    margin-top: 28px;
    font-size: 12px;
  }}
  @media (prefers-color-scheme: light) {{
    :root {{
      --bg: #f6f7fb;
      --panel: #ffffff;
      --muted: #5b6a88;
      --text: #0e1330;
      --accent: #3a63ff;
      --card: #ffffff;
      --card-hover: #f5f7ff;
      --shadow: rgba(0,0,0,0.12);
    }}
    body {{
      background: radial-gradient(1200px 800px at 20% -10%, #eaf0ff 0%, #f6f7fb 60%, #f2f4fa 100%) fixed;
    }}
    section {{
      box-shadow: 0 8px 24px var(--shadow);
    }}
  }}
</style>
</head>
<body>
  <div class="container">
    <header>
      <h1>Upcoming Events</h1>
      <div class="sub">Curated for you • {today_str}</div>
    </header>

    {sections}

    <footer>
      You’re receiving this preview based on your Spotify favorites and local listings.
    </footer>
  </div>
</body>
</html>"""


# -------------------------- Main --------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate an HTML newsletter of upcoming events.")
    parser.add_argument("--start", type=str, default=None, help="ISO start date (YYYY-MM-DD). Defaults to today.")
    parser.add_argument("--days", type=int, default=30, help="How many days ahead to consider (default: 30).")
    parser.add_argument("--out", type=str, default="newsletter.html", help="Output HTML file path.")
    args = parser.parse_args()

    # Resolve start date
    if args.start:
        try:
            start_date = date.fromisoformat(args.start)
        except ValueError:
            raise SystemExit(f"Invalid --start date: {args.start} (expected YYYY-MM-DD)")
    else:
        start_date = datetime.now(local_tz()).date()

    # Fetch recommended events (this loads .env inside event_selector)
    events: List[Event] = get_recommended_events(start_date=start_date.isoformat(), days=args.days)

    # Bucket & render
    buckets = bucket_events(events, today=start_date)
    html = render_html(buckets, today=start_date)

    # Write out
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Wrote newsletter to {args.out} ({sum(len(v) for v in buckets.values())} events across sections).")


if __name__ == "__main__":
    main()
