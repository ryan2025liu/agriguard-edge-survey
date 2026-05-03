"""
[INPUT]: API base URL, username/password or Bearer token.
[OUTPUT]: JWT string; list of mission dicts from GET /missions/my-active.
[POS]: Edge Survey CLI — password login + org active aerial missions (same auth as web).
[PROTOCOL]:
 1. POST /token with form fields username, password (OAuth2 password flow shape).
 2. GET /missions/my-active?mission_type=AERIAL_SURVEY with Authorization Bearer.
 3. Comments in English.
"""

from __future__ import annotations

from typing import Any, Dict, List

import requests


def _base(url: str) -> str:
    return (url or "").strip().rstrip("/")


def login_with_password(
    api_base_url: str,
    username: str,
    password: str,
    *,
    timeout: int = 60,
) -> str:
    """Return access_token (JWT) or raise RuntimeError."""
    url = f"{_base(api_base_url)}/token"
    r = requests.post(
        url,
        data={"username": username.strip(), "password": password},
        timeout=timeout,
    )
    if r.status_code != 200:
        raise RuntimeError(
            f"Login failed ({r.status_code}): {r.text[:800]}",
        )
    data = r.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError("Login response missing access_token")
    return str(token)


def list_my_active_aerial_missions(
    api_base_url: str,
    token: str,
    *,
    timeout: int = 60,
) -> List[Dict[str, Any]]:
    """Missions visible to the same rules as GET /missions/my-active (AERIAL_SURVEY only)."""
    url = f"{_base(api_base_url)}/missions/my-active"
    r = requests.get(
        url,
        params={"mission_type": "AERIAL_SURVEY"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    if r.status_code != 200:
        raise RuntimeError(
            f"missions/my-active failed ({r.status_code}): {r.text[:800]}",
        )
    body = r.json()
    if not isinstance(body, list):
        raise RuntimeError("Unexpected missions response shape")
    return body
