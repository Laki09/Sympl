import json
import os
import re
import sqlite3
from contextlib import closing
from html.parser import HTMLParser
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import urljoin

import requests
from dotenv import dotenv_values
from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_ENV_PATH = Path(__file__).with_name(".env")
CONFIG = {
    **os.environ,
    **dotenv_values(BACKEND_ENV_PATH),
    **dotenv_values(ROOT_DIR / ".env"),
}

DIFY_API_BASE = CONFIG.get("DIFY_API_BASE", "https://api.dify.ai/v1").rstrip("/")
DIFY_API_KEY = CONFIG.get("DIFY_API_KEY")
DIFY_APP_MODE = CONFIG.get("DIFY_APP_MODE", "chat").lower()
DIFY_INPUT_KEY = CONFIG.get("DIFY_INPUT_KEY", "query")
FRONTEND_ORIGIN = CONFIG.get("FRONTEND_ORIGIN", "http://localhost:3000")
ENABLE_LIVE_PORTAL_CRAWLING = str(CONFIG.get("ENABLE_LIVE_PORTAL_CRAWLING", "")).lower() in {
    "1",
    "true",
    "yes",
}

app = FastAPI(title="Sympl Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN, "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    query: str = Field(min_length=1)
    conversationId: str | None = None
    user: str = "demo-user"


class ChatResponse(BaseModel):
    answer: str
    conversationId: str | None = None


class ServiceCredentialInput(BaseModel):
    serviceKey: str = Field(min_length=2)
    label: str = Field(min_length=2)
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    notes: str | None = None


class ServiceCredentialUpsertRequest(BaseModel):
    serviceKey: str = Field(min_length=2)
    label: str = Field(min_length=2)
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    notes: str | None = None


class UserAccountCreateRequest(BaseModel):
    user: str = Field(min_length=2)
    displayName: str = Field(min_length=2)
    services: list[ServiceCredentialInput] = Field(default_factory=list)


class UserAccountSummary(BaseModel):
    user: str
    displayName: str
    createdAt: str
    updatedAt: str


class UserAccountListResponse(BaseModel):
    users: list[UserAccountSummary]


class StoredServiceCredential(BaseModel):
    user: str
    serviceKey: str
    label: str
    username: str
    password: str
    notes: str | None = None
    createdAt: str
    updatedAt: str


class ServiceCredentialListResponse(BaseModel):
    user: str
    services: list[StoredServiceCredential]


class MaterialSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    keywords: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    limit: int = Field(default=5, ge=1, le=20)
    user: str = "demo-user"


class MaterialItem(BaseModel):
    id: str
    title: str
    source: str
    course: str
    type: str
    url: str
    summary: str
    tags: list[str]
    relevance: float
    reason: str | None = None
    matches: list[dict[str, Any]] = Field(default_factory=list)


class MaterialSearchResponse(BaseModel):
    query: str
    matchedKeywords: list[str]
    materials: list[MaterialItem]


class CrawledMaterialStatus(BaseModel):
    source: str
    cached: bool
    count: int
    path: str


class MaterialIndexStatus(BaseModel):
    cached: bool
    count: int
    path: str


class CrawledMaterialStatusResponse(BaseModel):
    sources: list[CrawledMaterialStatus]
    index: MaterialIndexStatus


SERVICE_LOGIN_URLS: dict[str, dict[str, str]] = {
    "artemis": {
        "baseUrl": "https://artemis.tum.de/",
        "loginUrl": "https://artemis.tum.de/",
    },
    "moodle": {
        "baseUrl": "https://www.moodle.tum.de/",
        "loginUrl": "https://www.moodle.tum.de/login/index.php",
    },
}


MOCK_MATERIALS: list[dict[str, Any]] = [
    {
        "id": "moodle-ml-week-04-slides",
        "title": "Woche 4: Lineare Regression und Gradientenabstieg",
        "source": "moodle",
        "course": "Machine Learning",
        "type": "slides",
        "url": "https://moodle.example.edu/course/ml/week-04-slides.pdf",
        "summary": "Vorlesungsfolien zu linearer Regression, Loss-Funktionen und Gradientenabstieg.",
        "tags": ["machine learning", "lineare regression", "gradient descent", "loss"],
    },
    {
        "id": "moodle-ml-exercise-04",
        "title": "Uebungsblatt 4: Regression",
        "source": "moodle",
        "course": "Machine Learning",
        "type": "exercise",
        "url": "https://moodle.example.edu/course/ml/exercise-04.pdf",
        "summary": "Aufgaben zu Normalengleichung, Regularisierung und Fehleranalyse.",
        "tags": ["machine learning", "uebungsblatt", "regression", "regularisierung"],
    },
    {
        "id": "artemis-ml-programming-02",
        "title": "Artemis Aufgabe: Gradient Descent Implementierung",
        "source": "artemis",
        "course": "Machine Learning",
        "type": "programming_exercise",
        "url": "https://artemis.example.edu/courses/ml/exercises/gradient-descent",
        "summary": "Programmieraufgabe zur Implementierung von Batch Gradient Descent in Python.",
        "tags": ["artemis", "python", "gradient descent", "machine learning"],
    },
    {
        "id": "moodle-db-week-02",
        "title": "Woche 2: SQL Joins und Aggregationen",
        "source": "moodle",
        "course": "Datenbanken",
        "type": "slides",
        "url": "https://moodle.example.edu/course/db/week-02-slides.pdf",
        "summary": "Grundlagen zu INNER JOIN, LEFT JOIN, GROUP BY und HAVING.",
        "tags": ["datenbanken", "sql", "joins", "aggregation"],
    },
    {
        "id": "artemis-db-quiz-joins",
        "title": "Artemis Quiz: SQL Joins",
        "source": "artemis",
        "course": "Datenbanken",
        "type": "quiz",
        "url": "https://artemis.example.edu/courses/db/quizzes/sql-joins",
        "summary": "Kurzes Quiz zu Join-Typen und typischen SQL-Fehlern.",
        "tags": ["artemis", "datenbanken", "sql", "joins", "quiz"],
    },
    {
        "id": "moodle-se-project-brief",
        "title": "Projektbeschreibung: Software Engineering Teamprojekt",
        "source": "moodle",
        "course": "Software Engineering",
        "type": "document",
        "url": "https://moodle.example.edu/course/se/project-brief.pdf",
        "summary": "Anforderungen, Bewertungsschema und Abgabefristen fuer das Teamprojekt.",
        "tags": ["software engineering", "projekt", "anforderungen", "deadline"],
    },
    {
        "id": "moodle-analysis2-chapter-03-script",
        "title": "Analysis 2: Kapitel 3 - Mehrdimensionale Differentialrechnung",
        "source": "moodle",
        "course": "Analysis 2",
        "type": "script",
        "url": "https://moodle.example.edu/course/analysis2/chapter-03.pdf",
        "summary": "Skriptkapitel zu partiellen Ableitungen, Gradienten, Jacobi-Matrizen und Taylor-Formeln.",
        "tags": ["analysis 2", "kapitel 3", "mehrdimensionale differentialrechnung", "gradient"],
    },
    {
        "id": "moodle-analysis2-exercise-03",
        "title": "Analysis 2: Uebungsblatt 3",
        "source": "moodle",
        "course": "Analysis 2",
        "type": "exercise",
        "url": "https://moodle.example.edu/course/analysis2/exercise-03.pdf",
        "summary": "Aufgaben zu partiellen Ableitungen, Richtungsableitungen und lokalen Extrema.",
        "tags": ["analysis 2", "uebungsblatt", "kapitel 3", "partielle ableitungen"],
    },
    {
        "id": "artemis-analysis2-quiz-03",
        "title": "Artemis Quiz: Analysis 2 Kapitel 3",
        "source": "artemis",
        "course": "Analysis 2",
        "type": "quiz",
        "url": "https://artemis.example.edu/courses/analysis2/quizzes/chapter-03",
        "summary": "Selbsttest zu Gradienten, Hesse-Matrizen und Extremwertproblemen.",
        "tags": ["analysis 2", "quiz", "kapitel 3", "gradient", "hesse matrix"],
    },
    {
        "id": "moodle-analysis3-chapter-03-script",
        "title": "Analysis 3: Kapitel 3 - Integration auf Mannigfaltigkeiten",
        "source": "moodle",
        "course": "Analysis 3",
        "type": "script",
        "url": "https://moodle.example.edu/course/analysis3/chapter-03.pdf",
        "summary": "Skriptkapitel zu Kurvenintegralen, Oberflaechenintegralen und Integralsaetzen.",
        "tags": ["analysis 3", "kapitel 3", "integration", "mannigfaltigkeiten", "stokes"],
    },
    {
        "id": "artemis-analysis3-exercise-03",
        "title": "Artemis Aufgabe: Analysis 3 Kapitel 3",
        "source": "artemis",
        "course": "Analysis 3",
        "type": "exercise",
        "url": "https://artemis.example.edu/courses/analysis3/exercises/chapter-03",
        "summary": "Aufgaben zu Kurvenintegralen, Flussintegralen und dem Satz von Stokes.",
        "tags": ["analysis 3", "kapitel 3", "kurvenintegral", "stokes"],
    },
]

DATABASE_PATH = ROOT_DIR / "backend" / "sympl.db"
SESSIONS_DIR = ROOT_DIR / "backend" / "sessions"
CRAWLED_MATERIAL_PATHS = {
    "artemis": SESSIONS_DIR / "artemis-materials.json",
    "moodle": SESSIONS_DIR / "moodle-materials.json",
}
MATERIAL_INDEX_PATH = SESSIONS_DIR / "material-index.json"


class CredentialStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._lock = Lock()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS service_credentials (
                    user TEXT NOT NULL,
                    service_key TEXT NOT NULL,
                    label TEXT NOT NULL,
                    username TEXT NOT NULL,
                    password TEXT NOT NULL,
                    notes TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user, service_key)
                )
                """
            )
            self._migrate_service_credentials_table(connection)
            self._bootstrap_users_from_credentials(connection)
            connection.commit()

    def _migrate_service_credentials_table(self, connection: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(service_credentials)").fetchall()
        }

        legacy_columns = {"base_url", "login_url"}
        if not legacy_columns.intersection(columns):
            return

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS service_credentials_v2 (
                user TEXT NOT NULL,
                service_key TEXT NOT NULL,
                label TEXT NOT NULL,
                username TEXT NOT NULL,
                password TEXT NOT NULL,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user, service_key)
            )
            """
        )
        connection.execute(
            """
            INSERT OR REPLACE INTO service_credentials_v2 (
                user,
                service_key,
                label,
                username,
                password,
                notes,
                created_at,
                updated_at
            )
            SELECT
                user,
                service_key,
                label,
                username,
                password,
                notes,
                created_at,
                updated_at
            FROM service_credentials
            """
        )
        connection.execute("DROP TABLE service_credentials")
        connection.execute("ALTER TABLE service_credentials_v2 RENAME TO service_credentials")

    def _bootstrap_users_from_credentials(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO users (user, display_name)
            SELECT DISTINCT user, user
            FROM service_credentials
            WHERE user IS NOT NULL AND TRIM(user) != ''
            """
        )

    def list_users(self) -> list[UserAccountSummary]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT user, display_name, created_at, updated_at
                FROM users
                ORDER BY display_name COLLATE NOCASE, user COLLATE NOCASE
                """
            ).fetchall()

        return [
            UserAccountSummary(
                user=row["user"],
                displayName=row["display_name"],
                createdAt=row["created_at"],
                updatedAt=row["updated_at"],
            )
            for row in rows
        ]

    def create_user(self, payload: UserAccountCreateRequest) -> UserAccountSummary:
        normalized_user = normalize_user_key(payload.user)

        with self._lock, closing(self._connect()) as connection:
            existing = connection.execute(
                "SELECT user FROM users WHERE user = ?",
                (normalized_user,),
            ).fetchone()

            if existing is not None:
                raise HTTPException(status_code=409, detail="User already exists.")

            connection.execute(
                """
                INSERT INTO users (user, display_name)
                VALUES (?, ?)
                """,
                (normalized_user, payload.displayName.strip()),
            )

            for service in payload.services:
                normalized_service = slugify_service_key(service.serviceKey)
                connection.execute(
                    """
                    INSERT INTO service_credentials (
                        user,
                        service_key,
                        label,
                        username,
                        password,
                        notes
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        normalized_user,
                        normalized_service,
                        service.label.strip(),
                        service.username.strip(),
                        service.password,
                        service.notes.strip() if service.notes else None,
                    ),
                )

            connection.commit()
            row = connection.execute(
                """
                SELECT user, display_name, created_at, updated_at
                FROM users
                WHERE user = ?
                """,
                (normalized_user,),
            ).fetchone()

        if row is None:
            raise HTTPException(status_code=500, detail="User account could not be stored.")

        return UserAccountSummary(
            user=row["user"],
            displayName=row["display_name"],
            createdAt=row["created_at"],
            updatedAt=row["updated_at"],
        )

    def list_services(self, user: str) -> list[StoredServiceCredential]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT
                    user,
                    service_key,
                    label,
                    username,
                    password,
                    notes,
                    created_at,
                    updated_at
                FROM service_credentials
                WHERE user = ?
                ORDER BY label COLLATE NOCASE, service_key COLLATE NOCASE
                """,
                (user,),
            ).fetchall()

        return [self._row_to_credential(row) for row in rows]

    def upsert_service(
        self, user: str, payload: ServiceCredentialUpsertRequest
    ) -> StoredServiceCredential:
        normalized_key = slugify_service_key(payload.serviceKey)
        with self._lock, closing(self._connect()) as connection:
            self._ensure_user_exists(connection, user)
            connection.execute(
                """
                INSERT INTO service_credentials (
                    user,
                    service_key,
                    label,
                    username,
                    password,
                    notes
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user, service_key)
                DO UPDATE SET
                    label = excluded.label,
                    username = excluded.username,
                    password = excluded.password,
                    notes = excluded.notes,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    user,
                    normalized_key,
                    payload.label.strip(),
                    payload.username.strip(),
                    payload.password,
                    payload.notes.strip() if payload.notes else None,
                ),
            )
            connection.commit()
            row = connection.execute(
                """
                SELECT
                    user,
                    service_key,
                    label,
                    username,
                    password,
                    notes,
                    created_at,
                    updated_at
                FROM service_credentials
                WHERE user = ? AND service_key = ?
                """,
                (user, normalized_key),
            ).fetchone()

        if row is None:
            raise HTTPException(status_code=500, detail="Credential could not be stored.")

        return self._row_to_credential(row)

    def delete_service(self, user: str, service_key: str) -> None:
        normalized_key = slugify_service_key(service_key)
        with self._lock, closing(self._connect()) as connection:
            cursor = connection.execute(
                "DELETE FROM service_credentials WHERE user = ? AND service_key = ?",
                (user, normalized_key),
            )
            connection.commit()

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Service credentials not found.")

    @staticmethod
    def _ensure_user_exists(connection: sqlite3.Connection, user: str) -> None:
        row = connection.execute("SELECT user FROM users WHERE user = ?", (user,)).fetchone()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail="User account not found. Create the account before storing service credentials.",
            )

    @staticmethod
    def _row_to_credential(row: sqlite3.Row) -> StoredServiceCredential:
        return StoredServiceCredential(
            user=row["user"],
            serviceKey=row["service_key"],
            label=row["label"],
            username=row["username"],
            password=row["password"],
            notes=row["notes"],
            createdAt=row["created_at"],
            updatedAt=row["updated_at"],
        )


credential_store = CredentialStore(DATABASE_PATH)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/users", response_model=UserAccountListResponse)
def list_users() -> UserAccountListResponse:
    return UserAccountListResponse(users=credential_store.list_users())


@app.post("/api/users", response_model=UserAccountSummary)
def create_user(payload: UserAccountCreateRequest) -> UserAccountSummary:
    return credential_store.create_user(payload)


@app.get("/api/users/{user}/services", response_model=ServiceCredentialListResponse)
def list_service_credentials(user: str) -> ServiceCredentialListResponse:
    normalized_user = normalize_user_key(user)
    return ServiceCredentialListResponse(
        user=normalized_user,
        services=credential_store.list_services(normalized_user),
    )


@app.post("/api/users/{user}/services", response_model=StoredServiceCredential)
def upsert_service_credentials(
    user: str, payload: ServiceCredentialUpsertRequest
) -> StoredServiceCredential:
    return credential_store.upsert_service(normalize_user_key(user), payload)


@app.delete("/api/users/{user}/services/{service_key}")
def delete_service_credentials(user: str, service_key: str) -> dict[str, str]:
    credential_store.delete_service(normalize_user_key(user), service_key)
    return {"status": "deleted"}


@app.get("/api/materials/status", response_model=CrawledMaterialStatusResponse)
def material_status() -> CrawledMaterialStatusResponse:
    return CrawledMaterialStatusResponse(
        sources=[
            CrawledMaterialStatus(
                source=source,
                cached=path.exists(),
                count=len(load_crawled_materials(source)),
                path=str(path.relative_to(ROOT_DIR)),
            )
            for source, path in sorted(CRAWLED_MATERIAL_PATHS.items())
        ],
        index=MaterialIndexStatus(
            cached=MATERIAL_INDEX_PATH.exists(),
            count=len(load_material_index()),
            path=str(MATERIAL_INDEX_PATH.relative_to(ROOT_DIR)),
        ),
    )


@app.post("/api/materials/search", response_model=MaterialSearchResponse)
def search_materials(raw_payload: dict[str, Any] = Body(default_factory=dict)) -> MaterialSearchResponse:
    payload = normalize_material_search_payload(raw_payload)
    requested_terms = normalize_terms([payload.query, *payload.keywords])
    requested_sources = {source.lower() for source in payload.sources}
    credentials_by_source = get_credentials_by_source(payload.user)

    candidate_materials: list[dict[str, Any]] = []
    indexed_materials = search_indexed_materials(requested_terms, requested_sources)

    if indexed_materials:
        candidate_materials.extend(indexed_materials)
    else:
        if not requested_sources or "moodle" in requested_sources:
            candidate_materials.extend(
                search_moodle_materials(payload, credentials_by_source.get("moodle"))
            )

        if not requested_sources or "artemis" in requested_sources:
            candidate_materials.extend(
                search_artemis_materials(payload, credentials_by_source.get("artemis"))
            )

    if not candidate_materials:
        candidate_materials = [
            material
            for material in MOCK_MATERIALS
            if not requested_sources or material["source"].lower() in requested_sources
        ]

    ranked_materials: list[MaterialItem] = []

    for material in candidate_materials:
        score = calculate_material_score(material, requested_terms)

        if score <= 0 and requested_terms:
            continue

        ranked_materials.append(MaterialItem(**material, relevance=score))

    ranked_materials.sort(key=lambda item: item.relevance, reverse=True)

    return MaterialSearchResponse(
        query=payload.query,
        matchedKeywords=requested_terms,
        materials=ranked_materials[: payload.limit],
    )


@app.post("/api/chat", response_model=ChatResponse)
def chat(payload: ChatRequest) -> ChatResponse:
    if not DIFY_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="DIFY_API_KEY is missing. Add it to backend/.env or your environment.",
        )

    try:
        response = requests.post(**build_dify_request(payload))
        response.raise_for_status()
    except requests.HTTPError as error:
        detail = error.response.text if error.response is not None else str(error)
        raise HTTPException(status_code=502, detail=f"Dify request failed: {detail}") from error
    except requests.RequestException as error:
        raise HTTPException(status_code=502, detail=f"Dify is unreachable: {error}") from error

    data = response.json()

    return parse_dify_response(data)


def build_dify_request(payload: ChatRequest) -> dict[str, Any]:
    service_credentials = serialize_service_credentials(payload.user)
    headers = {
        "Authorization": f"Bearer {DIFY_API_KEY}",
        "Content-Type": "application/json",
    }

    if DIFY_APP_MODE == "chat":
        body: dict[str, Any] = {
            "inputs": {
                "service_credentials": service_credentials,
                "available_services": [service["serviceKey"] for service in service_credentials],
            },
            "query": payload.query,
            "response_mode": "blocking",
            "user": payload.user,
        }

        if payload.conversationId:
            body["conversation_id"] = payload.conversationId

        return {
            "url": f"{DIFY_API_BASE}/chat-messages",
            "headers": headers,
            "json": body,
            "timeout": 60,
        }

    if DIFY_APP_MODE == "workflow":
        return {
            "url": f"{DIFY_API_BASE}/workflows/run",
            "headers": headers,
            "json": {
                "inputs": {
                    DIFY_INPUT_KEY: payload.query,
                    "service_credentials": service_credentials,
                    "available_services": [service["serviceKey"] for service in service_credentials],
                },
                "response_mode": "blocking",
                "user": payload.user,
            },
            "timeout": 60,
        }

    if DIFY_APP_MODE == "completion":
        return {
            "url": f"{DIFY_API_BASE}/completion-messages",
            "headers": headers,
            "json": {
                "inputs": {
                    DIFY_INPUT_KEY: payload.query,
                    "service_credentials": service_credentials,
                    "available_services": [service["serviceKey"] for service in service_credentials],
                },
                "response_mode": "blocking",
                "user": payload.user,
            },
            "timeout": 60,
        }

    raise HTTPException(
        status_code=500,
        detail="DIFY_APP_MODE must be one of: chat, workflow, completion.",
    )


def parse_dify_response(data: dict[str, Any]) -> ChatResponse:
    if DIFY_APP_MODE in {"chat", "completion"}:
        return ChatResponse(
            answer=data.get("answer", ""),
            conversationId=data.get("conversation_id"),
        )

    outputs = data.get("data", {}).get("outputs", {})
    answer = extract_workflow_answer(outputs)

    if not answer:
        answer = str(outputs) if outputs else "Der Workflow hat keine Antwort ausgegeben."

    return ChatResponse(answer=answer)


def extract_workflow_answer(outputs: Any) -> str:
    if isinstance(outputs, str):
        return outputs

    if not isinstance(outputs, dict):
        return ""

    preferred_keys = [
        "answer",
        "text",
        "result",
        "output",
        "response",
        "content",
        "final_answer",
        "finalAnswer",
        "summary",
    ]

    for key in preferred_keys:
        value = outputs.get(key)
        answer = stringify_answer_value(value)

        if answer:
            return answer

    for value in outputs.values():
        answer = stringify_answer_value(value)

        if answer:
            return answer

    return ""


def stringify_answer_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()

    if isinstance(value, (int, float, bool)):
        return str(value)

    if isinstance(value, list):
        parts = [stringify_answer_value(item) for item in value]
        return "\n".join(part for part in parts if part).strip()

    if isinstance(value, dict):
        nested_answer = extract_workflow_answer(value)

        if nested_answer:
            return nested_answer

        return json.dumps(value, ensure_ascii=False)

    return ""


def normalize_material_search_payload(raw_payload: dict[str, Any]) -> MaterialSearchRequest:
    query = (
        raw_payload.get("query")
        or raw_payload.get("prompt")
        or raw_payload.get("Prompt")
        or raw_payload.get("text")
        or raw_payload.get("input")
        or ""
    )

    keywords = ensure_string_list(raw_payload.get("keywords"))
    sources = ensure_string_list(raw_payload.get("sources")) or ["moodle", "artemis"]
    user = (
        raw_payload.get("user")
        or raw_payload.get("sys_user_id")
        or raw_payload.get("sys.user_id")
        or raw_payload.get("userId")
        or "demo-user"
    )

    try:
        limit = int(raw_payload.get("limit", 5))
    except (TypeError, ValueError):
        limit = 5

    if not str(query).strip():
        raise HTTPException(
            status_code=400,
            detail=(
                "Missing search query. Send one of these JSON fields: "
                "query, prompt, Prompt, text, input."
            ),
        )

    return MaterialSearchRequest(
        query=str(query).strip(),
        keywords=keywords,
        sources=sources,
        limit=max(1, min(limit, 20)),
        user=normalize_user_key(str(user)),
    )


def ensure_string_list(value: Any) -> list[str]:
    if value is None:
        return []

    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]

    if isinstance(value, str):
        stripped = value.strip()

        if not stripped:
            return []

        return [item.strip() for item in stripped.split(",") if item.strip()]

    return [str(value).strip()] if str(value).strip() else []


def normalize_terms(values: list[str]) -> list[str]:
    stopwords = {
        "a",
        "about",
        "an",
        "and",
        "for",
        "in",
        "learn",
        "of",
        "on",
        "or",
        "the",
        "to",
        "today",
        "want",
        "ich",
        "will",
        "möchte",
        "moechte",
        "lernen",
        "bitte",
        "zum",
        "zur",
        "der",
        "die",
        "das",
        "ein",
        "eine",
        "und",
        "oder",
    }
    synonyms = {
        "continuity": ["stetigkeit"],
        "continuous": ["stetig"],
        "convergence": ["konvergenz"],
        "derivative": ["ableitung"],
        "derivatives": ["ableitungen"],
        "differentiation": ["differentialrechnung"],
        "function": ["funktion"],
        "functions": ["funktionen"],
        "limit": ["grenzwert"],
        "limits": ["grenzwerte"],
        "real": ["reell", "reelle"],
        "sequence": ["folge"],
        "sequences": ["folgen"],
        "series": ["reihen"],
        "summation": ["reihen"],
        "taylor": ["taylor", "taylorentwicklung"],
    }
    terms: list[str] = []

    for value in values:
        for raw_term in value.lower().replace(",", " ").split():
            term = raw_term.strip()

            if term in stopwords:
                continue

            if (len(term) >= 3 or term.isdigit()) and term not in terms:
                terms.append(term)

                for synonym in synonyms.get(term, []):
                    if synonym not in terms:
                        terms.append(synonym)

    return terms


def serialize_service_credentials(user: str) -> list[dict[str, str | None]]:
    services = credential_store.list_services(normalize_user_key(user))
    return [
        {
            "serviceKey": service.serviceKey,
            "label": service.label,
            "baseUrl": SERVICE_LOGIN_URLS.get(service.serviceKey, {}).get("baseUrl"),
            "loginUrl": SERVICE_LOGIN_URLS.get(service.serviceKey, {}).get("loginUrl"),
            "username": service.username,
            "hasPassword": "true" if service.password else "false",
            "notes": service.notes,
        }
        for service in services
    ]


def get_credentials_by_source(user: str) -> dict[str, StoredServiceCredential]:
    return {
        service.serviceKey: service
        for service in credential_store.list_services(normalize_user_key(user))
    }


def search_moodle_materials(
    payload: MaterialSearchRequest,
    credential: StoredServiceCredential | None,
) -> list[dict[str, Any]]:
    cached_materials = load_crawled_materials("moodle")
    if cached_materials:
        return cached_materials

    source_materials = [
        material for material in MOCK_MATERIALS if material["source"].lower() == "moodle"
    ]

    if not credential or not ENABLE_LIVE_PORTAL_CRAWLING:
        return source_materials

    live_materials = fetch_public_portal_links(
        source="moodle",
        base_url=SERVICE_LOGIN_URLS["moodle"]["baseUrl"],
        course_hint=payload.query,
    )

    return live_materials or source_materials


def search_artemis_materials(
    payload: MaterialSearchRequest,
    credential: StoredServiceCredential | None,
) -> list[dict[str, Any]]:
    cached_materials = load_crawled_materials("artemis")
    if cached_materials:
        return cached_materials

    source_materials = [
        material for material in MOCK_MATERIALS if material["source"].lower() == "artemis"
    ]

    if not credential or not ENABLE_LIVE_PORTAL_CRAWLING:
        return source_materials

    live_materials = fetch_public_portal_links(
        source="artemis",
        base_url=SERVICE_LOGIN_URLS["artemis"]["baseUrl"],
        course_hint=payload.query,
    )

    return live_materials or source_materials


def search_indexed_materials(
    requested_terms: list[str],
    requested_sources: set[str],
) -> list[dict[str, Any]]:
    indexed_items = load_material_index()
    materials: list[dict[str, Any]] = []

    for indexed_item in indexed_items:
        source = str(indexed_item.get("source") or "").lower()

        if requested_sources and source not in requested_sources:
            continue

        matches = find_index_matches(indexed_item, requested_terms)
        text_preview = str(indexed_item.get("textPreview") or "")
        topics = ensure_string_list(indexed_item.get("topics"))
        tags = ensure_string_list(indexed_item.get("tags")) + topics[:8]
        summary = str(indexed_item.get("summary") or indexed_item.get("title") or "")

        if matches:
            best_match = matches[0]
            summary = f"{summary} Relevant snippet page {best_match['page']}: {best_match['snippet']}"

        materials.append(
            {
                "id": str(indexed_item.get("id") or indexed_item.get("url")),
                "title": str(indexed_item.get("title") or ""),
                "source": source,
                "course": str(indexed_item.get("course") or "Unknown course"),
                "type": str(indexed_item.get("type") or "link"),
                "url": str(indexed_item.get("url") or ""),
                "summary": summary,
                "tags": tags,
                "searchText": " ".join(
                    [
                        text_preview,
                        " ".join(topics),
                        json.dumps(indexed_item.get("chapters") or [], ensure_ascii=False),
                    ]
                ),
                "reason": build_index_reason(matches, topics),
                "matches": matches[:3],
            }
        )

    return materials


def load_material_index() -> list[dict[str, Any]]:
    if not MATERIAL_INDEX_PATH.exists():
        return []

    try:
        raw_items = json.loads(MATERIAL_INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    return [item for item in raw_items if isinstance(item, dict)]


def find_index_matches(indexed_item: dict[str, Any], terms: list[str]) -> list[dict[str, Any]]:
    if not terms:
        return []

    matches: list[dict[str, Any]] = []

    for page in indexed_item.get("pages") or []:
        if not isinstance(page, dict):
            continue

        text = str(page.get("text") or "")
        lower_text = text.lower()
        hit_terms = [term for term in terms if term in lower_text]

        if not hit_terms:
            continue

        matches.append(
            {
                "page": page.get("page"),
                "snippet": build_snippet(text, hit_terms[0]),
                "terms": hit_terms,
            }
        )

    matches.sort(key=lambda match: len(match["terms"]), reverse=True)
    return matches


def build_snippet(text: str, term: str, radius: int = 220) -> str:
    lower_text = text.lower()
    index = lower_text.find(term.lower())

    if index < 0:
        return text[: radius * 2].strip()

    start = max(index - radius, 0)
    end = min(index + len(term) + radius, len(text))
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return f"{prefix}{text[start:end].strip()}{suffix}"


def build_index_reason(matches: list[dict[str, Any]], topics: list[str]) -> str | None:
    if matches:
        first_match = matches[0]
        terms = ", ".join(first_match.get("terms") or [])
        return f"PDF text match on page {first_match.get('page')} for: {terms}"

    if topics:
        return f"Indexed PDF topics include: {', '.join(topics[:5])}"

    return None


def load_crawled_materials(source: str) -> list[dict[str, Any]]:
    path = CRAWLED_MATERIAL_PATHS.get(source)
    if not path or not path.exists():
        return []

    try:
        raw_materials = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    materials: list[dict[str, Any]] = []

    for index, raw_material in enumerate(raw_materials, start=1):
        if not isinstance(raw_material, dict):
            continue

        title = str(raw_material.get("title") or "").strip()
        url = str(raw_material.get("url") or "").strip()

        if not title or not url:
            continue

        material_source = str(raw_material.get("source") or source).lower()
        material_type = str(
            raw_material.get("type") or infer_material_type(title, url)
        )
        tags = ensure_string_list(raw_material.get("tags")) or [material_source, material_type]

        materials.append(
            {
                "id": str(raw_material.get("id") or f"{material_source}-cached-{index}"),
                "title": title,
                "source": material_source,
                "course": str(raw_material.get("course") or "Unknown course"),
                "type": material_type,
                "url": url,
                "summary": str(raw_material.get("summary") or title),
                "tags": tags,
            }
        )

    return materials


def fetch_public_portal_links(source: str, base_url: str, course_hint: str) -> list[dict[str, Any]]:
    try:
        response = requests.get(base_url, timeout=12)
        response.raise_for_status()
    except requests.RequestException:
        return []

    extractor = LinkExtractor(base_url)
    extractor.feed(response.text)

    materials: list[dict[str, Any]] = []

    for index, link in enumerate(extractor.links[:30], start=1):
        title = link["text"] or link["url"]
        materials.append(
            {
                "id": f"{source}-live-{index}",
                "title": title[:160],
                "source": source,
                "course": course_hint,
                "type": infer_material_type(title, link["url"]),
                "url": link["url"],
                "summary": f"Live gefundener Link aus {source}: {title}",
                "tags": [source, course_hint, infer_material_type(title, link["url"])],
            }
        )

    return materials


class LinkExtractor(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.links: list[dict[str, str]] = []
        self._current_href: str | None = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return

        href = dict(attrs).get("href")
        if not href:
            return

        self._current_href = urljoin(self.base_url, href)
        self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_href:
            self._current_text.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._current_href:
            return

        text = " ".join(part for part in self._current_text if part).strip()

        if self._current_href.startswith("http"):
            self.links.append({"url": self._current_href, "text": text})

        self._current_href = None
        self._current_text = []


def infer_material_type(title: str, url: str) -> str:
    value = f"{title} {url}".lower()

    if ".pdf" in value or "script" in value or "skript" in value:
        return "script"

    if "exercise" in value or "uebung" in value or "übung" in value or "aufgabe" in value:
        return "exercise"

    if "quiz" in value:
        return "quiz"

    if "slide" in value or "folie" in value:
        return "slides"

    return "link"


def slugify_service_key(raw_value: str) -> str:
    normalized = "".join(
        character.lower() if character.isalnum() else "-"
        for character in raw_value.strip()
    )
    compact = "-".join(part for part in normalized.split("-") if part)
    if len(compact) < 2:
        raise HTTPException(status_code=422, detail="serviceKey must contain letters or numbers.")
    return compact


def normalize_user_key(raw_value: str) -> str:
    normalized = raw_value.strip().lower()
    if len(normalized) < 2:
        raise HTTPException(status_code=422, detail="user must contain at least 2 characters.")
    return normalized


def calculate_material_score(material: dict[str, Any], terms: list[str]) -> float:
    if not terms:
        return 0.5

    title = material["title"].lower()
    course = material["course"].lower()
    summary = material["summary"].lower()
    tags = " ".join(material["tags"]).lower()
    type_value = material["type"].lower()
    search_text = str(material.get("searchText") or "").lower()
    weighted_score = 0.0
    max_score = len(terms) * 5.5

    for term in terms:
        if term.isdigit():
            term_pattern = re.compile(rf"(?<![\d.]){re.escape(term)}(?![\d.])")
            term_hits = {
                "title": bool(term_pattern.search(title)),
                "course": bool(term_pattern.search(course)),
                "summary": bool(term_pattern.search(summary)),
                "tags": bool(term_pattern.search(tags)),
                "searchText": bool(term_pattern.search(search_text)),
            }
        else:
            term_hits = {
                "title": term in title,
                "course": term in course,
                "summary": term in summary,
                "tags": term in tags,
                "searchText": term in search_text,
            }

        if term_hits["title"]:
            weighted_score += 2.0
        if term_hits["course"]:
            weighted_score += 1.5
        if term_hits["summary"]:
            weighted_score += 0.4
        if term_hits["tags"]:
            weighted_score += 0.1
        if term_hits["searchText"]:
            weighted_score += 1.5

    if "script" in type_value or "exercise" in type_value:
        weighted_score += 0.15

    if material.get("matches"):
        weighted_score += 0.4

    return round(min(weighted_score / max_score, 1.0), 2)
