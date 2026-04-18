# Sympl

## Dify Connection

The browser never talks to Dify directly. The frontend calls your FastAPI backend,
and the backend calls the published Dify app with the Dify API key.

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
DIFY_INPUT_KEY=prompt
FRONTEND_ORIGIN=http://localhost:3000
```

The project is configured for a Dify Workflow by default:

- `DIFY_APP_MODE=workflow` calls `/workflows/run`
- `DIFY_INPUT_KEY=prompt` must match the Start node input variable in Dify
- `DIFY_API_KEY` must be the API key of the published Dify Workflow app

If your Dify workflow input variable is called `message`, set:

```bash
DIFY_INPUT_KEY=message
```

For this project, use `prompt` in Dify so the default works without changes.

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
prompt
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
  "query": "{{ prompt_analyzer.query }}",
  "keywords": "{{ prompt_analyzer.keywords }}",
  "sources": "{{ prompt_analyzer.sources }}",
  "limit": 5
}
```

When testing with Dify Cloud, your backend must be publicly reachable. Local
`http://localhost:8000` only works if Dify is also running on your machine. For
Dify Cloud, use ngrok or deploy the backend.

Final End node output:

```text
answer
```

The backend expects the workflow output to contain `answer`, `text`, or `result`.
Use `answer` to keep it simple.

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
    "query": "lineare regression uebungsblatt",
    "keywords": ["regression", "gradient descent"],
    "sources": ["moodle", "artemis"],
    "limit": 3
  }'
```

Request body:

```json
{
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
