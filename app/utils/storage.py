from __future__ import annotations

import json
import traceback
import uuid
from typing import Any, Optional

try:
    import psycopg
except ImportError:
    psycopg = None

from .config import DATABASE_URL

_storage_ready = False


def is_storage_enabled() -> bool:
    return _storage_ready


def init_db() -> None:
    global _storage_ready
    if not DATABASE_URL or psycopg is None:
        _storage_ready = False
        return

    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS analysis_runs (
                        id UUID PRIMARY KEY,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        source_type TEXT NOT NULL,
                        source_name TEXT NOT NULL,
                        source_url TEXT NULL,
                        detected_type TEXT NULL,
                        used_vision BOOLEAN NOT NULL DEFAULT FALSE,
                        max_pages INTEGER NOT NULL,
                        max_slides INTEGER NOT NULL,
                        markdown TEXT NOT NULL,
                        meta_json JSONB NOT NULL,
                        webhook_url TEXT NULL,
                        webhook_status TEXT NOT NULL DEFAULT 'not_requested',
                        webhook_attempts INTEGER NOT NULL DEFAULT 0,
                        last_webhook_error TEXT NULL,
                        last_webhook_at TIMESTAMPTZ NULL
                    )
                    """
                )
            conn.commit()
        _storage_ready = True
    except Exception:
        _storage_ready = False
        traceback.print_exc()


def create_analysis_run(
    *,
    source_type: str,
    source_name: str,
    source_url: Optional[str],
    markdown: str,
    meta: dict[str, Any],
    max_pages: int,
    max_slides: int,
    webhook_url: Optional[str],
) -> Optional[str]:
    if not _storage_ready or psycopg is None:
        return None

    run_id = str(uuid.uuid4())
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO analysis_runs (
                    id,
                    source_type,
                    source_name,
                    source_url,
                    detected_type,
                    used_vision,
                    max_pages,
                    max_slides,
                    markdown,
                    meta_json,
                    webhook_url,
                    webhook_status
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s
                )
                """,
                (
                    run_id,
                    source_type,
                    source_name,
                    source_url,
                    meta.get("detected_type"),
                    bool(meta.get("used_vision")),
                    max_pages,
                    max_slides,
                    markdown,
                    json.dumps(meta),
                    webhook_url,
                    "pending" if webhook_url else "not_requested",
                ),
            )
        conn.commit()
    return run_id


def update_webhook_status(
    run_id: str,
    *,
    status: str,
    attempts: int,
    error: Optional[str],
) -> None:
    if not _storage_ready or psycopg is None or not run_id:
        return

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE analysis_runs
                SET webhook_status = %s,
                    webhook_attempts = %s,
                    last_webhook_error = %s,
                    last_webhook_at = NOW()
                WHERE id = %s
                """,
                (status, attempts, error, run_id),
            )
        conn.commit()


def get_analysis_run(run_id: str) -> Optional[dict[str, Any]]:
    if not _storage_ready or psycopg is None:
        return None

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    created_at,
                    source_type,
                    source_name,
                    source_url,
                    detected_type,
                    used_vision,
                    max_pages,
                    max_slides,
                    markdown,
                    meta_json,
                    webhook_url,
                    webhook_status,
                    webhook_attempts,
                    last_webhook_error,
                    last_webhook_at
                FROM analysis_runs
                WHERE id = %s
                """,
                (run_id,),
            )
            row = cur.fetchone()

    if not row:
        return None

    return {
        "id": str(row[0]),
        "created_at": row[1].isoformat() if row[1] else None,
        "source_type": row[2],
        "source_name": row[3],
        "source_url": row[4],
        "detected_type": row[5],
        "used_vision": row[6],
        "max_pages": row[7],
        "max_slides": row[8],
        "markdown": row[9],
        "meta": row[10],
        "webhook_url": row[11],
        "webhook_status": row[12],
        "webhook_attempts": row[13],
        "last_webhook_error": row[14],
        "last_webhook_at": row[15].isoformat() if row[15] else None,
    }
