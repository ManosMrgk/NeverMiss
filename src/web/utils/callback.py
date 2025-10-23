import time
import requests
from utils.background import submit_background
from utils.tastes import fetch_and_store_tastes
from utils.settings import CLIENT_ID, INVITE_FORM_URL, REDIRECT_URI, SPOTIFY_API_BASE, SPOTIFY_TOKEN_URL
from utils.session_utils import TokenBundle, clear_tokens, set_tokens
from flask import redirect, render_template, session, url_for, Flask

def _allowlist_block(resp) -> bool:
    """Return True if Spotify indicates the user isn't allowed in dev mode."""
    if not resp is None:
        if resp.status_code == 403:
            return True
        try:
            txt = resp.text or ""
            low = txt.lower()
            return ("not registered" in low and "developer" in low) or ("restricted" in low and "client" in low)
        except Exception:
            pass
    return False

def callback(app: Flask, code, verifier):
    """Callback to handle post-authentication logic."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "code_verifier": verifier,
    }
    r = requests.post(SPOTIFY_TOKEN_URL, data=data, timeout=20)
    if r.status_code != 200:
        session.pop("pkce", None)
        session.pop("oauth_state", None)
        return f"Token exchange failed: {r.text}", 400

    tok = r.json()
    access = tok["access_token"]
    refresh = tok.get("refresh_token")
    expires_in = tok.get("expires_in", 3600)

    set_tokens(TokenBundle(access, refresh, time.time() + expires_in))

    me = requests.get(
        f"{SPOTIFY_API_BASE}/me",
        headers={"Authorization": f"Bearer {access}"},
        timeout=20,
    )
    if me.status_code != 200:
        session.pop("pkce", None)
        session.pop("oauth_state", None)
        if _allowlist_block(me):
            session.pop("pkce", None)
            session.pop("oauth_state", None)
            clear_tokens()
            
            return render_template(
                "invite_only.html",
                form_url=INVITE_FORM_URL,
                desired_url=url_for("invite_only_page"),
            ), 400

        return f"Failed to fetch profile: {me.text}", 400

    profile = me.json() or {}
    spotify_id = profile.get("id")
    if not spotify_id:
        session.pop("pkce", None)
        session.pop("oauth_state", None)
        return "Profile missing 'id'", 400

    try:
        from utils.db_utils import (
            get_user_by_spotify_id,
            upsert_user,                   
            update_tokens_for_spotify_id, 
        )

        row = get_user_by_spotify_id(spotify_id)
        if row is None:
            user_uuid = upsert_user(
                spotify_id=spotify_id,
                display_name=profile.get("display_name"),
                country=profile.get("country"),
                email=profile.get("email") or None,
                access_token=access,
                refresh_token=refresh,
                token_expires_at=time.time() + expires_in,
                default_frequency="weekly",
            )
        else:
            update_tokens_for_spotify_id(
                spotify_id=spotify_id,
                access_token=access,
                refresh_token=refresh,
                token_expires_at=time.time() + expires_in,
            )
            user_uuid = row["uuid"]

        session["user_uuid"] = user_uuid

        submit_background(fetch_and_store_tastes, app, user_uuid, access)

    except Exception as e:
        app.logger.warning("User save/refresh failed: %s", e)

    session.pop("pkce", None)
    session.pop("oauth_state", None)

    return redirect(url_for("index"))