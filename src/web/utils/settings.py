import os
import secrets
from dotenv import find_dotenv, load_dotenv


load_dotenv(find_dotenv(filename=".env", usecwd=True))  # loads from ./web/.env (run app from this folder)

# ---- Config ----
SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"

CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID") or ""
CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET", "")  # unused when PKCE-only
REDIRECT_URI = os.getenv("SPOTIPY_REDIRECT_URI") or "http://localhost:5000/auth/spotify/callback"
FLASK_SECRET = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(16)

FREQ_VALUES = {"weekly", "biweekly", "monthly"}

SCOPES = [
    "user-top-read",           # to read favorite artists/genres
    "user-read-email",       # uncomment later when you want email
    # add more scopes as needed
]

INVITE_FORM_URL = os.getenv("INVITE_FORM_URL", "")