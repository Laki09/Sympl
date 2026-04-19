from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from playwright.async_api import BrowserContext, Page, async_playwright

from backend.connectors.common import (
    CrawledMaterial,
    infer_material_type,
    normalize_text,
    unique_materials,
    write_materials_json,
)

# Local testing values. Prefer environment variables for real secrets.
# Do not commit real credentials.
ARTEMIS_USERNAME = os.getenv("ARTEMIS_USERNAME", "")
ARTEMIS_PASSWORD = os.getenv("ARTEMIS_PASSWORD", "")
ARTEMIS_BASE_URL = os.getenv("ARTEMIS_BASE_URL", "https://artemis.tum.de/")
ARTEMIS_SEARCH_QUERY = os.getenv("ARTEMIS_SEARCH_QUERY", "Analysis Kapitel 3")
ARTEMIS_HEADLESS = os.getenv("ARTEMIS_HEADLESS", "false").lower() == "true"
ARTEMIS_SETUP_ONLY = os.getenv("ARTEMIS_SETUP_ONLY", "false").lower() == "true"
ARTEMIS_SLOW_MO = int(os.getenv("ARTEMIS_SLOW_MO", "0"))
ARTEMIS_SESSION_PATH = Path(
    os.getenv("ARTEMIS_SESSION_PATH", "backend/sessions/artemis-storage-state.json")
)
ARTEMIS_OUTPUT_PATH = Path(
    os.getenv("ARTEMIS_OUTPUT_PATH", "backend/sessions/artemis-materials.json")
)
ARTEMIS_MAX_COURSES = int(os.getenv("ARTEMIS_MAX_COURSES", "50"))
ARTEMIS_MAX_MATERIALS_PER_COURSE = int(os.getenv("ARTEMIS_MAX_MATERIALS_PER_COURSE", "120"))
ARTEMIS_COURSE_IDS = [
    course_id.strip()
    for course_id in os.getenv("ARTEMIS_COURSE_IDS", "").split(",")
    if course_id.strip()
]


async def crawl_artemis_materials(
    query: str = ARTEMIS_SEARCH_QUERY,
    username: str = ARTEMIS_USERNAME,
    password: str = ARTEMIS_PASSWORD,
    headless: bool = ARTEMIS_HEADLESS,
) -> list[CrawledMaterial]:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=headless, slow_mo=ARTEMIS_SLOW_MO)
        context = await create_context(browser, ARTEMIS_SESSION_PATH)
        page = await context.new_page()

        await ensure_logged_in(page, context, username, password)

        if ARTEMIS_SETUP_ONLY:
            await run_setup_only(page, context)
            await browser.close()
            return []

        materials = await extract_api_materials(context, query)
        visible_materials = await extract_visible_materials(page, context, query)
        materials = unique_materials([*materials, *visible_materials])

        if not materials:
            materials = visible_materials

        await context.storage_state(path=str(ARTEMIS_SESSION_PATH))
        await browser.close()

    return unique_materials(materials)


async def run_setup_only(page: Page, context: BrowserContext) -> None:
    await page.goto(ARTEMIS_BASE_URL, wait_until="domcontentloaded")
    print()
    print("Artemis setup mode is active.")
    print("Use the opened browser to log in, adjust Artemis settings, or inspect your courses.")
    print("Press Enter in this terminal when you are done. The session will be saved.")
    await asyncio.to_thread(input)
    await context.storage_state(path=str(ARTEMIS_SESSION_PATH))
    print(f"Saved Artemis session to {ARTEMIS_SESSION_PATH}")


async def create_context(browser, storage_path: Path) -> BrowserContext:
    storage_path.parent.mkdir(parents=True, exist_ok=True)

    if storage_path.exists():
        return await browser.new_context(storage_state=str(storage_path))

    return await browser.new_context()


async def ensure_logged_in(
    page: Page,
    context: BrowserContext,
    username: str,
    password: str,
) -> None:
    await page.goto(ARTEMIS_BASE_URL, wait_until="domcontentloaded")

    if await looks_logged_in(page):
        return

    await try_fill_login(page, username, password)

    if not await looks_logged_in(page):
        print("Artemis login may require TUM SSO/2FA. Complete it in the opened browser.")
        await page.wait_for_url(lambda url: "login" not in url.lower(), timeout=180_000)

    await context.storage_state(path=str(ARTEMIS_SESSION_PATH))


