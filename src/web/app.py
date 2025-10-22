from __future__ import annotations

import base64
from datetime import date, datetime
import hashlib
import os
import secrets
import string
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple
import logging, sys
import requests
from dotenv import find_dotenv, load_dotenv
from flask import Flask, redirect, render_template, request, session, url_for, jsonify, abort
from jobs.scheduler import _start_scheduler
from utils.background import submit_background
from utils.session_utils import TokenBundle, clear_tokens, get_tokens, set_tokens
from utils.settings import CLIENT_ID, CLIENT_SECRET, FLASK_SECRET, FREQ_VALUES, REDIRECT_URI, SCOPES, SPOTIFY_API_BASE, SPOTIFY_AUTH_URL, SPOTIFY_TOKEN_URL
from utils.callback import callback
from utils.location_utils import LABEL_BY_VALUE, LOCATION_CHOICES, LOCATION_VALUES
from utils.db_utils import DB_PATH, delete_user_by_uuid, get_latest_user_suggested_events_list, init_db, get_user_by_uuid, update_preferences
from utils.tastes import fetch_and_store_tastes
from events.event_utils.time_utils import local_tz
from models.events import Event
from utils.suggestion_utils import _bucket_events, _fmt_event_date

try:
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("Europe/Athens")
except Exception:
    from datetime import timezone, timedelta
    LOCAL_TZ = timezone(timedelta(hours=3))

logging.basicConfig(
    level=logging.INFO,  # or DEBUG
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.getLogger("apscheduler").setLevel(logging.INFO)
# ---- Flask ----
app = Flask(__name__, template_folder="templates")
app.secret_key = FLASK_SECRET

# Ensure the SQLite schema exists at startup
try:
    init_db()
    app.logger.info("SQLite ready at %s", DB_PATH)
except Exception as e:
    app.logger.exception("Failed to initialize DB: %s", e)


# ---- PKCE helpers ----
def _urlsafe_b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")

def make_pkce_pair() -> Tuple[str, str]:
    """Return (code_verifier, code_challenge)."""
    # 43..128 chars from [A-Z,a-z,0-9,-._~]
    allowed = string.ascii_letters + string.digits + "-._~"
    code_verifier = "".join(secrets.choice(allowed) for _ in range(64))
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    code_challenge = _urlsafe_b64(digest)
    return code_verifier, code_challenge


# ---- Token refresh (PKCE flow can still give refresh_token) ----
def ensure_fresh_access_token() -> Optional[str]:
    tb = get_tokens()
    if not tb:
        return None
    if time.time() < tb.expires_at - 30:
        return tb.access_token  # still valid

    if not tb.refresh_token:
        # No refresh token; force re-auth
        clear_tokens()
        return None

    payload = {
        "grant_type": "refresh_token",
        "refresh_token": tb.refresh_token,
        "client_id": CLIENT_ID,
    }
    # If you are using confidential flow (no PKCE), include client_secret
    if CLIENT_SECRET:
        payload["client_secret"] = CLIENT_SECRET

    r = requests.post(SPOTIFY_TOKEN_URL, data=payload, timeout=20)
    if r.status_code != 200:
        clear_tokens()
        return None
    tok = r.json()
    new_access = tok["access_token"]
    expires_in = tok.get("expires_in", 3600)
    new_refresh = tok.get("refresh_token", tb.refresh_token)  # may rotate

    set_tokens(TokenBundle(new_access, new_refresh, time.time() + expires_in))
    return new_access


def _current_settings():
    """Return settings dict from session or None."""
    s = session.get("settings")
    return s if isinstance(s, dict) else None

@app.context_processor
def inject_now():
    now = datetime.now(LOCAL_TZ)
    return {
        "current_year": now.year,
        "today": now,
    }

# ---- Routes ----
@app.get("/")
def index():
    if session.get("spotify"):
        token = ensure_fresh_access_token()
        if not token:
            return render_template("index.html")

        me = requests.get(
            f"{SPOTIFY_API_BASE}/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
        )
        profile = me.json() if me.status_code == 200 else {}
        # Load settings from DB if we have a user_uuid
        user_uuid = session.get("user_uuid")
        row = get_user_by_uuid(user_uuid) if user_uuid else None

        settings = None
        default_email = ""
        email_editable = True

        if row:
            settings = {
                "email": row["email"],
                "location_label": row["location_label"],
                "location_value": row["location_value"],
                "frequency": row["frequency"],
            }
            # if DB already has an email, do not allow editing
            if row["email"]:
                email_editable = False
            else:
                # fallback to Spotify email for prefill, still editable
                default_email = (profile.get("email") or "").strip() if isinstance(profile, dict) else ""
        else:
            default_email = (profile.get("email") or "").strip() if isinstance(profile, dict) else ""

        return render_template(
            "authed.html",
            profile=profile,
            settings=settings,
            locations=LOCATION_CHOICES,
            default_email=default_email,
            email_editable=email_editable,  
        )
    return render_template("index.html")



@app.get("/auth/spotify")
def auth_spotify():
    if not CLIENT_ID:
        return "Missing SPOTIFY_CLIENT_ID", 500

    # PKCE
    code_verifier, code_challenge = make_pkce_pair()
    session["pkce"] = {"verifier": code_verifier}

    # CSRF state
    state = secrets.token_urlsafe(24)
    session["oauth_state"] = state

    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(SCOPES),
        "state": state,
        "code_challenge_method": "S256",
        "code_challenge": code_challenge,
        "show_dialog": "false",
    }
    # Build the URL manually
    from urllib.parse import urlencode
    url = f"{SPOTIFY_AUTH_URL}?{urlencode(params)}"
    return redirect(url)


