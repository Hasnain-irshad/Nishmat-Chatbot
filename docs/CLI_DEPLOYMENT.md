# Nishmat AI — Terminal CLI Deployment Guide

This guide details how to deploy **Nishmat AI** completely from your terminal using command-line interface (CLI) tools.

---

## 1. Prerequisites & CLI Tool Installations

Ensure Node.js is installed. Run the following commands in PowerShell / Terminal to install the CLI tools:

```powershell
# Install Vercel CLI (for Frontend)
npm install -g vercel

# Install Railway CLI (for Backend API & Worker)
npm install -g @railway/cli
```

---

## 2. Deploying the Frontend via Vercel CLI

### Step 2.1: Authenticate Vercel CLI
```powershell
vercel login
```
*(Follow the prompt in your terminal to complete one-time authentication).*

### Step 2.2: Link & Set Environment Variables
Navigate to `frontend/`:
```powershell
cd frontend
vercel link
```

Set the production environment variables directly from your terminal:
```powershell
vercel env add NEXT_PUBLIC_SUPABASE_URL production "https://<your-supabase-project-ref>.supabase.co"
vercel env add NEXT_PUBLIC_SUPABASE_ANON_KEY production "<your-supabase-anon-key>"
vercel env add NEXT_PUBLIC_API_BASE_URL production "https://<your-backend-railway-url>.railway.app"
vercel env add NEXT_PUBLIC_SITE_URL production "https://<your-frontend-vercel-url>.vercel.app"
```

### Step 2.3: Deploy to Production
```powershell
vercel --prod
```
Vercel CLI will output your live URL (e.g., `https://nishmat-ai.vercel.app`).

---

## 3. Deploying Backend API & Background Worker via Railway CLI

Railway allows running both the **FastAPI Web Service** and the **Background Worker** in the cloud via CLI.

### Step 3.1: Authenticate Railway CLI
```powershell
railway login
```

### Step 3.2: Initialize Project
Navigate to `backend/`:
```powershell
cd backend
railway init
```
*(Select "Empty Project" and give it a name like `nishmat-backend`).*

### Step 3.3: Add Environment Variables via CLI
Run the following CLI commands to set all required backend environment variables:

```powershell
railway variables --set ENVIRONMENT=production
railway variables --set API_CORS_ORIGINS="https://<your-vercel-domain>.vercel.app"
railway variables --set SUPABASE_URL="https://<your-supabase-project-ref>.supabase.co"
railway variables --set SUPABASE_ANON_KEY="<your-supabase-anon-key>"
railway variables --set SUPABASE_SERVICE_ROLE_KEY="<your-supabase-service-role-key>"
railway variables --set LLM_MODE=live
railway variables --set OPENAI_API_KEY="<your-openai-api-key>"
railway variables --set AI_SPEND_CAP_USD=8.00
railway variables --set AI_SPEND_WARN_USD=5.00
railway variables --set OPENAI_MODEL_GENERATION=gpt-4.1
railway variables --set OPENAI_MODEL_MODIFICATION=gpt-4.1
railway variables --set OPENAI_MODEL_ANALYSIS=gpt-4.1-mini
railway variables --set OPENAI_MODEL_QUALITY=gpt-4.1-mini
railway variables --set OPENAI_MODEL_CHAT=gpt-4.1-mini
railway variables --set OPENAI_MODEL_UTILITY=gpt-4.1-nano
railway variables --set OPENAI_MODEL_VISION=gpt-4.1-mini
railway variables --set OPENAI_MODEL_TRANSCRIPTION=gpt-4o-mini-transcribe
railway variables --set OPENAI_MODEL_EMBEDDING=text-embedding-3-small
```

### Step 3.4: Deploy API Service
```powershell
railway up
```
Generate a public URL for your Railway service:
```powershell
railway domain
```

### Step 3.5: Add the Background Worker Service

**This service is not optional.** Every lesson generation, file extraction and
reference-page upload runs through the Postgres job queue. The API only *queues*
the job; without a worker running, pressing "Generate" leaves a job in the queue
that nobody picks up and the admin watches a spinner that never resolves.

Both services deploy the same directory. What distinguishes them is which
Dockerfile they build — a start-command override in the repo would apply to
both, so the choice is made with a variable:

```powershell
cd backend
railway add --service nishmat-worker

# Same configuration as the API, plus the Dockerfile that runs the worker.
railway variables --service nishmat-worker `
  --set "RAILWAY_DOCKERFILE_PATH=Dockerfile.worker" `
  --set "SUPABASE_URL=..." --set "SUPABASE_SERVICE_ROLE_KEY=..." `
  --set "OPENAI_API_KEY=..." --set "LLM_MODE=live" `
  --skip-deploys   # ...and the rest, exactly as for the API

railway up --service nishmat-worker
```

Confirm it came up and registered its handlers:

```powershell
railway logs --service nishmat-worker
# worker_started handlers=['extract_file', 'generate_lesson', 'index_lesson', 'unindex_lesson']
```

The worker needs no public domain and no PORT.

---

## 3A. Loading the Reference Corpus

Lesson generation retrieves from a corpus of reference material — the Nishmat
text, the Psalms, and the teacher's own reference document. It is loaded once,
directly against the production database, by a person:

```powershell
cd backend
python -m scripts.index_references --status   # what is loaded; writes nothing
python -m scripts.index_references            # load anything missing
python -m scripts.index_references --force    # rebuild after a corrected file
```

Idempotent: a document is keyed on (kind, variant), so re-running replaces
rather than duplicates, and without `--force` anything already loaded is
skipped. The whole corpus is about 343 chunks and costs roughly $0.01 in
embeddings.

Reads `backend/.env`, so point that at production before running it.

Uploaded book pages are **not** loaded here — they arrive through the Admin
Dashboard, are scoped to one lesson, and are deliberately not part of this
permanent corpus.

---

## 4. Updating Supabase Configuration via CLI / API

Updating Supabase Auth Redirect URLs and Site URL via cURL from terminal:

```powershell
# Set Site URL and Redirect URLs via Supabase Management API (or CLI)
$headers = @{
    "Authorization" = "Bearer <your-supabase-access-token>"
    "Content-Type"  = "application/json"
}

$body = @{
    "site_url" = "https://<your-vercel-domain>.vercel.app"
    "additional_redirect_urls" = @(
        "https://<your-vercel-domain>.vercel.app/auth/callback"
    )
} | ConvertTo-Json

Invoke-RestMethod -Uri "https://api.supabase.com/v1/projects/<your-project-ref>/config/auth" -Method PATCH -Headers $headers -Body $body
```

---

## 5. Verification Commands

Run these terminal commands to test that your deployed environment is running cleanly:

```powershell
# 1. Test Backend Health Endpoint
Invoke-RestMethod -Uri "https://<your-backend-url>/health"

# 2. Test Frontend Availability
Invoke-WebRequest -Uri "https://<your-vercel-domain>.vercel.app" -Method HEAD

# 3. Confirm the worker is alive and polling
railway logs --service nishmat-worker
```

### End-to-end check of lesson generation

Drives the deployed API through the whole admin workflow — corpus visible,
lesson created from a brief, a page attached and read, a draft generated — then
deletes everything it created:

```powershell
cd backend
python -m scripts.verify_production
```

It creates a temporary admin account, uses it, and removes it. Costs a few
cents of the OpenAI budget per run, because it really does generate a lesson.
