#!/usr/bin/env python3
import os
import sys
import csv
import argparse
from collections import Counter
from typing import List, Dict, Tuple

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = lambda: None  # graceful if dotenv not installed

try:
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth
except ImportError as e:
    print("Missing dependency. Install with: pip install spotipy python-dotenv", file=sys.stderr)
    raise

SCOPE = "user-top-read"

def authenticate() -> spotipy.Spotify:
    """Authenticate the current user and return a Spotipy client."""
    load_dotenv()  # loads .env if present

    client_id = os.getenv("SPOTIPY_CLIENT_ID")
    client_secret = os.getenv("SPOTIPY_CLIENT_SECRET")
    redirect_uri = os.getenv("SPOTIPY_REDIRECT_URI")

    if not all([client_id, client_secret, redirect_uri]):
        print(
            "Error: Missing environment variables. Please set SPOTIPY_CLIENT_ID, "
            "SPOTIPY_CLIENT_SECRET, and SPOTIPY_REDIRECT_URI (e.g., via a .env file).",
            file=sys.stderr,
        )
        sys.exit(1)

    auth_manager = SpotifyOAuth(
        scope=SCOPE,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        # Caches token to .cache to avoid re-auth every run:
        open_browser=True,
        show_dialog=False,
        cache_path=".cache"
    )
    return spotipy.Spotify(auth_manager=auth_manager)

def get_user_profile(sp: spotipy.Spotify) -> Dict:
    try:
        me = sp.current_user()
        return me
    except spotipy.exceptions.SpotifyException as e:
        print(f"Failed to fetch current user: {e}", file=sys.stderr)
        sys.exit(1)

def fetch_top_artists(
    sp: spotipy.Spotify,
    time_range: str = "medium_term",
    limit: int = 50
) -> List[Dict]:
    """
    time_range: 'short_term' (4 weeks), 'medium_term' (6 months), 'long_term' (years)
    limit: 1-50
    """
    if time_range not in {"short_term", "medium_term", "long_term"}:
        raise ValueError("time_range must be one of: short_term, medium_term, long_term")
    limit = max(1, min(50, limit))
    results = sp.current_user_top_artists(time_range=time_range, limit=limit)
    return results.get("items", [])

def summarize_artists(artists: List[Dict]) -> List[Tuple[int, str, int, List[str]]]:
    """
    Returns list of (rank, artist_name, followers, genres)
    """
    ranked = []
    for idx, a in enumerate(artists, start=1):
        name = a.get("name")
        followers = (a.get("followers") or {}).get("total") or 0
        genres = a.get("genres") or []
        ranked.append((idx, name, followers, genres))
    return ranked

def aggregate_genres(artists: List[Dict], top_n: int = 25) -> List[Tuple[str, int]]:
    """
    Collates genres from the artists list and returns top N (genre, count).
    """
    counter = Counter()
    for a in artists:
        for g in (a.get("genres") or []):
            # normalize: lower-case trim
            counter[g.strip().lower()] += 1
    return counter.most_common(top_n)

def maybe_write_csv(
    out_path: str,
    artists_ranked: List[Tuple[int, str, int, List[str]]],
    genres_ranked: List[Tuple[str, int]]
) -> None:
    base, ext = os.path.splitext(out_path)
    if not ext:
        # default to csv if no extension
        out_artists = base + "_artists.csv"
        out_genres = base + "_genres.csv"
    else:
        out_artists = base + "_artists" + ext
        out_genres = base + "_genres" + ext

    # artists CSV
    with open(out_artists, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["rank", "artist", "followers", "genres"])
        for rank, name, followers, genres in artists_ranked:
            writer.writerow([rank, name, followers, "; ".join(genres)])

    # genres CSV
    with open(out_genres, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["genre", "count"])
        for genre, count in genres_ranked:
            writer.writerow([genre, count])

    print(f"\nSaved CSVs:\n  {out_artists}\n  {out_genres}")

def gather_spotify_data(time_range, limit, top_genres):
    sp = authenticate()
    me = get_user_profile(sp)
    display_name = me.get("display_name") or me.get("id") or "Unknown User"

    print(f"\nAuthenticated as: {display_name}")
    print(f"Pulling Top Artists [time_range={time_range}, limit={limit}] ...", end="", flush=True)

    artists = fetch_top_artists(sp, time_range=time_range, limit=limit)
    print("done.")
    if not artists:
        print("No top artists found for this user/time range.")
        sys.exit(0)

    artists_ranked = summarize_artists(artists)
    genres_ranked = aggregate_genres(artists, top_n=top_genres)

    return display_name, artists_ranked, genres_ranked


def main():
    parser = argparse.ArgumentParser(
        description="Fetch a Spotify user's most-listened artists and genres."
    )
    parser.add_argument(
        "--time-range",
        default="medium_term",
        choices=["short_term", "medium_term", "long_term"],
        help="History window: short_term (~4 weeks), medium_term (~6 months), long_term (years).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Number of top artists to fetch (1-50). Default: 50",
    )
    parser.add_argument(
        "--top-genres",
        type=int,
        default=25,
        help="How many top genres to display. Default: 25",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="Optional base filename to save CSVs (e.g., results or results.csv).",
    )
    args = parser.parse_args()

    _, artists_ranked, genres_ranked = gather_spotify_data(
        time_range=args.time_range,
        limit=args.limit,
        top_genres=args.top_genres
    )

    # Print artists
    print("\n=== Top Artists ===")
    for rank, name, followers, genres in artists_ranked:
        followers_str = f"{followers:,}" if followers else "—"
        genres_str = ", ".join(genres) if genres else "—"
        print(f"{rank:>2}. {name}  | followers: {followers_str} | genres: {genres_str}")

    # Print genres
    print("\n=== Top Genres (from your Top Artists) ===")
    if genres_ranked:
        width = max(len(g) for g, _ in genres_ranked)
    else:
        width = 10
    for genre, count in genres_ranked:
        print(f"{genre.ljust(width)}  {count}")

    # Save CSVs if requested
    if args.out:
        maybe_write_csv(args.out, artists_ranked, genres_ranked)

if __name__ == "__main__":
    main()