@app.get("/callback")
def spotify_callback():
    # CSRF check
    expected_state = session.get("oauth_state")
    got_state = request.args.get("state")
    if not expected_state or got_state != expected_state:
        return "Invalid state", 400

    code = request.args.get("code")
    if not code:
        return "Missing authorization code", 400

    verifier = (session.get("pkce") or {}).get("verifier")
    if not verifier:
        return "Missing PKCE verifier", 400

    return callback(app, code, verifier)
    



@app.get("/logout")
def logout():
    clear_tokens()
    return redirect(url_for("index"))


# --- Debug endpoints (you can remove these later) ---

@app.get("/me/top")
def me_top():
    """Quick sanity route to prove we can read top artists/genres."""
    token = ensure_fresh_access_token()
    if not token:
        return redirect(url_for("index"))

    # top artists
    r_art = requests.get(
        f"{SPOTIFY_API_BASE}/me/top/artists?time_range=medium_term&limit=10",
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    # top tracks genres can be inferred or you can collapse artists' genres
    data = {
        "top_artists": r_art.json() if r_art.status_code == 200 else {"error": r_art.text},
    }
    return jsonify(data)


@app.post("/save_info/")
def save_info():
    if not session.get("spotify"):
        return redirect(url_for("index"))

    user_uuid = session.get("user_uuid")
    row = get_user_by_uuid(user_uuid) if user_uuid else None
    if not row:
        return redirect(url_for("index"))

    # Read payload
    email = (request.form.get("email") or "").strip()
    location_value = (request.form.get("location") or "").strip()
    frequency = (request.form.get("frequency") or "").strip().lower()

    # If DB already has email OR Spotify gave us email at upsert time, email is not editable
    email_already_set = bool(row["email"])

    # Validate
    errors = []
    if location_value and location_value not in LOCATION_VALUES:
        errors.append("Invalid location selection.")

    if not email_already_set:
        # Email is required when we don't have one yet
        if not email:
            errors.append("Email is required.")
    else:
        # Ignore incoming email if already set
        email = None

    # Frequency required if we don't have one yet or if user submitted something invalid
    if frequency not in FREQ_VALUES:
        if not row["frequency"]:
            errors.append("Frequency is required.")
        else:
            # keep existing frequency if invalid or empty submitted
            frequency = row["frequency"]

    if errors:
        # Redirect with an error marker (or render template with errors if you prefer)
        app.logger.warning("save_info validation errors: %s", errors)
        return redirect(url_for("index"))

    # Resolve label
    location_label = LABEL_BY_VALUE.get(location_value) if location_value else row["location_label"]

    # Update DB
    update_preferences(
        user_uuid=user_uuid,
        email=email,  # will be ignored in DB if it already exists
        location_label=location_label,
        location_value=location_value or row["location_value"],
        frequency=frequency or row["frequency"],
    )

    row = get_user_by_uuid(user_uuid)

    token = ensure_fresh_access_token()
    if token:
        try:
            # Background refresh of tastes with fresh token
            submit_background(fetch_and_store_tastes, app, user_uuid, token)
        except Exception as e:
            app.logger.exception("Failed to refresh taste on save: %s", e)
        return redirect(url_for("index", saved=1))
    else:
        # queue a redirect to finish the taste refresh after login
        session["after_login_redirect"] = url_for("post_save_refresh")
        return redirect(url_for("auth_spotify"))

@app.get("/post_save_refresh")
def post_save_refresh():
    """Runs right after OAuth if we saved settings without a valid token."""
    token = ensure_fresh_access_token()
    if not token:
        # still no token → go get one
        session["after_login_redirect"] = url_for("post_save_refresh")
        return redirect(url_for("auth_spotify"))
    user_uuid = session.get("user_uuid")
    try:
        # Background refresh of tastes with fresh token
        submit_background(fetch_and_store_tastes, app, user_uuid, token)
    except Exception as e:
        app.logger.exception("Failed to refresh taste post-save: %s", e)

    session.pop("after_login_redirect", None)
    return redirect(url_for("index", saved=1))

@app.get("/refresh_taste")
def refresh_taste():
    user_uuid = session.get("user_uuid")
    token = ensure_fresh_access_token()
    if token and user_uuid:
        try:
            # Background refresh of tastes with fresh token
            submit_background(fetch_and_store_tastes, app, user_uuid, token)
        except Exception as e:
            app.logger.exception("Failed to refresh taste on save: %s", e)
        return redirect(url_for("index", saved=1))
    else:
        # queue a redirect to finish the taste refresh after login
        session["after_login_redirect"] = url_for("post_save_refresh")
        return redirect(url_for("auth_spotify"))

@app.get("/suggestions/<user_uuid>")
def suggestions(user_uuid: str):
    row = get_user_by_uuid(user_uuid)
    if not row:
        return abort(404)

    start_param = request.args.get("start")
    if start_param:
        try:
            today = date.fromisoformat(start_param)
        except ValueError:
            today = datetime.now(local_tz()).date()
    else:
        today = datetime.now(local_tz()).date()

    events: List[Event] = get_latest_user_suggested_events_list(user_uuid)
    print(f"Loaded {len(events)} suggested events for user {user_uuid}")
    buckets = _bucket_events(events, today=today)

    user_name = row["display_name"] or row["spotify_id"]
    today_str = today.strftime("%A, %d %B %Y")

    return render_template(
        "suggestions.html",
        user=row,
        user_name=user_name,
        today_str=today_str,
        weekday=today.weekday(),
        buckets=buckets,
        fmt_event_date=_fmt_event_date,
    )

@app.get("/unsubscribe")
def unsubscribe():
    # If we know who they are, remove them
    user_uuid = session.get("user_uuid")
    if user_uuid:
        try:
            delete_user_by_uuid(user_uuid)
        except Exception as e:
            app.logger.exception("Failed to delete user %s: %s", user_uuid, e)

    # Clear session auth + any saved settings
    clear_tokens()
    session.pop("user_uuid", None)
    session.pop("settings", None)

    # Show a simple success message on the homepage
    return redirect(url_for("index", unsubscribed=1))

@app.errorhandler(404)
def not_found(e):
    return render_template("404.html", path=request.path), 404


if __name__ == "__main__":
    # Run with:  FLASK_APP=app.py flask run  (or)  python app.py
    HOST = os.getenv("HOST", "127.0.0.1")   # bind all interfaces by default
    PORT = int(os.getenv("PORT", "8080")) # default to 8080
    _start_scheduler(app)
    app.run(host=HOST, port=PORT, debug=False)