async def looks_logged_in(page: Page) -> bool:
    url = page.url.lower()

    if "login" not in url and "shibboleth" not in url and "saml" not in url:
        return True

    logout = page.locator("a[href*='logout'], button:has-text('Logout'), button:has-text('Abmelden')")
    return await logout.count() > 0


async def try_fill_login(page: Page, username: str, password: str) -> None:
    if not username or not password:
        return

    username_input = await first_visible_locator(
        page,
        [
            "input[name='username']",
            "input[name='j_username']",
            "input[type='email']",
            "input[id*='user' i]",
        ],
    )
    password_input = await first_visible_locator(
        page,
        [
            "input[name='password']",
            "input[name='j_password']",
            "input[type='password']",
        ],
    )

    if username_input is None or password_input is None:
        return

    await username_input.fill(username)
    await password_input.fill(password)

    submit = await first_visible_locator(
        page,
        [
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('Login')",
            "button:has-text('Anmelden')",
        ],
    )

    if submit is not None:
        await submit.click()
        await page.wait_for_load_state("domcontentloaded")


async def first_visible_locator(page: Page, selectors: list[str]):
    for selector in selectors:
        locator = page.locator(selector).first

        if await locator.count() == 0:
            continue

        try:
            if await locator.is_visible(timeout=1_000):
                return locator
        except Exception:
            continue

    return None


async def extract_visible_materials(
    page: Page,
    context: BrowserContext,
    query: str,
) -> list[CrawledMaterial]:
    await page.goto(urljoin(ARTEMIS_BASE_URL, "/courses"), wait_until="networkidle")

    materials: list[CrawledMaterial] = []
    course_links = await collect_course_links(page)
    old_course_links = await collect_old_course_links(page)
    course_links = unique_links([*course_links, *old_course_links])

    for course_index, course_link in enumerate(course_links[:ARTEMIS_MAX_COURSES], start=1):
        course_title = course_link["text"] or query
        course_url = course_link["url"]
        course_id = extract_course_id_from_url(course_url)

        materials.append(
            build_material(
                id_value=f"artemis-course-{course_index}",
                title=course_title,
                url=course_url,
                course=course_title,
                summary=f"Artemis course found for '{query}': {course_title}",
            )
        )

        if course_id:
            materials.extend(
                await extract_course_api_materials(
                    context=context,
                    course_id=course_id,
                    course_title=course_title,
                )
            )

        materials.extend(await extract_course_materials(page, course_url, course_title, course_index))

    if materials:
        return materials

    return await extract_materials_from_current_page(page, query, id_prefix="artemis-visible")


async def collect_old_course_links(page: Page) -> list[dict[str, str]]:
    old_courses_link = await find_old_courses_link(page)

    if old_courses_link is None:
        return []

    try:
        archive_url = await old_courses_link.get_attribute("href")
        if archive_url:
            await page.goto(normalize_artemis_url(archive_url), wait_until="networkidle", timeout=30_000)
        else:
            await old_courses_link.click()
            await page.wait_for_url("**/courses/archive", timeout=30_000)
            await page.wait_for_load_state("networkidle", timeout=30_000)
    except Exception:
        return []

    return await collect_course_links(page)


async def find_old_courses_link(page: Page):
    locators = [
        page.locator("a:has-text('hier')").last,
        page.locator("a:has-text('alten Kursen')").first,
        page.locator("a:has-text('old courses')").first,
        page.locator("a[href*='archive']").first,
    ]

    for locator in locators:
        if await locator.count() == 0:
            continue

        try:
            if await locator.is_visible(timeout=1_000):
                return locator
        except Exception:
            continue

    return None


async def extract_api_materials(context: BrowserContext, query: str) -> list[CrawledMaterial]:
    dashboard = await fetch_artemis_json(context, "api/core/courses/for-dashboard")
    courses = merge_course_summaries(
        [
            {"id": course_id, "title": f"Artemis course {course_id}"}
            for course_id in ARTEMIS_COURSE_IDS
        ],
        extract_course_summaries(dashboard),
    )
    materials: list[CrawledMaterial] = []

    for course_index, course in enumerate(courses[:ARTEMIS_MAX_COURSES], start=1):
        course_id = course["id"]
        course_title = course["title"]
        course_url = normalize_artemis_url(f"/courses/{course_id}")

        materials.append(
            build_material(
                id_value=f"artemis-course-{course_id}",
                title=course_title,
                url=course_url,
                course=course_title,
                summary=f"Artemis course available for '{query}': {course_title}",
            )
        )

        materials.extend(
            await extract_course_api_materials(
                context=context,
                course_id=course_id,
                course_title=course_title,
            )
        )

        if len(materials) >= ARTEMIS_MAX_COURSES * ARTEMIS_MAX_MATERIALS_PER_COURSE:
            break

    return unique_materials(materials)


