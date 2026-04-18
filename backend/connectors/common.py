from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class CrawledMaterial:
    id: str
    title: str
    source: str
    course: str
    type: str
    url: str
    summary: str
    tags: list[str]


def infer_material_type(title: str, url: str) -> str:
    value = f"{title} {url}".lower()

    if ".pdf" in value or "skript" in value or "script" in value:
        return "script"

    if "aufgabe" in value or "exercise" in value or "uebung" in value or "übung" in value:
        return "exercise"

    if "quiz" in value or "test" in value:
        return "quiz"

    if "folie" in value or "slide" in value or "lecture" in value:
        return "slides"

    if "forum" in value or "announcement" in value or "ankuendigung" in value:
        return "announcement"

    return "link"


def normalize_text(value: str | None) -> str:
    return " ".join((value or "").split()).strip()


def unique_materials(materials: Iterable[CrawledMaterial]) -> list[CrawledMaterial]:
    seen_urls: set[str] = set()
    unique: list[CrawledMaterial] = []

    for material in materials:
        if material.url in seen_urls:
            continue

        seen_urls.add(material.url)
        unique.append(material)

    return unique


def write_materials_json(materials: Iterable[CrawledMaterial], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps([asdict(material) for material in materials], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
