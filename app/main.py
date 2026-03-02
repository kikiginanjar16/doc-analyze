from __future__ import annotations

import traceback
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, Query, Body, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

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
from .utils.openai_client import summarize_text_markdown, answer_question_with_context
from .utils.rag import build_chunks, select_relevant_chunks, select_relevant_chunks_from_list
from .utils.config import OPENAI_MODEL_TEXT, OPENAI_MODEL_VISION
from .utils.storage import (
    create_analysis_run,
    get_analysis_chunks,
    get_chunks_by_reference_id,
    get_analysis_run,
    init_db,
    is_storage_enabled,
    store_analysis_chunks,
    update_webhook_status,
)
from .utils.webhook import deliver_webhook

PROMPTS_DIR = Path(__file__).parent / "prompts"

app = FastAPI(
    title="Doc Analyzer (Summary-only) v1",
    version="1.3.0",
    description="Analyze image/pdf/docx/pptx/txt/md, return a Markdown summary, and support simple RAG Q&A on stored analysis results or by reference_id.",
)

def _read_prompt(name: str) -> str:
    p = PROMPTS_DIR / name
    return p.read_text(encoding="utf-8")

SUMMARY_SYSTEM = _read_prompt("summary_system.txt")
VISION_PAGE_SYSTEM = _read_prompt("vision_page_system.txt")
RAG_SYSTEM = _read_prompt("rag_system.txt")


class AnalyzeUrlPayload(BaseModel):
    file_url: str = Field(..., description="Public file URL to download and analyze.")
    filename: Optional[str] = Field(None, description="Optional filename override used for type detection and storage.")
    webhook_url: Optional[str] = Field(None, description="Optional webhook endpoint called after analysis completes.")
    application: Optional[str] = Field(None, description="Application name from the user system for filtering analysis runs.")
    reference_id: Optional[str] = Field(None, description="Application-level reference identifier from the user system.")
    document_id: Optional[str] = Field(None, description="Document identifier from the user system.")
    prompt: Optional[str] = Field(None, description="Additional user instruction appended to the summary prompt.")


class RagQueryPayload(BaseModel):
    question: str = Field(..., description="Question to answer from the stored analysis result.")
    analysis_id: Optional[str] = Field(None, description="Optional analysis run ID for single-document RAG.")
    reference_id: Optional[str] = Field(None, description="Optional reference ID for cross-document RAG.")
    top_k: int = Field(4, ge=1, le=8, description="How many retrieved chunks to send into the answer step.")
    application: Optional[str] = Field(None, description="Optional application filter, mainly for reference_id queries.")
    document_id: Optional[str] = Field(None, description="Optional document filter, mainly for reference_id queries.")


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


def _normalize_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _build_summary_prompt(user_prompt: Optional[str]) -> str:
    if not user_prompt:
        return SUMMARY_SYSTEM

    return (
        f"{SUMMARY_SYSTEM}\n\n"
        "Tambahan instruksi dari user:\n"
        f"{user_prompt}\n\n"
        "Ikuti instruksi tambahan di atas selama tidak bertentangan dengan instruksi sistem."
    )


def _normalize_question(question: str) -> str:
    normalized = (question or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="Question must not be empty.")
    return normalized

def _analyze_bytes(
    data: bytes,
    filename: str,
    content_type: Optional[str],
    max_pages: int,
    max_slides: int,
    source_type: str,
    source_url: Optional[str] = None,
    webhook_url: Optional[str] = None,
    application: Optional[str] = None,
    reference_id: Optional[str] = None,
    document_id: Optional[str] = None,
    user_prompt: Optional[str] = None,
):
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    content_type = (content_type or "").lower()
    filename = filename or "upload"
    application = _normalize_optional_text(application)
    reference_id = _normalize_optional_text(reference_id)
    document_id = _normalize_optional_text(document_id)
    user_prompt = _normalize_optional_text(user_prompt)

    detected = detect_type(filename, content_type)
    meta = {"detected_type": detected}
    if application:
        meta["application"] = application
    if reference_id:
        meta["reference_id"] = reference_id
    if document_id:
        meta["document_id"] = document_id
    if user_prompt:
        meta["prompt"] = user_prompt

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
        markdown = summarize_text_markdown(ext.combined_text, _build_summary_prompt(user_prompt))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"OpenAI summarization failed: {e}")

    analysis_id = None
    try:
        analysis_id = create_analysis_run(
            source_type=source_type,
            source_name=filename,
            source_url=source_url,
            application=application,
            reference_id=reference_id,
            document_id=document_id,
            user_prompt=user_prompt,
            markdown=markdown,
            meta=meta,
            max_pages=max_pages,
            max_slides=max_slides,
            webhook_url=webhook_url,
        )
        if analysis_id:
            store_analysis_chunks(analysis_id, build_chunks(markdown))
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
                "application": application,
                "reference_id": reference_id,
                "document_id": document_id,
                "prompt": user_prompt,
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
            "application": application,
            "reference_id": reference_id,
            "document_id": document_id,
            "prompt": user_prompt,
            "markdown": markdown,
            "meta": meta,
            "webhook": webhook_result,
        }
    )