async def extract_course_api_materials(
    context: BrowserContext,
    course_id: str,
    course_title: str,
) -> list[CrawledMaterial]:
    materials: list[CrawledMaterial] = []
    course_dashboard = await fetch_artemis_json(
        context,
        f"api/core/courses/{course_id}/for-dashboard",
    )
    course_title = resolve_course_title(course_dashboard, course_id, course_title)

    materials.extend(extract_exercise_materials(course_dashboard, course_id, course_title))

    lecture_endpoints = [
        f"api/lecture/courses/{course_id}/lectures",
        f"api/lecture/courses/{course_id}/lectures-with-slides",
        f"api/lecture/courses/{course_id}/tutorial-lectures",
    ]

    for endpoint in lecture_endpoints:
        lectures = await fetch_artemis_json(context, endpoint)
        materials.extend(await extract_lecture_materials(context, lectures, course_id, course_title))

    return unique_materials(materials)[:ARTEMIS_MAX_MATERIALS_PER_COURSE]


async def fetch_artemis_json(context: BrowserContext, endpoint: str) -> Any:
    url = normalize_artemis_url(endpoint)

    try:
        response = await context.request.get(
            url,
            headers={
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=30_000,
        )
    except Exception:
        return None

    if not response.ok:
        return None

    try:
        return await response.json()
    except Exception:
        return None


def extract_course_summaries(raw_value: Any) -> list[dict[str, str]]:
    summaries: list[dict[str, str]] = []

    for item in find_dicts(raw_value):
        if isinstance(item.get("course"), dict):
            course = item["course"]
        elif any(key in item for key in ["shortName", "semester", "enrollmentEnabled"]):
            course = item
        else:
            continue

        course_id = as_int(course.get("id"))
        title = first_text(course, ["title", "name", "shortName"])

        if course_id is None or not title:
            continue

        summaries.append({"id": str(course_id), "title": title})

    return unique_course_summaries(summaries)


def merge_course_summaries(*course_groups: list[dict[str, str]]) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []

    for courses in course_groups:
        merged.extend(courses)

    return unique_course_summaries(merged)


def resolve_course_title(raw_value: Any, course_id: str, fallback: str) -> str:
    for course in extract_course_summaries(raw_value):
        if course["id"] == str(course_id):
            return course["title"]

    return fallback


def extract_exercise_materials(
    raw_value: Any,
    course_id: str,
    course_title: str,
) -> list[CrawledMaterial]:
    materials: list[CrawledMaterial] = []

    for exercise in find_dicts(raw_value):
        exercise_id = as_int(exercise.get("id"))
        title = first_text(exercise, ["title", "exerciseName", "name"])

        if exercise_id is None or not title:
            continue

        if str(exercise_id) == str(course_id) and title == course_title:
            continue

        type_value = first_text(exercise, ["type", "exerciseType"])
        exercise_specific_keys = {
            "assessmentType",
            "dueDate",
            "maxPoints",
            "participations",
            "problemStatement",
            "releaseDate",
            "studentParticipations",
        }

        if not type_value and not exercise_specific_keys.intersection(exercise.keys()):
            continue

        type_value = type_value or "exercise"
        lower_type = type_value.lower()

        if "lecture" in lower_type:
            continue

        if not any(
            marker in lower_type
            for marker in ["exercise", "programming", "quiz", "modeling", "text", "file"]
        ):
            continue

        materials.append(
            build_material(
                id_value=f"artemis-exercise-{exercise_id}",
                title=title,
                url=f"/courses/{course_id}/exercises/{exercise_id}",
                course=course_title,
                summary=f"Artemis exercise in '{course_title}': {title}",
            )
        )

    return materials[:ARTEMIS_MAX_MATERIALS_PER_COURSE]


async def extract_lecture_materials(
    context: BrowserContext,
    raw_value: Any,
    course_id: str,
    course_title: str,
) -> list[CrawledMaterial]:
    materials: list[CrawledMaterial] = []
    lectures = extract_lecture_summaries(raw_value)

    for lecture in lectures:
        lecture_id = lecture["id"]
        lecture_title = lecture["title"]
        lecture_url = f"/courses/{course_id}/lectures/{lecture_id}"

        materials.append(
            build_material(
                id_value=f"artemis-lecture-{lecture_id}",
                title=lecture_title,
                url=lecture_url,
                course=course_title,
                summary=f"Artemis lecture in '{course_title}': {lecture_title}",
            )
        )

        materials.extend(
            extract_attachment_materials(
                raw_value=lecture["raw"],
                course_id=course_id,
                course_title=course_title,
                lecture_id=lecture_id,
                lecture_title=lecture_title,
            )
        )

        lecture_details = await fetch_artemis_json(context, f"api/lecture/lectures/{lecture_id}/details")
        materials.extend(
            extract_attachment_materials(
                raw_value=lecture_details,
                course_id=course_id,
                course_title=course_title,
                lecture_id=lecture_id,
                lecture_title=lecture_title,
            )
        )

        attachments = await fetch_artemis_json(
            context,
            f"api/lecture/lectures/{lecture_id}/attachments",
        )
        materials.extend(
            extract_attachment_materials(
                raw_value=attachments,
                course_id=course_id,
                course_title=course_title,
                lecture_id=lecture_id,
                lecture_title=lecture_title,
            )
        )

    return materials[:ARTEMIS_MAX_MATERIALS_PER_COURSE]


def extract_lecture_summaries(raw_value: Any) -> list[dict[str, Any]]:
    lectures: list[dict[str, Any]] = []

    for item in find_dicts(raw_value):
        lecture_id = as_int(item.get("id"))
        title = first_text(item, ["title", "name"])

        if lecture_id is None or not title:
            continue

        value_hint = " ".join(str(key).lower() for key in item.keys())

        if "lecture" not in value_hint and not item.get("lectureUnits"):
            continue

        lectures.append({"id": str(lecture_id), "title": title, "raw": item})

    return unique_lecture_summaries(lectures)


def extract_attachment_materials(
    raw_value: Any,
    course_id: str,
    course_title: str,
    lecture_id: str,
    lecture_title: str,
) -> list[CrawledMaterial]:
    materials: list[CrawledMaterial] = []

    for attachment in find_dicts(raw_value):
        attachment_id = as_int(attachment.get("id"))
        title = first_text(attachment, ["name", "title", "fileName", "link"])
        link = first_text(attachment, ["link", "url", "filePath", "downloadUrl"])

        if not title and not link:
            continue

        if not link:
            continue

        id_suffix = attachment_id if attachment_id is not None else stable_suffix(link)
        materials.append(
            build_material(
                id_value=f"artemis-lecture-{lecture_id}-attachment-{id_suffix}",
                title=title or f"Attachment for {lecture_title}",
                url=link,
                course=course_title,
                summary=f"Artemis lecture attachment for '{lecture_title}': {title or link}",
            )
        )

    return materials


async def collect_course_links(page: Page) -> list[dict[str, str]]:
    anchors = await collect_anchors(page)
    course_links: list[dict[str, str]] = []

    for anchor in anchors:
        url = normalize_artemis_url(anchor["url"])
        path = urlparse(url).path.strip("/")

        if not path.startswith("courses/"):
            continue

        path_parts = path.split("/")
        if len(path_parts) != 2 or not path_parts[1].isdigit():
            continue

        text = anchor["text"] or f"Artemis course {path_parts[1]}"

        course_links.append({"url": url, "text": text})

    return unique_links(course_links)


async def extract_course_materials(
    page: Page,
    course_url: str,
    course_title: str,
    course_index: int,
) -> list[CrawledMaterial]:
    route_urls = [
        course_url,
        f"{course_url}/lectures",
        f"{course_url}/exercises",
    ]
    materials: list[CrawledMaterial] = []

    for route_index, route_url in enumerate(route_urls, start=1):
        try:
            await page.goto(route_url, wait_until="networkidle", timeout=30_000)
        except Exception:
            continue

        materials.extend(
            await extract_materials_from_current_page(
                page,
                course_title,
                id_prefix=f"artemis-course-{course_index}-{route_index}",
            )
        )

    return materials


async def extract_materials_from_current_page(
    page: Page,
    course: str,
    id_prefix: str,
) -> list[CrawledMaterial]:
    anchors = await collect_anchors(page)
    materials: list[CrawledMaterial] = []

    for index, anchor in enumerate(anchors, start=1):
        title = normalize_text(anchor.get("text"))
        url = normalize_artemis_url(anchor.get("url") or "")

        if not title or not url:
            continue

        if not is_likely_material(title, url, course):
            continue

        materials.append(
            build_material(
                id_value=f"{id_prefix}-{index}",
                title=title[:180],
                url=url,
                course=course,
                summary=f"Artemis material found for '{course}': {title}",
            )
        )

    return materials


async def collect_anchors(page: Page) -> list[dict[str, str]]:
    return await page.locator("a[href]").evaluate_all(
        """
        anchors => anchors.map(anchor => ({
          url: anchor.href,
          text: anchor.innerText ||
            anchor.getAttribute('aria-label') ||
            anchor.title ||
            anchor.closest('.card, [class*="course"], [class*="Course"]')?.innerText ||
            ''
        }))
        """
    )


async def try_artemis_search(page: Page, query: str) -> None:
    search_input = await first_visible_locator(
        page,
        [
            "input[type='search']",
            "input[placeholder*='Search' i]",
            "input[placeholder*='Suche' i]",
            "input[name='search']",
        ],
    )

    if search_input is None:
        return

    await search_input.fill(query)
    await search_input.press("Enter")
    await page.wait_for_load_state("networkidle")


def is_likely_material(title: str, url: str, query: str) -> bool:
    value = f"{title} {url}".lower()
    query_terms = normalize_query_terms(query)
    material_markers = [
        "exercise",
        "exercises",
        "lecture",
        "lectures",
        "quiz",
        "attachment",
        "attachments",
        "file",
        "download",
        "programming",
        "modeling",
        "text",
        "aufgabe",
        "kapitel",
        "chapter",
        ".pdf",
    ]

    return any(marker in value for marker in material_markers) or any(
        term in value for term in query_terms
    )


def build_material(
    id_value: str,
    title: str,
    url: str,
    course: str,
    summary: str,
) -> CrawledMaterial:
    material_type = infer_material_type(title, url)

    return CrawledMaterial(
        id=id_value,
        title=title,
        source="artemis",
        course=course,
        type=material_type,
        url=normalize_artemis_material_url(url),
        summary=summary,
        tags=["artemis", course, material_type],
    )


def normalize_artemis_material_url(url: str) -> str:
    normalized_url = normalize_artemis_url(url)
    parsed_url = urlparse(normalized_url)
    path = parsed_url.path.lstrip("/")

    if path.startswith("attachments/"):
        return normalize_artemis_url(f"/api/core/files/{path}")

    return normalized_url


def normalize_artemis_url(url: str) -> str:
    return urljoin(ARTEMIS_BASE_URL, url)


def extract_course_id_from_url(url: str) -> str | None:
    path_parts = urlparse(normalize_artemis_url(url)).path.strip("/").split("/")

    if len(path_parts) >= 2 and path_parts[0] == "courses" and path_parts[1].isdigit():
        return path_parts[1]

    return None


def normalize_query_terms(query: str) -> list[str]:
    return [term for term in query.lower().replace(",", " ").split() if len(term) >= 3]


def find_dicts(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    if isinstance(value, dict):
        found.append(value)

        for child in value.values():
            found.extend(find_dicts(child))

    if isinstance(value, list):
        for child in value:
            found.extend(find_dicts(child))

    return found


def first_text(value: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        raw_value = value.get(key)

        if isinstance(raw_value, str):
            text = normalize_text(raw_value)

            if text:
                return text

    return ""


def as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None

    if isinstance(value, int):
        return value

    if isinstance(value, str) and value.isdigit():
        return int(value)

    return None


def stable_suffix(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def unique_course_summaries(courses: list[dict[str, str]]) -> list[dict[str, str]]:
    seen_ids: set[str] = set()
    unique: list[dict[str, str]] = []

    for course in courses:
        course_id = course["id"]

        if course_id in seen_ids:
            continue

        seen_ids.add(course_id)
        unique.append(course)

    return unique


def unique_lecture_summaries(lectures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_ids: set[str] = set()
    unique: list[dict[str, Any]] = []

    for lecture in lectures:
        lecture_id = lecture["id"]

        if lecture_id in seen_ids:
            continue

        seen_ids.add(lecture_id)
        unique.append(lecture)

    return unique


def unique_links(links: list[dict[str, str]]) -> list[dict[str, str]]:
    seen_urls: set[str] = set()
    unique: list[dict[str, str]] = []

    for link in links:
        url = link["url"]

        if url in seen_urls:
            continue

        seen_urls.add(url)
        unique.append(link)

    return unique


async def main() -> None:
    materials = await crawl_artemis_materials()

    if ARTEMIS_SETUP_ONLY:
        return

    write_materials_json(materials, ARTEMIS_OUTPUT_PATH)
    print(f"Wrote {len(materials)} Artemis materials to {ARTEMIS_OUTPUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
