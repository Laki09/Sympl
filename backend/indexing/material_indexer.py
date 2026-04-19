from __future__ import annotations

import json
import hashlib
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from backend.indexing.pdf_fetcher import download_pdf
from backend.indexing.pdf_text_extractor import ExtractedPage, extract_pdf_pages

ROOT_DIR = Path(__file__).resolve().parents[2]
SESSIONS_DIR = ROOT_DIR / "backend" / "sessions"
PDF_CACHE_DIR = SESSIONS_DIR / "pdf-cache"
INDEX_PATH = SESSIONS_DIR / "material-index.json"
CRAWLED_MATERIAL_PATHS = [
    SESSIONS_DIR / "moodle-materials.json",
    SESSIONS_DIR / "artemis-materials.json",
]
SESSION_STATE_PATHS = {
    "artemis": SESSIONS_DIR / "artemis-storage-state.json",
    "moodle": SESSIONS_DIR / "moodle-storage-state.json",
}
DEFAULT_MAX_PAGES = int(os.environ.get("MATERIAL_INDEX_MAX_PAGES", "80"))


@dataclass
class IndexedPage:
    page: int
    text: str


@dataclass
class IndexedMaterial:
    id: str
    title: str
    source: str
    course: str
    type: str
    url: str
    summary: str
    tags: list[str]
    localPdfPath: str | None
    textPreview: str
    pages: list[IndexedPage]
    topics: list[str]
    chapters: list[dict[str, Any]]


def build_material_index() -> list[IndexedMaterial]:
    materials = load_crawled_materials()
    indexed_materials: list[IndexedMaterial] = []

    for material in materials:
        indexed_material = index_material(material)

        if indexed_material is not None:
            indexed_materials.append(indexed_material)

    write_material_index(indexed_materials)
    return indexed_materials


def load_crawled_materials() -> list[dict[str, Any]]:
    materials: list[dict[str, Any]] = []

    for path in CRAWLED_MATERIAL_PATHS:
        if not path.exists():
            continue

        try:
            raw_items = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        for item in raw_items:
            if isinstance(item, dict):
                materials.append(item)

    return unique_materials(materials)


def index_material(material: dict[str, Any]) -> IndexedMaterial | None:
    url = str(material.get("url") or "")
    title = str(material.get("title") or "")
    source = str(material.get("source") or "").lower()

    if not url or not title:
        return None

    pdf_path = resolve_pdf(material)
    pages = extract_pdf_pages(pdf_path, max_pages=DEFAULT_MAX_PAGES) if pdf_path else []
    indexed_pages = [IndexedPage(page=page.page, text=page.text) for page in pages]
    joined_text = " ".join(page.text for page in pages)
    text_preview = joined_text[:800]

    return IndexedMaterial(
        id=str(material.get("id") or stable_id(url)),
        title=title,
        source=source,
        course=str(material.get("course") or "Unknown course"),
        type=str(material.get("type") or "link"),
        url=url,
        summary=str(material.get("summary") or title),
        tags=coerce_string_list(material.get("tags")),
        localPdfPath=str(pdf_path.relative_to(ROOT_DIR)) if pdf_path else None,
        textPreview=text_preview,
        pages=indexed_pages,
        topics=extract_topics(title, joined_text),
        chapters=extract_chapters(pages),
    )


def resolve_pdf(material: dict[str, Any]) -> Path | None:
    url = str(material.get("url") or "")
    source = str(material.get("source") or "").lower()

    if not is_probable_pdf_resource(url, str(material.get("type") or "")):
        return None

    storage_state_path = SESSION_STATE_PATHS.get(source)
    return download_pdf(url, PDF_CACHE_DIR, storage_state_path=storage_state_path)


def is_probable_pdf_resource(url: str, material_type: str) -> bool:
    value = f"{url} {material_type}".lower()
    return ".pdf" in value or "pluginfile.php" in value or "/mod/resource/" in value


def write_material_index(indexed_materials: list[IndexedMaterial]) -> None:
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(
        json.dumps([asdict(material) for material in indexed_materials], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_material_index(path: Path = INDEX_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    try:
        raw_items = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    return [item for item in raw_items if isinstance(item, dict)]


def extract_topics(title: str, text: str, limit: int = 24) -> list[str]:
    value = f"{title} {text}".lower()
    candidates = re.findall(r"[a-zäöüß][a-zäöüß-]{4,}", value)
    stopwords = {
        "diese",
        "einer",
        "eines",
        "einen",
        "einem",
        "nicht",
        "oder",
        "sowie",
        "werden",
        "wurde",
        "haben",
        "kann",
        "dass",
        "theorem",
        "beweis",
        "definition",
        "aufgabe",
    }
    frequencies: dict[str, int] = {}

    for candidate in candidates:
        if candidate in stopwords:
            continue

        frequencies[candidate] = frequencies.get(candidate, 0) + 1

    return [
        topic
        for topic, _count in sorted(frequencies.items(), key=lambda item: item[1], reverse=True)[:limit]
    ]


def extract_chapters(pages: list[ExtractedPage]) -> list[dict[str, Any]]:
    chapters: list[dict[str, Any]] = []
    chapter_pattern = re.compile(
        r"(?:kapitel|chapter)\s+([0-9]+)\s*[:.-]?\s*([^\n]{0,100})",
        re.IGNORECASE,
    )
    numbered_heading_pattern = re.compile(r"^([0-9]+)\.?\s+([A-ZÄÖÜ][^\n]{4,100})$", re.MULTILINE)

    for page in pages:
        for match in chapter_pattern.finditer(page.text):
            chapters.append(
                {
                    "chapter": match.group(1),
                    "title": match.group(2).strip(),
                    "page": page.page,
                }
            )

        for match in numbered_heading_pattern.finditer(page.text[:2500]):
            chapters.append(
                {
                    "chapter": match.group(1),
                    "title": match.group(2).strip(),
                    "page": page.page,
                }
            )

    return unique_chapters(chapters)


def unique_chapters(chapters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, int]] = set()
    unique: list[dict[str, Any]] = []

    for chapter in chapters:
        key = (
            str(chapter.get("chapter") or ""),
            str(chapter.get("title") or "").lower(),
            int(chapter.get("page") or 0),
        )

        if key in seen:
            continue

        seen.add(key)
        unique.append(chapter)

    return unique


def coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]

    if isinstance(value, str) and value.strip():
        return [value.strip()]

    return []


def unique_materials(materials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_urls: set[str] = set()
    unique: list[dict[str, Any]] = []

    for material in materials:
        url = str(material.get("url") or "")

        if not url or url in seen_urls:
            continue

        seen_urls.add(url)
        unique.append(material)

    return unique


def stable_id(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def main() -> None:
    indexed_materials = build_material_index()
    print(f"Wrote {len(indexed_materials)} indexed materials to {INDEX_PATH}")


if __name__ == "__main__":
    main()
