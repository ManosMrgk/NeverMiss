from dataclasses import dataclass
from typing import Optional
from flask import session


# ---- Simple token store (in session for demo) ----
@dataclass
class TokenBundle:
    access_token: str
    refresh_token: Optional[str]
    expires_at: float  # epoch seconds

def set_tokens(tb: TokenBundle) -> None:
    session["spotify"] = {
        "access_token": tb.access_token,
        "refresh_token": tb.refresh_token,
        "expires_at": tb.expires_at,
    }

def get_tokens() -> Optional[TokenBundle]:
    data = session.get("spotify")
    if not data:
        return None
    return TokenBundle(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token"),
        expires_at=float(data["expires_at"]),
    )

def clear_tokens():
    session.pop("spotify", None)