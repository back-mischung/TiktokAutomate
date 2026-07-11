from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from typing import Any

import requests

from config import require_env, settings
from token_store import TokenStore


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OAuthSession:
    state: str
    code_verifier: str
    started_at: int


def create_code_verifier() -> str:
    return secrets.token_urlsafe(64)[:128]


def create_code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


def build_login_url(session: OAuthSession) -> str:
    require_env(settings.client_key, "TIKTOK_CLIENT_KEY")
    require_env(settings.client_secret, "TIKTOK_CLIENT_SECRET")
    require_env(settings.redirect_uri, "TIKTOK_REDIRECT_URI")
    params = {
        "client_key": settings.client_key,
        "scope": settings.scopes,
        "response_type": "code",
        "redirect_uri": settings.redirect_uri,
        "state": session.state,
        "code_challenge": create_code_challenge(session.code_verifier),
        "code_challenge_method": "S256",
    }
    return f"{settings.authorize_url}?{urllib.parse.urlencode(params)}"


def run_manual_oauth(open_browser: bool = True) -> None:
    session = OAuthSession(
        state=secrets.token_urlsafe(24),
        code_verifier=create_code_verifier(),
        started_at=int(time.time()),
    )
    login_url = build_login_url(session)
    print("\nTikTok Login-Link:")
    print(login_url)
    print("\nRedirect URI:")
    print(settings.redirect_uri)
    print("\nNach dem Login landest du auf deiner Vercel-Callback-Seite.")
    print("Kopiere dort den Authorization Code und fuege ihn hier ein.\n")
    if open_browser:
        webbrowser.open(login_url)
    code = input("Kopiere den Authorization Code von der Vercel-Callback-Seite hier hinein: ").strip()
    if not code:
        raise RuntimeError("Kein Authorization Code eingegeben. Auth abgebrochen.")
    token_data = exchange_code_for_token(code, session.code_verifier)
    token = TokenStore.from_tiktok_response(token_data)
    TokenStore(settings.token_file).save(token)
    print(f"\nToken gespeichert in: {settings.token_file}")
    print(f"Scope: {token.scope or '(nicht angegeben)'}")
    print("Du kannst jetzt Videos mit `python main.py upload --file ...` hochladen.")


def exchange_code_for_token(code: str, code_verifier: str) -> dict[str, Any]:
    require_env(settings.client_key, "TIKTOK_CLIENT_KEY")
    require_env(settings.client_secret, "TIKTOK_CLIENT_SECRET")
    require_env(settings.redirect_uri, "TIKTOK_REDIRECT_URI")
    # TODO: verify with current TikTok docs if PKCE code_verifier is required for every app type.
    response = requests.post(
        settings.token_url,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Cache-Control": "no-cache"},
        data={
            "client_key": settings.client_key,
            "client_secret": settings.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": settings.redirect_uri,
            "code_verifier": code_verifier,
        },
        timeout=30,
    )
    if not response.ok:
        raise RuntimeError(f"Token-Austausch fehlgeschlagen: HTTP {response.status_code} {response.text}")
    data = response.json()
    if "access_token" not in data:
        raise RuntimeError(f"Unerwartete Token-Response: {data}")
    return data
