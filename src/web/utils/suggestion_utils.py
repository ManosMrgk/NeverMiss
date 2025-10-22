from typing import List, Dict
from events.event_utils.time_utils import local_tz, next_monday, next_sunday, upcoming_weekend_bounds, parse_event_dt
from models.events import Event
from datetime import date, datetime, timedelta
from events.event_utils.time_utils import start_of_week

def _bucket_events(events: List[Event], today: date) -> Dict[str, List[Event]]:
    """
    Buckets events by:
      - this_week (Mon..Thu from today; omitted entirely if today is Fri)
      - this_weekend (Fri..Sun this week)
      - next_week (Mon..Sun next week)
      - coming_soon (from Monday two weeks out .. today+30d)
    """
    mon_this = start_of_week(today)
    thu_this = mon_this + timedelta(days=3)
    fri_this, sun_this = upcoming_weekend_bounds(today)
    mon_next = next_monday(today)
    sun_next = next_sunday(today)
    mon_two_weeks = mon_next + timedelta(days=7)
    thirty_days_out = today + timedelta(days=30)

    weekday = today.weekday()  # Mon=0..Sun=6

    def in_range(d: date, start: date, end: date) -> bool:
        return start <= d <= end

    this_week, this_weekend, next_week, coming_soon = [], [], [], []
    for ev in events:
        dt = parse_event_dt(ev)
        if not dt:
            continue
        d = dt.date()

        if weekday != 4:
            start_bound = max(today, mon_this)
            if in_range(d, start_bound, thu_this):
                this_week.append(ev)
                continue

        if in_range(d, fri_this, sun_this):
            this_weekend.append(ev)
            continue

        if in_range(d, mon_next, sun_next):
            next_week.append(ev)
            continue

        if in_range(d, mon_two_weeks, thirty_days_out):
            coming_soon.append(ev)
            continue

    key_dt = lambda e: (parse_event_dt(e) or datetime.max.replace(tzinfo=local_tz()))
    for bucket in (this_week, this_weekend, next_week, coming_soon):
        bucket.sort(key=key_dt)

    return {
        "this_week": this_week,
        "this_weekend": this_weekend,
        "next_week": next_week,
        "coming_soon": coming_soon,
    }

def _fmt_event_date(ev: Event) -> str:
    dt = parse_event_dt(ev)
    if not dt:
        return "Date TBA"
    return dt.strftime("%a, %d %b %Y • %H:%M")