# Sympl

Sympl is an AI study assistant that helps students find the right course
materials faster. A student can ask a natural-language question such as:

```text
I want to learn about sequences and series in my Analysis 1 course.
```

Sympl searches locally crawled Moodle and Artemis materials, ranks relevant
documents, and uses a Dify workflow to generate a concise learning answer with
links to the most useful PDFs, exercises, lecture notes, and solutions.

## Demo Flow

1. The student logs into the Sympl frontend.
2. The student asks a study question in the chat.
3. The frontend sends the request to the FastAPI backend.
4. The backend forwards the prompt to the Dify workflow.
5. Dify calls the backend material-search endpoint.
6. The backend searches the local Moodle/Artemis material index.
7. Dify filters the material list and writes the final answer.
8. The frontend renders the answer as Markdown with clickable links.

## Tech Stack

**Frontend**

- Next.js
- React
- TypeScript
- CSS
- React Markdown for rendering structured AI answers

**Backend**

- Python
- FastAPI
- Pydantic
- SQLite for local prototype user/service state

**AI Orchestration**

- Dify Workflow
- LLM nodes for prompt analysis, relevance filtering, and answer generation
- HTTP node for calling the backend material-search API

**Crawling and Retrieval**

- Playwright for Moodle and Artemis browser/session automation
- Custom Moodle connector
- Custom Artemis connector
- PyMuPDF for PDF text extraction
- Local JSON material index for topic and keyword search

**Local Integration**

- REST APIs between frontend, backend, and Dify
- ngrok for exposing the local backend to Dify Cloud during development

## Architecture

```text
Frontend
  -> FastAPI Backend
      -> Dify Workflow
          -> Backend /api/materials/search
              -> Moodle crawl cache
              -> Artemis crawl cache
              -> PDF text index
          -> Final AI answer
  -> Frontend Markdown rendering
```

The browser never talks to Dify directly. The Dify API key stays in the backend.

## Project Structure

```text
backend/
  main.py                         FastAPI app and API endpoints
  requirements.txt                Python dependencies
  .env.example                    Backend environment template
  connectors/
    moodle.py                     Moodle crawler
    artemis.py                    Artemis crawler
    common.py                     Shared crawler helpers
  indexing/
    material_indexer.py           Builds the searchable material index
    pdf_fetcher.py                Downloads PDFs using stored browser sessions
    pdf_text_extractor.py         Extracts text from PDFs
  sessions/                       Local crawl output and browser sessions

frontend/
  src/app/                        Next.js app shell and global styles
  src/components/chat-panel.tsx   Login and chat UI
  src/lib/                        API client and shared types
  .env.example                    Frontend environment template
```

`backend/sessions/` is intentionally local runtime data and should not be
committed.

## Setup

### Backend

Create and activate a Python virtual environment from the project root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
```

Edit `backend/.env`:

```env
DIFY_API_BASE=https://api.dify.ai/v1
DIFY_API_KEY=your-dify-workflow-api-key
DIFY_APP_MODE=workflow
DIFY_INPUT_KEY=Prompt
FRONTEND_ORIGIN=http://localhost:3000
ENABLE_LIVE_PORTAL_CRAWLING=false
```

Start the backend:

```bash
./.venv/bin/uvicorn backend.main:app --reload --port 8000
```

Health check:

```bash
curl http://localhost:8000/health
```

### Frontend

In a second terminal:

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

`frontend/.env.local` should point to the backend:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

Open:

```text
http://localhost:3000
```

## Dify Workflow Setup

Create a Dify Workflow app with this structure:

```text
Start
  -> Prompt Processing
  -> HTTP Request: Material Search
  -> Relevance Filter
  -> Final Answer
  -> End
