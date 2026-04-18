from __future__ import annotations

import asyncio
import os
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

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
MOODLE_USERNAME = os.getenv("MOODLE_USERNAME", "")
MOODLE_PASSWORD = os.getenv("MOODLE_PASSWORD", "")
MOODLE_BASE_URL = os.getenv("MOODLE_BASE_URL", "https://www.moodle.tum.de/")
MOODLE_LOGIN_URL = os.getenv("MOODLE_LOGIN_URL", "https://www.moodle.tum.de/login/index.php")
MOODLE_SEARCH_QUERY = os.getenv("MOODLE_SEARCH_QUERY", "Analysis Kapitel 3")
MOODLE_HEADLESS = os.getenv("MOODLE_HEADLESS", "false").lower() == "true"
MOODLE_SESSION_PATH = Path(
    os.getenv("MOODLE_SESSION_PATH", "backend/sessions/moodle-storage-state.json")
)
MOODLE_OUTPUT_PATH = Path(os.getenv("MOODLE_OUTPUT_PATH", "backend/sessions/moodle-materials.json"))
MOODLE_MAX_COURSES = int(os.getenv("MOODLE_MAX_COURSES", "12"))
MOODLE_MAX_MATERIALS_PER_COURSE = int(os.getenv("MOODLE_MAX_MATERIALS_PER_COURSE", "120"))
MOODLE_COURSE_IDS = [
    course_id.strip()
    for course_id in os.getenv("MOODLE_COURSE_IDS", "").split(",")
    if course_id.strip()
]


async def crawl_moodle_materials(
    query: str = MOODLE_SEARCH_QUERY,
    username: str = MOODLE_USERNAME,
    password: str = MOODLE_PASSWORD,
    headless: bool = MOODLE_HEADLESS,
) -> list[CrawledMaterial]:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=headless)
        context = await create_context(browser, MOODLE_SESSION_PATH)
        page = await context.new_page()

        await ensure_logged_in(page, context, username, password)
        materials = await extract_course_materials(page, query)

        if not materials:
            materials = await extract_visible_materials(page, query)

        await context.storage_state(path=str(MOODLE_SESSION_PATH))
        await browser.close()

    return unique_materials(materials)


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
    await page.goto(MOODLE_LOGIN_URL, wait_until="domcontentloaded")

    if await looks_logged_in(page):
        return

    await try_fill_login(page, username, password)

    if not await looks_logged_in(page):
        print("Moodle login may require TUM SSO/2FA. Complete it in the opened browser.")
        await page.wait_for_url(lambda url: "login" not in url.lower(), timeout=180_000)

    await context.storage_state(path=str(MOODLE_SESSION_PATH))


async def looks_logged_in(page: Page) -> bool:
    url = page.url.lower()

    if "login" not in url and "shibboleth" not in url and "saml" not in url:
        return True

    logout_link = page.locator("a[href*='logout']").first
    return await logout_link.count() > 0


async def try_fill_login(page: Page, username: str, password: str) -> None:
    if not username or not password:
        return

    username_selectors = [
        "input[name='username']",
        "input[name='j_username']",
        "input[type='email']",
        "input[id*='user' i]",
    ]
    password_selectors = [
        "input[name='password']",
        "input[name='j_password']",
        "input[type='password']",
    ]

    username_input = await first_visible_locator(page, username_selectors)
    password_input = await first_visible_locator(page, password_selectors)

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


async def extract_visible_materials(page: Page, query: str) -> list[CrawledMaterial]:
    await page.goto(MOODLE_BASE_URL, wait_until="domcontentloaded")
    await try_moodle_search(page, query)

    anchors = await page.locator("a[href]").evaluate_all(
        """
        anchors => anchors.map(anchor => ({
          href: anchor.href,
          text: anchor.innerText || anchor.getAttribute('aria-label') || anchor.title || ''
        }))
        """
    )

    materials: list[CrawledMaterial] = []

    for index, anchor in enumerate(anchors, start=1):
        title = normalize_text(anchor.get("text"))
        url = anchor.get("href") or ""

        if not title or not url:
            continue

        if not is_likely_material(title, url, query):
            continue

        material_type = infer_material_type(title, url)
        materials.append(
            CrawledMaterial(
                id=f"moodle-live-{index}",
                title=title[:180],
                source="moodle",
                course=query,
                type=material_type,
                url=urljoin(MOODLE_BASE_URL, url),
                summary=f"Moodle material found for '{query}': {title}",
                tags=["moodle", query, material_type],
            )
        )

    return materials


