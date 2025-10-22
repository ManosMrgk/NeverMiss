from dataclasses import asdict
from typing import List
from models.events import Event
import json
# ========== Prompting helpers ==========

def build_system_prompt() -> str:
    return (
        "You are an event-recommendation assistant. Select ONLY from the provided events.\n"
        "Return a RAW JSON array (no prose, no markdown fences) of Event objects with EXACT fields:\n"
        "title, url, start_date, venue, city, region, image.\n"
        "Do not invent or modify details. If nothing matches, return []."
    )


def build_user_prompt(spotify_favorites: dict, upcoming_events: List[Event]) -> str:
    """
    Provide Spotify tastes + upcoming events. Matching heuristic:
    - Prefer titles containing favorite artists
    - Secondarily, titles or known acts that align with favorite genres
    - Avoid low-confidence guesses
    """
    payload = {
        "spotify_tastes": spotify_favorites,
        "upcoming_events": [asdict(e) for e in upcoming_events],
        "instructions": {
            "matching_rules": [
                "Prefer events whose title contains a favorite artist name (case-insensitive).",
                "Secondarily, match by genre relevance if artist not present.",
                "If an artist is not explicitly named but someone with similar sound and vibe is, you may include it.",
                "Avoid guessing or low-confidence matches.",
                "If unsure, omit the event.",
                "Both artists and genres are ordered by most-favorite first.",
            ],
            "output_schema": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["title", "url", "start_date", "venue", "city", "region", "image"],
                    "properties": {
                        "title": {"type": "string"},
                        "url": {"type": "string", "format": "uri"},
                        "start_date": {"type": "string", "description": "ISO 8601 date or datetime"},
                        "venue": {"type": "string", "nullable": True},
                        "city": {"type": "string", "nullable": True},
                        "region": {"type": "string", "nullable": True},
                        "image": {"type": "string", "format": "uri", "nullable": True},
                    },
                },
            },
        },
    }
    prefix = (
        "Select relevant events for the user based on Spotify favorites. "
        "Return ONLY a JSON array with the exact Event fields."
    )
    return prefix + "\n\n" + json.dumps(payload, ensure_ascii=False, indent=2)

