# Sympl

## Dify Connection

The browser never talks to Dify directly. The frontend calls your FastAPI backend,
and the backend calls the published Dify app with the Dify API key.

The backend now also stores per-user service credentials in a local SQLite database
at `backend/sympl.db`. These credentials are forwarded to Dify on every chat request
as `service_credentials` and `available_services`, so your workflow can decide when
extra portals such as Moodle, Artemis, or other university pages are needed.

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `backend/.env`:

```bash
DIFY_API_BASE=https://api.dify.ai/v1
DIFY_API_KEY=your-real-dify-workflow-api-key
DIFY_APP_MODE=workflow
DIFY_INPUT_KEY=Prompt
FRONTEND_ORIGIN=http://localhost:3000
ENABLE_LIVE_PORTAL_CRAWLING=false
```

The project is configured for a Dify Workflow by default:

- `DIFY_APP_MODE=workflow` calls `/workflows/run`
- `DIFY_INPUT_KEY=Prompt` must match the Start node input variable in Dify
- `DIFY_API_KEY` must be the API key of the published Dify Workflow app

If your Dify workflow input variable is called `message`, set:

```bash
DIFY_INPUT_KEY=message
```

For this project, use `Prompt` in Dify so the default works without changes.

### Dify Workflow Setup

Build this in your Dify workspace:

```text
Start
  -> LLM: Prompt Analyzer
  -> HTTP Request: Material Search
  -> LLM: Relevance Filter
  -> LLM: Final Answer Composer
  -> End
```

Start node input:

```text
Prompt
```

Prompt Analyzer should return JSON:

```json
{
  "query": "short search query",
  "keywords": ["keyword1", "keyword2"],
  "sources": ["moodle", "artemis"],
  "intent": "find_relevant_study_materials"
}
```

Material Search HTTP node:

```http
POST https://your-public-backend-url/api/materials/search
Content-Type: application/json
```

Body:

```json
{
  "user": "{{ sys.user_id }}",
  "query": "{{ prompt_analyzer.query }}",
  "keywords": "{{ prompt_analyzer.keywords }}",
  "sources": "{{ prompt_analyzer.sources }}",
  "limit": 5
}
```

The `user` field is important: Dify should pass the workflow user id back to the
backend. The backend then loads the stored Moodle/Artemis credentials for that
user and performs the portal lookup itself.

When testing with Dify Cloud, your backend must be publicly reachable. Local
`http://localhost:8000` only works if Dify is also running on your machine. For
Dify Cloud, use ngrok or deploy the backend.

Final End node output:

```text
answer
```

The backend expects the workflow output to contain `answer`, `text`, or `result`.
Use `answer` to keep it simple.

Additional workflow inputs available on every request:

```json
{
  "service_credentials": [
    {
      "serviceKey": "moodle",
      "label": "Moodle",
      "baseUrl": "https://moodle.example.edu",
      "loginUrl": "https://moodle.example.edu/login",
      "username": "student@example.edu",
      "hasPassword": "true",
      "notes": "optional"
    }
  ],
  "available_services": ["moodle"]
}
```

Passwords are intentionally not forwarded to Dify. Dify only decides which
sources are needed. The backend keeps credentials local and uses them inside
`/api/materials/search`.

### Moodle and Artemis Crawling

`/api/materials/search` now routes source searches through connector functions:

```text
search_materials
  -> search_moodle_materials
  -> search_artemis_materials
  -> ranking/filtering
```

By default, the connector functions use realistic local fallback materials. Set
`ENABLE_LIVE_PORTAL_CRAWLING=true` to let the connectors try a public HTTP fetch
from the portal base URLs. TUM SSO often requires browser-based login and 2FA, so
the current live hook is intentionally conservative and does not send passwords
to arbitrary login pages. The next production step is a dedicated browser/session
connector for TUM SSO.

Start the backend:

```bash
uvicorn main:app --reload --port 8000
```

Health check:

```bash
curl http://localhost:8000/health
```

Mock material search for a Dify HTTP node:

```bash
curl -X POST http://localhost:8000/api/materials/search \
  -H "Content-Type: application/json" \
  -d '{
    "user": "demo-user",
    "query": "lineare regression uebungsblatt",
    "keywords": ["regression", "gradient descent"],
    "sources": ["moodle", "artemis"],
    "limit": 3
  }'
```

Request body:

```json
{
  "user": "demo-user",
  "query": "lineare regression uebungsblatt",
  "keywords": ["regression", "gradient descent"],
  "sources": ["moodle", "artemis"],
  "limit": 3
}
```

Response shape:

```json
{
  "query": "lineare regression uebungsblatt",
  "matchedKeywords": ["lineare", "regression", "uebungsblatt"],
  "materials": [
    {
      "id": "moodle-ml-exercise-04",
      "title": "Uebungsblatt 4: Regression",
      "source": "moodle",
      "course": "Machine Learning",
      "type": "exercise",
      "url": "https://moodle.example.edu/course/ml/exercise-04.pdf",
      "summary": "Aufgaben zu Normalengleichung, Regularisierung und Fehleranalyse.",
      "tags": ["machine learning", "uebungsblatt", "regression", "regularisierung"],
      "relevance": 0.67
    }
  ]
}
```

### Frontend

```bash
cd frontend
cp .env.example .env.local
npm run dev
```

`frontend/.env.local` should point to the backend:

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

Now open `http://localhost:3000`. Chat messages go through:

```text
Frontend -> FastAPI backend -> Dify API -> FastAPI backend -> Frontend
```
