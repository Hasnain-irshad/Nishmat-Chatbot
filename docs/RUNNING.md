# Running the project

Everything you need to start Nishmat AI on your machine, in order.

If this is a brand-new machine or a fresh Supabase project, do **Part A** first.
If you are just starting the app again on a machine that already works, skip to
**Part B — Daily start**.

---

## Part A · One-time setup

You have already done all of this. It is written down so you can repeat it on a
new machine, and so the client's developer can too.

### A1. Requirements

| | Version | Check with |
|---|---|---|
| Node.js | 18 or newer | `node --version` |
| Python | 3.11 or newer | `python --version` |
| A Supabase project | — | <https://supabase.com/dashboard> |

### A2. Database

In the Supabase dashboard → **SQL Editor**, run the migration files from
`backend/migrations/` **in numerical order**:

```
0001_init.sql                   tables, enums, indexes, RLS, search function, storage bucket
0002_seed_template.sql          the series and the default lesson template
0003_import_rpc.sql             transactional corpus import
0004_job_queue.sql              the background job queue
0005_fix_version_allocation.sql atomic version creation
0006_fix_version_status_cast.sql  enum cast fix
```

Or paste `backend/migrations/apply_all.sql`, which is all six concatenated.

> Some of these use `create or replace function`, and Supabase warns that this
> will overwrite something. That is expected — say yes.

### A3. Environment files

**`frontend/.env.local`**

```bash
NEXT_PUBLIC_SUPABASE_URL=https://<project-ref>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<publishable / anon key>
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_SITE_URL=http://localhost:3000
```

**`backend/.env`** (copy `backend/.env.example`)

```bash
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_ANON_KEY=<publishable / anon key>
SUPABASE_SERVICE_ROLE_KEY=<secret key — sb_secret_… or the legacy JWT>
LLM_MODE=mock
AI_SPEND_CAP_USD=8.00
```

Keys are in **Supabase → Settings → API Keys**. The *secret* key is the one
under "Secret keys"; older projects show it as `service_role` under the
"Legacy anon, service_role API keys" tab.

> The service-role key bypasses Row Level Security completely. It belongs only
> in `backend/.env`, which is gitignored. It must never appear in
> `frontend/.env.local` — that file ships to the browser.

### A4. Install dependencies

```bash
cd frontend
npm install

cd ../backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### A5. Import the lessons

```bash
# from the project root
python backend/scripts/ingest_corpus.py --dry-run    # parse only, writes nothing
python backend/scripts/ingest_corpus.py              # load into Supabase
```

Safe to run repeatedly — unchanged lessons are skipped, changed ones create a
new version.

### A6. Make yourself an admin

Sign up through the app first (Part B), then in the Supabase SQL Editor:

```sql
update profiles set role = 'admin' where email = 'your@email.com';
```

Sign out and back in. You will land on `/admin` instead of `/app`.

### A7. Google sign-in (optional)

Skip this and use email/password if you prefer.

1. Google Cloud Console → **Credentials → OAuth client ID → Web application**
2. Authorised redirect URI: `https://<project-ref>.supabase.co/auth/v1/callback`
3. Supabase → **Authentication → Providers → Google** → paste the Client ID and Secret
4. Supabase → **Authentication → URL Configuration**:
   - Site URL: `http://localhost:3000`
   - Redirect URLs: add `http://localhost:3000/auth/callback`

While developing, turn **off** *Authentication → Providers → Email → Confirm
email*, or every test signup waits on an inbox.

---

## Part B · Daily start

**Three terminals.** All three need to be running.

### Terminal 1 — the API

