# web/db.py
from __future__ import annotations
from datetime import datetime, timezone
import json
import os, sqlite3, uuid, time
from typing import List, Optional, Tuple, Dict, Any
from models.events import Event

DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "nevermiss.db"))

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db() -> None:
    conn = _connect()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        uuid             TEXT UNIQUE NOT NULL,
        spotify_id       TEXT UNIQUE NOT NULL,
        display_name     TEXT,
        country          TEXT,
        email            TEXT,
        location_label   TEXT,
        location_value   TEXT,
        frequency        TEXT,
        access_token     TEXT,
        refresh_token    TEXT,
        token_expires_at REAL,
        created_at       REAL NOT NULL,
        updated_at       REAL NOT NULL
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_tastes (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        user_uuid     TEXT NOT NULL,
        artists_json  TEXT NOT NULL,      -- JSON array of strings in user-preferred order
        genres_json   TEXT NOT NULL,      -- JSON array of strings in user-preferred order
        retrieved_at  REAL NOT NULL,      -- epoch seconds
        FOREIGN KEY (user_uuid) REFERENCES users(uuid) ON DELETE CASCADE
    );
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_user_tastes_user_time ON user_tastes(user_uuid, retrieved_at DESC);")
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_uuid   TEXT NOT NULL,
    period_key  TEXT NOT NULL,        -- e.g. 2025-W42 / 2025-B21 / 2025-10
    created_at  TEXT NOT NULL,        -- ISO8601 UTC
    payload_json TEXT NOT NULL,
    FOREIGN KEY (user_uuid) REFERENCES users(uuid) ON DELETE CASCADE            
    );
    """)

    cur.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS uq_user_suggestions_period
    ON user_suggestions(user_uuid, period_key);
    """)
    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_user_suggestions_user_time
    ON user_suggestions(user_uuid, created_at DESC);
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS city_events_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    location_value TEXT NOT NULL,
    location_label TEXT NOT NULL,
    created_at INTEGER NOT NULL,          -- epoch seconds
    payload_json TEXT NOT NULL
    );
    """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_city_events_daily_loc_time
    ON city_events_daily(location_value, created_at DESC);
    """)
    
    conn.commit()
    conn.close()

def get_all_users() -> List[dict]:
    with _connect() as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("""
            SELECT uuid as user_uuid, email, location_label, location_value, frequency
            FROM users
            WHERE uuid IS NOT NULL
        """).fetchall()
        return [dict(r) for r in rows]

def get_latest_suggestion_time(user_uuid: str) -> Optional[datetime]:
    with _connect() as con:
        con.row_factory = sqlite3.Row
        row = con.execute("""
            SELECT created_at
            FROM user_suggestions
            WHERE user_uuid = ?
            ORDER BY created_at DESC
            LIMIT 1
        """, (user_uuid,)).fetchone()
        if not row:
            return None
        return datetime.fromisoformat(row["created_at"])

def insert_user_suggestions(user_uuid: str, period_key: str, payload: Dict[str, Any]) -> bool:
    """
    Insert or replace by (user_uuid, period_key).
    Returns True on success (inserted or replaced).
    """
    created_at = datetime.now(timezone.utc).isoformat()
    with _connect() as con:
        con.execute("""
            INSERT INTO user_suggestions (user_uuid, period_key, created_at, payload_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_uuid, period_key) DO UPDATE SET
                created_at  = excluded.created_at,
                payload_json = excluded.payload_json
        """, (user_uuid, period_key, created_at, json.dumps(payload, ensure_ascii=False)))
    return True

def get_latest_user_suggestions(user_uuid: str) -> Optional[Dict[str, Any]]:
    with _connect() as con:
        con.row_factory = sqlite3.Row
        row = con.execute("""
            SELECT payload_json
            FROM user_suggestions
            WHERE user_uuid = ?
            ORDER BY created_at DESC
            LIMIT 1
        """, (user_uuid,)).fetchone()
        if not row:
            return None
        return json.loads(row["payload_json"])

def get_latest_user_suggested_events_list(user_uuid: str) -> Optional[Event]:
    """
    Return the latest user's suggested events list as a list of Events.
    If no snapshot exists, return None.
    """
    payload = get_latest_user_suggestions(user_uuid)
    if not payload:
        return None
    try:
        events_data = payload.get("events")
        if isinstance(events_data, list):
            events = []
            for event_dict in events_data:
                try:
                    events.append(Event(**event_dict))
                except (TypeError, KeyError) as e:
                    print(f"Skipping malformed event: {e}")
                    continue
            return events
        return []
    except Exception:
        return [] 

