from datetime import datetime, timedelta, timezone, date
import re
from typing import List, Optional, Tuple
import unicodedata
from models.events import Event

def parse_event_dt(ev: Event) -> Optional[datetime]:
    """Parse Event.start_date (ISO string) into an aware datetime in Europe/Athens.
    Falls back to fixed +03:00 if zoneinfo is unavailable. Returns None if unparsable."""
    if not ev.start_date:
        return None

    # Resolve local timezone (prefer IANA, fallback to fixed offset)
    try:
        from zoneinfo import ZoneInfo  # Python 3.9+
        tz = ZoneInfo("Europe/Athens")
    except Exception:
        tz = timezone(timedelta(hours=3))  # EET/EEST approximation (no DST transitions)

    s = ev.start_date.strip()

    try:
        # Date-only (YYYY-MM-DD) → assume local midnight
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            dt = datetime.fromisoformat(s).replace(tzinfo=tz)
        else:
            # Normalize trailing Z to +00:00 for fromisoformat
            if s.endswith("Z"):
                dt = datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(tz)
            else:
                dt = datetime.fromisoformat(s)
                # If naive, assume local tz; if aware, convert to local tz
                dt = dt.replace(tzinfo=tz) if dt.tzinfo is None else dt.astimezone(tz)
    except Exception:
        return None

    return dt

def daterange(start: date, end: date) -> List[date]:
    """Inclusive date range [start, end]."""
    days = (end - start).days
    return [start + timedelta(days=i) for i in range(days + 1)]


def start_of_week(d: date) -> date:
    """Monday of the week for date d."""
    return d - timedelta(days=d.weekday())


def end_of_week(d: date) -> date:
    """Sunday of the week for date d."""
    return start_of_week(d) + timedelta(days=6)


def next_monday(d: date) -> date:
    return start_of_week(d) + timedelta(days=7)


def next_sunday(d: date) -> date:
    return next_monday(d) + timedelta(days=6)


def upcoming_weekend_bounds(today: date) -> tuple[date, date]:
    """Friday..Sunday of the current week containing 'today'."""
    mon = start_of_week(today)
    fri = mon + timedelta(days=4)
    sun = mon + timedelta(days=6)
    return fri, sun

def local_tz():
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo("Europe/Athens")
        except Exception:
            return timezone(timedelta(hours=3))  # fallback if zoneinfo/tzdata unavailable
        
def athens_now():
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Europe/Athens")
    except Exception:
        tz = timezone(timedelta(hours=3))
    return datetime.now(tz)

def month_bounds(y: int, m: int) -> Tuple[datetime, datetime]:
    start = datetime(y, m, 1)
    end = datetime(y + (m == 12), (m % 12) + 1, 1) - timedelta(days=1)
    return start, end

# Inclusive end = start + days - 1
def range_bounds(start_d: date, days: int) -> Tuple[datetime, datetime]:
    start_dt = datetime(start_d.year, start_d.month, start_d.day)
    end_dt = start_dt + timedelta(days=max(1, days) - 1)
    return start_dt, end_dt

# ---------- greek dates ----------
G_MONTHS_FULL = {
    "ιανουαριου":1,"ιανουαριος":1,"φεβρουαριου":2,"φεβρουαριος":2,
    "μαρτιου":3,"μαρτιος":3,"απριλιου":4,"απριλιος":4,
    "μαιου":5,"μαϊου":5,"μαιος":5,"μαϊος":5,
    "ιουνιου":6,"ιουνιος":6,"ιουλιου":7,"ιουλιος":7,
    "αυγουστου":8,"αυγουστος":8,"σεπτεμβριου":9,"σεπτεμβριος":9,
    "οκτωβριου":10,"οκτωβριος":10,"νοεμβριου":11,"νοεμβριος":11,
    "δεκεμβριου":12,"δεκεμβριος":12,
}
# common abbreviations on more.com UI
G_MONTHS_ABBR = {
    "ιαν":1, "φεβ":2, "μαρ":3, "απρ":4, "μαϊ":5, "μαι":5, "ιουν":6,
    "ιουλ":7, "αυγ":8, "σεπ":9, "οκτ":10, "νοε":11, "δεκ":12
}

G_MONTHS_LABEL = {
    1:"Ιανουαριος",2:"Φεβρουαριος",3:"Μαρτιος",4:"Απριλιος",5:"Μαιος",
    6:"Ιουνιος",7:"Ιουλιος",8:"Αυγουστος",9:"Σεπτεμβριος",10:"Οκτωβριος",
    11:"Νοεμβριος",12:"Δεκεμβριος"
}

def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()

DATE_NUM = re.compile(r"(\d{1,2})[\/\.-](\d{1,2})[\/\.-](\d{2,4})")
DATE_G_WORD = re.compile(r"(\d{1,2})\s+([A-Za-zΆ-ώΰϊΐϋΫόάέήύώΊΎ\.]+)")

def parse_greek_date_piece(txt: str, fallback_year: int) -> Optional[datetime]:
    if not txt:
        return None
    m = DATE_NUM.search(txt)
    if m:
        d, mm, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if yy < 100: yy += 2000
        try:
            return datetime(yy, mm, d)
        except Exception:
            return None
    m = DATE_G_WORD.search(txt)
    if not m:
        return None
    d = int(m.group(1))
    mon_raw = _strip_accents(m.group(2)).replace(".", "")
    mm = (G_MONTHS_ABBR.get(mon_raw) or G_MONTHS_FULL.get(mon_raw))
    if not mm:
        return None
    try:
        return datetime(fallback_year, mm, d)
    except Exception:
        return None

def parse_greek_date_or_range(txt: str, fallback_year: int) -> Tuple[Optional[datetime], Optional[datetime]]:
    if not txt:
        return (None, None)
    parts = [p.strip() for p in txt.split("-")]
    if len(parts) == 1:
        d = parse_greek_date_piece(parts[0], fallback_year)
        return (d, d)
    start = parse_greek_date_piece(parts[0], fallback_year)
    end = parse_greek_date_piece(parts[-1], fallback_year)
    return (start, end or start)

def overlaps_range(start: Optional[datetime], end: Optional[datetime], a: datetime, b: datetime) -> bool:
    if not start and not end:
        return False
    s = start or end
    e = end or start
    return not (e < a or s > b)

def parse_iso_date(s: str) -> Optional[datetime]:
    m = re.search(r"(\d{4})[-/](\d{2})[-/](\d{2})", s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception:
            return None
    return None