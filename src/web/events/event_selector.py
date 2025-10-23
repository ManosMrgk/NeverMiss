from __future__ import annotations
import os
import json
from dataclasses import asdict
from typing import Optional, List
from dotenv import load_dotenv
from events.spotify_data import gather_spotify_data
from events.event_gatherer import scrape_more
from models.events import Event
from events.event_utils.gemini import call_gemini
from events.event_utils.prompting import build_system_prompt, build_user_prompt


def get_upcoming_events(start_date: Optional[str], days: int, location_code: Optional[str] = None) -> List[Event]:
    events = scrape_more(
        location_only=True,
        start_date_str=start_date, days=days,
        headful=False, engine="firefox",
        max_location_reloads=1,
        debug=True,
        use_fast_mode=True,
        location_code=location_code,
    )

    # for e in events:
    #     print(e)

    return events

def get_spotify_favorites() -> dict:
    _, artists_ranked, genres_ranked = gather_spotify_data(time_range="long_term", limit=50, top_genres=25)
    artists = [name for _, name, _, _ in artists_ranked]
    genres = [genre for genre, _ in genres_ranked]
    # print(f"Top artists: {artists}")
    # print(f"Top genres: {genres}")
    return {
        "favorite_artists": artists,
        "favorite_genres": genres,
    }

# ========== Entry point ==========
def get_recommended_events(start_date: Optional[str] = None, days: int = 7, events: Optional[List[Event]] = None, spotify_data: Optional[dict[str, list[str]]] = None) -> List[Event]:
    load_dotenv()  # loads GOOGLE_API_KEY from .env
    api_key = os.getenv("GOOGLE_API_KEY")
    model_name = os.getenv("GOOGLE_MODEL_NAME") or "gemini-2.5-flash" #"gemini-2.0-flash-exp"
    system_prompt = build_system_prompt()

    if events:
        upcoming = events
    else:
        upcoming = get_upcoming_events(start_date=start_date, days=days)
    if spotify_data:
        spotify = spotify_data
    else:
        spotify = get_spotify_favorites()

    user_prompt = build_user_prompt(spotify, upcoming)
    print("Calling Gemini for event selection...", end="", flush=True)
    selected = call_gemini(api_key, system_prompt, user_prompt, model_name=model_name)
    print("done.")

    return selected

def main():
    selected = get_recommended_events(start_date=None, days=7)

    # Print a clean JSON array of Event dataclasses
    print(json.dumps([asdict(e) for e in selected], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
