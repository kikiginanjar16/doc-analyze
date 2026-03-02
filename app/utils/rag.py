from __future__ import annotations

import re
from typing import Any

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "atau", "be", "by", "dari", "dan", "di",
    "for", "from", "i", "in", "is", "it", "ke", "of", "on", "or", "that", "the",
    "this", "to", "untuk", "yang",
}


def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z0-9_]+", (text or "").lower())
    return [token for token in tokens if len(token) > 1 and token not in _STOPWORDS]


def _split_paragraphs(markdown: str) -> list[str]:
    parts = re.split(r"\n\s*\n", (markdown or "").strip())
    return [part.strip() for part in parts if part and part.strip()]


def build_chunks(markdown: str, chunk_size: int = 1200) -> list[str]:
    paragraphs = _split_paragraphs(markdown)
    if not paragraphs:
        return []

    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= chunk_size:
            current = candidate
            continue

        if current:
            chunks.append(current)
        if len(paragraph) <= chunk_size:
            current = paragraph
            continue

        start = 0
        while start < len(paragraph):
            end = start + chunk_size
            chunks.append(paragraph[start:end].strip())
            start = end
        current = ""

    if current:
        chunks.append(current)

    return [chunk for chunk in chunks if chunk]


def select_relevant_chunks_from_list(chunks: list[str], question: str, top_k: int = 4) -> list[dict[str, Any]]:
    question_terms = set(_tokenize(question))
    normalized_question = (question or "").strip().lower()
    scored: list[dict[str, Any]] = []

    for index, chunk in enumerate(chunks, start=1):
        normalized_chunk = chunk.lower()
        chunk_terms = set(_tokenize(chunk))
        overlap = len(question_terms & chunk_terms)
        phrase_bonus = 0
        if normalized_question and normalized_question in normalized_chunk:
            phrase_bonus = 3
        elif any(term in normalized_chunk for term in question_terms):
            phrase_bonus = 1

        score = overlap + phrase_bonus
        scored.append(
            {
                "rank_source": index,
                "score": score,
                "content": chunk,
            }
        )

    scored.sort(key=lambda item: (item["score"], len(item["content"])), reverse=True)
    selected = scored[: max(1, min(top_k, len(scored)))]

    if selected and selected[0]["score"] == 0:
        selected = scored[:1]

    return [
        {
            "rank": index,
            "source_chunk": item["rank_source"],
            "score": item["score"],
            "content": item["content"],
        }
        for index, item in enumerate(selected, start=1)
    ]


def select_relevant_chunks(markdown: str, question: str, top_k: int = 4) -> list[dict[str, Any]]:
    chunks = build_chunks(markdown)
    if not chunks:
        return []
    return select_relevant_chunks_from_list(chunks, question, top_k=top_k)
