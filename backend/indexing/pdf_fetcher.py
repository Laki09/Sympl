from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests


def download_pdf(
    url: str,
    output_dir: Path,
    storage_state_path: Path | None = None,
    timeout: int = 45,
) -> Path | None:
    output_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()

    if storage_state_path and storage_state_path.exists():
        apply_playwright_cookies(session, storage_state_path, url)

    try:
        response = session.get(url, allow_redirects=True, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException:
        return None

    content_type = response.headers.get("content-type", "").lower()
    content_disposition = response.headers.get("content-disposition", "").lower()

    if not looks_like_pdf(response.url, content_type, content_disposition, response.content):
        return None

    file_path = output_dir / build_pdf_filename(response.url, content_disposition)
    file_path.write_bytes(response.content)
    return file_path


def apply_playwright_cookies(session: requests.Session, storage_state_path: Path, url: str) -> None:
    try:
        state = json.loads(storage_state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return

    request_domain = urlparse(url).hostname or ""

    for cookie in state.get("cookies", []):
        if not isinstance(cookie, dict):
            continue

        domain = str(cookie.get("domain") or "").lstrip(".")
        name = str(cookie.get("name") or "")
        value = str(cookie.get("value") or "")

        if not name or not domain_matches(request_domain, domain):
            continue

        session.cookies.set(name, value, domain=domain, path=str(cookie.get("path") or "/"))


def looks_like_pdf(
    url: str,
    content_type: str,
    content_disposition: str,
    content: bytes,
) -> bool:
    return (
        "application/pdf" in content_type
        or ".pdf" in url.lower()
        or ".pdf" in content_disposition
        or content.startswith(b"%PDF")
    )


def build_pdf_filename(url: str, content_disposition: str) -> str:
    filename = extract_filename(content_disposition) or Path(urlparse(url).path).name

    if not filename.lower().endswith(".pdf"):
        filename = f"{filename or 'material'}.pdf"

    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    safe_name = "".join(character if character.isalnum() or character in ".-_" else "_" for character in filename)
    return f"{digest}-{safe_name}"


def extract_filename(content_disposition: str) -> str:
    marker = "filename="

    if marker not in content_disposition:
        return ""

    value = content_disposition.split(marker, 1)[1].split(";", 1)[0].strip()
    return value.strip("\"'")


def domain_matches(request_domain: str, cookie_domain: str) -> bool:
    return request_domain == cookie_domain or request_domain.endswith(f".{cookie_domain}")
