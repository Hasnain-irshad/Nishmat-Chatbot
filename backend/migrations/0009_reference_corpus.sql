-- =============================================================================
-- Nishmat AI — reference corpus for lesson generation
--
-- The generator until now had exactly one input: a transcript the admin
-- uploaded. It had no access to the prayer it teaches, to the Psalms it quotes,
-- or to any commentary — so a lesson "about a Nishmat phrase" could only be
-- written from whatever the transcript happened to say, and any Hebrew beyond
-- that was, structurally, a guess.
--
-- This migration adds a reference corpus alongside the existing lesson index.
-- Deliberately a SEPARATE pair of tables rather than more rows in
-- `lesson_chunks`:
--
--   * `lesson_chunks` is the learner-facing chatbot index. Its search function
--     is gated on `status = 'published'`, and putting a scanned page of a
--     copyrighted book in there would put that page one question away from a
--     learner. That must not be possible.
--   * references carry a KIND and an AUTHORITY that lesson chunks do not, and
--     retrieval has to filter on both — the primary Hebrew text and a
--     client-supplied essay about it are not interchangeable.
--
-- Nothing here changes an existing table's meaning. `search_published_chunks`
-- is untouched, so the deployed chatbot behaves exactly as it did.
-- =============================================================================

-- =============================================================================
-- ENUMS
-- =============================================================================

do $$ begin
  create type reference_kind as enum (
    'nishmat_text',   -- the prayer itself, by nusach. PRIMARY.
    'scripture',      -- Tehillim and other biblical text. PRIMARY.
    'commentary',     -- interpretive material: books, essays, analyses.
    'transcript',     -- teaching transcripts (NJOP, when supplied).
    'translation',    -- an authoritative translation, when legitimately obtained.
    'other'
  );
exception when duplicate_object then null; end $$;

do $$ begin
  -- How much weight the generator may give this material.
  --   primary         — quote it, rely on it, treat it as the text.
  --   secondary       — a published authority; attribute it, do not extend it.
  --   client_supplied — provided by the client. Usable, NOT authoritative:
  --                     where it conflicts with a primary text, the text wins.
  create type reference_authority as enum ('primary', 'secondary', 'client_supplied');
exception when duplicate_object then null; end $$;

-- =============================================================================
-- REFERENCE DOCUMENTS
-- =============================================================================