async def extract_course_materials(page: Page, query: str) -> list[CrawledMaterial]:
    course_links = await collect_course_links(page, query)
    materials: list[CrawledMaterial] = []

    for course_index, course_link in enumerate(course_links[:MOODLE_MAX_COURSES], start=1):
        course_url = course_link["url"]
        course_title = course_link["text"] or f"Moodle course {course_link['id']}"

        try:
            await page.goto(course_url, wait_until="networkidle", timeout=45_000)
        except Exception:
            try:
                await page.goto(course_url, wait_until="domcontentloaded", timeout=45_000)
            except Exception:
                continue

        course_title = await resolve_course_title(page, course_title)
        materials.append(
            build_material(
                id_value=f"moodle-course-{course_link['id']}",
                title=course_title,
                url=course_url,
                course=course_title,
                summary=f"Moodle course available for '{query}': {course_title}",
            )
        )

        page_materials = await extract_materials_from_current_page(
            page,
            course_title,
            id_prefix=f"moodle-course-{course_index}",
        )
        materials.extend(page_materials)

        folder_links = [
            material.url
            for material in page_materials
            if "/mod/folder/" in material.url
        ]
        materials.extend(
            await extract_folder_materials(
                page,
                folder_links[:10],
                course_title,
                id_prefix=f"moodle-course-{course_index}-folder",
            )
        )

    return unique_materials(materials)


async def collect_course_links(page: Page, query: str) -> list[dict[str, str]]:
    configured_courses = [
        {
            "id": course_id,
            "url": normalize_moodle_url(f"/course/view.php?id={course_id}"),
            "text": f"Moodle course {course_id}",
        }
        for course_id in MOODLE_COURSE_IDS
    ]
    discovered_courses: list[dict[str, str]] = []

    for path in ["/my/courses.php", "/my/", "/course/"]:
        try:
            await page.goto(normalize_moodle_url(path), wait_until="networkidle", timeout=45_000)
        except Exception:
            try:
                await page.goto(normalize_moodle_url(path), wait_until="domcontentloaded", timeout=45_000)
            except Exception:
                continue

        discovered_courses.extend(extract_course_links_from_anchors(await collect_anchors(page)))

    if not discovered_courses:
        await page.goto(MOODLE_BASE_URL, wait_until="domcontentloaded")
        await try_moodle_search(page, query)
        discovered_courses.extend(extract_course_links_from_anchors(await collect_anchors(page)))

    return unique_course_links([*configured_courses, *discovered_courses])


def extract_course_links_from_anchors(anchors: list[dict[str, str]]) -> list[dict[str, str]]:
    courses: list[dict[str, str]] = []

    for anchor in anchors:
        url = normalize_moodle_url(anchor.get("url") or anchor.get("href") or "")
        course_id = extract_moodle_course_id(url)

        if course_id is None:
            continue

        title = normalize_text(anchor.get("text"))

        if not title or is_navigation_label(title):
            title = f"Moodle course {course_id}"

        courses.append({"id": course_id, "url": url, "text": title[:180]})

    return courses


async def extract_materials_from_current_page(
    page: Page,
    course: str,
    id_prefix: str,
) -> list[CrawledMaterial]:
    anchors = await collect_anchors(page)
    materials: list[CrawledMaterial] = []

    for index, anchor in enumerate(anchors, start=1):
        title = normalize_text(anchor.get("text"))
        url = normalize_moodle_url(anchor.get("url") or anchor.get("href") or "")

        if not title or not url:
            continue

        if not is_likely_course_material(title, url):
            continue

        resolved_url = await resolve_moodle_resource_url(page, url)
        materials.append(
            build_material(
                id_value=f"{id_prefix}-{index}",
                title=title[:180],
                url=resolved_url,
                course=course,
                summary=f"Moodle material found in '{course}': {title}",
            )
        )

    return materials[:MOODLE_MAX_MATERIALS_PER_COURSE]


async def extract_folder_materials(
    page: Page,
    folder_links: list[str],
    course: str,
    id_prefix: str,
) -> list[CrawledMaterial]:
    materials: list[CrawledMaterial] = []

    for folder_index, folder_url in enumerate(folder_links, start=1):
        try:
            await page.goto(folder_url, wait_until="networkidle", timeout=30_000)
        except Exception:
            try:
                await page.goto(folder_url, wait_until="domcontentloaded", timeout=30_000)
            except Exception:
                continue

        materials.extend(
            await extract_materials_from_current_page(
                page,
                course,
                id_prefix=f"{id_prefix}-{folder_index}",
            )
        )

    return materials


async def collect_anchors(page: Page) -> list[dict[str, str]]:
    return await page.locator("a[href]").evaluate_all(
        """
        anchors => anchors.map(anchor => ({
          url: anchor.href,
          text: anchor.innerText || anchor.getAttribute('aria-label') || anchor.title || ''
        }))
        """
    )