def get_users_without_suggestions() -> List[dict]:
    """
    Return a list of user_uuid for users that have ZERO suggestion records.
    """
    with _connect() as con:
        rows = con.execute("""
            SELECT uuid as user_uuid, email, location_label, location_value, frequency
            FROM users u
            LEFT JOIN user_suggestions s ON s.user_uuid = u.uuid
            GROUP BY u.uuid
            HAVING COUNT(s.id) = 0
        """).fetchall()
        return [dict(r) for r in rows]

def has_any_suggestions(user_uuid: str) -> bool:
    with _connect() as con:
        row = con.execute("""
            SELECT 1 FROM user_suggestions
            WHERE user_uuid = ?
            LIMIT 1
        """, (user_uuid,)).fetchone()
        return row is not None
                
def get_user_by_spotify_id(spotify_id: str) -> Optional[sqlite3.Row]:
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE spotify_id = ?", (spotify_id,))
    row = cur.fetchone()
    conn.close()
    return row

def get_user_by_uuid(user_uuid: str) -> Optional[sqlite3.Row]:
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE uuid = ?", (user_uuid,))
    row = cur.fetchone()
    conn.close()
    return row

def get_distinct_selected_locations():
    """Return [(value, label)] for all locations chosen by any user."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT location_value, COALESCE(location_label, '')
        FROM users
        WHERE location_value IS NOT NULL AND location_value <> ''
    """)
    return [(r[0], r[1]) for r in cur.fetchall()]

def get_last_city_snapshot_time(location_value: str) -> Optional[int]:
    """Return epoch seconds of the latest snapshot for that location."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT created_at
        FROM city_events_daily
        WHERE location_value = ?
        ORDER BY created_at DESC
        LIMIT 1
    """, (location_value,))
    row = cur.fetchone()
    return int(row[0]) if row else None

def insert_city_events_snapshot(location_value: str, location_label: str, payload_json: str, created_at: Optional[int]=None) -> None:
    conn = _connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO city_events_daily (location_value, location_label, created_at, payload_json)
        VALUES (?, ?, ?, ?)
    """, (location_value, location_label, int(created_at or time.time()), payload_json))
    conn.commit()

def get_latest_city_events_snapshot(location_value: str) -> Optional[Tuple[int, str]]:
    """
    Return (created_at, payload_json) for the latest snapshot for a location,
    or None if there is no snapshot yet.
    """
    conn = _connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT created_at, payload_json
        FROM city_events_daily
        WHERE location_value = ?
        ORDER BY created_at DESC
        LIMIT 1
    """, (location_value,))
    row = cur.fetchone()
    return (int(row[0]), row[1]) if row else None

def get_latest_city_events_list(location_value: str) -> Optional[List[Event]]:
    """
    Return the latest snapshot's events list as a list of Events.
    If no snapshot exists, return None.
    """
    snap = get_latest_city_events_snapshot(location_value)
    if not snap:
        return None
    _, payload_json = snap
    try:
        payload = json.loads(payload_json) if payload_json else {}
        events_data = payload.get("events")
        if isinstance(events_data, list):
            events = []
            for event_dict in events_data:
                try:
                    events.append(Event(**event_dict))
                except (TypeError, KeyError) as e:
                    print(f"Skipping malformed event: {e}")
                    continue
            return events
        return []
    except Exception:
        return []
    
