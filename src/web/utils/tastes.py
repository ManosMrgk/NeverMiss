# utils/tastes.py
from __future__ import annotations
import requests, time
from typing import Tuple, List
from utils.db_utils import insert_tastes_snapshot
from flask import Flask


SPOTIFY_API_BASE = "https://api.spotify.com/v1"

def _fetch_top_artists(access_token: str, time_range: str = "medium_term", limit: int = 50) -> list[dict]:
    r = requests.get(
        f"{SPOTIFY_API_BASE}/me/top/artists",
        params={"time_range": time_range, "limit": limit},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )
    r.raise_for_status()
    j = r.json() or {}
    return j.get("items", [])

def _rank_genres(artists_items: list[dict]) -> list[str]:
    # flatten and count occurrences while keeping a rough preference order
    from collections import Counter
    genres = []
    for a in artists_items:
        genres.extend(a.get("genres", []) or [])
    counted = Counter(genres)
    # sort by frequency desc, then alphabetically for stability
    return [g for (g, _) in sorted(counted.items(), key=lambda kv: (-kv[1], kv[0]))]

def fetch_and_store_tastes(app: Flask, user_uuid: str, access_token: str) -> None:
    """
    Fire-and-forget function:
      1) read top artists via Spotify
      2) derive genre ranking
      3) store in user_tastes with retrieved_at
    """
    try:
        artists_items = _fetch_top_artists(access_token, time_range="medium_term", limit=50)
        artists_ordered = [a.get("name") for a in artists_items if a.get("name")] 
        genres_ranked = _rank_genres(artists_items)

        insert_tastes_snapshot(
            user_uuid=user_uuid,
            artists=artists_ordered,
            genres=genres_ranked,
            retrieved_at=time.time(),
        )
        try:
            app.logger.info("Stored tastes snapshot for user %s: %d artists, %d genres",
                            user_uuid, len(artists_ordered), len(genres_ranked))
        except Exception:
            pass
    except Exception as e:
        try:
            app.logger.exception("Tastes snapshot failed for %s: %s", user_uuid, e)
        except Exception:
            print(f"[tastes] snapshot failed for {user_uuid}: {e}")
