from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def load_service_account_info(
    *,
    api_sheets_google_key: str | None,
    google_service_account_json: str | None,
) -> dict[str, Any]:
    if api_sheets_google_key:
        raw = api_sheets_google_key.strip()
        if raw.startswith("{"):
            return json.loads(raw)
        path = Path(raw)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return json.loads(raw)

    if google_service_account_json:
        path = Path(google_service_account_json)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        # allow inline JSON in the path env as well
        if google_service_account_json.strip().startswith("{"):
            return json.loads(google_service_account_json)

    raise ValueError(
        "Missing Google credentials: set API_SHEETS_GOOGLE_KEY or GOOGLE_SERVICE_ACCOUNT_JSON"
    )


def build_credentials(
    *,
    api_sheets_google_key: str | None,
    google_service_account_json: str | None,
) -> Credentials:
    info = load_service_account_info(
        api_sheets_google_key=api_sheets_google_key,
        google_service_account_json=google_service_account_json,
    )
    return Credentials.from_service_account_info(info, scopes=SCOPES)
