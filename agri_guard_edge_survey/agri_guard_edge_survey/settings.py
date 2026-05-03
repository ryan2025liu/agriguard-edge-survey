"""
[INPUT]: Environment variables and optional `.env` (python-dotenv).
[OUTPUT]: `EdgeSurveySettings` dataclass.
[POS]: Local configuration for Edge Survey CLI (sync phase uses API URL/token).
[PROTOCOL]:
 1. Never embed secrets in code; keep tokens in env only.
 2. API base URL: `SURVEY_API_BASE_URL` first, then `AGRI_GUARD_API_BASE_URL` (monorepo shared dev).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None  # type: ignore

_API_BASE_KEYS = ("SURVEY_API_BASE_URL", "AGRI_GUARD_API_BASE_URL")


def _ensure_dotenv_loaded() -> None:
    if load_dotenv is not None:
        load_dotenv()


def resolve_api_base_url() -> str:
    """Backend API root (no trailing slash). Reads .env via load_dotenv."""
    _ensure_dotenv_loaded()
    for key in _API_BASE_KEYS:
        v = os.getenv(key, "").strip().rstrip("/")
        if v:
            return v
    return ""


@dataclass
class EdgeSurveySettings:
    api_base_url: str
    api_token: str


def load_settings() -> EdgeSurveySettings:
    _ensure_dotenv_loaded()
    return EdgeSurveySettings(
        api_base_url=resolve_api_base_url(),
        api_token=os.getenv("SURVEY_API_TOKEN", "").strip(),
    )