```

The Start node should contain one required text input:

```text
Prompt
```

The backend expects:

```env
DIFY_APP_MODE=workflow
DIFY_INPUT_KEY=Prompt
```

### Prompt Processing Node

This node should extract a search query, keywords, sources, and intent from the
user request. It is useful to include German topic synonyms because many TUM
materials are written in German.

Example desired JSON:

```json
{
  "query": "Analysis 1 Folgen Reihen",
  "keyword": ["sequences", "series", "Folgen", "Reihen", "Analysis 1"],
  "sources": ["moodle", "artemis"],
  "intent": "find_relevant_study_materials"
}
```

### Material Search HTTP Node

For local Dify Cloud testing, expose the backend with ngrok:

```bash
ngrok http 8000
```

Use the public ngrok URL in the HTTP node:

```http
POST https://your-ngrok-url.ngrok-free.app/api/materials/search
Content-Type: application/json
```

Example body:

```json
{
  "user": "{{ sys.user_id }}",
  "query": "{{ Prompt-Verarbeitung.query }}",
  "keywords": {{ Prompt-Verarbeitung.keyword }},
  "sources": ["moodle", "artemis"],
  "limit": 8
}
```

The exact variable names depend on the names of your Dify nodes. The important
part is that `query` is a plain string and `keywords` is an array, not a string
with extra braces.

### Relevance Filter Node

The relevance filter receives:

- the original user request
- the JSON body from the HTTP material-search node

It should return only relevant materials and must not invent URLs.

### Final Answer Node

The final answer node should produce a Markdown answer with:

1. A short assessment
2. Relevant materials with links
3. Suggested next steps

The End node should expose the result as:

```text
answer
```

The backend can parse Dify workflow outputs named `answer`, `text`, or `result`.

## Crawling Moodle and Artemis

The crawler stores browser session state and crawl output under
`backend/sessions/`.

Run the Artemis crawler:

```bash
ARTEMIS_HEADLESS=true ./.venv/bin/python -m backend.connectors.artemis
```

Run the Moodle crawler:

```bash
MOODLE_HEADLESS=true ./.venv/bin/python -m backend.connectors.moodle
```

For visible browser debugging:

```bash
ARTEMIS_HEADLESS=false ARTEMIS_SLOW_MO=300 ./.venv/bin/python -m backend.connectors.artemis
MOODLE_HEADLESS=false ./.venv/bin/python -m backend.connectors.moodle
```

If login is required, run the crawler in headed mode, complete the SSO login in
the opened browser, and let Playwright save the browser session state.

## Building the Material Index

After crawling, build the searchable PDF index:

```bash
./.venv/bin/python -m backend.indexing.material_indexer
```

The indexer:

1. Reads `backend/sessions/moodle-materials.json`
2. Reads `backend/sessions/artemis-materials.json`
3. Downloads linked PDFs using the stored browser session cookies
4. Extracts PDF text with PyMuPDF
5. Writes `backend/sessions/material-index.json`

The `/api/materials/search` endpoint uses this index to find materials by title,
course, tags, and extracted PDF text.

## Useful API Endpoints

Health check:

```bash
curl http://localhost:8000/health
```

Material status:

```bash
curl http://localhost:8000/api/materials/status
```

Material search:

```bash
curl -X POST http://localhost:8000/api/materials/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "I want to learn about sequences and series in Analysis 1",
    "keywords": ["sequences", "series", "Folgen", "Reihen"],
    "sources": ["moodle", "artemis"],
    "limit": 8
  }'
```

Chat endpoint:

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "query": "I want to learn about sequences and series in Analysis 1",
    "user": "demo-user"
  }'
```

## Security and Privacy

Do not commit local secrets, browser sessions, private course materials, or local
databases.

These files and folders must stay local:

```text
.env
backend/.env
frontend/.env.local
backend/sympl.db
backend/sessions/
backend/sessions/*storage-state.json
backend/sessions/pdf-cache/
```

`backend/.env.example` and `frontend/.env.example` are safe to commit because
they contain placeholders only.

## Known Limitations

- The current version is optimized for a local MVP/demo setup.
- Moodle and Artemis access depends on valid user sessions and university SSO.
- The material index is stored locally as JSON instead of in a production vector
  database.
- The crawler should be rate-limited and used responsibly to avoid unnecessary
  load on university systems.
- For deployment, replace ngrok with a hosted backend such as Cloud Run, ECS,
  or another managed service.

