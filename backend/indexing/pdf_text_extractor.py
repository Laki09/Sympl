from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz


@dataclass
class ExtractedPage:
    page: int
    text: str


def extract_pdf_pages(pdf_path: Path, max_pages: int | None = None) -> list[ExtractedPage]:
    pages: list[ExtractedPage] = []

    try:
        document = fitz.open(pdf_path)
    except Exception:
        return []

    try:
        page_count = min(len(document), max_pages or len(document))

        for page_index in range(page_count):
            try:
                text = normalize_text(document[page_index].get_text("text"))
            except Exception:
                continue

            if text:
                pages.append(ExtractedPage(page=page_index + 1, text=text))
    finally:
        document.close()

    return pages


def normalize_text(value: str) -> str:
    return " ".join(value.split()).strip()