def upsert_user(
    spotify_id: str,
    display_name: Optional[str],
    country: Optional[str],
    email: Optional[str],
    access_token: str,
    refresh_token: Optional[str],
    token_expires_at: float,
    default_frequency: str = "weekly",
) -> str:
    """Insert or update the user; returns uuid."""
    now = time.time()
    row = get_user_by_spotify_id(spotify_id)
    conn = _connect()
    cur = conn.cursor()

    if row is None:
        user_uuid = str(uuid.uuid4())
        cur.execute("""
            INSERT INTO users (uuid, spotify_id, display_name, country, email,
                               frequency, access_token, refresh_token, token_expires_at,
                               created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_uuid, spotify_id, display_name, country, email,
            default_frequency, access_token, refresh_token, token_expires_at, now, now
        ))
        conn.commit()
        conn.close()
        return user_uuid
    else:
        user_uuid = row["uuid"]
        # only write email if we didn't have one already
        new_email = row["email"] or email
        new_freq = row["frequency"] or default_frequency
        cur.execute("""
            UPDATE users
               SET display_name = ?,
                   country = ?,
                   email = ?,
                   frequency = ?,
                   access_token = ?,
                   refresh_token = ?,
                   token_expires_at = ?,
                   updated_at = ?
             WHERE spotify_id = ?
        """, (
            display_name, country, new_email, new_freq,
            access_token, refresh_token, token_expires_at, now, spotify_id
        ))
        conn.commit()
        conn.close()
        return user_uuid

def update_preferences(
    user_uuid: str,
    email: Optional[str],
    location_label: Optional[str],
    location_value: Optional[str],
    frequency: Optional[str],
) -> None:
    """Update preferences; email is only set if not already present."""
    row = get_user_by_uuid(user_uuid)
    if row is None:
        return
    now = time.time()
    # preserve existing email if present
    new_email = row["email"] or email

    conn = _connect()
    cur = conn.cursor()
    cur.execute("""
        UPDATE users
           SET email = ?,
               location_label = ?,
               location_value = ?,
               frequency = ?,
               updated_at = ?
         WHERE uuid = ?
    """, (new_email, location_label, location_value, frequency, now, user_uuid))
    conn.commit()
    conn.close()

def update_tokens_for_spotify_id(
    spotify_id: str,
    access_token: str,
    refresh_token: Optional[str],
    token_expires_at: float,
) -> None:
    conn = _connect()
    cur = conn.cursor()
    # keep old refresh_token if Spotify didn't return a new one
    cur.execute("SELECT refresh_token FROM users WHERE spotify_id = ?", (spotify_id,))
    row = cur.fetchone()
    current_refresh = row["refresh_token"] if row else None
    new_refresh = refresh_token or current_refresh

    cur.execute("""
        UPDATE users
           SET access_token = ?,
               refresh_token = ?,
               token_expires_at = ?,
               updated_at = ?
         WHERE spotify_id = ?
    """, (access_token, new_refresh, token_expires_at, time.time(), spotify_id))
    conn.commit()
    conn.close()
    
def insert_tastes_snapshot(user_uuid: str, artists: list[str], genres: list[str], retrieved_at: float | None = None) -> None:
    ts = retrieved_at or time.time()
    conn = _connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO user_tastes (user_uuid, artists_json, genres_json, retrieved_at)
        VALUES (?, ?, ?, ?)
    """, (user_uuid, json.dumps(artists, ensure_ascii=False), json.dumps(genres, ensure_ascii=False), ts))
    conn.commit()
    conn.close()
    
def get_latest_user_tastes_row(user_uuid: str) -> Optional[sqlite3.Row]:
    """
    Return the latest row from user_tastes for a user, or None if not found.
    """
    conn = _connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT artists_json, genres_json, retrieved_at
        FROM user_tastes
        WHERE user_uuid = ?
        ORDER BY retrieved_at DESC
        LIMIT 1
    """, (user_uuid,))
    row = cur.fetchone()
    conn.close()
    return row

def get_latest_user_tastes(user_uuid: str) -> Optional[Tuple[List[str], List[str], float]]:
    """
    Return (artists, genres, retrieved_at_epoch) for the latest tastes snapshot,
    or None if no snapshot exists.
    """
    row = get_latest_user_tastes_row(user_uuid)
    if not row:
        return None
    try:
        artists = json.loads(row["artists_json"]) if row["artists_json"] else []
        genres  = json.loads(row["genres_json"])  if row["genres_json"]  else []
        artists = artists if isinstance(artists, list) else []
        genres  = genres  if isinstance(genres, list)  else []
        return (artists, genres, float(row["retrieved_at"]))
    except Exception:
        return ([], [], float(row["retrieved_at"]) if row.get("retrieved_at") is not None else 0.0)
    
def delete_user_by_uuid(user_uuid: str) -> None:
    conn = _connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE uuid = ?", (user_uuid,))
    conn.commit()
    conn.close()