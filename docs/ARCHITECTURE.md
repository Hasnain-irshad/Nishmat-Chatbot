# Nishmat Lesson Platform — Architecture & Implementation Plan

**Status:** Approved. Phases 0–2 built (scaffold, schema, auth, landing page, both dashboards, lesson reader).
**Date:** 2026-08-22
**Author:** Engineering plan prepared for client delivery

---

## 0. Repository inspection — what actually exists today

There is **no existing application code**. The repository currently contains exactly two things:

```
f:\AI-powered Learning Management\
├── Data/                    131 .docx files (+2 Word lock files to ignore)
└── sample output.txt        1 target-format lesson (Lesson #17, "Moshia")
```

So this is a **greenfield build**. No stack to adapt to, no legacy decisions to work around.

### 0.1 What the `Data/` corpus really is

I extracted and analysed all 131 documents. Findings that materially change the design:

| Finding | Detail | Impact |
|---|---|---|
| **Series is sequential** | Lessons #1–#130 + an "Introduction". Each lesson covers the **next word/phrase of the Nishmat Kol Chai prayer**, in order. #115 explicitly says *"Last week we spoke about Shir u'Shevachah… this week Hallel v'Zimrah."* #130 covers `אַתָּה אֵל` — the final words. | Lessons need an explicit **sequence position**, and the AI needs the **previous lesson** as context. Not just a bag of documents. |
| **Two formats coexist in the corpus** | ~120 files are *polished* (`🌸 Insights into Nishmat Kol Chai – Lesson #N`, flowing paragraphs). ~11 are *raw transcripts* of spoken WhatsApp recordings (#33–#39, #125–#127, Introduction). | The corpus already contains **source → polished pairs** (e.g. `Nishmat Introduction.docx` is the raw transcript; `Nishmat #1.docx` is its polished rewrite). This is a ready-made **style-example training set** — very valuable. |
| **Target format ≠ corpus format** | `sample output.txt` uses a *newer, tighter* editorial style: series title "Nishmat: A Journey of Praise", one sentence per line, heavy use of line breaks for emotional pacing. The corpus mostly uses ordinary paragraphs. | The sample is the **target for new generation**. The corpus is **knowledge + style substrate**, not the output spec. |
| **Author signature** | 105 of 131 files end `— Rivkah`. | Sign-off is a template field, not a hard-coded string. |
| **"WhatsApp Summary" blocks** | 6 files end with a condensed recap block (see #130, #17). | Real, recurring client need. Should be an **optional template section**, likely valuable as a feature ("generate the WhatsApp summary"). |
| **Data quality issues** | `#130` and `#58` contain leftover ChatGPT chatter (*"This version is tighter. Stronger… If you want, we can now shape the exact 90-second recording cadence"*). `#35` (94 words), `#36` (38 words), `#7`, `#48` are stubs. `#36`, `#38`, Introduction contain **no Hebrew at all**. | Ingestion needs a **cleaning pass + admin review queue**, not a blind import. |
| **Naming is inconsistent** | `Nishmat #1.docx`, `Nishmat#12.docx`, `Nishmat_13.docx`, `NIshmat #54.docx`. | Lesson number must be parsed with a tolerant regex, then **confirmed by the admin**, never trusted blindly. |
| **No embedded media** | 0 of 131 files contain images or audio. | The PDF/audio/image pipelines are required by spec but have **no test data yet** — I will need samples from the client, or I will generate my own fixtures. |
| **Hebrew** | Present in 128/131 files, fully vocalised (nikud), e.g. `הַמְנַהֵג עוֹלָמוֹ בְּחֶסֶד`. | RTL handling and **nikud preservation** are hard requirements. Nikud is easily destroyed by careless normalisation. |
| **Length** | Median 624 words, range 38–1158. | Lessons are short. This is good news: whole-lesson AI operations fit comfortably in context, and RAG chunking can be generous. |

### 0.2 Concrete example of the transformation the client wants

Source (`Nishmat Introduction.docx`, raw transcript):
> *"Good morning everyone or good evening depending on when you're listening to this recording. We are learning insights into the words of nishmat kol chai. We started out learning until the sheloshim of our good friend Rachel bat Rut…"*

Polished (`Nishmat #1.docx`):
> *"Shavua tov, neshamot yekarot 🌸*
> *Whether you've been with us since the very first Nishmat lesson or you're joining our group for the very first time — welcome.*
> *Each of you is part of this growing circle of women whose voices, hearts, and tefillot are joining together in gratitude to Hashem."*

Target style (`sample output.txt`) pushes it further — shorter lines, more breath:
> *"You've been davening.*
> *Maybe for weeks.*
> *Maybe for months.*
> *Maybe for years."*

**This is the single most important thing the product must do well.** Everything else is plumbing.

---

## 1. Understanding of the project

A two-role web application for a Torah-learning series ("Insights into Nishmat Kol Chai" / "Nishmat: A Journey of Praise"), authored by a single teacher (Rivkah) for a community of women.

**Admin (the teacher / her assistant)** uploads raw source material — a spoken-recording transcript, a PDF, a DOCX, an audio file, a photo of a page — and the system turns it into a *publishable lesson written in her voice*, following her editorial format. She reviews it, edits it by hand or by talking to the AI, and only then publishes it.

**Audience (community members)** read published lessons and ask an AI chatbot questions grounded in those lessons, with conversation memory and persistent chat history.

**The product's real value is the writing.** Not summarisation — *voice transfer plus structural reformatting, with strict factual fidelity to the source.* Fabricating a Torah source or a research statistic in this domain is not a bug, it is a reputational incident for the client. The architecture treats anti-fabrication as a first-class requirement, not a prompt afterthought.

---

## 2. Recommended technology stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | **Next.js 15 (App Router) + TypeScript + Tailwind + shadcn/ui** | Server components for auth-gated pages, excellent RTL support, one deploy to Vercel. shadcn gives a professional look without design time. |
| Rich text editor | **TipTap (ProseMirror)** | The only mainstream editor with proper per-block `dir="rtl"` support, and it stores structured JSON — which we need for *section-aware* AI edits. |
| Backend | **FastAPI (Python 3.12) — modular monolith** | Document parsing in Python is genuinely better (PyMuPDF, python-docx). Async-native for OpenAI calls. Pydantic gives typed contracts end to end. |
| Database | **Supabase Postgres + pgvector** | Relational data + auth + storage + vectors in one managed service. Correct call — no reason to deviate. |
| Auth | **Supabase Auth (JWT, asymmetric ES256 keys)** | Backend verifies signatures via JWKS with no shared secret; role authority stays in our DB. |
| Storage | **Supabase Storage, private buckets** | Signed URLs only. Source files are never public. |
| AI | **OpenAI** (client-provided key), behind our own `LLMProvider` interface | Client's key, client's cost. The interface keeps a future provider swap to one file. |
| Background work | **Postgres job queue + dedicated worker process** | No Redis, no Celery. ~150 lines, survives restarts, gives real status tracking. See §12. |
| Testing | pytest + httpx (backend), Vitest + Playwright (frontend) | |
| Deploy | Vercel (web) + Render or Railway via Docker (API) + Supabase (data) | Cheapest practical production setup. See §19. |

### 2.1 The one decision worth debating: two services or one?

An all-Next.js app (API routes doing everything) would be **one deploy instead of two**. I am recommending against it:

- PyMuPDF has no real JS equivalent for reliable multi-column / scanned PDF extraction.
- Long-running generation jobs on Vercel serverless hit execution limits; a persistent Python worker does not.
- The AI pipeline is the heart of this product and is much easier to test, log, and evolve as typed Python services.

**Cost of the split:** two deploy targets, CORS config, and JWT verification implemented once in the API. That is a few hours of setup for a much better foundation. If you would prefer a single deployable, say so now — it is cheap to change today and expensive later.

---

## 3. System architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        BROWSER                                    │
│   /admin/*  (role=admin only)      │   /app/*  (any auth user)   │
│   Next.js 15 App Router  ·  TipTap editor  ·  Tailwind/shadcn     │
└───────────────┬──────────────────────────────┬───────────────────┘
                │ Supabase JWT (Bearer)        │
                ▼                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                   FastAPI  (modular monolith)                     │
│                                                                   │
│  api/  ── routers: admin_lessons · admin_templates · admin_files │
│          ·  lessons · chat · health                              │
│  deps/ ── get_current_user  →  require_admin  (DB-authoritative) │
│                                                                   │
│  services/                                                        │
│   ├ ingestion/    pdf · docx · audio · image · text  (registry)  │
│   ├ analysis      source text → StructuredAnalysis (JSON schema) │
│   ├ generation    analysis + template + style pack → lesson      │
│   ├ modification  scoped or whole-lesson AI editing              │
│   ├ quality       PASS / WARN / FAIL + issue list                │
│   ├ embedding     chunk → vectors                                │
│   ├ retrieval     hybrid vector + full-text search               │
│   └ chat          RAG answer + conversation memory               │
│                                                                   │
│  llm/    provider abstraction · prompt builder · prompt registry  │
│  jobs/   queue client (enqueue / claim / complete)               │
└──────┬──────────────────────────┬───────────────────┬────────────┘
       │                          │                   │
       ▼                          ▼                   ▼
┌──────────────┐        ┌──────────────────┐   ┌──────────────┐
│  Worker      │        │    Supabase      │   │   OpenAI     │
│  process     │───────▶│  Postgres+pgvec  │   │              │
│  (same code, │        │  Auth · Storage  │   │ chat · vision│
│   polls jobs)│        │  RLS policies    │   │ stt · embed  │
└──────────────┘        └──────────────────┘   └──────────────┘
```

**Trust boundary:** the browser never talks to OpenAI, never receives the OpenAI key, and its claimed role is never believed. Role is read from `profiles` in Postgres on every request.

---

## 4. Database schema

Postgres, in Supabase. `vector` extension enabled. All tables have RLS on.

```
profiles ─────┬──< lessons ──┬──< lesson_versions ──< lesson_chunks
              │              ├──< source_files
              │              └──> lesson_templates
              │
              ├──< conversations ──< messages
              ├──< style_examples
              └──< jobs
```

### 4.1 `profiles`
Mirrors `auth.users`, created by trigger on signup.

| column | type | notes |
|---|---|---|
| `id` | uuid PK | FK → `auth.users.id` |
| `email` | text | |
| `full_name` | text | |
| `role` | `user_role` enum (`'admin'`,`'user'`) | **default `'user'`**. Only a service-role connection may change this. |
| `created_at` | timestamptz | |

### 4.2 `lesson_templates`
The lesson format lives here as data, never in Python.

| column | type | notes |
|---|---|---|
| `id` | uuid PK | |
| `name` | text | e.g. `"Nishmat — Journey of Praise"` |
| `description` | text | |
| `series_title` | text | `"Nishmat: A Journey of Praise"` |
| `sections` | jsonb | ordered array — see §8 |
| `style_guide` | text | prose style instructions given to the model |
| `formatting_rules` | jsonb | line-break cadence, paragraph length, emoji policy |
| `constraints` | jsonb | word-count range, content policy default |
| `signoff` | text | `"— Rivkah"` |
| `is_default` | boolean | |
| `version` | int | bumped on edit; versions kept in `lesson_template_versions` |
| `created_by`, `created_at`, `updated_at` | | |

### 4.3 `lessons`
The stable identity of a lesson. Content lives in versions.

| column | type | notes |
|---|---|---|
| `id` | uuid PK | |
| `title` | text | |
| `lesson_number` | int | nullable, **unique per series when set** |
| `series_id` | uuid | FK → `series` (a light table: id, title, slug) |
| `sequence_position` | int | ordering within the series — the corpus is sequential |
| `hebrew_phrase` | text | denormalised for list display / search |
| `template_id` | uuid | FK |
| `status` | `lesson_status` enum | `draft · processing · generated · review · approved · published · archived · failed` |
| `current_version_id` | uuid | FK → `lesson_versions` (nullable, deferred) |
| `published_version_id` | uuid | FK → `lesson_versions` (nullable) — **the only thing learners see** |
| `published_at` | timestamptz | |
| `created_by`, `created_at`, `updated_at` | | |

> `published_version_id` and `current_version_id` being separate columns is what makes Rule 6 and the "learners keep seeing v3 while admin drafts v4" requirement true *by construction*, not by convention.

### 4.4 `lesson_versions` — immutable
Never updated after creation (except the `status` label). This is the audit trail.

| column | type | notes |
|---|---|---|
| `id` | uuid PK | |
| `lesson_id` | uuid FK | |
| `version_number` | int | unique per lesson, allocated in a transaction |
| `parent_version_id` | uuid | which version this was derived from |
| `content` | jsonb | **structured**: `{sections:[{key,title,body,dir,order}]}` |
| `content_text` | text | flattened plain text — for search, embedding, export |
| `structured_analysis` | jsonb | the analysis stage output that produced this |
| `origin` | enum | `ai_generated · ai_modified · manual_edit · imported` |
| `modification_instruction` | text | the admin's natural-language request, if any |
| `quality_report` | jsonb | QC verdict + issues |
| `model_metadata` | jsonb | model names, prompt version, token usage, cost |
| `created_by`, `created_at` | | |

### 4.5 `source_files`

| column | type | notes |
|---|---|---|
| `id` | uuid PK | |
| `lesson_id` | uuid FK nullable | a file can be uploaded before a lesson exists |
| `original_filename`, `mime_type`, `size_bytes`, `checksum_sha256` | | checksum enables dedupe |
| `kind` | enum | `pdf · docx · audio · image · text` |
| `storage_path` | text | private bucket key |
| `extracted_text` | text | unified output of every extractor |
| `extraction_metadata` | jsonb | page count, audio duration, per-page confidence, warnings |
| `processing_status` | enum | `pending · processing · completed · failed` |
| `error_message` | text | user-safe message only |
| `uploaded_by`, `created_at` | | |

Transcription is stored in `extracted_text` with `extraction_metadata.transcript = true` plus segment timings — one field, one code path, no special-casing audio downstream.

### 4.6 `lesson_chunks` — RAG index
**Only ever populated from a published version.**

| column | type | notes |
|---|---|---|
| `id` | uuid PK | |
| `lesson_id`, `version_id` | uuid FK | |
| `chunk_index` | int | |
| `section_key` | text | which template section it came from |
| `chunk_text` | text | |
| `embedding` | `vector(1536)` | |
| `tsv` | tsvector GENERATED | `to_tsvector('simple', chunk_text)` — `'simple'`, not `'english'`, so Hebrew and transliterations survive |
| `metadata` | jsonb | lesson number, hebrew phrase, series |

Indexes: `hnsw (embedding vector_cosine_ops)`, `gin (tsv)`, `btree (lesson_id)`.

### 4.7 `style_examples` — the voice library

| column | type | notes |
|---|---|---|
| `id` | uuid PK | |
| `title`, `source_text` (nullable), `final_text` | | a pair when we have one, else just the polished text |
| `embedding` | `vector(1536)` | over `final_text` |
| `tags` | text[] | `story`, `hebrew-heavy`, `holiday`, `short-line-cadence` |
| `is_approved` | boolean | only approved examples are ever retrieved |
| `notes` | text | |

Seeded from the 131 corpus files (see §16, Phase 1b).

### 4.8 `conversations` / `messages`

`conversations`: `id, user_id, title, lesson_id (nullable — a chat can be scoped to one lesson), summary, message_count, last_message_at, created_at, updated_at, archived_at`

`messages`: `id, conversation_id, role (user|assistant|system), content, citations jsonb, token_usage jsonb, created_at`

`summary` on the conversation is the rolling compaction described in §13.

### 4.9 `jobs`

`id, type, payload jsonb, status (queued|running|succeeded|failed|cancelled), progress_stage text, progress_pct int, attempts int, max_attempts int, locked_at, locked_by, result jsonb, error text, created_by, created_at, updated_at`

Partial index on `(status, created_at) WHERE status='queued'` for cheap polling.

### 4.10 RLS policy summary

| Table | `user` role | `admin` role |
|---|---|---|
| `profiles` | read/update **own row**, cannot change `role` | read all |
| `lessons` | **SELECT only where `status='published'` AND `published_version_id IS NOT NULL`** | full |
| `lesson_versions` | SELECT only the row referenced by its lesson's `published_version_id` | full |
| `source_files` | **no access at all** | full |
| `lesson_chunks` | no direct access — reached only through a `SECURITY DEFINER` search function that hard-filters to published | full |
| `conversations`, `messages` | own rows only | own rows only (admins get no special read on other people's chats — privacy) |
| `style_examples`, `lesson_templates`, `jobs` | no access | full |

RLS is **defence in depth**, not the primary control. The API enforces authorisation first; RLS ensures a bug or a leaked anon key still cannot expose drafts.

---

## 5. Authentication & authorisation

**Three enforcement layers.** A normal user calling `POST /admin/lessons` by hand with a valid token must fail at layer 2 even if layers 1 and 3 were broken.

**Layer 1 — Frontend (UX only, not security).** Next.js middleware reads the Supabase session, redirects unauthenticated users to `/login`, and blocks `/admin/*` for non-admins. Navigation and buttons differ by role.

**Layer 2 — Backend (authoritative).**
```python
async def get_current_user(authorization: str = Header(...)) -> CurrentUser:
    token = _bearer(authorization)
    claims = verify_jwt(token)            # ES256 via cached Supabase JWKS
    profile = await profiles.get(claims["sub"])   # role read from OUR DB
    if profile is None: raise HTTPException(401)
    return CurrentUser(id=profile.id, email=profile.email, role=profile.role)

async def require_admin(user = Depends(get_current_user)) -> CurrentUser:
    if user.role != "admin": raise HTTPException(403, "Admin access required")
    return user
```
Every admin router is mounted with `dependencies=[Depends(require_admin)]` — an authorisation check cannot be forgotten on an individual endpoint. A test asserts that *every* route under `/admin` carries the dependency.

**Layer 3 — Database.** RLS as above. The backend uses the **user's own JWT** for user-scoped reads (so RLS applies), and the **service-role key only** for genuinely privileged operations (publishing, indexing, job processing) — never as a blanket default.

**Role assignment.** `role` defaults to `'user'` and is not settable through any public API. The first admin is promoted by SQL during setup; afterwards an admin can promote others from the admin panel (that endpoint is `require_admin` + audit-logged).

---

## 6. File processing architecture

A registry of processors behind one interface, so a new file type is one new file plus one registration line.

```python
class ExtractionResult(BaseModel):
    text: str
    metadata: dict
    warnings: list[str]

class FileProcessor(Protocol):
    kind: SourceKind
    def supports(self, mime: str, ext: str) -> bool: ...
    async def extract(self, path: Path) -> ExtractionResult: ...
```

| Type | Library / model | Notes |
|---|---|---|
| **PDF** | PyMuPDF (`fitz`) | Per-page extraction preserving reading order and headings. If a page yields < 20 chars → likely scanned → **fall back to OpenAI vision** on the rendered page image. Warn the admin which pages used fallback. |
| **DOCX** | `python-docx` | Paragraphs + tables + heading levels. **Falls back to raw XML parsing** if python-docx chokes — the corpus already proves DOCX in the wild is messy. |
| **Audio** | OpenAI speech-to-text | Files > 24 MB are chunked on silence boundaries (`pydub`) and re-joined. `prompt` seeded with a Hebrew/Yiddish glossary (`Hashem, neshamot, tefillah, shidduch, parnassah, yeshuah, Shavua tov…`) — this dramatically improves transliteration accuracy on this vocabulary. Transcript is stored and shown to the admin for correction **before** generation. |
| **Image** | OpenAI vision | Not naive OCR: the prompt asks for verbatim text (Hebrew preserved with nikud, marked as Hebrew) *and* a description of non-text visual content. Multiple images → one merged document. |
| **Text/MD** | stdlib | Encoding sniffing, UTF-8 normalisation. |

**Validation before anything is stored:** extension allowlist, MIME sniffed from **content** (`python-magic`) not the client header, size caps per type (PDF/DOCX 25 MB, image 10 MB, audio 100 MB), and SHA-256 dedupe.

**Hebrew handling rule:** Unicode normalisation is **NFC only**. No aggressive stripping — NFKD or naive "accent removal" destroys nikud. This is asserted by a unit test using a vocalised string from the corpus.

---

## 7. AI lesson-generation architecture

Four discrete, individually testable, individually re-runnable stages. Every stage's output is persisted, so when a lesson comes out wrong you can see *which stage* went wrong.

```
source_file.extracted_text
   │
   ├─ [1] ANALYSE ──────────────► StructuredAnalysis  (JSON, schema-enforced)
   │      temperature 0.2 · no writing, only understanding
   │
   ├─ [2] BUILD CONTEXT ────────► template + style pack + 2-3 retrieved
   │      deterministic code       examples + previous lesson + policy
   │
   ├─ [3] GENERATE ─────────────► LessonDraft (sections[])
   │      temperature 0.8 · the actual writing
   │
   └─ [4] QUALITY CHECK ────────► QualityReport {PASS|WARN|FAIL, issues[]}
          temperature 0 · adversarial, fresh eyes
              │
              └─ FAIL → regenerate ONCE with the issues appended → then stop.
                        Never loop. Always land in the admin's review queue.
```

### Stage 1 — Analysis (understanding, not writing)

Uses OpenAI **Structured Outputs** (strict JSON schema) so the result is guaranteed parseable.

```python
class Quote(BaseModel):
    text: str
    attribution: str | None
    verbatim_from_source: bool          # anti-fabrication flag

class StructuredAnalysis(BaseModel):
    detected_lesson_number: int | None
    central_theme: str
    hebrew_phrase: str | None           # verbatim, nikud preserved
    transliteration: str | None
    translation: str | None
    key_concepts: list[str]
    main_points: list[str]
    stories: list[Story]                # each with source_span
    examples: list[str]
    torah_sources: list[Quote]          # NEVER invented
    research_claims: list[Quote]        # statistics etc., flagged for verification
    reflection_questions: list[str]
    practical_takeaway: str | None
    closing_message: str | None
    emotional_arc: str
    source_coverage_notes: str          # what is thin / missing
    warnings: list[str]                 # "no Hebrew phrase found", "very short source"
```

Two things here are deliberate and important:

1. **`verbatim_from_source` on every quote.** The generator is instructed it may only present a Torah source or a statistic as a quotation if this flag is true. Everything else must be paraphrased or dropped. This is how we make Rule "do not fabricate sources" mechanically checkable rather than aspirational.
2. **`source_coverage_notes`.** If the source is a 38-word stub (`#36` exists!), the analysis says so, and the admin sees a warning instead of a confidently hallucinated 700-word lesson.

### Stage 2 — Context assembly (deterministic Python, zero AI)

Gathers: the template record · the style pack · 2–3 style examples retrieved by embedding similarity to `central_theme` · the previous lesson in the series (title + hebrew phrase + closing lines, for continuity like *"Last week we spoke about…"*) · the content policy · the admin's extra instructions.

### Stage 3 — Generation

Output is **structured sections**, not a wall of markdown:

```json
{"sections":[
  {"key":"series_title","title":null,"body":"Nishmat: A Journey of Praise","dir":"ltr"},
  {"key":"hebrew_phrase","title":null,"body":"וּמִבַּלְעָדֶךָ אֵין לָנוּ מֶלֶךְ...","dir":"rtl"},
  {"key":"transliteration","body":"U'mibaladecha ein lanu Melech...","dir":"ltr"},
  ...
]}
```

Why sections rather than one blob: it makes template compliance checkable in code, lets the editor render RTL per block, lets the admin regenerate *one* section, and gives RAG chunking natural boundaries. This is the single highest-leverage structural decision in the AI layer.

### Stage 4 — Quality check

A separate call with a **fresh context** (it does not see the generation prompt — otherwise it just agrees with itself). Returns:

```json
{"verdict":"WARN",
 "checks":{"meaning_preserved":true,"template_followed":true,"sections_present":true,
           "tone_appropriate":true,"hebrew_intact":true,"no_fabricated_quotes":false,
           "no_fabricated_sources":true,"no_unrelated_material":true,"coherent":true},
 "issues":[{"severity":"high","section":"supporting_source",
            "message":"Quotes a Gemara not present in the source material",
            "suggestion":"Remove or replace with the Gemara actually cited in the source"}]}
```

Plus **deterministic checks in Python** — required sections present, word count in range, Hebrew codepoints preserved byte-for-byte from the analysis, no forbidden phrases. Cheap, instant, no tokens, catches the boring failures.

**FAIL** → one automatic retry with issues fed back → then it goes to the admin regardless, clearly badged. No infinite loops, no silent auto-publishing.

### Content policy (configurable, defaults conservative)

| Policy | Behaviour | Default |
|---|---|---|
| `strict_source_only` | Nothing beyond the source. No added Torah sources. | ✅ **MVP default** |
| `source_plus_approved_refs` | May draw on the client's own prior lessons in the DB, cited. | available |
| `source_plus_external` | Allowed to add outside material. | present in schema, **disabled in MVP** |

Creative expansion level `strict | moderate | creative` maps to temperature + explicit prompt latitude. Default **moderate** for generation (the sample output is clearly not a mechanical restatement), **strict** for modifications.

---

## 8. Lesson template architecture

A template is a row, not code. Structure:

```json
{
  "name": "Nishmat — Journey of Praise",
  "series_title": "Nishmat: A Journey of Praise",
  "sections": [
    {"key":"series_title",       "label":"Series title",        "required":true,  "dir":"ltr", "max_words":10,
     "guidance":"The series name, exactly as configured."},
    {"key":"lesson_number",      "label":"Lesson number",       "required":true,  "dir":"ltr"},
    {"key":"hebrew_phrase",      "label":"Hebrew phrase",       "required":false, "dir":"rtl",
     "guidance":"Verbatim from source, nikud preserved. Omit the section entirely if the source has no Hebrew."},
    {"key":"transliteration",    "label":"Transliteration",     "required":false, "dir":"ltr"},
    {"key":"translation",        "label":"English translation", "required":false, "dir":"ltr"},
    {"key":"greeting",           "label":"Warm greeting",       "required":true,
     "guidance":"e.g. 'Shavua tov, neshamot yekarot.' Vary it — do not reuse the same opening every lesson."},
    {"key":"introduction",       "label":"Introduction",        "required":true},
    {"key":"central_concept",    "label":"Central word/concept","required":true},
    {"key":"personal_hook",      "label":"Personal hook",       "required":true},
    {"key":"story_example",      "label":"Story or example",    "required":true},
    {"key":"spiritual_connection","label":"Connection to the idea","required":true},
    {"key":"supporting_source",  "label":"Supporting Torah source","required":false,
     "guidance":"ONLY if present in the source material. Never invent."},
    {"key":"reflection",         "label":"Deeper reflection",   "required":true},
    {"key":"practical_takeaway", "label":"Practical invitation","required":true},
    {"key":"closing_blessing",   "label":"Closing blessing",    "required":true},
    {"key":"signoff",            "label":"Sign-off",            "required":true}
  ],
  "optional_addons": [
    {"key":"whatsapp_summary", "label":"WhatsApp summary", "enabled_by_default": false,
     "guidance":"A condensed shareable recap, ~120 words, ending with the sign-off."}
  ],
  "formatting_rules": {
    "line_break_cadence":"frequent — one thought per line during emotional passages",
    "paragraph_max_sentences":3,
    "emphasis_technique":"very short standalone lines, and deliberate ellipses for breath",
    "emoji_policy":"sparing — at most one decorative emoji in the header",
    "rtl_blocks":["hebrew_phrase"]
  },
  "constraints": {"min_words":450,"max_words":900,
                  "content_policy":"strict_source_only","creative_level":"moderate"},
  "signoff":"— Rivkah"
}
```

The `whatsapp_summary` addon comes directly from the corpus — 6 lessons already have one and it is clearly how the client distributes. It is a small feature with obvious value.

**No section key, no label, and no style phrase appears anywhere in the Python source.** The prompt builder walks `sections` and emits instructions.

---

## 9. Style architecture — how the voice is captured

Three layers, cheapest first. **No fine-tuning** — 131 documents is far too few for a good fine-tune, and it would freeze the style at today's snapshot while the client's voice is visibly still evolving (compare #33 to #130).

1. **Style guide (static, in the template).** Explicit prose rules distilled from the corpus + sample: warm and personal, second person, rhetorical questions, short lines for emphasis, Hebrew with transliteration and translation on first use, no academic register, no "In conclusion", no generic AI throat-clearing.
2. **Few-shot examples (dynamic, retrieved).** 2–3 approved `style_examples` selected by embedding similarity to the new lesson's `central_theme`. Retrieval is **rotated** — the top match plus a random pick from the next 10 — so the same three exemplars are not injected into every lesson. This is what stops the model reusing *"Maybe for weeks. Maybe for months."* verbatim in lesson after lesson.
3. **Anti-repetition guard.** Before returning a draft, we check its distinctive n-grams against the last ~10 generated lessons. Heavy overlap → a targeted "vary the phrasing" regeneration. The client explicitly asked for this; it is the difference between "sounds like her" and "sounds like a template".

---

## 10. AI modification architecture

Two scopes, deliberately different in what they send.

**A. Scoped edit** — admin selects a paragraph or section and types an instruction.
Sent: the selected text · the section's template guidance · the ±1 neighbouring sections (trimmed) · the style pack · the instruction.
**Not sent:** the whole lesson. On a 700-word lesson the saving is modest, but the *quality* gain is the real point — a narrow context produces a surgical edit instead of the model quietly rewriting three other paragraphs.
Returns: replacement text for that span only + a one-line explanation. The UI shows a **diff** before the admin accepts.

**B. Whole-lesson edit** — "make the whole thing warmer", "shorten by 20%".
Sent: the full structured content · template · style pack · instruction. Returns a complete new section set.

Both paths:
- create a **new immutable version** (`origin='ai_modified'`, `modification_instruction` stored);
- run the deterministic quality checks (Hebrew intact, required sections present);
- **never** change `published_version_id`. Publishing is always a separate, explicit admin action.

Manual typing in the editor also creates a version, but debounced — one version per editing session, not per keystroke.

---

## 11. Versioning & publishing

```
lesson.current_version_id   → what the admin is editing   (advances freely)
lesson.published_version_id → what learners see           (advances ONLY on publish)
```

**Publish** (`POST /admin/lessons/{id}/publish`, transactional):
1. Validate: version exists, belongs to the lesson, required sections present.
2. Set `published_version_id = <version>`, `status='published'`, `published_at=now()`.
3. Enqueue a `reindex_lesson` job.
4. The job deletes this lesson's old chunks and inserts fresh ones **from the newly published version only**.

**Unpublish** nulls `published_version_id`, sets `status='archived'`, and deletes the chunks. Learner visibility and RAG visibility are therefore *the same switch* — they cannot drift apart. That is the structural guarantee behind Rules 4 and 5.

Version history UI: list with author, timestamp, origin, instruction; side-by-side diff between any two; "restore" creates a *new* version copying the old content (never rewrites history).

---

## 12. Background jobs — why a table, not Redis

Requirements: transcription (30 s–3 min), generation (20–60 s), embedding (10–30 s). These exceed a comfortable HTTP request and must survive a redeploy.

Chosen approach: **a `jobs` table and a worker process running the same codebase.**

```
POST /admin/lessons/{id}/generate → INSERT job(queued) → 202 {job_id}
Worker: SELECT ... FOR UPDATE SKIP LOCKED → run → update progress_stage → complete
Frontend: GET /jobs/{id} every 2s → shows Analyzing… / Generating… / Validating… / Ready
```

Cost: ~150 lines. Gains: durable, restart-safe, retryable, visible progress, and **zero extra infrastructure**. `SKIP LOCKED` makes it safe to run multiple workers later. A stale-lock reaper requeues jobs whose worker died.

Redis/Celery would add a service, a bill, and deployment complexity for a workload of a few dozen jobs a week. If throughput ever demands it, the queue client interface is the only thing that changes.

SSE streaming for progress is a Phase 13 nice-to-have; polling is simpler and completely adequate at this scale.

---

## 13. RAG architecture

**Indexing** (published versions only)
- Chunk on **template section boundaries**, then split any section over ~350 words at sentence boundaries with ~15% overlap. Median lesson is 624 words → roughly 3–6 semantically coherent chunks. No 200-token confetti.
- Every chunk is prefixed with a small context header (`Lesson #17 — "Moshia" — section: Story`) before embedding. Cheap, and materially improves retrieval on short chunks.
- `text-embedding-3-large` (1536 dims via the `dimensions` parameter, keeping the index small).

**Retrieval — hybrid, and this matters here**
Pure vector search underperforms on this corpus because the highest-signal query terms are *transliterated Hebrew* (`Moshia`, `chesed`, `hakarat hatov`) which embedding models handle unevenly. So:

```
query ──┬─► vector search (cosine, top 20) ─┐
        └─► full-text search (tsv, top 20) ─┴─► Reciprocal Rank Fusion ─► top 6
```

One `SECURITY DEFINER` SQL function does both and fuses them. That function contains the published-only filter, so **no caller can accidentally retrieve a draft**.

**Answering**
System prompt: answer *only* from the provided excerpts; cite lesson numbers; if the excerpts are insufficient, say so plainly and warmly and suggest what the community *does* cover. Every answer returns `citations: [{lesson_id, lesson_number, title, section}]`, rendered as clickable chips.

**Grounding guard:** if the best fused score falls below a threshold, we skip the LLM call entirely and return the "I don't have that in the lessons yet" response deterministically. Cheaper, faster, and impossible to hallucinate through.

---

## 14. Chat memory & history

**Memory strategy — sliding window plus rolling summary:**

- Always send: system prompt + retrieved chunks + `conversation.summary` (if any) + the **last 8 messages** verbatim.
- When a conversation exceeds 16 messages, a background job summarises messages 1..N-8 into `conversation.summary` (~200 words, focused on entities and threads: *"Discussing Lesson #17 (Moshia); user asked about the tantrum analogy; interested in Elul"*). Older raw messages stay in the DB for display but leave the LLM context.
- **Query rewriting:** before retrieval, a small cheap call turns `"explain the second idea"` into a standalone query using the last 4 messages. This is what makes follow-up questions actually work — without it, `"the second idea"` embeds to noise. It is the single most valuable 200 tokens in the chat path.

Result: bounded and predictable context (~2–3 k tokens) no matter how long the conversation runs.

**History:** conversations grouped Today / Yesterday / This week / Earlier. Title auto-generated from the first exchange. Users may rename, archive, delete, and resume any conversation. A chat can be *scoped to a lesson* (opened from the reader, retrieval boosted toward that lesson) or global.

---

## 15. Frontend structure

```
app/
├─ (auth)/login · signup · forgot-password
├─ (admin)/admin/                      ← middleware: role must be admin
│   ├─ page.tsx                        Dashboard: counts, recent, failed jobs
│   ├─ lessons/
│   │   ├─ page.tsx                    List: filters by status, search
│   │   ├─ new/page.tsx                Upload → processing → template → generate
│   │   └─ [id]/
│   │       ├─ page.tsx                Editor  (the main workspace)
│   │       ├─ versions/page.tsx       History + diff viewer
│   │       └─ source/page.tsx         Extracted text / transcript review
│   ├─ templates/                      List + editor
│   ├─ style-examples/                 Library, approve/reject
│   └─ users/                          Role management
├─ (app)/                              ← any authenticated user
│   ├─ page.tsx                        Lesson grid, search
│   ├─ lessons/[id]/page.tsx           Reader + "Ask about this lesson"
│   └─ chat/
│       ├─ page.tsx                    New conversation
│       └─ [conversationId]/page.tsx   Continue
components/
├─ editor/           LessonEditor · SectionBlock · AiEditPopover · DiffView
├─ lesson/           LessonReader · HebrewBlock · CitationChip · StatusBadge
├─ chat/             ChatWindow · MessageBubble · ChatSidebar · Citations
├─ upload/           Dropzone · ProcessingStatus · JobProgress
└─ ui/               shadcn primitives
```

**The admin editor** is the product's centre of gravity, so it gets the most design care: section-based editing with each section labelled by its template role, `dir="rtl"` automatically on Hebrew blocks, a floating "Ask AI" popover on text selection, a right-hand panel with the source text and the quality report, and a persistent status bar (`Draft v4 · Published v3 · unsaved changes`).

**Hebrew/RTL rules applied throughout:**
- `dir="auto"` on all user/AI content containers; explicit `dir="rtl"` on Hebrew section blocks.
- A Hebrew font stack with nikud support (`Frank Ruhl Libre` / `David Libre` / `Noto Sans Hebrew`), increased line-height so vowel points do not collide.
- CSS logical properties (`margin-inline-start`, not `margin-left`) so layout never breaks under RTL.
- Mixed-direction inline Hebrew wrapped in `<span dir="rtl">` — a bare Hebrew word inside an English sentence otherwise drags surrounding punctuation to the wrong side (the classic bidi bug).

**States:** every async surface has explicit loading (skeletons), empty, and error states with a retry. No spinners-forever.

---

## 16. Backend API

```
GET    /health

──── ADMIN  (all require role=admin) ────────────────────────────
POST   /admin/files/upload                 multipart → source_file + extraction job
GET    /admin/files/{id}                   status + extracted text
PATCH  /admin/files/{id}/text              admin corrects a transcript/extraction

POST   /admin/lessons                      create (title, template, source_file_ids)
GET    /admin/lessons                      list ?status= &q= &page=
GET    /admin/lessons/{id}                 lesson + current version + quality report
PATCH  /admin/lessons/{id}                 metadata (title, number, template)
DELETE /admin/lessons/{id}                 soft delete
POST   /admin/lessons/{id}/generate        → 202 job
POST   /admin/lessons/{id}/modify          {scope: section|whole, instruction, ...} → 202 job
POST   /admin/lessons/{id}/versions        manual save → new version
GET    /admin/lessons/{id}/versions        history
GET    /admin/lessons/{id}/versions/{v}    one version
POST   /admin/lessons/{id}/versions/{v}/restore
POST   /admin/lessons/{id}/publish         {version_id}
POST   /admin/lessons/{id}/unpublish

GET    /admin/templates                    CRUD
POST   /admin/templates
GET    /admin/templates/{id}
PATCH  /admin/templates/{id}

GET    /admin/style-examples               CRUD + approve
POST   /admin/style-examples
PATCH  /admin/style-examples/{id}

GET    /admin/users
PATCH  /admin/users/{id}/role              audit-logged

──── AUTHENTICATED USERS ────────────────────────────────────────
GET    /lessons                            published only ?q= &page=
GET    /lessons/{id}                       published version only
POST   /chat/conversations                 {lesson_id?} → conversation
GET    /chat/conversations                 own, grouped by recency
GET    /chat/conversations/{id}            with messages
PATCH  /chat/conversations/{id}            rename / archive
DELETE /chat/conversations/{id}
POST   /chat/conversations/{id}/messages   → answer + citations

──── SHARED ─────────────────────────────────────────────────────
GET    /jobs/{id}                          own jobs (admin: any)
GET    /me                                 profile + role
```

Route handlers stay thin: validate → call service → map to response. All business logic lives in `services/`.

### Folder structure

```
/
├─ Data/                              (existing corpus — read-only, git-ignored)
├─ sample output.txt                  (existing reference)
├─ docs/
│   ├─ ARCHITECTURE.md                ← this document
│   ├─ SETUP.md · DEPLOYMENT.md · CLIENT_GUIDE.md
├─ backend/
│   ├─ app/
│   │   ├─ main.py  config.py  logging.py
│   │   ├─ api/            routers/ · deps.py · errors.py
│   │   ├─ core/           security.py · jwt.py · rate_limit.py
│   │   ├─ db/             supabase.py · repositories/
│   │   ├─ models/         pydantic schemas (domain + api)
│   │   ├─ services/
│   │   │   ├─ ingestion/  base.py pdf.py docx.py audio.py image.py text.py registry.py
│   │   │   ├─ analysis_service.py       generation_service.py
│   │   │   ├─ modification_service.py   quality_service.py
│   │   │   ├─ embedding_service.py      retrieval_service.py
│   │   │   ├─ chat_service.py           publishing_service.py
│   │   │   └─ style_service.py
│   │   ├─ llm/            provider.py openai_provider.py prompt_builder.py
│   │   │                  prompts/ (versioned .md/.j2 templates)
│   │   ├─ jobs/           queue.py worker.py handlers/
│   │   └─ utils/          hebrew.py text.py files.py
│   ├─ migrations/         0001_init.sql … (plain SQL, ordered)
│   ├─ scripts/            seed_corpus.py  promote_admin.py  reindex_all.py
│   ├─ tests/              unit/ integration/ fixtures/
│   ├─ pyproject.toml  Dockerfile  .env.example
└─ frontend/
    ├─ app/ components/ lib/ hooks/ types/ messages/
    ├─ middleware.ts  tailwind.config.ts  package.json  .env.example
```

Prompts live in `llm/prompts/` as versioned files, **not** as string literals inside services. Changing the client's tone becomes editing one file, and every generated version records which prompt version produced it.

---

## 17. Environment variables

**Backend** (`backend/.env`)
```bash
ENVIRONMENT=development                  # development | production
LOG_LEVEL=INFO
API_CORS_ORIGINS=http://localhost:3000

SUPABASE_URL=https://<project>.supabase.co
SUPABASE_ANON_KEY=<anon key>
SUPABASE_SERVICE_ROLE_KEY=<service role key>   # BACKEND ONLY — never in frontend
SUPABASE_JWT_ISSUER=https://<project>.supabase.co/auth/v1
SUPABASE_DB_URL=postgresql://...               # direct connection for migrations

OPENAI_API_KEY=<client's key>
OPENAI_MODEL_ANALYSIS=<strong reasoning model>
OPENAI_MODEL_GENERATION=<strong writing model>
OPENAI_MODEL_MODIFICATION=<same as generation>
OPENAI_MODEL_QUALITY=<cheaper model>
OPENAI_MODEL_CHAT=<mid-tier model>
OPENAI_MODEL_UTILITY=<cheap model — titles, query rewriting, summaries>
OPENAI_MODEL_VISION=<vision-capable model>
OPENAI_MODEL_TRANSCRIPTION=<speech-to-text model>
OPENAI_MODEL_EMBEDDING=text-embedding-3-large
OPENAI_EMBEDDING_DIMENSIONS=1536
OPENAI_MAX_RETRIES=3
OPENAI_TIMEOUT_SECONDS=120

MAX_UPLOAD_MB_DOCUMENT=25
MAX_UPLOAD_MB_IMAGE=10
MAX_UPLOAD_MB_AUDIO=100
SUPABASE_STORAGE_BUCKET=source-files

WORKER_POLL_INTERVAL_SECONDS=3
WORKER_MAX_ATTEMPTS=3
GENERATION_MAX_AUTO_RETRIES=1
RAG_TOP_K=6
RAG_MIN_SCORE=0.25
CHAT_HISTORY_WINDOW=8
CHAT_SUMMARY_THRESHOLD=16
```

**Frontend** (`frontend/.env.local`)
```bash
NEXT_PUBLIC_SUPABASE_URL=https://<project>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon key>
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```
Only these three. **No OpenAI key, no service-role key, ever.** A CI check greps the frontend bundle for `sk-` and for the service-role key prefix and fails the build on a hit.

> Model IDs are intentionally left as placeholders. I will confirm which models the client's key actually has access to and their current pricing before pinning defaults — hard-coding a model the key cannot call is a classic day-one failure.

---

## 18. Security

| Risk | Mitigation |
|---|---|
| Learner calls an admin endpoint directly | `require_admin` on the router, role read from DB not JWT claims; a test enumerates every `/admin` route and asserts the dependency is present |
| Learner reads a draft | API filters + RLS + published-only retrieval function — three independent layers |
| Draft leaks through the chatbot | Chunks only ever written on publish, deleted on unpublish; the search function hard-filters published |
| OpenAI key exposure | Backend-only, never returned by any endpoint, redacted in logs |
| Malicious upload | Content-sniffed MIME, extension allowlist, size caps, no execution, private bucket, SHA-256 dedupe |
| Prompt injection via an uploaded file | Source text is delimited and explicitly labelled untrusted data; the system prompt states that instructions inside source material must be ignored; the LLM never triggers a privileged action — publishing is a human click |
| Stack traces / internals to users | Global exception handler returns `{error, code, request_id}`; details go to logs only |
| Storage URL guessing | Private bucket, short-lived signed URLs, admin-only issuance |
| Cost / abuse | Per-user rate limits on generation and chat; token usage recorded per version and per message; a monthly spend view for the admin |
| PII in logs | Structured logging with a redaction filter; message bodies are never logged at INFO |
| Someone self-promotes to admin | `role` is not writable through any public API; RLS blocks it; changes are audit-logged |

---

## 19. Testing strategy

**Backend (pytest)** — targeting ~70% coverage on services, 100% on authorisation.

- *Auth & roles*: admin passes, user gets 403 on every admin route (parametrised over the actual router table), missing/expired/tampered tokens rejected, role cannot be self-elevated.
- *Ingestion*: real fixtures — a corpus DOCX, a text PDF, a scanned PDF (vision fallback), a Hebrew image, a short audio clip; corrupt-file and oversize-file paths; **a nikud-preservation assertion** on a real corpus string.
- *Analysis/generation/QC*: mocked LLM with recorded responses; schema-violation handling; QC FAIL → exactly one retry, never two.
- *Versioning*: version numbers are gapless and unique under concurrency; publishing a version does not mutate it; restore creates a new version.
- *Publishing*: publish → chunks exist; unpublish → chunks gone; a draft's chunks never exist.
- *RAG*: relevant query returns the right lesson; irrelevant query returns the honest "not covered" answer; **a draft lesson is never retrievable** (the security-critical test).
- *Chat*: memory window honoured; summary triggers at threshold; follow-up query rewriting resolves `"the second idea"`; users cannot read another user's conversation.

**Frontend** — Vitest for components (RTL rendering, status badges, diff view); Playwright for two end-to-end journeys: *admin uploads → generates → edits → publishes* and *user reads → asks → gets a cited answer → returns to history*.

**Manual acceptance with the client**: generate lessons from 5 real sources, sit with the client, and compare against her own published versions. Her judgement is the acceptance test that matters. Budget a tuning round after this.

---

## 20. Deployment

| Component | Where | Notes |
|---|---|---|
| Frontend | **Vercel** | Free/hobby tier is sufficient. Preview deploys per branch. |
| Backend API | **Render** or **Railway** (Docker) | ~$7–20/mo. Health check on `/health`. |
| Worker | **Same image, different start command** (`python -m app.jobs.worker`) | One extra small instance. |
| Database/Auth/Storage | **Supabase** | Free tier to start; Pro ($25/mo) when the client wants daily backups — recommend Pro before real launch. |
| Migrations | Plain ordered SQL, applied via Supabase CLI in CI | Every migration reviewed before it runs against production. |
| Secrets | Platform env vars only | Nothing in git. `.env.example` documents every key. |
| Monitoring | Sentry (free tier) + structured JSON logs + a `/health` uptime check | |
| Backups | Supabase automated + a weekly `pg_dump` to object storage | The 131 lessons are irreplaceable client IP. |

**Running cost estimate:** ~$30–50/month infrastructure, plus OpenAI usage (roughly $0.15–0.60 per generated lesson depending on model tier; chat is a fraction of a cent per message). Worth stating to the client explicitly — who pays the OpenAI bill should be settled in writing before launch.

---

## 21. Implementation roadmap

Sequenced so that something demonstrable exists early and the riskiest thing (the writing quality) is validated before the surrounding UI is polished.

| Phase | Deliverable | Est. |
|---|---|---|
| **0** | Repo scaffold, Docker, `.env.example`, CI lint/test, `/health` | 0.5 d |
| **1** | Supabase project, all migrations, RLS policies, seed template from §8, RLS tests | 1.5 d |
| **1b** | **Corpus ingestion script** — parse all 131 DOCX, clean the ChatGPT artifacts, parse lesson numbers, flag the short/Hebrew-less files for review, load as lessons + style examples | 1 d |
| **2** | Supabase Auth, `profiles` trigger, JWT verification, `require_admin`, login/signup UI, route guards, **the security test suite** | 1.5 d |
| **3** | Upload endpoint, validation, private storage, jobs table + worker, status polling UI | 1 d |
| **4** | Ingestion processors: DOCX, PDF (+vision fallback), audio, image, text; transcript review screen | 2 d |
| **5** | Template CRUD + admin template editor | 1 d |
| **6** | **AI pipeline: analysis → context → generation → QC.** Prompt registry. Style retrieval. Anti-repetition. | 3 d |
| **6b** | **Quality checkpoint with the client** — generate from her real sources, review together, tune prompts | 1 d + client time |
| **7** | Admin lesson editor (TipTap, sections, RTL blocks, source panel, quality panel) | 2.5 d |
| **8** | AI modification (scoped + whole), diff view, version history, restore | 2 d |
| **9** | Publish/unpublish workflow, status management, admin dashboard | 1 d |
| **10** | Chunking, embeddings, hybrid search function, reindex-on-publish | 1.5 d |
| **11** | User dashboard, lesson reader (RTL-correct), chat with RAG + citations + memory | 2.5 d |
| **12** | Chat history sidebar, grouping, rename/archive/resume | 1 d |
| **13** | UI polish, all loading/empty/error states, accessibility pass, mobile | 2 d |
| **14** | Test suite completion, Playwright journeys, security review | 1.5 d |
| **15** | Deployment, monitoring, backups, `SETUP.md` + `CLIENT_GUIDE.md`, handover walkthrough | 1.5 d |

**≈ 28 working days of focused effort.** Phases 6 and 6b are where this project is won or lost — the client's judgement of the writing is the real acceptance criterion, so that checkpoint is scheduled deliberately early, before 10 days of UI work are built on an unvalidated pipeline.

---

## 22. Open questions — resolved and outstanding

### Answered by the client (2026-08-22)

| # | Question | Decision |
|---|---|---|
| **Q1** | Are the 131 `Data/` lessons already-published content? | **Yes.** They are imported as **published lessons preserving their original text**, and registered as style examples. An admin "Reformat with template" action lets the client upgrade any of them to the newer style, one at a time, with review. |
| **Q3** | Does the chatbot answer in the lesson format? | **No.** `sample output.txt` is the **lesson generator's** target format. The **chatbot answers conversationally in Rivkah's voice, with citations.** |
| **Q4** | Real source samples for the file processors | **Audio provided** — `Audios/`, four WhatsApp voice notes (OGG/Opus, 2.5–6.7 min, ~19 min total). Enough to validate and tune the transcription glossary. PDF and image samples are still outstanding but not blocking. |
| **Q7** | Who pays for OpenAI? | **The client.** $10 of credit provided for development and testing; longer-term billing to be arranged with the client directly. See the budget note below. |
| **Q11** | Single deployable or two services? | **Two services confirmed** — Next.js + FastAPI. |

### Budget — $10 total, fixed. This is a hard constraint from the client.

An earlier draft of this document estimated $0.15–0.60 per generated lesson.
**That was wrong — it was a conservative guess made without doing the
arithmetic.** The real figure is about **$0.023**, and the whole project fits
inside $10 with room to spare.

**Cost of one generated lesson.** A generation call is ~6,400 input tokens
(system prompt + template + style guide + 2 retrieved style examples + source
text + previous-lesson context) and ~950 output tokens:

| Stage | Model tier | Cost |
|---|---|---|
| Analysis — source to structured JSON | cheap | ~$0.002 |
| **Generation — the actual writing** | **strong** | **~$0.020** |
| Quality check | cheap | ~$0.001 |
| **Per lesson, end to end** | | **~$0.023** |

**Whole-project budget:**

| Item | Cost |
|---|---|
| Embed all 131 lessons for RAG | $0.01 |
| Embed 128 style examples | $0.01 |
| Transcribe the 4 audio samples (19 min) | $0.06 |
| ~100 test generations across development and tuning | $2.30 |
| ~300 chat messages of RAG testing | $0.50 |
| Client demo runs | $0.50 |
| **Subtotal** | **~$3.40** |
| **Headroom** | **~$6.60** |

**Two caveats.** These are list prices from training knowledge — verify against
the client's actual account before pinning any model, and re-check after the
first real generation. And do NOT use reasoning models (the o-series) for
generation: they cost roughly 10x more and would break the budget.

#### Where the money is allowed to go

Spend on **generation only**, where quality is visible in the delivered
product. Analysis, quality-check, chat answers, query rewriting, and title
generation all run on the cheap tier — nobody reads those outputs directly.

Embeddings use `text-embedding-3-small`: it is natively 1536 dimensions (which
is what `lesson_chunks.embedding` already expects) and roughly 6x cheaper than
`-large`, for a quality difference that does not show on a corpus this size.

#### Guardrails (build these before the first paid call)

1. **A hard spend ceiling in code.** Every AI call records tokens and cost in
   `ai_usage`. The LLM service reads the running total and *refuses* new calls
   above `AI_SPEND_CAP_USD` (default 8.00). It raises, it does not warn.
2. **Mock mode.** `LLM_MODE=mock` replays recorded fixtures so the entire
   pipeline can be built and tested at zero cost. Live calls only when
   validating writing quality.
3. **Cost preview** before the admin presses Generate, and a running total on
   the admin dashboard.
4. **Caching** — analysis never re-runs for unchanged source text.
5. **Tests never hit the live API.** Fixtures only.

#### Phase 6b is a sample, not a sweep

Tune against **3–5 representative sources**, not the corpus:

- one raw audio recording (the real client workflow)
- one polished DOCX
- one thin/short source — does it flag the gap rather than invent filler?
- one Hebrew-heavy lesson — is the nikud preserved exactly?

Roughly 20 generations across a few tuning rounds. Under $0.50.

### Still outstanding

| # | Question | Default in use |
|---|---|---|
| **Q2** | Series title: corpus says *"Insights into Nishmat Kol Chai"*, sample says *"Nishmat: A Journey of Praise"* | Template field. New lessons use **"Nishmat: A Journey of Praise"** (matching the landing page); imported lessons keep their own. One row to change. |
| **Q5** | Lessons are voice recordings — should learners get audio playback? | Not built. Schema leaves room. Worth asking the client; likely high value for low cost. |
| **Q6** | Open signup or invite-only? | **Open signup** as `role='user'`. |
| **Q8** | `#130` reads as a series conclusion — is a new series starting? | Multiple series supported from the start. |
| **Q9** | Corpus defects: `#130`/`#58` contain ChatGPT chatter; `#35`/`#36`/`#7`/`#48` are stubs; 3 files have no Hebrew | Ingestion cleans the obvious artifacts and **flags** the rest for admin review. The client should look at the flagged list. |
| **Q10** | Hebrew UI needed? | English UI, full RTL support for content. |

---

## 22b. Frontend decisions made during implementation

**Reads go straight to Supabase; writes and AI go through FastAPI.**
Server Components query Supabase directly with the user's own session, so RLS
is the enforcement boundary and page loads avoid a second network hop. Every
mutation and every AI operation goes through FastAPI, where `require_admin`
and the OpenAI key live. This is a deliberate split, not an inconsistency.

**Design language.** Taken from the client's reference: deep indigo night
ground, warm candle-gold accent, elegant serif display (Cormorant Garamond),
Frank Ruhl Libre for Hebrew with increased line-height so nikud does not
collide. Tokens are defined once in `app/globals.css` under `@theme`.

**3D and motion.** A depth-layered canvas star field with pointer parallax, a
CSS-3D emblem with orbital rings, pointer-tracked tilt cards with a moving
specular highlight, and scroll-triggered reveals. Canvas rather than DOM nodes
for the stars (~300 elements would be far too expensive as divs), animation
paused in background tabs, and `prefers-reduced-motion` genuinely honoured.

**Landing page content** follows the client's reference exactly, minus the
sections marked in blue: the "community of women learning" paragraph, the
badge chips row, and "with other women" on the share line. The removal of the
women-only framing means the product now reads as open to everyone —
**flagging this in case it was not the intent.**

---

## 23. Things I would push back on

Being direct, as asked:

1. **Do not fine-tune.** 131 documents is not enough, the client's voice is visibly still evolving across the corpus, and a fine-tune would lock in today's style while making iteration slow and expensive. Retrieval-based few-shot achieves more and can be improved by simply approving a new example.
2. **Do not let the AI publish.** Ever, under any "confidence" heuristic. In a Torah-learning context a fabricated source is a reputational injury to the client, not a bug ticket. Publishing stays a human click.
3. **Do not build lesson progress, bookmarks, favourites, ratings, or notifications in v1.** They were listed as *future* extensibility. Each is a day that should go into the writing quality instead — which is the only thing the client will actually judge you on.
4. **Do not skip the Phase 6b checkpoint.** The temptation is to build all the UI first because it is visible and satisfying. If the generated writing does not sound like her, none of the UI matters. Validate the voice early, with her, on her own source material.
5. **The `Data/` folder should be git-ignored and treated as client IP** — it is the client's original work product, and it should not end up in a public repository or in a portfolio.

---

**Build progress**

| Phase | Status |
|---|---|
| 0 — Scaffold, config, build pipeline | ✅ Done |
| 1 — Schema, RLS, seed template | ✅ Written (`backend/migrations/`), needs applying to a Supabase project |
| 1b — Corpus ingestion of the 131 lessons | ⏳ Next |
| 2 — Auth, roles, route guards, landing page | ✅ Done |
| 3–15 | ⏳ Per the roadmap in §21 |

See `docs/SETUP.md` to run what exists today.
