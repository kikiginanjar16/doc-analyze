from __future__ import annotations

import base64
import re
from typing import Optional
from openai import OpenAI
from .config import OPENAI_API_KEY, OPENAI_MODEL_TEXT, OPENAI_MODEL_VISION, REQUEST_TIMEOUT_SECONDS

_client: Optional[OpenAI] = None

def get_client() -> OpenAI:
    global _client
    if _client is None:
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set. Please set it in your environment.")
        _client = OpenAI(api_key=OPENAI_API_KEY, timeout=REQUEST_TIMEOUT_SECONDS)
    return _client


def _chat_completion_text(resp) -> str:
    content = resp.choices[0].message.content
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        return "\n".join(p for p in parts if p).strip()
    return str(content).strip()


def _clean_markdown(markdown: str) -> str:
    text = (markdown or "").strip()
    if "\\n" in text:
        text = text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t")
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return "# Ringkasan Dokumen"

    lines = []
    for raw_line in text.split("\n"):
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue

        if stripped in {"•", "-", "*"}:
            continue

        bullet_match = re.match(r"^([*\-•])\s+", stripped)
        if bullet_match:
            stripped = re.sub(r"^([*\-•])\s+", "- ", stripped)
            lines.append(stripped)
            continue

        numbered_match = re.match(r"^\d+[.)]\s+", stripped)
        if numbered_match:
            stripped = re.sub(r"^\d+[.)]\s+", "1. ", stripped)
            lines.append(stripped)
            continue

        if stripped.endswith(":") and not stripped.startswith("#"):
            heading = stripped[:-1].strip()
            if heading:
                lines.append(f"## {heading}")
                continue

        lines.append(stripped)

    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    if not cleaned.startswith("# "):
        cleaned = "# Ringkasan Dokumen\n\n" + cleaned

    cleaned = re.sub(r"\n(## [^\n]+)\n(?!\n)", r"\n\1\n\n", cleaned)
    return cleaned.strip()


def summarize_text_markdown(text: str, system_prompt: str) -> str:
    client = get_client()
    if hasattr(client, "responses"):
        resp = client.responses.create(
            model=OPENAI_MODEL_TEXT,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            temperature=0.2,
        )
        return _clean_markdown(resp.output_text)

    resp = client.chat.completions.create(
        model=OPENAI_MODEL_TEXT,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ],
        temperature=0.2,
    )
    return _clean_markdown(_chat_completion_text(resp))


def answer_question_with_context(question: str, context: str, system_prompt: str) -> str:
    client = get_client()
    user_prompt = f"Pertanyaan:\n{question.strip()}\n\nKonteks dokumen:\n{context.strip()}"
    if hasattr(client, "responses"):
        resp = client.responses.create(
            model=OPENAI_MODEL_TEXT,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
        )
        return resp.output_text.strip()

    resp = client.chat.completions.create(
        model=OPENAI_MODEL_TEXT,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
    )
    return _chat_completion_text(resp)


def vision_page_to_markdown(image_bytes: bytes, mime: str, system_prompt: str, hint: str = "") -> str:
    client = get_client()
    b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"
    user_parts = []
    if hint:
        user_parts.append({"type": "input_text", "text": hint})
    user_parts.append({"type": "input_image", "image_url": data_url})
    if hasattr(client, "responses"):
        resp = client.responses.create(
            model=OPENAI_MODEL_VISION,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_parts},
            ],
            temperature=0.2,
        )
        return resp.output_text.strip()

    resp = client.chat.completions.create(
        model=OPENAI_MODEL_VISION,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": hint or "Analyze this image and extract meaningful content."},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        temperature=0.2,
    )
    return _chat_completion_text(resp)
