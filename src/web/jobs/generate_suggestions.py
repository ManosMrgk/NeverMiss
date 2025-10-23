from __future__ import annotations
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
import random
import time
from typing import Iterable, Literal
from flask import Flask
from utils.db_utils import get_all_users, get_latest_city_events_list, get_latest_suggestion_time, get_latest_user_tastes, get_users_without_suggestions, insert_user_suggestions
from events.event_selector import get_recommended_events, get_upcoming_events
from jobs.gather_events import save_city_events_snapshot

Freq = Literal["weekly", "biweekly", "monthly"]

def compute_period_key(now: datetime, freq: Freq) -> str:
    '''Compute a period key string based on current time and frequency.'''
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if freq == "weekly":
        iso_year, iso_week, _ = now.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    if freq == "biweekly":
        iso_year, iso_week, _ = now.isocalendar()
        bucket = (iso_week + 1) // 2  # 1-26 or 27
        return f"{iso_year}-B{bucket:02d}"
    # monthly
    return f"{now.year}-{now.month:02d}"

def cadence_reached(last: datetime | None, now: datetime, freq: Freq) -> bool:
    '''Check if enough time has passed since last suggestion generation.'''
    if last is None:
        return True  # first time
    delta = now - last
    if freq == "weekly":
        return delta >= timedelta(days=7)
    if freq == "biweekly":
        return delta >= timedelta(days=14)
    return delta >= timedelta(days=28)

def _events_to_dicts(events: Iterable) -> list[dict]:
    out: list[dict] = []
    for e in (events or []):
        if is_dataclass(e):
            out.append(asdict(e))
        elif isinstance(e, dict):
            out.append(e)
        else:
            out.append(dict(getattr(e, "__dict__", {})))
    return out

def _with_retries(fn, *, max_attempts=3, base_sleep=0.6):
    """
    Simple exponential backoff with jitter for transient errors.
    Only wrap the parts that can fail (API/db/network). DB insert is idempotent via unique key.
    """
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as e:
            attempt += 1
            if attempt >= max_attempts:
                raise
            sleep = base_sleep * (2 ** (attempt - 1))
            sleep = sleep + random.uniform(0, 0.3)
            time.sleep(sleep)

def _run_for_users(app: Flask,  users: list[dict], *, now: datetime) -> tuple[int, int, int]:
    """
    Core worker: builds and inserts suggestions for the supplied users,
    respecting cadence & dedup-by-period. Returns (made, skipped_due, skipped_dupe).
    """
    made, skipped_due, skipped_dupe = 0, 0, 0

    for u in users:
        freq = (u.get("frequency") or "weekly").lower()
        if freq not in ("weekly", "biweekly", "monthly"):
            freq = "weekly"

        last = get_latest_suggestion_time(u["user_uuid"])
        if last is not None and not cadence_reached(last, now, freq):
            skipped_due += 1
            continue

        period_key = compute_period_key(now, freq)
        location_value = (u.get("location_value") or "").strip()
        location_label = (u.get("location_label") or "").strip()
        if not location_value or location_value == "":
            continue

        def _build_payload():
            events = get_latest_city_events_list(location_value=location_value)
            if not events or len(events) == 0:
                events = get_upcoming_events(start_date=None, days=30, location_code=location_value)
                now_ts = int(time.time())
                save_city_events_snapshot(events, location_value=location_value, location_label=location_label, generated_at=now_ts)
            artists, genres, _ = get_latest_user_tastes(u["user_uuid"])
            spotify_data = {
                "favorite_artists": artists,
                "favorite_genres": genres,
            }
            recommended = get_recommended_events(events=events, spotify_data=spotify_data)
            return {
                "user_uuid": u["user_uuid"],
                "generated_at": now.isoformat(),
                "location": u.get("location_label"),
                "frequency": freq,
                "period_key": period_key,
                "events": _events_to_dicts(recommended),
            }
        try:
            payload = _with_retries(_build_payload)
        except Exception as e:
            app.logger.exception("Failed to build suggestions for %s: %s", u["user_uuid"], e)
            continue

        try:
            inserted = insert_user_suggestions(u["user_uuid"], period_key, payload)
        except Exception as e:
            def _try_insert():
                return insert_user_suggestions(u["user_uuid"], period_key, payload)
            try:
                inserted = _with_retries(_try_insert)
            except Exception as e2:
                app.logger.exception("Insert failed for %s: %s", u["user_uuid"], e2)
                continue

        if inserted:
            made += 1
        else:
            skipped_dupe += 1

    return made, skipped_due, skipped_dupe

def run_suggestions_job(app: Flask) -> tuple[int, int, int]:
    now = datetime.now(timezone.utc)
    users = get_all_users()
    made, skipped_due, skipped_dupe = _run_for_users(app, users, now=now)
    app.logger.info("Suggestions run: made=%d, skipped_due=%d, skipped_dupe=%d", made, skipped_due, skipped_dupe)
    return made, skipped_due, skipped_dupe

def run_new_users_job(app: Flask) -> tuple[int, int, int]:
    """
    Every 10 minutes: only process users who have *no* suggestions yet.
    Cadence passes automatically (last=None). Dedup is still guaranteed by the unique constraint.
    """
    now = datetime.now(timezone.utc)
    newbies = get_users_without_suggestions()
    if not newbies:
        app.logger.info("New-users job: nothing to do.")
        return (0, 0, 0)
    made, skipped_due, skipped_dupe = _run_for_users(app, newbies, now=now)
    app.logger.info(
        "New-users job: made=%d, skipped_due=%d, skipped_dupe=%d (checked=%d)",
        made, skipped_due, skipped_dupe, len(newbies)
    )
    return made, skipped_due, skipped_dupe