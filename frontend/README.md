# Sympl Frontend

Next.js frontend for the Sympl MVP. The frontend talks only to your own backend;
the backend is responsible for auth, Dify calls, secrets and cloud services.

## Start

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

Open `http://localhost:3000`.

## Environment

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

The first backend endpoint expected by the UI is:

```http
POST /api/chat
Content-Type: application/json

{
  "query": "User question"
}
```

Expected response:

```json
{
  "answer": "Assistant answer",
  "conversationId": "optional-id"
}
```

## Frontend Plan

1. MVP chat screen
   Build a usable first screen that sends a prompt to the backend and renders the
   answer. Keep Dify credentials out of the browser.

2. API contract
   Agree with backend on `POST /api/chat`, error format, loading states and
   optional `conversationId` for follow-up messages.

3. Auth boundary
   Add login/session handling in the frontend only after the backend has chosen
   the auth provider. The browser should receive user sessions, never cloud or
   Dify secrets.

4. Conversation state
   Store temporary messages in React state for the first demo. Persist
   conversations through the backend once user accounts exist.

5. Uploads and context
   If the product needs files, upload them to the backend first. The backend can
   store files in cloud storage and pass references or extracted content into
   Dify.

6. Deployment
   Deploy the frontend separately from the backend. For GCP, use Cloud Run or a
   managed frontend host. For AWS, use Amplify or S3 plus CloudFront.

## Suggested Structure

```text
frontend/
  src/
    app/              Next.js routes and global styles
    components/       Reusable UI components
    lib/              API clients, config and shared types
```