create table if not exists reference_documents (
  id             uuid primary key default gen_random_uuid(),
  title          text not null,
  kind           reference_kind not null,
  authority      reference_authority not null default 'client_supplied',

  -- Which text this is, when that matters. For Nishmat this is the nusach —
  -- the client davens Edot HaMizrach and an Ashkenaz text is the wrong text.
  variant        text,
  language       text not null default 'he',
  attribution    text,
  notes          text,

  -- NULL = part of the permanent corpus, available to every generation.
  -- Set    = uploaded for ONE lesson (a photographed book page) and retrieved
  --          only while generating that lesson. This is what keeps a scan of a
  --          copyrighted book out of the global knowledge base.
  lesson_id      uuid references lessons(id) on delete cascade,
  source_file_id uuid references source_files(id) on delete set null,

  is_active      boolean not null default true,
  metadata       jsonb not null default '{}'::jsonb,
  created_by     uuid references profiles(id) on delete set null,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create index if not exists reference_documents_kind_idx
  on reference_documents(kind) where is_active;
create index if not exists reference_documents_lesson_idx
  on reference_documents(lesson_id) where lesson_id is not null;

-- One global document per (kind, variant): re-running the loader replaces
-- rather than duplicates, which is what makes the indexer safely idempotent.
create unique index if not exists reference_documents_global_variant_idx
  on reference_documents(kind, coalesce(variant, ''))
  where lesson_id is null;

drop trigger if exists reference_documents_updated_at on reference_documents;
create trigger reference_documents_updated_at before update on reference_documents
  for each row execute function set_updated_at();

-- =============================================================================
-- REFERENCE CHUNKS
-- =============================================================================

create table if not exists reference_chunks (
  id           uuid primary key default gen_random_uuid(),
  document_id  uuid not null references reference_documents(id) on delete cascade,
  chunk_index  integer not null,

  -- A citable address: "Tehillim 103:1-5", "Nishmat 4", "ArtScroll p.412".
  -- Carried into the prompt with the text, so the model cites what it was
  -- actually shown instead of reconstructing a reference from memory.
  ref          text,
  heading      text,
  chunk_text   text not null,
  embedding    vector(1536),

  -- Denormalised from the parent so retrieval can filter on them without a
  -- join. Every retrieval filters on all three; the join cost is real.
  kind         reference_kind not null,
  authority    reference_authority not null,
  lesson_id    uuid references lessons(id) on delete cascade,

  metadata     jsonb not null default '{}'::jsonb,
  created_at   timestamptz not null default now(),

  -- 'simple', never 'english': Hebrew and transliteration must survive.
  tsv          tsvector generated always as (to_tsvector('simple', chunk_text)) stored,

  -- Hebrew with nikud and cantillation removed.
  --
  -- Exists so a quotation can be verified against the corpus. The same verse
  -- appears with different pointing in different editions, and a byte-exact
  -- comparison would report every one of them as a fabrication. Stripping the
  -- marks compares the consonantal text, which is the thing that is actually
  -- fixed.
  chunk_text_plain text generated always as (
    regexp_replace(chunk_text, '[֑-ׇ׳״]', '', 'g')
  ) stored,

  unique (document_id, chunk_index)
);

create index if not exists reference_chunks_embedding_idx
  on reference_chunks using hnsw (embedding vector_cosine_ops);
create index if not exists reference_chunks_tsv_idx
  on reference_chunks using gin (tsv);
create index if not exists reference_chunks_kind_idx
  on reference_chunks(kind);
create index if not exists reference_chunks_lesson_idx
  on reference_chunks(lesson_id) where lesson_id is not null;
create index if not exists reference_chunks_ref_idx
  on reference_chunks(ref);

-- Trigram index: quote verification is a substring search over Hebrew, which
-- no btree can serve.
create index if not exists reference_chunks_plain_trgm_idx
  on reference_chunks using gin (chunk_text_plain gin_trgm_ops);

-- =============================================================================
-- RETRIEVAL
--
-- Same hybrid shape as the lesson search (vector + full text, fused by RRF),
-- with two additions that matter here:
--
--   * `filter_kinds` — the caller asks for scripture, or for commentary, and
--     gets only that. Mixing a Psalm and an essay about the Psalm into one
--     ranked list means the essay outranks the verse it discusses, because it
--     shares more vocabulary with the query than the verse does.
--   * `filter_lesson_id` — global corpus PLUS this lesson's uploaded pages,
--     and no other lesson's. A page photographed for lesson 42 has no business
--     appearing in lesson 87.
-- =============================================================================

create or replace function match_reference_chunks(
  query_embedding  vector(1536),
  query_text       text,
  match_count      integer default 6,
  filter_kinds     text[] default null,
  filter_lesson_id uuid default null,
  include_global   boolean default true
)
returns table (
  chunk_id         uuid,
  document_id      uuid,
  title            text,
  variant          text,
  attribution      text,
  kind             text,
  authority        text,
  ref              text,
  heading          text,
  chunk_text       text,
  metadata         jsonb,
  is_lesson_scoped boolean,
  score            double precision,
  similarity       double precision
)
language sql stable security definer set search_path = public as $$
  with candidates as (
    select c.id, c.document_id, c.ref, c.heading, c.chunk_text, c.metadata,
           c.embedding, c.tsv, c.kind, c.authority, c.lesson_id,
           d.title, d.variant, d.attribution
    from reference_chunks c
    join reference_documents d on d.id = c.document_id
    where d.is_active
      and c.embedding is not null
      and (filter_kinds is null or c.kind::text = any(filter_kinds))
      and (
        (include_global and c.lesson_id is null)
        or (filter_lesson_id is not null and c.lesson_id = filter_lesson_id)
      )
  ),
  vector_hits as (
    select id,
           row_number() over (order by embedding <=> query_embedding) as rnk,
           1 - (embedding <=> query_embedding) as similarity
    from candidates
    order by embedding <=> query_embedding
    limit greatest(match_count * 4, 20)
  ),
  text_hits as (
    select id,
           row_number() over (
             order by ts_rank_cd(tsv, websearch_to_tsquery('simple', query_text)) desc
           ) as rnk
    from candidates
    where query_text is not null
      and query_text <> ''
      and tsv @@ websearch_to_tsquery('simple', query_text)
    limit greatest(match_count * 4, 20)
  ),
  fused as (
    select coalesce(v.id, t.id) as id,
           coalesce(1.0 / (60 + v.rnk), 0.0) + coalesce(1.0 / (60 + t.rnk), 0.0) as score,
           v.similarity
    from vector_hits v
    full outer join text_hits t on t.id = v.id
  )
  select c.id, c.document_id, c.title, c.variant, c.attribution,
         c.kind::text, c.authority::text, c.ref, c.heading, c.chunk_text,
         c.metadata,
         c.lesson_id is not null,
         f.score,
         coalesce(f.similarity, 1 - (c.embedding <=> query_embedding))
  from fused f
  join candidates c on c.id = f.id
  order by f.score desc
  limit match_count;
$$;

revoke all on function match_reference_chunks from public, anon;

-- -----------------------------------------------------------------------------
-- Exact lookup by address.
--
-- "The lesson quotes Tehillim 103:1" is not a similarity question — the answer
-- is one specific psalm and any other psalm is wrong. Embeddings are the wrong
-- tool for it, so this path does not use them.
-- -----------------------------------------------------------------------------

create or replace function lookup_reference_chunks(
  p_kind    text,
  p_variant text default null,
  p_refs    text[] default null,
  p_limit   integer default 12
)
returns table (
  chunk_id    uuid,
  title       text,
  variant     text,
  attribution text,
  kind        text,
  authority   text,
  ref         text,
  heading     text,
  chunk_text  text,
  metadata    jsonb
)
language sql stable security definer set search_path = public as $$
  select c.id, d.title, d.variant, d.attribution, c.kind::text, c.authority::text,
         c.ref, c.heading, c.chunk_text, c.metadata
  from reference_chunks c
  join reference_documents d on d.id = c.document_id
  where d.is_active
    and c.lesson_id is null
    and c.kind::text = p_kind
    and (p_variant is null or d.variant = p_variant)
    and (p_refs is null or c.ref = any(p_refs))
  order by c.chunk_index
  limit p_limit;
$$;

revoke all on function lookup_reference_chunks from public, anon;

-- -----------------------------------------------------------------------------
-- Quote verification.
--
-- Given a Hebrew string from a generated lesson, does it actually appear in the
-- primary corpus? Returns the addresses it was found at, or nothing.
--
-- Matching is on the consonantal text (see `chunk_text_plain`) because vowel
-- and cantillation marks legitimately differ between editions, and because the
-- alternative — byte equality — flags correct quotations as invented, which
-- would train the admin to ignore the warning.
-- -----------------------------------------------------------------------------

create or replace function verify_hebrew_quote(
  p_quote text,
  p_kinds text[] default array['nishmat_text', 'scripture']
)
returns table (ref text, title text, variant text, kind text)
language sql stable security definer set search_path = public as $$
  with needle as (
    select regexp_replace(
             regexp_replace(p_quote, '[֑-ׇ׳״]', '', 'g'),
             '\s+', ' ', 'g'
           ) as text
  )
  select c.ref, d.title, d.variant, c.kind::text
  from reference_chunks c
  join reference_documents d on d.id = c.document_id
  cross join needle n
  where d.is_active
    and c.lesson_id is null
    and c.kind::text = any(p_kinds)
    and length(n.text) > 3
    and regexp_replace(c.chunk_text_plain, '\s+', ' ', 'g') like '%' || n.text || '%'
  limit 5;
$$;

revoke all on function verify_hebrew_quote from public, anon;

-- =============================================================================
-- SOURCE FILES — separate a lesson's own material from reference pages
--
-- Both arrive through the same upload endpoint and the same extraction worker.
-- What differs is what they MEAN: the transcript is what the lesson is about;
-- a photographed page of ArtScroll is something to consult while writing it.
-- Feeding both to the generator as undifferentiated "source" is exactly how a
-- commentator's words end up presented as the teacher's own.
-- =============================================================================

do $$ begin
  alter table source_files
    add column role text not null default 'lesson_source'
    check (role in ('lesson_source', 'reference'));
exception when duplicate_column then null; end $$;

do $$ begin
  alter table source_files add column reference_book text;
exception when duplicate_column then null; end $$;

do $$ begin
  alter table source_files add column reference_page text;
exception when duplicate_column then null; end $$;

do $$ begin
  -- Set when an admin asks for a reference page to join the permanent corpus.
  -- Default false: an uploaded book page is temporary context for ONE lesson
  -- unless someone deliberately decides otherwise.
  alter table source_files add column reference_persist boolean not null default false;
exception when duplicate_column then null; end $$;

create index if not exists source_files_role_idx on source_files(lesson_id, role);

-- =============================================================================
-- LESSONS — the generation brief
--
-- What the admin asked for: a phrase, a theme, a Psalm, a commentator, a
-- season, an objective. Stored on the lesson rather than only on the job, so a
-- regeneration six weeks later starts from the same brief instead of from
-- whatever the admin can remember.
-- =============================================================================

do $$ begin
  alter table lessons add column generation_brief jsonb;
exception when duplicate_column then null; end $$;

-- =============================================================================
-- RLS — admin only, both tables, no exceptions
--
-- Reference material includes photographed pages of books the client owns
-- physically. Learners must not reach it: not through the API, not through
-- PostgREST, and not through the chatbot (which queries `lesson_chunks`, a
-- different table entirely).
-- =============================================================================

alter table reference_documents enable row level security;
alter table reference_chunks    enable row level security;

drop policy if exists reference_documents_admin on reference_documents;
create policy reference_documents_admin on reference_documents
  for all using (is_admin()) with check (is_admin());

drop policy if exists reference_chunks_admin on reference_chunks;
create policy reference_chunks_admin on reference_chunks
  for all using (is_admin()) with check (is_admin());
