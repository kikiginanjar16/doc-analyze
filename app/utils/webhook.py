from __future__ import annotations

import time
from typing import Any, Optional

import httpx

from .config import (
    WEBHOOK_MAX_RETRIES,
    WEBHOOK_RETRY_BACKOFF_SECONDS,
    WEBHOOK_TIMEOUT_SECONDS,
)


def deliver_webhook(
    webhook_url: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    last_error: Optional[str] = None

    for attempt in range(1, WEBHOOK_MAX_RETRIES + 1):
        try:
            response = httpx.post(
                webhook_url,
                json=payload,
                timeout=WEBHOOK_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return {
                "status": "delivered",
                "attempts": attempt,
                "last_error": None,
                "status_code": response.status_code,
            }
        except Exception as e:
            last_error = str(e)
            if attempt < WEBHOOK_MAX_RETRIES:
                time.sleep(max(WEBHOOK_RETRY_BACKOFF_SECONDS, 0))

    return {
        "status": "failed",
        "attempts": WEBHOOK_MAX_RETRIES,
        "last_error": last_error,
        "status_code": None,
    }
