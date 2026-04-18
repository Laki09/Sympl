import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")
load_dotenv(Path(__file__).with_name(".env"), override=True)

DIFY_API_BASE = os.getenv("DIFY_API_BASE", "https://api.dify.ai/v1").rstrip("/")
DIFY_API_KEY = os.getenv("DIFY_API_KEY")
DIFY_APP_MODE = os.getenv("DIFY_APP_MODE", "chat").lower()
DIFY_INPUT_KEY = os.getenv("DIFY_INPUT_KEY", "query")
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")

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


class MaterialSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    keywords: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    limit: int = Field(default=5, ge=1, le=20)


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


class MaterialSearchResponse(BaseModel):
    query: str
    matchedKeywords: list[str]
    materials: list[MaterialItem]


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
]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/materials/search", response_model=MaterialSearchResponse)
def search_materials(raw_payload: dict[str, Any] = Body(default_factory=dict)) -> MaterialSearchResponse:
    payload = normalize_material_search_payload(raw_payload)
    requested_terms = normalize_terms([payload.query, *payload.keywords])
    requested_sources = {source.lower() for source in payload.sources}

    ranked_materials: list[MaterialItem] = []

    for material in MOCK_MATERIALS:
        if requested_sources and material["source"].lower() not in requested_sources:
            continue

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
    headers = {
        "Authorization": f"Bearer {DIFY_API_KEY}",
        "Content-Type": "application/json",
    }

    if DIFY_APP_MODE == "chat":
        body: dict[str, Any] = {
            "inputs": {},
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
                "inputs": {DIFY_INPUT_KEY: payload.query},
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
                "inputs": {DIFY_INPUT_KEY: payload.query},
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
    answer = outputs.get("answer") or outputs.get("text") or outputs.get("result")

    if not answer:
        answer = str(outputs) if outputs else "Der Workflow hat keine Antwort ausgegeben."

    return ChatResponse(answer=answer)


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
    terms: list[str] = []

    for value in values:
        for raw_term in value.lower().replace(",", " ").split():
            term = raw_term.strip()

            if len(term) >= 3 and term not in terms:
                terms.append(term)

    return terms


def calculate_material_score(material: dict[str, Any], terms: list[str]) -> float:
    searchable_text = " ".join(
        [
            material["title"],
            material["source"],
            material["course"],
            material["type"],
            material["summary"],
            " ".join(material["tags"]),
        ],
    ).lower()

    if not terms:
        return 0.5

    hits = sum(1 for term in terms if term in searchable_text)
    return round(hits / len(terms), 2)
