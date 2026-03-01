from __future__ import annotations
import httpx

def download_file(url: str, timeout_seconds: int = 60) -> tuple[bytes, str]:
    # Returns (bytes, content_type)
    with httpx.Client(follow_redirects=True, timeout=timeout_seconds) as client:
        r = client.get(url)
        r.raise_for_status()
        ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
        return r.content, ctype