async def resolve_course_title(page: Page, fallback: str) -> str:
    for selector in ["h1", ".page-header-headings h1", "header h1", ".coursename"]:
        locator = page.locator(selector).first

        try:
            if await locator.count() == 0:
                continue

            text = normalize_text(await locator.inner_text(timeout=1_000))

            if text and not is_navigation_label(text):
                return text[:180]
        except Exception:
            continue

    return fallback


async def resolve_moodle_resource_url(page: Page, url: str) -> str:
    if "/mod/resource/view.php" not in url:
        return url

    try:
        response = await page.context.request.get(url, max_redirects=10, timeout=20_000)
    except Exception:
        return url

    content_type = response.headers.get("content-type", "").lower()
    content_disposition = response.headers.get("content-disposition", "").lower()
    final_url = response.url

    if (
        "pluginfile.php" in final_url
        or "application/pdf" in content_type
        or "filename=" in content_disposition
    ):
        return final_url

    return url


async def try_moodle_search(page: Page, query: str) -> None:
    search_input = await first_visible_locator(
        page,
        [
            "input[type='search']",
            "input[name='q']",
            "input[placeholder*='Search' i]",
            "input[placeholder*='Suche' i]",
        ],
    )

    if search_input is None:
        return

    await search_input.fill(query)
    await search_input.press("Enter")
    await page.wait_for_load_state("domcontentloaded")


def is_likely_material(title: str, url: str, query: str) -> bool:
    value = f"{title} {url}".lower()
    query_terms = [term for term in query.lower().replace(",", " ").split() if len(term) >= 3]
    material_markers = [
        ".pdf",
        "mod/resource",
        "mod/folder",
        "mod/assign",
        "pluginfile",
        "script",
        "skript",
        "uebung",
        "übung",
        "aufgabe",
        "chapter",
        "kapitel",
    ]

    return any(marker in value for marker in material_markers) or any(
        term in value for term in query_terms
    )


def is_likely_course_material(title: str, url: str) -> bool:
    value = f"{title} {url}".lower()
    material_markers = [
        "/mod/resource/",
        "/mod/folder/",
        "/mod/assign/",
        "/mod/url/",
        "/mod/page/",
        "/mod/book/",
        "/mod/quiz/",
        "/mod/forum/",
        "/pluginfile.php",
        "pluginfile",
        ".pdf",
        ".ipynb",
        ".zip",
        ".py",
        ".java",
        ".cpp",
        ".ppt",
        ".pptx",
        ".doc",
        ".docx",
        "skript",
        "script",
        "slide",
        "folie",
        "uebung",
        "übung",
        "aufgabe",
        "assignment",
        "worksheet",
        "chapter",
        "kapitel",
    ]
    excluded_markers = [
        "logout",
        "login",
        "calendar/",
        "managesubscriptions",
        "profile.php",
        "grade/report",
        "participants.php",
    ]

    if any(marker in value for marker in excluded_markers):
        return False

    return any(marker in value for marker in material_markers)


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
        source="moodle",
        course=course,
        type=material_type,
        url=normalize_moodle_url(url),
        summary=summary,
        tags=["moodle", course, material_type],
    )


def normalize_moodle_url(url: str) -> str:
    return urljoin(MOODLE_BASE_URL, url)


def extract_moodle_course_id(url: str) -> str | None:
    parsed_url = urlparse(url)

    if not parsed_url.path.endswith("/course/view.php"):
        return None

    course_id = parse_qs(parsed_url.query).get("id", [None])[0]

    if course_id and course_id.isdigit():
        return course_id

    return None


def is_navigation_label(title: str) -> bool:
    normalized = title.lower().strip()
    navigation_labels = {
        "dashboard",
        "home",
        "kalender",
        "calendar",
        "meine kurse",
        "my courses",
        "kurse",
        "courses",
        "übersicht",
        "overview",
    }

    return normalized in navigation_labels or len(normalized) <= 2


def unique_course_links(courses: list[dict[str, str]]) -> list[dict[str, str]]:
    seen_ids: set[str] = set()
    unique: list[dict[str, str]] = []

    for course in courses:
        course_id = course["id"]

        if course_id in seen_ids:
            continue

        seen_ids.add(course_id)
        unique.append(course)

    return unique


async def main() -> None:
    materials = await crawl_moodle_materials()
    write_materials_json(materials, MOODLE_OUTPUT_PATH)
    print(f"Wrote {len(materials)} Moodle materials to {MOODLE_OUTPUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