```bash
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Wait for `Application startup complete`, then check
<http://127.0.0.1:8000/health> — you should see:

```json
{"status":"ok","environment":"development","llm_mode":"mock","openai_configured":false}
```

Interactive API docs: <http://127.0.0.1:8000/docs>

### Terminal 2 — the worker

```bash
cd backend
.venv\Scripts\python.exe -m app.jobs.worker
```

Wait for `worker_started`.

> **This one is easy to forget.** Without it, uploads sit at "Queued" forever —
> the file is stored, but nothing ever reads it. If a file seems stuck, check
> this terminal first.

### Terminal 3 — the web app

```bash
cd frontend
npm run dev
```

Open <http://localhost:3000>.

The first load of each page takes 5–20 seconds while Next.js compiles it and
fetches fonts. That is development only — the production build is instant.

### Stopping

`Ctrl+C` in each terminal. The worker finishes its current job first.

---

## Part C · Check it works

| Step | Where | Expected |
|---|---|---|
| 1 | <http://localhost:3000> | Landing page — starfield, 3D emblem, dedication |
| 2 | Sign up | Lands on `/app` with all 131 lessons |
| 3 | Open any lesson | Hebrew right-to-left, transliteration, translation, prev/next |
| 4 | Try `/admin` | Redirected back to `/app` — the role gate working |
| 5 | Promote yourself (A6), sign out and in | Lands on `/admin` |
| 6 | `/admin/lessons` | All 131, with filter tabs and search |
| 7 | Open a lesson, edit a section, **Save version** | New version appears in the sidebar; the old one is untouched |
| 8 | **Publish** | Status becomes Published |
| 9 | `/admin/lessons/new` | Drop a `.docx` from `Data/` → progress → "Ready" |
| 10 | `/admin/templates` | The lesson format, editable |

---

## Part D · Running the tests

The API and worker must be running (Terminals 1 and 2).

```bash
cd backend
.venv\Scripts\python.exe -m pytest tests/ -q          # everything
.venv\Scripts\python.exe -m pytest tests/test_auth_live.py -v   # security only
```

Takes about 8 minutes — most of it is the end-to-end upload tests polling real
jobs. They create throwaway accounts and delete them afterwards, and never
touch the client's real lessons.

Frontend:

```bash
cd frontend
npx tsc --noEmit     # types
npm run build        # production build
```

---

## Part E · When the OpenAI key arrives

1. Add it to `backend/.env`:
   ```bash
   OPENAI_API_KEY=sk-…
   LLM_MODE=live
   ```
2. Restart the API and the worker.
3. `/health` should now report `"openai_configured": true`.

Until then `LLM_MODE=mock` replays fixtures, so audio and image uploads produce
placeholder text and **nothing is billed**. That is deliberate: no amount of
development can spend the client's budget.

The spend cap (`AI_SPEND_CAP_USD`) is enforced in code, not just displayed. Once
the total in `ai_usage` reaches it, further AI calls are refused outright.

---

## Troubleshooting

**A file upload sits at "Queued" and never finishes**
The worker is not running. Start Terminal 2.

**"We couldn't reach the server"**
The API is not running, or `NEXT_PUBLIC_API_BASE_URL` does not match its port.
Restart `npm run dev` after changing any env file — Next.js reads them only at
startup.

**`error while attempting to bind on address ('127.0.0.1', 8000)`**
Something is already on that port — usually an API you forgot to stop.

```powershell
Get-NetTCPConnection -State Listen -LocalPort 8000 |
  Select-Object -ExpandProperty OwningProcess -Unique |
  ForEach-Object { Stop-Process -Id $_ -Force }
```

**Everything loads but there are no lessons**
The corpus has not been imported. Run A5.

**`/admin` keeps redirecting to `/app`**
Your role is still `user`. Run A6, then sign out and back in — the session
carries the old profile until it refreshes.

**"Invalid API key"**
`.env.local` is missing or stale. Restart the dev server after editing it.

**`relation "..." does not exist`**
A migration did not finish. Re-run it and read the error where it stopped —
usually the `vector` extension, which you can enable under
*Database → Extensions → pgvector*.

**Sign-in fails intermittently with an expired/invalid token**
Clock drift between your machine and Supabase. The backend already tolerates 60
seconds; beyond that, sync your system clock.

**Tests fail right after a previous run crashed**
They shouldn't any more — the fixtures purge stale rows before running. If it
persists, check for a leftover lesson numbered 9001 (the scratch lesson).