@app.post("/analyze")
async def analyze_upload(
    max_pages: int = Query(MAX_PAGES_DEFAULT, ge=1, le=200, description="Max PDF pages to process (scanned PDFs use Vision per page)."),
    max_slides: int = Query(MAX_SLIDES_DEFAULT, ge=1, le=500, description="Max PPTX slides to process."),
    file: UploadFile = File(..., description="Document file to analyze."),
    webhook_url: Optional[str] = Form(None, description="Optional webhook endpoint called after analysis completes."),
    application: Optional[str] = Form(None, description="Application name from the user system for filtering analysis runs."),
    reference_id: Optional[str] = Form(None, description="Application-level reference identifier from the user system."),
    document_id: Optional[str] = Form(None, description="Document identifier from the user system."),
    prompt: Optional[str] = Form(None, description="Additional user instruction appended to the summary prompt."),
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
        application=application,
        reference_id=reference_id,
        document_id=document_id,
        user_prompt=prompt,
    )


@app.post("/analyze/url")
async def analyze_url(
    payload: AnalyzeUrlPayload = Body(..., description="Analyze a document fetched from a URL."),
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
        application=payload.application,
        reference_id=payload.reference_id,
        document_id=payload.document_id,
        user_prompt=payload.prompt,
    )


@app.get("/analysis-runs/{run_id}")
def get_analysis(run_id: str):
    record = get_analysis_run(run_id)
    if record is None:
        if not is_storage_enabled():
            raise HTTPException(status_code=503, detail="PostgreSQL storage is not enabled or unavailable.")
        raise HTTPException(status_code=404, detail="Analysis run not found.")
    return JSONResponse(record)


@app.post("/rag")
def ask_rag(
    payload: RagQueryPayload = Body(..., description="Ask a question using either a single analysis_id or a reference_id."),
):
    if not is_storage_enabled():
        raise HTTPException(status_code=503, detail="PostgreSQL storage is not enabled or unavailable.")

    question = _normalize_question(payload.question)
    analysis_id = _normalize_optional_text(payload.analysis_id)
    reference_id = _normalize_optional_text(payload.reference_id)
    application = _normalize_optional_text(payload.application)
    document_id = _normalize_optional_text(payload.document_id)

    if bool(analysis_id) == bool(reference_id):
        raise HTTPException(status_code=400, detail="Provide exactly one of analysis_id or reference_id.")

    response_payload: dict[str, object]
    if analysis_id:
        record = get_analysis_run(analysis_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Analysis run not found.")

        stored_chunks = get_analysis_chunks(analysis_id)
        if stored_chunks:
            retrieved_chunks = select_relevant_chunks_from_list(
                [chunk["content"] for chunk in stored_chunks],
                question,
                top_k=payload.top_k,
            )
            for chunk in retrieved_chunks:
                source_index = chunk["source_chunk"]
                if 1 <= source_index <= len(stored_chunks):
                    chunk["source_chunk"] = stored_chunks[source_index - 1]["source_chunk"]
        else:
            markdown = (record.get("markdown") or "").strip()
            if not markdown:
                raise HTTPException(status_code=400, detail="Stored analysis does not contain markdown content.")
            retrieved_chunks = select_relevant_chunks(markdown, question, top_k=payload.top_k)

        if not retrieved_chunks:
            raise HTTPException(status_code=400, detail="Unable to build retrieval context from the stored analysis.")

        context = "\n\n".join(
            f"[Chunk {chunk['source_chunk']} | score={chunk['score']}]\n{chunk['content']}"
            for chunk in retrieved_chunks
        )
        response_payload = {
            "analysis_id": analysis_id,
            "reference_id": record.get("reference_id"),
            "application": record.get("application"),
            "question": question,
            "retrieved_chunks": retrieved_chunks,
        }
    else:
        stored_chunks = get_chunks_by_reference_id(
            reference_id,
            application=application,
            document_id=document_id,
        )
        if not stored_chunks:
            raise HTTPException(status_code=404, detail="No stored analysis chunks found for the given reference_id and filters.")

        retrieved_chunks = select_relevant_chunks_from_list(
            [chunk["content"] for chunk in stored_chunks],
            question,
            top_k=payload.top_k,
        )
        if not retrieved_chunks:
            raise HTTPException(status_code=400, detail="Unable to build retrieval context from the stored analysis.")

        for chunk in retrieved_chunks:
            source_index = chunk["source_chunk"]
            if 1 <= source_index <= len(stored_chunks):
                source = stored_chunks[source_index - 1]
                chunk["analysis_id"] = source["analysis_id"]
                chunk["application"] = source["application"]
                chunk["reference_id"] = source["reference_id"]
                chunk["document_id"] = source["document_id"]
                chunk["source_name"] = source["source_name"]
                chunk["source_chunk"] = source["source_chunk"]

        context = "\n\n".join(
            (
                f"[Analysis {chunk.get('analysis_id')} | Document {chunk.get('document_id')} | "
                f"Chunk {chunk['source_chunk']} | score={chunk['score']}]\n{chunk['content']}"
            )
            for chunk in retrieved_chunks
        )
        response_payload = {
            "reference_id": reference_id,
            "application": application,
            "document_id": document_id,
            "question": question,
            "retrieved_chunks": retrieved_chunks,
        }

    try:
        answer = answer_question_with_context(question, context, RAG_SYSTEM)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"OpenAI RAG answer failed: {e}")

    response_payload["answer"] = answer
    return JSONResponse(response_payload)
