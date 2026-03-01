from __future__ import annotations

import traceback
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, Query, Body, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .utils.config import MAX_PAGES_DEFAULT, MAX_SLIDES_DEFAULT
from .utils.fetch import download_file
from .utils.detect import detect_type, guess_mime_from_filename
from .utils.extractors import (
    extract_txt_md,
    extract_docx,
    extract_pptx,
    extract_pdf_text_or_vision,
    ExtractResult,
)
from .utils.openai_client import summarize_text_markdown
from .utils.config import OPENAI_MODEL_TEXT, OPENAI_MODEL_VISION
from .utils.storage import (
    create_analysis_run,
    get_analysis_run,
    init_db,
    is_storage_enabled,
    update_webhook_status,
)
from .utils.webhook import deliver_webhook

PROMPTS_DIR = Path(__file__).parent / "prompts"

app = FastAPI(
    title="Doc Analyzer (Summary-only) v1",
    version="1.0.0",
    description="Analyze image/pdf/docx/pptx/txt/md and return a single Markdown summary.",
)

def _read_prompt(name: str) -> str:
    p = PROMPTS_DIR / name
    return p.read_text(encoding="utf-8")

SUMMARY_SYSTEM = _read_prompt("summary_system.txt")
VISION_PAGE_SYSTEM = _read_prompt("vision_page_system.txt")


class AnalyzeUrlPayload(BaseModel):
    file_url: str
    filename: Optional[str] = None
    webhook_url: Optional[str] = None


@app.on_event("startup")
def startup() -> None:
    init_db()

@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "models": {"text": OPENAI_MODEL_TEXT, "vision": OPENAI_MODEL_VISION},
        "storage": {"enabled": is_storage_enabled()},
    }

def _analyze_bytes(
    data: bytes,
    filename: str,
    content_type: Optional[str],
    max_pages: int,
    max_slides: int,
    source_type: str,
    source_url: Optional[str] = None,
    webhook_url: Optional[str] = None,
):
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    content_type = (content_type or "").lower()
    filename = filename or "upload"

    detected = detect_type(filename, content_type)
    meta = {"detected_type": detected}

    # Extract text
    try:
        if detected in ("txt", "md"):
            ext = ExtractResult(**extract_txt_md(data, filename).__dict__)
        elif detected == "docx":
            ext = extract_docx(data)
        elif detected == "pptx":
            ext = extract_pptx(data, max_slides=max_slides)
        elif detected == "pdf":
            ext = extract_pdf_text_or_vision(
                data=data,
                max_pages=max_pages,
                vision_system_prompt=VISION_PAGE_SYSTEM,
            )
        elif detected == "image":
            # Vision-only: treat as one page and then summarize into final format
            mime = content_type if content_type.startswith("image/") else guess_mime_from_filename(filename)
            from .utils.openai_client import vision_page_to_markdown
            page_md = vision_page_to_markdown(
                image_bytes=data,
                mime=mime,
                system_prompt=VISION_PAGE_SYSTEM,
                hint="Analyze this image as a document/photo/screenshot and extract meaningful content.",
            )
            ext = ExtractResult(combined_text=page_md, meta={"detected_type": "image", "pages": 1}, used_vision=True)
        else:
            raise HTTPException(status_code=415, detail=f"Unsupported file type: {filename} (content-type={content_type})")
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Extraction failed: {e}")
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Extraction failed: {e}")

    meta.update(ext.meta)
    meta["used_vision"] = bool(ext.used_vision)

    # Summarize to final Markdown
    try:
        markdown = summarize_text_markdown(ext.combined_text, SUMMARY_SYSTEM)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"OpenAI summarization failed: {e}")

    analysis_id = None
    try:
        analysis_id = create_analysis_run(
            source_type=source_type,
            source_name=filename,
            source_url=source_url,
            markdown=markdown,
            meta=meta,
            max_pages=max_pages,
            max_slides=max_slides,
            webhook_url=webhook_url,
        )
    except Exception:
        traceback.print_exc()

    webhook_result = {
        "requested": bool(webhook_url),
        "url": webhook_url,
        "status": "not_requested",
        "attempts": 0,
        "last_error": None,
    }

    if webhook_url:
        try:
            webhook_payload = {
                "analysis_id": analysis_id,
                "source_type": source_type,
                "source_name": filename,
                "source_url": source_url,
                "markdown": markdown,
                "meta": meta,
            }
            delivery = deliver_webhook(webhook_url, webhook_payload)
            webhook_result.update(
                {
                    "status": delivery["status"],
                    "attempts": delivery["attempts"],
                    "last_error": delivery["last_error"],
                }
            )
            if analysis_id:
                update_webhook_status(
                    analysis_id,
                    status=delivery["status"],
                    attempts=delivery["attempts"],
                    error=delivery["last_error"],
                )
        except Exception:
            traceback.print_exc()
            webhook_result.update(
                {
                    "status": "failed",
                    "attempts": 0,
                    "last_error": "Unexpected webhook delivery failure.",
                }
            )
            if analysis_id:
                update_webhook_status(
                    analysis_id,
                    status="failed",
                    attempts=0,
                    error=webhook_result["last_error"],
                )

    return JSONResponse(
        {
            "analysis_id": analysis_id,
            "markdown": markdown,
            "meta": meta,
            "webhook": webhook_result,
        }
    )


@app.post("/analyze")
async def analyze_upload(
    max_pages: int = Query(MAX_PAGES_DEFAULT, ge=1, le=200, description="Max PDF pages to process (scanned PDFs use Vision per page)."),
    max_slides: int = Query(MAX_SLIDES_DEFAULT, ge=1, le=500, description="Max PPTX slides to process."),
    file: UploadFile = File(...),
    webhook_url: Optional[str] = Form(None),
):
    data = await file.read()
    return _analyze_bytes(
        data=data,
        filename=file.filename or "upload",
        content_type=file.content_type,
        max_pages=max_pages,
        max_slides=max_slides,
        source_type="upload",
        webhook_url=webhook_url,
    )


@app.post("/analyze/url")
async def analyze_url(
    payload: AnalyzeUrlPayload = Body(...),
    max_pages: int = Query(MAX_PAGES_DEFAULT, ge=1, le=200, description="Max PDF pages to process (scanned PDFs use Vision per page)."),
    max_slides: int = Query(MAX_SLIDES_DEFAULT, ge=1, le=500, description="Max PPTX slides to process."),
):
    try:
        data, content_type = download_file(payload.file_url, timeout_seconds=60)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to download file_url: {e}")

    filename = payload.filename or (payload.file_url.split("?")[0].split("/")[-1] or "download")
    return _analyze_bytes(
        data=data,
        filename=filename,
        content_type=content_type,
        max_pages=max_pages,
        max_slides=max_slides,
        source_type="url",
        source_url=payload.file_url,
        webhook_url=payload.webhook_url,
    )


@app.get("/analysis-runs/{run_id}")
def get_analysis(run_id: str):
    record = get_analysis_run(run_id)
    if record is None:
        if not is_storage_enabled():
            raise HTTPException(status_code=503, detail="PostgreSQL storage is not enabled or unavailable.")
        raise HTTPException(status_code=404, detail="Analysis run not found.")
    return JSONResponse(record)
