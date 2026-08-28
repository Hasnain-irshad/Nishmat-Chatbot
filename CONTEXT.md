# CONTEXT.md — read this before changing anything

Single source of truth for the Nishmat AI project. Written so that someone —
or some model — arriving with no history can understand the whole system,
avoid the traps already discovered, and continue the work safely.

**If you read only one section, read [§8 Decisions that look wrong but are
deliberate](#8-decisions-that-look-wrong-but-are-deliberate).** Several choices
here appear to be mistakes and are not. Reverting them will break the product
in ways tests may not catch immediately.

If you are here to work on **lesson generation**, read [§6b](#6b-how-a-lesson-is-actually-generated)
as well — it explains why the sources are kept apart and why two of them are
looked up exactly rather than searched.

---

## 1. What this is

A two-role web application for **Nishmat AI**, a weekly Torah-learning series
taught by **Rivkah Dahan** to a community of learners. It is a paid client
project. The client's real, published work is in this repository.

**The admin** (the teacher) uploads source material — usually a WhatsApp voice
recording of herself teaching, sometimes a document or a photo of a page. The
system transcribes/reads it, then writes a polished lesson *in her voice*
following her editorial format. She reviews it, edits it, and publishes it.

**Learners** read published lessons and ask an AI chatbot questions that are
answered only from those lessons.

**The product's value is the writing.** This is not summarisation. It is voice
transfer plus structural reformatting, with strict factual fidelity to the
source. In a Torah-learning context, a fabricated source or misquoted pasuk is
not a bug ticket — it is a reputational injury to the teacher whose name is on
the lesson. Anti-fabrication is architectural here, not a prompt afterthought.

### The two reference documents

- `sample output.txt` — the client's **target lesson format**. Study its rhythm:
  one sentence per line, deliberate blank lines, short lines for emphasis.
- `Landing page sample gui.jpeg` — the client's design reference for the public
  page. Blue scribbles on it mark sections she wanted **removed** (they already
  have been).

---

## 2. Current status

**Live in production.** All 131 of the client's existing lessons are imported
and published. Lesson generation, reference retrieval and the chatbot all work
end to end against the real OpenAI API, verified against the deployed system —
not only locally.

| Phase | State |
|---|---|
| 0 Scaffold, config, build | ✅ Done |
| 1 Database, RLS, seed | ✅ Done |
| 1b Corpus import (131 lessons) | ✅ Done |
| 2 Auth, roles, landing page | ✅ Done |
| 3 Upload + storage + job queue | ✅ Done |
| 4 File processors (pdf/docx/text/audio/image) | ✅ Done |
| 5 Template system + editor | ✅ Done |
| 6 **AI lesson generation** | ✅ Done, validated live |
| 6b Voice tuning | ✅ Tuned against measured evidence — **still needs Rivkah's sign-off** |
| 7 Admin lesson editor | ✅ Done |
| 8 AI revision ("make this warmer") | ✅ Done — scoped + whole-lesson, with diff preview |
| 9 Publishing workflow | ✅ Done |
| 10 Chunking, embeddings, retrieval | ✅ Done, 493 lesson chunks indexed |
| 11 Learner dashboard + chatbot | ✅ Done |
| 12 Chat history | ✅ Done |
| 13 Polish | 🟨 **3 stub pages remain** |
| 14 Testing | 🟨 111 backend tests; **no browser tests** |
| 15 Deployment | ✅ Done — API, worker, web and database all live |
| 16 **Reference-grounded generation** | ✅ Done, verified in production |

**Spend so far: about $0.41 of the client's $10 OpenAI budget.**

### What is NOT finished

Read this before telling anyone the project is complete.

- **Rivkah has still not signed off on the voice.** This is the acceptance
  criterion for the whole project (§14A) and no human who knows her writing has
  read the output yet. Everything else is machinery in service of this.
- **Three admin/learner pages are stubs** — style library, people, settings.
- **No browser tests.** The backend is well covered; nothing exercises the UI.
- **Two reference sources the client has not supplied**: an authoritative
  English Nishmat translation, and the 17 NJOP transcripts. Both have load
  paths ready (§6b) — adding either is a run of the indexer, not a redesign.
- **`ENVIRONMENT` is still `development` on the production API**, which exposes
  `/docs` and `/openapi.json` publicly and leaks internal error detail. One
  variable on each Railway service fixes it; left alone because it changes log
  format and doc availability, which is the client's call.

### Still stubs (show a "coming soon" page)

- `frontend/app/admin/style-examples/page.tsx`
- `frontend/app/admin/users/page.tsx`
- `frontend/app/app/settings/page.tsx`

### Deployed at

| Piece | Where |
|---|---|
| Web | `https://nishmat-ai.vercel.app` (Vercel, project `nishmat-ai`) |
| API | `https://nishmat-ai-production.up.railway.app` (Railway, `nishmat-ai`) |
| Worker | Railway service `nishmat-worker` — **no public URL, and no less essential** |
| Database | Supabase `eqkxhhvjsvuhfchavjqi` |

Deploy commands and the corpus loader: **`docs/CLI_DEPLOYMENT.md`**.

---

## 3. Running it

Three processes. All three must be running.

```bash
# 1. API
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000

# 2. Worker  ← easy to forget; without it uploads sit at "Queued" forever
cd backend
.venv\Scripts\python.exe -m app.jobs.worker

# 3. Web
cd frontend
npm run dev            # http://localhost:3000
```

A fresh database also needs the **reference corpus** loaded once, or every
generated lesson will quietly be written without the prayer text, the Psalms or
the client's reference material — and nothing will look broken:

```bash
cd backend
.venv\Scripts\python.exe -m scripts.index_references --status   # writes nothing
.venv\Scripts\python.exe -m scripts.index_references            # load what is missing
```

Full setup, troubleshooting and Supabase configuration: **`docs/RUNNING.md`**.
Architecture rationale and the original plan: **`docs/ARCHITECTURE.md`**.
Deployment, the worker service and the corpus loader: **`docs/CLI_DEPLOYMENT.md`**.

### Accounts

| Account | Role |
|---|---|
| the client's own address | admin |
| a test address | user |

The real addresses are deliberately not written down here — this repository is
public, and one of them is the client's admin login.

Promote someone in the Supabase SQL editor:

```sql
update profiles set role = 'admin' where email = '...';
```

Role is read from the database on **every** request, so a change takes effect
on the next request — but the person must sign out and in for the frontend to
route them to the right dashboard.

---

## 4. Architecture

```
Browser
  /            landing page (public)
  /app/*       learner: lesson library, reader, chatbot
  /admin/*     admin only: lessons, editor, templates
     │
     │  reads  → Supabase directly (RLS enforces access)
     │  writes → FastAPI (require_admin + the OpenAI key live there)
     ▼
FastAPI (port 8000)  ──────►  Supabase (Postgres + pgvector + Auth + Storage)
     │                                    ▲
     └──► OpenAI                          │
                                          │
Worker process (same codebase) ───────────┘
  polls the `jobs` table, runs extraction / generation / indexing
```

**Two vector indexes, deliberately separate:**

```
lesson_chunks      published lessons        → the LEARNER chatbot
reference_chunks   Nishmat, Tehillim,       → the lesson GENERATOR only
                   commentary, uploaded
                   book pages
```

They are not one table with a flag. `lesson_chunks` is reachable by any signed-in
learner through the chatbot; `reference_chunks` holds photographed pages of
copyrighted books the client owns on paper, and is admin-only at every layer.
Merging them would put a scanned book page one question away from a learner.

**Stack:** Next.js 15 (App Router, TypeScript, Tailwind v4) · FastAPI (Python
3.12) · Supabase · OpenAI.

### Why reads bypass the API

Server Components query Supabase directly with the user's own session, so RLS
is the enforcement boundary and page loads avoid a second hop. **Every mutation
and every AI call goes through FastAPI**, because that is where `require_admin`
and the OpenAI key live. This split is deliberate, not an inconsistency.

### Authorisation — three independent layers

1. **Middleware** (`frontend/middleware.ts`) — redirects signed-out users. UX only.
2. **Server layout** (`frontend/app/admin/layout.tsx` → `requireAdmin()`) — reads
   `profiles.role` from the database.
3. **Backend** (`backend/app/api/deps.py` → `require_admin`) — mounted on the
   *router*, so a new admin endpoint cannot ship without it. RLS is the fourth
   layer beneath all of this.

**A JWT proves identity only. Role always comes from the `profiles` table.**
Never read a role from a token claim — anyone who can influence their own user
metadata would then be able to grant themselves admin.

---

## 5. Directory map

### `backend/app/`

| Path | Purpose |
|---|---|
| `main.py` | FastAPI app factory, middleware, request logging |
| `config.py` | All settings from env. `get_settings()` is lru_cached |
| `logging.py` | structlog + **secret redaction** (keys never reach a log) |
| `core/jwt.py` | Supabase token verification via JWKS (ES256) |
| `db/supabase.py` | PostgREST client. `service()` bypasses RLS; `as_user()` does not |
| `api/deps.py` | `get_current_user`, `require_admin` |
| `api/errors.py` | Global handlers. Users get a sentence + `request_id`, never internals |
| `api/routers/admin.py` | Admin router — carries `require_admin`, mounts the rest |
| `api/routers/admin_lessons.py` | Lesson CRUD, versions, restore, publish, generate |
| `api/routers/admin_templates.py` | Lesson format + style guide |
| `api/routers/files.py` | Upload, extracted-text review, signed URLs |
| `api/routers/chat.py` | Learner chatbot + conversations |
| `api/routers/jobs.py` | Job status polling |
| `jobs/queue.py` | Postgres-backed queue client |
| `jobs/worker.py` | The worker loop. Register new handlers in `HANDLERS` |
| `jobs/handlers/extract_file.py` | Upload → text |
| `jobs/handlers/generate_lesson.py` | Source → lesson draft |
| `jobs/handlers/index_lesson.py` | Published lesson → search index |
| `llm/provider.py` | The LLM seam. `get_provider()` returns mock or OpenAI |
| `llm/mock_provider.py` | Fixture replay. **Zero cost.** Used by all tests |
| `llm/openai_provider.py` | Real calls. Budget check → call → price → record |
| `llm/pricing.py` | Cost table. Unknown models priced *pessimistically* |
| `llm/usage.py` | Spend tracking + the hard cap |
| `llm/prompt_builder.py` | **All prompts.** Versioned via `PROMPT_VERSION` |
| `models/analysis.py` | `StructuredAnalysis` — the anti-fabrication schema |
| `services/generation_service.py` | The 6-stage pipeline (§6b) |
| `services/reference_service.py` | **Which sources this lesson needs, and finding them** |
| `services/reference_indexing.py` | Reference material → `reference_chunks` |
| `services/grounding_service.py` | **Quotes checked against the corpus, in code not by a model** |
| `services/chunking_service.py` | Lesson → retrievable chunks |
| `services/indexing_service.py` | Chunks + embeddings → `lesson_chunks` |
| `services/retrieval_service.py` | Hybrid search + grounding decision (chatbot) |
| `services/chat_service.py` | RAG answering + conversation memory |
| `services/publishing_service.py` | Publish/unpublish. Enforces Rules 4–6 |
| `services/ingestion/` | One processor per file type, the corpus parser, and `reference_parsers.py` |
| `api/routers/admin_references.py` | Corpus status + per-lesson book pages |
| `scripts/index_references.py` | Loads the permanent corpus. Idempotent |
| `scripts/verify_production.py` | Drives the **deployed** system end to end, then cleans up |

### `frontend/`

| Path | Purpose |
|---|---|
| `app/page.tsx` | Landing page (starfield, 3D emblem, dedication) |
| `app/(auth)/` | Sign in / up / forgot password |
| `app/auth/callback/route.ts` | OAuth landing; routes by role |
| `app/app/` | Learner: library, reader, chat |
| `app/admin/` | Admin: dashboard, lessons, editor, templates |
| `lib/api.ts` | Typed client for FastAPI |
| `lib/auth.ts` | `getProfile`, `requireUser`, `requireAdmin` (server only) |
| `lib/auth-settings.ts` | Reads which auth providers are actually enabled |
| `lib/supabase/` | Browser / server / middleware clients |
| `components/admin/LessonComposer.tsx` | Chat-style upload (the "+" menu) |
| `components/admin/LessonEditor.tsx` | Section editing, versions, publish, generate |
| `components/chat/` | Chatbot window + history sidebar |
| `types/database.ts` | Row types. See §8 for why these exist |

---

## 6. Database

Supabase Postgres with `pgvector`. Migrations in `backend/migrations/`, applied
in numerical order. `apply_all.sql` is all of them concatenated for a fresh
project.

```
profiles ──┬──< lessons ──┬──< lesson_versions ──< lesson_chunks
           │              ├──< source_files          (role: lesson_source | reference)
           │              ├──< reference_documents ──< reference_chunks   (lesson-scoped)
           │              └──> lesson_templates
           ├──< conversations ──< messages
           ├──< style_examples
           └──< jobs, ai_usage, audit_log

reference_documents ──< reference_chunks   (lesson_id NULL = permanent corpus)
```

### The tables that matter most

**`lessons`** — identity and pointers, not content.

- `current_version_id` — what the admin is editing
- `published_version_id` — **what learners see.** The only thing they can see.

These being separate columns is what makes "learners keep seeing v3 while the
admin drafts v4" true *by construction*.

**`lesson_versions`** — **immutable**. A database trigger
(`guard_lesson_version_immutability`) raises if you try to change `content`,
`content_text`, `lesson_id`, `version_number` or `origin`. Edits create a new
version. Always.

Content shape:
```json
{"sections": [{"key": "greeting", "title": null, "body": "...", "dir": "ltr", "order": 6}]}
```

**`lesson_chunks`** — the chatbot's index. Written **only** on publish, deleted
on unpublish. Learner visibility and chatbot visibility are therefore the same
switch and cannot drift apart.

**`jobs`** — the queue. `claim_job` uses `FOR UPDATE SKIP LOCKED`.

**`reference_documents` / `reference_chunks`** — what the *generator* reads.
`lesson_id IS NULL` means permanent corpus, shared by every lesson. `lesson_id`
set means a page an admin photographed for **one** lesson: retrieved only while
generating that lesson, and deleted with it. That column is the whole reason a
scan of a copyrighted book never becomes part of the global knowledge base.

Each chunk carries `kind` (what it is) and `authority` (how far the generator
may lean on it) so retrieval can filter on both — see §6b.

**`source_files.role`** — `lesson_source` is the recording the lesson is made
*from*; `reference` is a book page to consult *while writing it*. The generator
reads only the former as source text. Feeding both in as undifferentiated
"source", as this used to, is exactly how a commentator's sentence ends up in
the lesson as the teacher's own words.

### Important SQL functions

| Function | Why it exists |
|---|---|
| `create_lesson_version(...)` | Allocates the number, inserts, and repoints the lesson **in one transaction**. Do not split these apart — see §9 |
| `search_published_chunks(...)` | Hybrid search for the **chatbot**. The published-only filter lives inside this function, so no caller can retrieve a draft |
| `match_reference_chunks(...)` | Hybrid search for the **generator**, filtered by `kind` and by lesson |
| `lookup_reference_chunks(...)` | Exact lookup **by address**. "Which psalm is this" has one right answer; similarity search will happily return a near miss |
| `verify_hebrew_quote(...)` | Is this Hebrew actually in the corpus? The grounding check |
| `hebrew_plain(...)` | Consonantal skeleton for comparison. **Shared with Python — see §9.7** |
| `import_lesson(...)` | Idempotent corpus import |
| `claim_job / complete_job / fail_job / reap_stale_jobs` | The queue |

---

## 6b. How a lesson is actually generated

The pipeline used to have exactly one input: text extracted from an uploaded
file. It had no access to the prayer it teaches, to the Psalms it quotes, or to
any commentary — so a lesson "about a Nishmat phrase" could only be written from
whatever a recording happened to say about it, and any Hebrew beyond that was
recalled from training data rather than read. That is the gap this closes.

```
brief and/or source text
   │
   ├─ 0. RETRIEVE   the sources this lesson needs      (no model decides)
   ├─ 1. ANALYSE    what is actually in them           (cheap model, temp 0.2)
   ├─ 2. ASSEMBLE   template + style + series + refs   (no model at all)
   ├─ 3. WRITE      the lesson                         (strong model, temp 0.85)
   ├─ 4. GROUND     every quote against stored text    (no model at all)
   └─ 5. CHECK      fresh reader, adversarial          (cheap model, temp 0)
```

### A lesson no longer needs an upload

`lessons.generation_brief` holds what the admin asked for — a Nishmat phrase, a
Hebrew word, a theme, a Psalm, a commentator, a season, an objective. **Any one
of them is enough.** Most of this series is written that way; requiring a file
made the natural request impossible to express.

### The sources are not interchangeable

Each class is retrieved its own way and kept in its own labelled slot, all the
way into the prompt:

| Slot | What | How it is found |
|---|---|---|
| **A** | Nishmat, Edot HaMizrach | **Exact** match on the phrase, ignoring pointing |
| **B** | Tehillim 1–150 | **By address** — never by similarity |
| **C** | The client's reference document | Vector search, labelled *not authoritative* |
| **D** | Her published lessons | Existing `style_examples` vector search |
| **E** | The rest of the series | Last 4 lessons *with their themes*, plus the next one |
| **F** | Pages she photographed | Not searched at all — she already chose them |

Three of those deserve the reasoning spelled out:

- **A is exact, not similar.** When the admin pastes a phrase from the siddur,
  which stanza it belongs to is a *fact*. Answering a fact with a similarity
  score is how a lesson ends up teaching the wrong line.
- **B is by address, and the addresses are discovered from the text.** Nishmat
  quotes two verses outright. Which ones is not guessed and not recalled — every
  stanza line is checked for a literal occurrence in the stored Psalms, and the
  database answers. `Nishmat 8 → Tehillim 35`, `Nishmat 9 → Tehillim 33`.
- **C is labelled untrustworthy on purpose.** "The Magnificent Nishmat Kol Chai"
  is client-supplied material, not scholarship — it contains obvious
  LLM artefacts ("the Bouth of", "Atterances"). The prompt says plainly that
  where it disagrees with the primary text, the primary text wins.

### Grounding runs in code, not in a model

Stage 4 is deterministic, and that is the point. Ask a model "is this verse
real?" and it says yes — because it recognises the verse from training, not from
the sources this lesson was allowed to use. Three checks:

1. **Hebrew** — every substantial run must appear in the stored corpus, in a
   retrieved reference, or in the lesson's own source. Compared on the
   consonantal text, because pointing legitimately differs between editions.
2. **Psalms** — every citation must name a real chapter *and* one that was
   actually put in front of the writer. Citing Tehillim 62 when only 34 was
   retrieved means the quotation is being recalled rather than read.
3. **Names** — a commentator may only be named if the sources name them. This is
   the failure the client cares about most: an invented interpretation hung on a
   real rabbi's name reads as authoritative and is nearly impossible to spot.

A finding is not proof of fabrication. It is proof the claim cannot be traced to
anything supplied, which is the question that actually matters.

### Uploaded book pages

The client owns **ArtScroll Tehillim** and **Nishmas: Song of the Soul** on
paper. Neither is available digitally and neither will be pirated. Instead the
admin photographs the pages she wants, tags them with the book and page, and
attaches them to the lesson she is writing. They are read by the vision model,
indexed against that lesson only, used with attribution, and deleted with it.

`source_files.reference_persist` exists for promoting one into the permanent
corpus. **No UI uses it yet** — deliberately, so an uploaded page never becomes
part of the global knowledge base by accident.

### Extending it

`reference_kind` already has `translation` and `transcript` values. When the
client supplies an authoritative English Nishmat or the NJOP transcripts, add a
parser and an entry in `SOURCES` in `scripts/index_references.py` and run it.
No pipeline change. The admin dashboard already **reports both as missing**, so
their absence is visible rather than silently degrading every lesson.

---

## 7. The domain — things you cannot guess from the code

### The corpus

`Data/` holds **131 real `.docx` lessons** — the client's actual work, two
years of it. Treat it as client IP; it is gitignored.

- Lessons #1–#130 plus an Introduction.
- **The series is sequential.** Each lesson covers the *next word or phrase of
  the Nishmat Kol Chai prayer*. Lesson #115 literally says *"Last week we spoke
  about Shir u'Shevachah… this week Hallel v'Zimrah."* This is why lessons have
  `sequence_position` and why the generator is given the previous lesson.
- Filenames are inconsistent (`Nishmat #1.docx`, `Nishmat#12.docx`,
  `Nishmat_13.docx`, `NIshmat #54.docx`).
- 15 lessons are flagged `needs_review = true` — stubs, missing Hebrew, or
  leftover ChatGPT chatter that the importer stripped.

`Audios/` holds four real WhatsApp voice notes (OGG/Opus, 2.5–6.7 min). This is
the client's actual workflow: she records, and the recording becomes the lesson.

### Hebrew

Hebrew in this corpus is **fully vocalised** (with nikud):
`הַמְנַהֵג עוֹלָמוֹ בְּחֶסֶד`.

- **Only ever NFC-normalise.** NFKD or any "strip accents" step silently
  destroys the vowel points. There is a test asserting a real corpus string
  survives untouched (`test_normalise_preserves_nikud_exactly`).
- Hebrew inside an English sentence must be wrapped and marked `dir="rtl"`,
  or bidi drags the surrounding punctuation to the wrong side.
- The generator is told to copy Hebrew character for character and never retype
  it from memory.

### The writing style

Read `sample output.txt` before touching any prompt. The defining feature is
**line breaks used as punctuation**:

```
You've been davening.

Maybe for weeks.

Maybe for months.

Maybe for years.
```

That spacing *is* the writing. Anything that normalises whitespace destroys the
voice. This is why the editor uses plain textareas rather than a rich-text
editor (see §8).

The full style guide lives in the database, in
`lesson_templates.style_guide`. Edit it at `/admin/templates`, not in code.

---

## 8. Decisions that look wrong but are deliberate

**Do not "fix" these.** Each was chosen for a reason, and several were arrived
at by hitting the alternative first.

### 8.1 The lesson editor uses plain `<textarea>`, not a rich-text editor

Looks primitive. It is correct. The content model is section-based plain text
where **newlines are meaningful punctuation**. TipTap, Slate, Quill and friends
normalise whitespace and convert blank lines into paragraph nodes — destroying
exactly the thing that defines this author's voice. A textarea stores what was
typed. See `frontend/components/admin/SectionEditor.tsx`.

### 8.2 Explicit row types instead of generated Supabase types

`frontend/types/database.ts` declares row shapes by hand, used via
`.returns<T>()`. supabase-js infers result types by parsing the `.select()`
string *as a type literal* — a string built with `+` across lines is not a
literal, so inference collapses to `GenericStringError`. Declaring the shape is
both the fix and a clearer contract. Replace with `supabase gen types` output
later if you like; no call site changes.

### 8.3 JWT verification allows 60 seconds of clock leeway

`backend/app/core/jwt.py`, `LEEWAY_SECONDS = 60`. Without it, verification fails
with `ImmatureSignatureError` whenever this server's clock is even a second
behind Supabase's — the token is checked milliseconds after it is issued. This
was a real, observed failure (1.2s of drift). Removing the leeway produces
intermittent, unreproducible sign-in failures in production.

### 8.4 The service-role client sends the same key in `apikey` and `Authorization`

`backend/app/db/supabase.py`. PostgREST resolves the caller's Postgres role
from `apikey` and only parses `Authorization` as a JWT. Newer Supabase secret
keys (`sb_secret_…`) are **opaque, not JWTs** — putting one in `Authorization`
alongside an anon `apikey` makes PostgREST try to parse it as a token and fail
with *"Expected 3 parts in JWT"*. For a **user** request the two headers
correctly differ.

### 8.5 Grounding uses cosine similarity, not the fused search score

`search_published_chunks` returns **both** `score` (RRF) and `similarity`
(cosine). Ordering uses `score`; the decision of whether to answer at all uses
`similarity`. RRF encodes *rank*, not *quality* — the best match for "what's
the best chocolate cake recipe" scores identically to the best match for a
question the corpus answers well. Both are rank 1. See §9.2.

### 8.6 The chatbot's text query strips stopwords and ORs the rest

`retrieval_service.build_text_query`. `websearch_to_tsquery` **ANDs** bare
terms, so *"What does Moshia mean?"* becomes `what & does & moshia & mean`,
which matches nothing. "Moshia" appears in exactly **one chunk** in the whole
corpus, and it never surfaced. This matters most for transliterated Hebrew,
where a single lexical hit is highly informative.

### 8.7 Unknown models are priced pessimistically

`backend/app/llm/pricing.py`. A model not in the table is priced at the most
expensive tier known. Pricing an unrecognised model at zero would silently
disable the budget cap — the worst possible failure for a fixed budget. Also
note `_lookup` matches the **longest** prefix: `gpt-4.1-mini-2025-04-14` must
not match `gpt-4.1`.

### 8.8 Generation retries at most once, then stops

`generation_service.generate`. On a `FAIL` verdict it regenerates once with the
issues fed back, then hands the draft to the admin regardless. An automatic
loop chasing a `PASS` would burn a fixed budget in minutes and, on a genuinely
thin source, would never converge. **A human reading the draft is the real
quality gate.**

### 8.9 Tests force `LLM_MODE=mock` regardless of `.env`

`backend/tests/conftest.py`. The app now runs in live mode. Without this, a
full test run would spend the client's money. Do not remove it.

### 8.10 Style examples are rotated, not always the top matches

`prompt_builder.pick_style_examples` takes the closest match plus a random pick
from the next few. Always sending the top N makes every generated lesson echo
the same two examples — the client explicitly asked that phrases not repeat.

### 8.11 Scripts force UTF-8 on stdout

Windows consoles default to cp1252 and cannot encode box-drawing characters or
Hebrew. Without the `sys.stdout.reconfigure` at the top of each script, a script
can do all its work and still exit non-zero on its closing summary. This
actually happened during the corpus indexing.

---

### 8.12 The style guide is measured, not guessed

Phase 6b was done by measuring her 131 published lessons and comparing
generated output against them numerically, not by taste.

| metric | hers | before tuning | after |
|---|---|---|---|
| median line length | 8.5 words | 18–25 | 9–12 |
| lines of ≤6 words | 40% | 15–28% | 22–32% |
| lines per 100 words | 7.3 | 4.3–4.9 | 6.8–7.3 |
| lesson length | ~572 words | 609–775 | 497–757 |

**Line length was the single largest gap in voice.** Her line breaks are
punctuation; output written as 20-word sentences is wrong however good its
content. If you revise the style guide, re-measure — `scripts/tune_style.py`
documents the numbers and is the file to edit.

Two mechanical checks now back this up in `generation_service`, because prompt
instruction alone did not hold:

- **Padding guard** — output beyond ~3.5× the source words is flagged high.
  A 185-word source was producing 561 words; most of that had to be invented.
- **Rhythm check** — flags when short lines fall far below the template's
  `target_short_line_percentage`.

Still short of target: the proportion of very short lines (22–32% against 40%).
Worth another pass, ideally with Rivkah watching.

### 8.13 AI revision returns a proposal, and saves nothing

`POST /admin/lessons/{id}/modify` returns the revised text as a **preview**. It
does not create a version and does not publish. The admin sees a diff, presses
"Use this", and the change lands in the editor as an unsaved edit — she still
presses Save herself.

Two reasons this matters:
- A revision she dislikes leaves **no trace** in the version history.
- An AI suggestion never writes itself into the record. Accepting goes through
  the same `POST /versions` path as a hand edit, so both are stored identically.

**Scoped edits send only the selected section plus its immediate neighbours.**
Not the whole lesson. The token saving is modest; the real gain is that a narrow
context produces a surgical edit rather than the model quietly rewriting three
paragraphs it was never asked to touch. Do not "simplify" this by sending
everything.

The endpoint is **synchronous**, unlike generation. A scoped edit is one call of
a few seconds and the admin is waiting to see the diff — queuing it would add
more latency than the work takes.

Two deterministic checks run on every revision (`modification_service._warn`):
Hebrew runs must survive unchanged, and a revision that grows past 1.6× or
shrinks below 0.5× is flagged. Verified adversarially: asked to *"add a quote
from the Gemara"*, it refused to fabricate one.

### 8.14 Reference material lives in its own tables, not in `lesson_chunks`

It would be less code to add a `kind` column to `lesson_chunks` and put
everything in one index. Two reasons not to:

- `lesson_chunks` is the **learner** chatbot's index, reachable by anyone signed
  in. `reference_chunks` holds photographed pages of copyrighted books. One flag
  away from a leak is too close.
- Reference chunks carry `kind` and `authority`, which lesson chunks have no
  meaning for, and **every** reference retrieval filters on both.

`search_published_chunks` was left completely untouched, so the deployed chatbot
behaves exactly as it did.

### 8.15 A Nishmat phrase is matched exactly; a Psalm is fetched by address

Neither uses the vector index, in a system built on vector search. Both are
questions with one correct answer, and similarity search returns the *nearest*
answer, which for a prayer taught one phrase at a time means teaching the wrong
line. Embeddings are used where the question is genuinely "what is relevant" —
commentary, style examples, an open-ended theme.

### 8.16 Chunk size is budgeted in estimated tokens, not words

`reference_parsers.estimate_tokens` weights Hebrew characters ~3.5× Latin ones.
This looks like over-engineering and is not: vocalised Hebrew carries a separate
codepoint per vowel point and tokenises far more finely, so a word count
underestimates a page of it badly. See §9.8 for what that cost.

### 8.17 The API refuses to generate while a reference page is still being read

`POST /admin/lessons/{id}/generate` returns 409 if any attached page is still
extracting. Waiting is annoying; the alternative is worse — the admin attaches
pages, presses Generate, and gets a lesson written **without** the material she
just supplied, with nothing anywhere to indicate it was missed.

### 8.18 Photographs are downscaled before they reach the vision model

`image_processor.prepare_for_vision`, 2000px on the long edge, via PyMuPDF (no
new dependency). The client photographs pages with a phone, and a phone photo is
3–8 MB — 4–11 MB once base64-encoded into a JSON body. See §9.9.

---

## 9. Bugs already found and fixed — do not reintroduce

### 9.1 `SELECT max(...) ... FOR UPDATE` is invalid Postgres

Migration 0001 tried to lock an aggregate. Postgres rejects it (`0A000`), so
**every attempt to save a lesson edit failed**. Fixed in 0005 by doing
allocation + insert + repoint inside one function. 0006 then fixed an enum cast
in the same function (`text` vs `lesson_status`, `42804`).

### 9.2 The grounding threshold could never be met

`rag_min_score` was `0.25`, compared against an RRF score whose maximum is
`2/61 = 0.033`. **Every chatbot question was refused**, including ones the
corpus answers well. Fixed in 0007 — see §8.5.

### 9.3 The corpus parser silently dropped content

The lesson number appears *inside a real sentence* in the spoken transcripts
("…l'iluy nishmat Rachel bat Rut a"h. This is lesson #35."), and the header
rule swallowed the whole line. Lesson #35 imported at **36% of its content and
looked completely fine.**

This is why `corpus_parser` has a **content-retention check** (parsed words vs
source words, flagged below 92%). Keep it. An importer that quietly loses a
paragraph is the worst kind of bug — nothing looks wrong.

### 9.4 Tests were not hermetic after a crash

Uploads are deduplicated by SHA-256, so a row left behind by a crashed run made
the next run's first upload return "already uploaded" with no job. The fixtures
now purge **before** running, not only after.

### 9.5 The Google button offered a provider that was not enabled

`signInWithOAuth` navigates the browser away, so when the provider is disabled
Supabase renders raw JSON into the address bar and no client-side handler can
catch it. `lib/auth-settings.ts` now reads `/auth/v1/settings` and only renders
the button if Google is actually live.

### 9.6 "Words:" is a label, not a transliteration

Lesson #93 writes `Words: הַגִּבּוֹר לָנֶצַח`. Both the corpus parser and the
titling helper had to learn that the Latin half can be a *label*. Without the
`GLOSS_LABEL` check, that lesson was titled **"Words"**.

### 9.7 Stripping "vowel points" welded Hebrew words together

Quote verification reduces Hebrew to its consonantal skeleton so a quotation can
be compared across editions with different pointing. The first version deleted
every character in `U+0591–U+05C7`. **That range is not all vowel points.** It
also contains the word *separators*, and deleting a separator does not remove a
mark — it joins two words into one:

```
כׇּל־עַצְמוֹתַי   ->  כלעצמותי      (maqaf U+05BE deleted)
מִי־כָמוֹךָ       ->  מיכמוך        (maqaf U+05BE deleted)
```

Tehillim 35:10 is quoted **verbatim inside Nishmat**, and could no longer be
found in the stored Psalms. So a lesson quoting that verse perfectly correctly
would have been reported as having invented it.

That is worse than having no check. A grounding warning that fires on correct
quotations teaches the admin to ignore grounding warnings, which is precisely
when a real fabrication gets published.

Fixed in migration 0010: separators become a **space**, only true marks are
deleted, and the normalisation lives in **one** function (`hebrew_plain`) shared
by SQL and Python. The two normalise opposite halves of the same comparison — if
they ever disagree, nothing matches and every quotation looks fabricated.
`test_sql_normalisation_uses_the_same_character_classes` asserts they agree, by
**codepoint**, because reading a character class of invisible combining marks is
exactly how the maqaf got into the delete set.

### 9.8 One oversized chunk lost an entire page, silently

A photographed page of dense pointed Hebrew produced a single 2,000-word chunk.
The embedding API rejects anything over 8192 tokens — and rejects the whole
**batch** when one item is too long. So the page uploaded cleanly, reported
success, and indexed **nothing**.

Two causes, both fixed: the chunker only ever split *between* paragraphs, so one
unbroken run of text sailed past the budget untouched; and the budget was in
words, which underestimates vocalised Hebrew badly (§8.16). There is now also a
last-resort truncation in `reference_indexing._fit_to_budget`, because losing
one chunk's vector is far better than losing every chunk in its batch.

### 9.9 A photographed page timed out after six minutes and three attempts

`describe_image` sent the original bytes. A full-page image plus a
transcribe-everything instruction ran past the shared 120s timeout, retried
three times, and failed — with the message `network error: `, because httpx
timeout exceptions stringify to an empty string.

Fixed three ways: images are downscaled first (§8.18), vision has its own longer
timeout and tighter retry count, and an empty exception message now falls back
to the exception class name and reports the timeout that was in force.

### 9.10 The worker was never deployed at all

Production ran the API only. The API *queues* jobs; nothing consumed them. The
`jobs` table was empty and all 132 lesson versions had origin `imported` —
lesson generation had never run in production and structurally could not have.
Pressing "Generate" would have left the admin watching a spinner forever.

`nishmat-worker` now runs alongside the API, built from `Dockerfile.worker` via
`RAILWAY_DOCKERFILE_PATH`. Both services deploy the same directory, so the
Dockerfile choice is what distinguishes them — a start command in the repo would
apply to both. **If lesson generation ever appears to hang, check this service
first.**

### 9.11 Every auth email linked to `localhost:3000`

Supabase `site_url` and `uri_allow_list` were never moved off localhost. The app
builds `emailRedirectTo` from `window.location.origin`, which is correct — but
Supabase **validates that against the allow-list and silently falls back to
`site_url` when it does not match**. So every confirmation, recovery and magic
link pointed at `http://localhost:3000`, and anyone clicking one on their phone
got "this site can't be reached".

Nothing in the app or its logs shows this. The redirect is rewritten inside
Supabase, so the code looks right and the email is wrong.

Now:

```
site_url       = https://nishmat-ai.vercel.app
uri_allow_list = https://nishmat-ai.vercel.app/**,http://localhost:3000/**
```

**Any new domain has to be added to the allow-list**, or its auth emails will
quietly point somewhere else. It is project configuration, not code — no deploy
changes it and no test catches it.

### 9.12 The chatbot answered "lesson 112" from whichever lessons mentioned lessons

Two compounding causes:

- `build_text_query` tokenised with `[^\W\d_]+`, which **excludes digits**.
  "lesson 112" became the single term "lesson" — the number, the only thing in
  the question that identified anything, was discarded. Exactly the §8.6 bug
  again, in a different disguise.
- Nothing else knew what a lesson number was. The vector arm embedded "what is
  lesson 112" to something generic, returned four unrelated lessons scoring
  ~0.4, and **that clears the 0.25 grounding threshold** — so the learner was
  told about lesson 120 with complete confidence.

That is worse than a refusal. A wrong answer that cites a lesson number looks
exactly like a right one.

Fixed by treating an explicit reference as a **fact**: `lesson_reference()`
parses "lesson 112" / "shiur #65" / "lesson no. 44", resolves it to a lesson id,
and scopes retrieval to that lesson — the same reasoning as looking a Psalm up
by address (§8.15). A number that names no lesson, or an unpublished one, is now
told plainly instead of answered from something else.

Two details worth keeping:

- The pattern requires the **word** before the number. A bare "112" is far more
  likely a Psalm or a year, and scoping an entire answer on that guess would be
  worse than not scoping.
- When a lesson is named explicitly, the similarity gate is bypassed if any
  passage came back. Relevance was established by the reference; a loosely
  phrased question ("anything interesting in lesson 3?") can score below the
  threshold against a lesson it is unambiguously about, and answering "I don't
  have anything in the lessons" about a lesson we just located is simply wrong.

---

## 10. Environment

**`backend/.env`** — never commit; never expose to the browser.

```bash
SUPABASE_URL=...
SUPABASE_ANON_KEY=...
SUPABASE_SERVICE_ROLE_KEY=sb_secret_...   # bypasses RLS
OPENAI_API_KEY=sk-proj-...

LLM_MODE=live                 # live | mock
AI_SPEND_CAP_USD=8.00         # hard stop, enforced in code
AI_SPEND_WARN_USD=5.00

OPENAI_MODEL_GENERATION=gpt-4.1          # quality matters, spend here
OPENAI_MODEL_MODIFICATION=gpt-4.1
OPENAI_MODEL_ANALYSIS=gpt-4.1-mini
OPENAI_MODEL_QUALITY=gpt-4.1-mini
OPENAI_MODEL_CHAT=gpt-4.1-mini
OPENAI_MODEL_UTILITY=gpt-4.1-nano
OPENAI_MODEL_VISION=gpt-4.1-mini
OPENAI_MODEL_TRANSCRIPTION=gpt-4o-mini-transcribe
OPENAI_MODEL_EMBEDDING=text-embedding-3-small   # 1536 dims, matches the schema

RAG_MIN_SCORE=0.25            # cosine similarity, NOT the RRF score
RAG_TOP_K=6
CHAT_HISTORY_WINDOW=8
CHAT_SUMMARY_THRESHOLD=16

# Vision gets its own budget — transcribing a page of vocalised Hebrew is
# several times a normal completion. See §9.9.
OPENAI_VISION_TIMEOUT_SECONDS=300
OPENAI_VISION_MAX_RETRIES=2
OPENAI_VISION_MAX_TOKENS=6000
```

**In production these are set as Railway variables on *both* services**, not
carried in a `.env` inside the image. `railway variables --service nishmat-ai`
and `--service nishmat-worker` list them.

**`frontend/.env.local`** — only these three. Anything else here is public.

```bash
NEXT_PUBLIC_SUPABASE_URL=...
NEXT_PUBLIC_SUPABASE_ANON_KEY=...
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

---

## 11. Budget — this is a hard constraint

**The client provided $10 of OpenAI credit and it will not be topped up.**
About **$0.41** has been spent.

| Operation | Cost |
|---|---|
| Generate one lesson (analysis + writing + check) | ~$0.027 |
| Generate one lesson **with references and an uploaded page** | **~$0.041** |
| Reading one photographed book page (vision) | ~$0.004 |
| One chat answer | ~$0.0005 |
| Embedding all 131 lessons | ~$0.03 (one-off) |
| Embedding the reference corpus (343 chunks) | ~$0.01 (one-off) |
| One run of `scripts/verify_production.py` | ~$0.05 (it really generates a lesson) |

Protections already in place — **do not weaken them**:

1. `AI_SPEND_CAP_USD` is checked before every call and **raises**, not warns.
2. Every call is recorded in `ai_usage`; the admin dashboard shows the total.
3. Tests force mock mode (§8.9).
4. Generation retries once, never loops (§8.8).
5. A second generate is refused while one is already running for that lesson.
6. Scanned PDFs are capped at 15 vision calls per upload.
7. Vision requests are downscaled, token-capped and retried at most twice.

---

## 12. Testing

```bash
cd backend
.venv\Scripts\python.exe -m pytest tests/ -q          # ~8 min, needs API + worker
.venv\Scripts\python.exe -m pytest tests/test_ingestion.py -q   # fast, offline
```

| File | Tests | Covers |
|---|---|---|
| `test_ingestion.py` | 24 | Validation, extraction, Hebrew, pricing. Offline, fast |
| `test_references.py` | 49 | **The reference pipeline.** Parsers against the real documents, briefs, prompt assembly, grounding, Hebrew normalisation, embed budgets. Offline, fast |
| `test_auth_live.py` | 14 | **The security suite.** Role enforcement, tampered tokens |
| `test_lessons_live.py` | 15 | Versioning, publishing, draft invisibility |
| `test_upload_live.py` | 9 | Upload → storage → worker → text, end to end |

`test_references.py` runs against the **actual** reference documents rather than
fixtures, because the failure it guards is a document arriving in a slightly
different shape and the corpus silently indexing half of it.

### Checking the deployed system

```bash
cd backend
.venv\Scripts\python.exe -m scripts.verify_production
```

Drives the real Railway API through the whole admin workflow — corpus visible,
lesson created from a brief, page attached and read, draft generated, sources
confirmed — then deletes everything it created including its temporary admin
account. Answers a different question from the unit tests: they say the code is
correct, this says the thing actually deployed does the job. Costs a few cents.

The live tests create throwaway accounts and delete them, and never touch the
client's real lessons (they use a scratch lesson numbered 9001).

`test_every_admin_route_carries_the_admin_dependency` is structural — it fails
if anyone mounts an admin route without `require_admin`. Keep it.

---

## 13. Product rules — never break these

1. Normal users can **never** create lessons.
2. Normal users can **never** publish.
3. Only an admin can generate or modify lessons.
4. Only an explicitly published version is visible to learners.
5. The chatbot answers **only** from published lessons.
6. Modifications create versions; history is never destroyed.
7. The OpenAI key is backend-only.
8. The source's meaning must be preserved; nothing is invented.
9. Format and style stay configurable (database, not code).
10. Hebrew and RTL are handled correctly everywhere.

**No AI output is ever auto-published.** Generation sets status to `generated`.
Publishing is always a human click.

---

## 14. What to do next

In recommended order.

### A. Show the output to Rivkah *(highest value, costs almost nothing)*

Phase 6b has been done against measured evidence (§8.12), and the fixed issues
were real: over-long lines, "dear friends", repeated sources, padded thin
sources. **But no human who knows her voice has read the output yet, and her
judgement is the acceptance criterion for this whole project.**

Generate 3–4 lessons, sit with her, and adjust
`lesson_templates.style_guide` at `/admin/templates` — it is data, no deploy
needed. About 3¢ per lesson.

Ask her specifically about:
- the proportion of very short lines (currently 22–32%, hers is 40%)
- whether the greetings sound like her
- whether anything reads as invented

Now also worth asking her, since the pipeline changed under it:

- whether the Nishmat and Tehillim passages it now pulls are the ones she would
  have reached for
- whether lessons feel connected to the ones before them (continuity now sees
  the last four lessons and their themes, not just one title)
- whether anything still reads as invented — and if so, whether the grounding
  check caught it. If it did and she disagrees with it, that is worth knowing.

### B. Set `ENVIRONMENT=production` *(one command, real exposure)*

The production API still reports `environment: development`, which leaves
`/docs` and `/openapi.json` publicly readable and lets internal error detail
reach users. Left undone only because it also changes log format:

```powershell
railway variables --service nishmat-ai     --set ENVIRONMENT=production
railway variables --service nishmat-worker --set ENVIRONMENT=production
```

Also worth adding a `.dockerignore` containing `.env` — secrets no longer need
to travel in the image now that Railway variables are set properly.

### C. Try a real ArtScroll page through the vision model

The uploaded-page path is verified end to end in production, but only with the
Nishmat page image — the one book-like scan in the repo. How well the model
reads a dense ArtScroll commentary page, with its footnotes and running heads,
needs one real photograph to judge. Cheap to find out (~$0.004).

### D. Phase 13 — the three stub pages

- **Style library** (`/admin/style-examples`) — 128 examples already exist in
  the database, 117 approved. Needs a list with approve/reject.
- **People** (`/admin/users`) — list accounts, change roles. Audit-log it.
- **Settings** (`/app/settings`) — name, email, password.

### E. Phase 14 — browser tests

Playwright for the two journeys: *admin uploads → generates → edits →
publishes*, and *learner reads → asks → gets a cited answer*.

A third is now worth adding: *admin enters a Nishmat phrase → attaches a book
page → generates → sees which sources were used*. `scripts/verify_production.py`
covers that path at the API level; nothing covers it in a browser.

---

## 15. Open questions for the client

1. **Audio playback for learners?** The lessons *are* voice recordings. The
   schema leaves room. Likely high value, low cost. Not built.
2. **`Nishmat #35.docx` is filed as #35 but its text says "lesson #36"**, and a
   separate `#36` exists. Both are unusually short. Mislabelled duplicate, or an
   unfinished lesson?
3. **The landing page no longer says "women only."** Those lines were marked for
   removal on the design reference, so the page now reads as open to everyone.
   Confirm that was intended.
4. **Who pays for OpenAI after the $10?** Get it in writing. $0.41 is spent and
   a reference-grounded lesson costs ~$0.04, so the remaining credit is roughly
   200 more lessons — enough for a long while, not forever.
5. **The English Nishmat translation.** The Tehillim document happens to carry
   an English rendering under each verse, so Psalms are covered. Nishmat itself
   is Hebrew only. If she wants English quotation of the prayer, we need a
   translation we may legitimately use — ask which one she considers correct.
6. **The 17 NJOP transcripts.** Never supplied. The system has a slot for them
   and reports them as missing; worth confirming whether they are actually
   coming or should be dropped from the plan.
7. **Should any uploaded book page ever become permanent?** Currently every one
   is scoped to its lesson and deleted with it. `reference_persist` exists if
   she wants a page kept — but that means storing copyrighted material
   indefinitely, which is her decision, not ours.
