from __future__ import annotations
import json, time
from dataclasses import asdict
from typing import List, Optional
from events.event_selector import get_upcoming_events
from utils.db_utils import (
    get_distinct_selected_locations,
    get_last_city_snapshot_time,
    insert_city_events_snapshot,
)
from models.events import Event

def _already_snapshotted_today(last_ts: Optional[int], now_ts: int) -> bool:
    if not last_ts:
        return False

    return time.gmtime(last_ts)[:3] == time.gmtime(now_ts)[:3]

def save_city_events_snapshot(events: List[Event], location_value: str, location_label: str, generated_at: int) -> None:
    """Saves a snapshot of events for a given city/location."""
    payload = {
        "generated_at": generated_at,
        "location_value": location_value,
        "location_label": location_label,
        "events": [asdict(e) for e in events],
    }
    insert_city_events_snapshot(location_value, location_label or "", json.dumps(payload, ensure_ascii=False))

def run_city_events_job(app) -> None:
    """Once a day: for each location selected by at least one user,
    save a snapshot of available events (dummy for now) into city_events_daily.
    De-dupes per location/day."""
    with app.app_context():
        app.logger.info("[city-events] ===== JOB STARTED =====")
        now_ts = int(time.time())
        locs = get_distinct_selected_locations()
        if not locs:
            app.logger.info("[city-events] no user-selected locations; skipping.")
            return

        for value, label in locs:
            try:
                last_ts = get_last_city_snapshot_time(value)
                if _already_snapshotted_today(last_ts, now_ts):
                    app.logger.debug("[city-events] %s already snapshotted today; skip.", value)
                    continue


                events = get_upcoming_events(start_date=None, days=30, location_code=value)
                app.logger.info("[city-events] gathered %d events for %s (%s).", len(events), label, value)
                save_city_events_snapshot(events, location_value=value, location_label=label, generated_at=now_ts)
                app.logger.info("[city-events] snapshotted %d events for %s (%s).", len(events), label, value)
            except Exception as e:
                app.logger.exception("[city-events] failed for %s: %s", value, e)
