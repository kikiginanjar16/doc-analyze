from __future__ import annotations
import os
import mimetypes

def detect_type(filename: str | None, content_type: str | None) -> str:
    # Returns: image|pdf|docx|pptx|txt|md|unknown
    ctype = (content_type or "").split(";")[0].strip().lower()
    name = (filename or "").lower()

    if ctype.startswith("image/"):
        return "image"
    if ctype == "application/pdf":
        return "pdf"
    if ctype in ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",):
        return "docx"
    if ctype in ("application/vnd.openxmlformats-officedocument.presentationml.presentation",):
        return "pptx"
    if ctype.startswith("text/"):
        # decide md vs txt by extension
        if name.endswith(".md") or ctype in ("text/markdown", "text/x-markdown"):
            return "md"
        return "txt"

    # fallback by extension
    ext = os.path.splitext(name)[1]
    if ext in (".png", ".jpg", ".jpeg", ".webp"):
        return "image"
    if ext == ".pdf":
        return "pdf"
    if ext == ".docx":
        return "docx"
    if ext == ".pptx":
        return "pptx"
    if ext == ".md":
        return "md"
    if ext == ".txt":
        return "txt"
    return "unknown"

def guess_mime_from_filename(filename: str) -> str:
    mime, _ = mimetypes.guess_type(filename)
    return (mime or "application/octet-stream").lower()
