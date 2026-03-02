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
                        application TEXT NULL,
                        reference_id TEXT NULL,
                        document_id TEXT NULL,
                        user_prompt TEXT NULL,
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
                cur.execute("ALTER TABLE analysis_runs ADD COLUMN IF NOT EXISTS application TEXT NULL")
                cur.execute("ALTER TABLE analysis_runs ADD COLUMN IF NOT EXISTS reference_id TEXT NULL")
                cur.execute("ALTER TABLE analysis_runs ADD COLUMN IF NOT EXISTS document_id TEXT NULL")
                cur.execute("ALTER TABLE analysis_runs ADD COLUMN IF NOT EXISTS user_prompt TEXT NULL")
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS analysis_chunks (
                        id BIGSERIAL PRIMARY KEY,
                        run_id UUID NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
                        chunk_index INTEGER NOT NULL,
                        content TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        UNIQUE (run_id, chunk_index)
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
    application: Optional[str],
    reference_id: Optional[str],
    document_id: Optional[str],
    user_prompt: Optional[str],
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
                    application,
                    reference_id,
                    document_id,
                    user_prompt,
                    detected_type,
                    used_vision,
                    max_pages,
                    max_slides,
                    markdown,
                    meta_json,
                    webhook_url,
                    webhook_status
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s
                )
                """,
                (
                    run_id,
                    source_type,
                    source_name,
                    source_url,
                    application,
                    reference_id,
                    document_id,
                    user_prompt,
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


def store_analysis_chunks(run_id: str, chunks: list[str]) -> None:
    if not _storage_ready or psycopg is None or not run_id or not chunks:
        return

    normalized_chunks = [chunk.strip() for chunk in chunks if chunk and chunk.strip()]
    if not normalized_chunks:
        return

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM analysis_chunks WHERE run_id = %s", (run_id,))
            cur.executemany(
                """
                INSERT INTO analysis_chunks (
                    run_id,
                    chunk_index,
                    content
                ) VALUES (%s, %s, %s)
                """,
                [
                    (run_id, index, chunk)
                    for index, chunk in enumerate(normalized_chunks, start=1)
                ],
            )
        conn.commit()


def get_analysis_chunks(run_id: str) -> list[dict[str, Any]]:
    if not _storage_ready or psycopg is None or not run_id:
        return []

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    chunk_index,
                    content
                FROM analysis_chunks
                WHERE run_id = %s
                ORDER BY chunk_index ASC
                """,
                (run_id,),
            )
            rows = cur.fetchall()

    return [
        {
            "source_chunk": row[0],
            "content": row[1],
        }
        for row in rows
    ]


def get_chunks_by_reference_id(
    reference_id: str,
    *,
    application: Optional[str] = None,
    document_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    if not _storage_ready or psycopg is None or not reference_id:
        return []

    query = """
        SELECT
            ar.id,
            ar.application,
            ar.reference_id,
            ar.document_id,
            ar.source_name,
            ac.chunk_index,
            ac.content
        FROM analysis_chunks ac
        INNER JOIN analysis_runs ar
            ON ar.id = ac.run_id
        WHERE ar.reference_id = %s
    """
    params: list[Any] = [reference_id]

    if application:
        query += " AND ar.application = %s"
        params.append(application)

    if document_id:
        query += " AND ar.document_id = %s"
        params.append(document_id)

    query += " ORDER BY ar.created_at DESC, ac.chunk_index ASC"

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(query, tuple(params))
            rows = cur.fetchall()

    return [
        {
            "analysis_id": str(row[0]),
            "application": row[1],
            "reference_id": row[2],
            "document_id": row[3],
            "source_name": row[4],
            "source_chunk": row[5],
            "content": row[6],
        }
        for row in rows
    ]


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
                    application,
                    reference_id,
                    document_id,
                    user_prompt,
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
        "application": row[5],
        "reference_id": row[6],
        "document_id": row[7],
        "prompt": row[8],
        "detected_type": row[9],
        "used_vision": row[10],
        "max_pages": row[11],
        "max_slides": row[12],
        "markdown": row[13],
        "meta": row[14],
        "webhook_url": row[15],
        "webhook_status": row[16],
        "webhook_attempts": row[17],
        "last_webhook_error": row[18],
        "last_webhook_at": row[19].isoformat() if row[19] else None,
    }
