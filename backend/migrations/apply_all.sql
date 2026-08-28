-- =============================================================================
-- Nishmat AI - combined migrations (0001 - 0010)
-- Fresh project: paste this whole file into the Supabase SQL Editor.
-- Existing project: run only the files you have not applied yet.
-- =============================================================================


-- >>>>>>>>>>>>>>>>>>>>>>>>>> 0001_init.sql <<<<<<<<<<<<<<<<<<<<<<<<<<

-- =============================================================================
-- Nishmat AI — initial schema
-- Target: Supabase Postgres 15+
-- Apply with: supabase db push   (or paste into the Supabase SQL editor)
--
-- Design notes:
--   * lesson_versions is IMMUTABLE. Content is never updated in place.
--   * lessons.published_version_id is the ONLY thing learners can see.
--   * lesson_chunks (the RAG index) is written on publish and deleted on
--     unpublish, so learner visibility and chatbot visibility cannot drift.
--   * RLS is defence-in-depth. The API is the primary authorisation layer.
-- =============================================================================

create extension if not exists "pgcrypto";
create extension if not exists "vector";
create extension if not exists "pg_trgm";

-- =============================================================================
-- ENUMS
-- =============================================================================

create type user_role as enum ('admin', 'user');

create type lesson_status as enum (
  'draft',       -- created, no content yet
  'processing',  -- a job is running (extraction / generation)
  'generated',   -- AI produced a draft
  'review',      -- admin is working on it
  'approved',    -- admin approved, not yet published
  'published',   -- live for learners
  'archived',    -- withdrawn
  'failed'       -- a pipeline stage failed
);

create type version_origin as enum (
  'ai_generated',
  'ai_modified',
  'manual_edit',
  'imported'      -- migrated from the client's existing corpus
);

create type source_kind as enum ('pdf', 'docx', 'audio', 'image', 'text');

create type processing_status as enum ('pending', 'processing', 'completed', 'failed');

create type job_status as enum ('queued', 'running', 'succeeded', 'failed', 'cancelled');

create type message_role as enum ('user', 'assistant', 'system');

-- =============================================================================
-- HELPERS
-- =============================================================================

create or replace function set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- =============================================================================
-- PROFILES  (mirrors auth.users; role authority lives here)
-- =============================================================================

create table profiles (
  id          uuid primary key references auth.users(id) on delete cascade,
  email       text not null,
  full_name   text,
  avatar_url  text,
  role        user_role not null default 'user',
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create index profiles_role_idx on profiles(role);
create trigger profiles_updated_at before update on profiles
  for each row execute function set_updated_at();

-- Auto-create a profile on signup. Role ALWAYS defaults to 'user' — it is never
-- taken from user-supplied metadata, otherwise anyone could self-promote by
-- passing {"role":"admin"} at signup.
create or replace function handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, email, full_name, avatar_url)
  values (
    new.id,
    coalesce(new.email, ''),
    coalesce(new.raw_user_meta_data ->> 'full_name', new.raw_user_meta_data ->> 'name'),
    new.raw_user_meta_data ->> 'avatar_url'
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function handle_new_user();

-- Authoritative role check, used by every RLS policy below.
create or replace function is_admin()
returns boolean language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.profiles
    where id = auth.uid() and role = 'admin'
  );
$$;

-- =============================================================================
-- SERIES
-- =============================================================================

create table series (
  id          uuid primary key default gen_random_uuid(),
  title       text not null,
  slug        text not null unique,
  description text,
  is_active   boolean not null default true,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create trigger series_updated_at before update on series
  for each row execute function set_updated_at();

-- =============================================================================
-- LESSON TEMPLATES  (the lesson format lives here as data, never in code)
-- =============================================================================

create table lesson_templates (
  id               uuid primary key default gen_random_uuid(),
  name             text not null,
  description      text,
  series_title     text,
  sections         jsonb not null default '[]'::jsonb,
  optional_addons  jsonb not null default '[]'::jsonb,
  style_guide      text not null default '',
  formatting_rules jsonb not null default '{}'::jsonb,
  constraints      jsonb not null default '{}'::jsonb,
  signoff          text,
  is_default       boolean not null default false,
  version          integer not null default 1,
  created_by       uuid references profiles(id) on delete set null,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

create unique index lesson_templates_single_default_idx
  on lesson_templates(is_default) where is_default;

create trigger lesson_templates_updated_at before update on lesson_templates
  for each row execute function set_updated_at();

-- Snapshot of a template each time it is edited, so an old lesson version can
-- always be explained by the template that actually produced it.
create table lesson_template_versions (
  id          uuid primary key default gen_random_uuid(),
  template_id uuid not null references lesson_templates(id) on delete cascade,
  version     integer not null,
  snapshot    jsonb not null,
  created_by  uuid references profiles(id) on delete set null,
  created_at  timestamptz not null default now(),
  unique (template_id, version)
);

-- =============================================================================
-- LESSONS
-- =============================================================================

create table lessons (
  id                   uuid primary key default gen_random_uuid(),
  series_id            uuid references series(id) on delete set null,
  template_id          uuid references lesson_templates(id) on delete set null,
  title                text not null default 'Untitled lesson',
  lesson_number        integer,
  sequence_position    integer,
  hebrew_phrase        text,
  transliteration      text,
  translation          text,
  summary              text,
  status               lesson_status not null default 'draft',
  current_version_id   uuid,
  published_version_id uuid,
  published_at         timestamptz,
  needs_review         boolean not null default false,
  review_notes         text,
  created_by           uuid references profiles(id) on delete set null,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  deleted_at           timestamptz
);

create unique index lessons_series_number_idx
  on lessons(series_id, lesson_number)
  where lesson_number is not null and deleted_at is null;

create index lessons_status_idx    on lessons(status) where deleted_at is null;
create index lessons_published_idx on lessons(published_at desc)
  where status = 'published' and deleted_at is null;
create index lessons_sequence_idx  on lessons(series_id, sequence_position);
create index lessons_title_trgm_idx on lessons using gin (title gin_trgm_ops);

create trigger lessons_updated_at before update on lessons
  for each row execute function set_updated_at();

-- =============================================================================
-- LESSON VERSIONS  (immutable content)
-- =============================================================================

create table lesson_versions (
  id                       uuid primary key default gen_random_uuid(),
  lesson_id                uuid not null references lessons(id) on delete cascade,
  version_number           integer not null,
  parent_version_id        uuid references lesson_versions(id) on delete set null,

  -- Structured content: {"sections":[{"key","title","body","dir","order"}]}
  content                  jsonb not null default '{"sections":[]}'::jsonb,
  content_text             text not null default '',
  word_count               integer not null default 0,

  structured_analysis      jsonb,
  quality_report           jsonb,
  model_metadata           jsonb not null default '{}'::jsonb,

  origin                   version_origin not null,
  modification_instruction text,
  template_snapshot        jsonb,

  created_by               uuid references profiles(id) on delete set null,
  created_at               timestamptz not null default now(),

  unique (lesson_id, version_number)
);

create index lesson_versions_lesson_idx on lesson_versions(lesson_id, version_number desc);

-- Enforce immutability: only the derived/annotation columns may ever change.
create or replace function guard_lesson_version_immutability()
returns trigger language plpgsql as $$
begin
  if new.content is distinct from old.content
     or new.content_text is distinct from old.content_text
     or new.lesson_id is distinct from old.lesson_id
     or new.version_number is distinct from old.version_number
     or new.origin is distinct from old.origin then
    raise exception 'lesson_versions rows are immutable; create a new version instead';
  end if;
  return new;
end;
$$;

create trigger lesson_versions_immutable before update on lesson_versions
  for each row execute function guard_lesson_version_immutability();

-- Deferred FKs (circular reference between lessons and lesson_versions).
alter table lessons
  add constraint lessons_current_version_fk
  foreign key (current_version_id) references lesson_versions(id)
  on delete set null deferrable initially deferred;

alter table lessons
  add constraint lessons_published_version_fk
  foreign key (published_version_id) references lesson_versions(id)
  on delete set null deferrable initially deferred;

-- Allocate the next version number atomically.
create or replace function next_version_number(p_lesson_id uuid)
returns integer language plpgsql as $$
declare n integer;
begin
  select coalesce(max(version_number), 0) + 1 into n
  from lesson_versions where lesson_id = p_lesson_id
  for update;
  return n;
end;
$$;

-- =============================================================================
-- SOURCE FILES
-- =============================================================================

create table source_files (
  id                  uuid primary key default gen_random_uuid(),
  lesson_id           uuid references lessons(id) on delete set null,
  original_filename   text not null,
  mime_type           text not null,
  size_bytes          bigint not null,
  checksum_sha256     text,
  kind                source_kind not null,
  storage_path        text not null,
  extracted_text      text,
  extraction_metadata jsonb not null default '{}'::jsonb,
  processing_status   processing_status not null default 'pending',
  error_message       text,
  uploaded_by         uuid references profiles(id) on delete set null,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

create index source_files_lesson_idx   on source_files(lesson_id);
create index source_files_checksum_idx on source_files(checksum_sha256);
create index source_files_status_idx   on source_files(processing_status);

create trigger source_files_updated_at before update on source_files
  for each row execute function set_updated_at();

-- =============================================================================
-- LESSON CHUNKS  (RAG index — published content ONLY)
-- =============================================================================

create table lesson_chunks (
  id           uuid primary key default gen_random_uuid(),
  lesson_id    uuid not null references lessons(id) on delete cascade,
  version_id   uuid not null references lesson_versions(id) on delete cascade,
  chunk_index  integer not null,
  section_key  text,
  chunk_text   text not null,
  embedding    vector(1536),
  metadata     jsonb not null default '{}'::jsonb,
  created_at   timestamptz not null default now(),
  -- 'simple' (not 'english') so Hebrew and transliterated terms survive.
  tsv          tsvector generated always as (to_tsvector('simple', chunk_text)) stored,
  unique (version_id, chunk_index)
);

create index lesson_chunks_embedding_idx on lesson_chunks
  using hnsw (embedding vector_cosine_ops);
create index lesson_chunks_tsv_idx    on lesson_chunks using gin (tsv);
create index lesson_chunks_lesson_idx on lesson_chunks(lesson_id);

-- =============================================================================
-- STYLE EXAMPLES  (the voice library)
-- =============================================================================

create table style_examples (
  id          uuid primary key default gen_random_uuid(),
  title       text not null,
  source_text text,
  final_text  text not null,
  embedding   vector(1536),
  tags        text[] not null default '{}',
  is_approved boolean not null default false,
  notes       text,
  lesson_id   uuid references lessons(id) on delete set null,
  created_by  uuid references profiles(id) on delete set null,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create index style_examples_embedding_idx on style_examples
  using hnsw (embedding vector_cosine_ops);
create index style_examples_approved_idx on style_examples(is_approved) where is_approved;

create trigger style_examples_updated_at before update on style_examples
  for each row execute function set_updated_at();

-- =============================================================================
-- CONVERSATIONS / MESSAGES
-- =============================================================================

create table conversations (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references profiles(id) on delete cascade,
  lesson_id       uuid references lessons(id) on delete set null,
  title           text not null default 'New conversation',
  summary         text,
  message_count   integer not null default 0,
  last_message_at timestamptz,
  archived_at     timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index conversations_user_idx on conversations(user_id, last_message_at desc nulls last);

create trigger conversations_updated_at before update on conversations
  for each row execute function set_updated_at();

create table messages (
  id              uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references conversations(id) on delete cascade,
  role            message_role not null,
  content         text not null,
  citations       jsonb not null default '[]'::jsonb,
  token_usage     jsonb not null default '{}'::jsonb,
  created_at      timestamptz not null default now()
);

create index messages_conversation_idx on messages(conversation_id, created_at);

-- =============================================================================
-- JOBS  (Postgres-backed queue — no Redis, no Celery)
-- =============================================================================

create table jobs (
  id             uuid primary key default gen_random_uuid(),
  type           text not null,
  payload        jsonb not null default '{}'::jsonb,
  status         job_status not null default 'queued',
  progress_stage text,
  progress_pct   integer not null default 0,
  attempts       integer not null default 0,
  max_attempts   integer not null default 3,
  locked_at      timestamptz,
  locked_by      text,
  result         jsonb,
  error          text,
  lesson_id      uuid references lessons(id) on delete cascade,
  created_by     uuid references profiles(id) on delete set null,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create index jobs_queue_idx on jobs(created_at) where status = 'queued';
create index jobs_lesson_idx on jobs(lesson_id, created_at desc);
create index jobs_stale_idx on jobs(locked_at) where status = 'running';

create trigger jobs_updated_at before update on jobs
  for each row execute function set_updated_at();

-- =============================================================================
-- AUDIT LOG  (privileged actions only)
-- =============================================================================

create table audit_log (
  id          uuid primary key default gen_random_uuid(),
  actor_id    uuid references profiles(id) on delete set null,
  action      text not null,
  entity_type text,
  entity_id   uuid,
  detail      jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now()
);

create index audit_log_actor_idx  on audit_log(actor_id, created_at desc);
create index audit_log_entity_idx on audit_log(entity_type, entity_id);

-- =============================================================================
-- USAGE TRACKING  (the client's OpenAI budget is small — make spend visible)
-- =============================================================================

create table ai_usage (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid references profiles(id) on delete set null,
  operation       text not null,     -- analysis | generation | chat | embedding | transcription ...
  model           text not null,
  input_tokens    integer not null default 0,
  output_tokens   integer not null default 0,
  audio_seconds   numeric  not null default 0,
  estimated_cost  numeric(10,6) not null default 0,
  lesson_id       uuid references lessons(id) on delete set null,
  conversation_id uuid references conversations(id) on delete set null,
  created_at      timestamptz not null default now()
);

create index ai_usage_created_idx   on ai_usage(created_at desc);
create index ai_usage_operation_idx on ai_usage(operation, created_at desc);

-- =============================================================================
-- HYBRID RETRIEVAL  (vector + full-text, fused by RRF)
--
-- SECURITY DEFINER + the published-only filter lives INSIDE this function, so
-- no caller — however buggy — can retrieve a draft or archived lesson.
-- =============================================================================

create or replace function search_published_chunks(
  query_embedding vector(1536),
  query_text      text,
  match_count     integer default 6,
  filter_lesson_id uuid default null
)
returns table (
  chunk_id      uuid,
  lesson_id     uuid,
  lesson_title  text,
  lesson_number integer,
  section_key   text,
  chunk_text    text,
  metadata      jsonb,
  score         double precision
)
language sql stable security definer set search_path = public as $$
  with published as (
    select l.id, l.title, l.lesson_number, l.published_version_id
    from lessons l
    where l.status = 'published'
      and l.published_version_id is not null
      and l.deleted_at is null
      and (filter_lesson_id is null or l.id = filter_lesson_id)
  ),
  candidates as (
    select c.id, c.lesson_id, c.section_key, c.chunk_text, c.metadata, c.embedding, c.tsv
    from lesson_chunks c
    join published p on p.id = c.lesson_id and p.published_version_id = c.version_id
  ),
  vector_hits as (
    select id, row_number() over (order by embedding <=> query_embedding) as rnk
    from candidates
    where embedding is not null
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
           coalesce(1.0 / (60 + v.rnk), 0.0) + coalesce(1.0 / (60 + t.rnk), 0.0) as score
    from vector_hits v
    full outer join text_hits t on t.id = v.id
  )
  select c.id, c.lesson_id, p.title, p.lesson_number,
         c.section_key, c.chunk_text, c.metadata, f.score
  from fused f
  join candidates c on c.id = f.id
  join published  p on p.id = c.lesson_id
  order by f.score desc
  limit match_count;
$$;

-- Style-example retrieval for few-shot prompting (admin/service use only).
create or replace function match_style_examples(
  query_embedding vector(1536),
  match_count     integer default 8
)
returns table (id uuid, title text, source_text text, final_text text,
               tags text[], similarity double precision)
language sql stable security definer set search_path = public as $$
  select s.id, s.title, s.source_text, s.final_text, s.tags,
         1 - (s.embedding <=> query_embedding) as similarity
  from style_examples s
  where s.is_approved and s.embedding is not null
  order by s.embedding <=> query_embedding
  limit match_count;
$$;

-- =============================================================================
-- ROW LEVEL SECURITY
-- =============================================================================

alter table profiles                enable row level security;
alter table series                  enable row level security;
alter table lesson_templates        enable row level security;
alter table lesson_template_versions enable row level security;
alter table lessons                 enable row level security;
alter table lesson_versions         enable row level security;
alter table source_files            enable row level security;
alter table lesson_chunks           enable row level security;
alter table style_examples          enable row level security;
alter table conversations           enable row level security;
alter table messages                enable row level security;
alter table jobs                    enable row level security;
alter table audit_log               enable row level security;
alter table ai_usage                enable row level security;

-- ---- profiles ----------------------------------------------------------
create policy profiles_select_own on profiles
  for select using (id = auth.uid() or is_admin());

-- Users may edit their own profile but NOT their role. The WITH CHECK compares
-- against the existing row, so an attempted self-promotion fails.
create policy profiles_update_own on profiles
  for update using (id = auth.uid())
  with check (id = auth.uid() and role = (select p.role from profiles p where p.id = auth.uid()));

create policy profiles_admin_all on profiles
  for all using (is_admin()) with check (is_admin());

-- ---- series ------------------------------------------------------------
create policy series_read on series for select using (true);
create policy series_admin on series for all using (is_admin()) with check (is_admin());

-- ---- templates (admin only) --------------------------------------------
create policy templates_admin on lesson_templates
  for all using (is_admin()) with check (is_admin());
create policy template_versions_admin on lesson_template_versions
  for all using (is_admin()) with check (is_admin());

-- ---- lessons -----------------------------------------------------------
create policy lessons_read_published on lessons
  for select using (
    deleted_at is null
    and status = 'published'
    and published_version_id is not null
  );

create policy lessons_admin on lessons
  for all using (is_admin()) with check (is_admin());

-- ---- lesson_versions: learners see ONLY the published version ----------
create policy lesson_versions_read_published on lesson_versions
  for select using (
    exists (
      select 1 from lessons l
      where l.published_version_id = lesson_versions.id
        and l.status = 'published'
        and l.deleted_at is null
    )
  );

create policy lesson_versions_admin on lesson_versions
  for all using (is_admin()) with check (is_admin());

-- ---- source files: admin only, no learner access whatsoever ------------
create policy source_files_admin on source_files
  for all using (is_admin()) with check (is_admin());

-- ---- chunks: no direct access; reached only via search_published_chunks -
create policy lesson_chunks_admin on lesson_chunks
  for all using (is_admin()) with check (is_admin());

-- ---- style examples: admin only ----------------------------------------
create policy style_examples_admin on style_examples
  for all using (is_admin()) with check (is_admin());

-- ---- conversations / messages: strictly own. Admins get NO special read
--      on other people's chats — that is private.
create policy conversations_own on conversations
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy messages_own on messages
  for all using (
    exists (select 1 from conversations c
            where c.id = messages.conversation_id and c.user_id = auth.uid())
  )
  with check (
    exists (select 1 from conversations c
            where c.id = messages.conversation_id and c.user_id = auth.uid())
  );

-- ---- jobs: own jobs readable, admin full ------------------------------
create policy jobs_read_own on jobs for select using (created_by = auth.uid() or is_admin());
create policy jobs_admin    on jobs for all using (is_admin()) with check (is_admin());

-- ---- audit / usage: admin only ----------------------------------------
create policy audit_admin on audit_log for select using (is_admin());
create policy usage_admin on ai_usage  for select using (is_admin());

-- =============================================================================
-- STORAGE  (private bucket for uploaded source material)
-- =============================================================================

insert into storage.buckets (id, name, public, file_size_limit)
values ('source-files', 'source-files', false, 104857600)
on conflict (id) do nothing;

create policy "source files: admin read"
  on storage.objects for select
  using (bucket_id = 'source-files' and is_admin());

create policy "source files: admin write"
  on storage.objects for insert
  with check (bucket_id = 'source-files' and is_admin());

create policy "source files: admin delete"
  on storage.objects for delete
  using (bucket_id = 'source-files' and is_admin());

-- >>>>>>>>>>>>>>>>>>>>>>>>>> 0002_seed_template.sql <<<<<<<<<<<<<<<<<<<<<<<<<<

-- =============================================================================
-- Seed: the default series and the "Nishmat — A Journey of Praise" template.
--
-- Everything about the lesson FORMAT and the WRITING STYLE lives in this row.
-- No section key, label, or style rule appears anywhere in the application code.
-- The client can change any of it from the admin template editor.
-- =============================================================================

insert into series (id, title, slug, description)
values (
  '00000000-0000-0000-0000-000000000001',
  'Nishmat: A Journey of Praise',
  'nishmat-journey-of-praise',
  'A weekly journey through the words of Nishmat Kol Chai — one word, one phrase at a time.'
)
on conflict (slug) do nothing;

insert into lesson_templates (
  id, name, description, series_title, sections, optional_addons,
  style_guide, formatting_rules, constraints, signoff, is_default, version
) values (
  '00000000-0000-0000-0000-000000000010',
  'Nishmat — A Journey of Praise',
  'The polished lesson format: Hebrew phrase, transliteration and translation, a warm '
  'greeting, a personal hook, a relatable story, the spiritual connection, a reflection, '
  'a practical invitation, and a closing blessing.',
  'Nishmat: A Journey of Praise',

  -- ---------------------------------------------------------------- sections
  $json$[
    {"key":"series_title","label":"Series title","required":true,"dir":"ltr","order":1,
     "guidance":"The series name exactly as configured. Nothing else on this line."},

    {"key":"lesson_number","label":"Lesson number","required":true,"dir":"ltr","order":2,
     "guidance":"Formatted as 'Lesson #N'. Use the number given; never invent one."},

    {"key":"hebrew_phrase","label":"Hebrew phrase","required":false,"dir":"rtl","order":3,
     "guidance":"The phrase from Nishmat that this lesson explores, copied VERBATIM from the source material with all nikud intact. If the source contains no Hebrew, omit this section entirely rather than supplying Hebrew from memory."},

    {"key":"transliteration","label":"Transliteration","required":false,"dir":"ltr","order":4,
     "guidance":"Sephardic/Modern Hebrew transliteration of the phrase above, in the client's established spelling conventions (e.g. 'U'mibaladecha ein lanu Melech, Go'el u'Moshia.'). Only if a Hebrew phrase is present."},

    {"key":"translation","label":"English translation","required":false,"dir":"ltr","order":5,
     "guidance":"The English meaning, in double quotes. Only if a Hebrew phrase is present."},

    {"key":"greeting","label":"Warm greeting","required":true,"dir":"ltr","order":6,
     "max_words":40,
     "guidance":"A warm personal opening in the teacher's voice, e.g. 'Shavua tov, neshamot yekarot.' followed by a brief friendly line and the lesson's place in the series. VARY this between lessons — do not open every lesson with identical wording."},

    {"key":"introduction","label":"Introduction","required":true,"dir":"ltr","order":7,
     "guidance":"Set the scene. Where we are in the journey through Nishmat, and what this week's word is. May reference the season, the parashah, or the Jewish calendar ONLY if the source material does."},

    {"key":"central_concept","label":"The central word or concept","required":true,"dir":"ltr","order":8,
     "guidance":"Name the word plainly, then unfold what it means. Often just the word on its own line, then its translation on the next."},

    {"key":"personal_hook","label":"Personal or emotional hook","required":true,"dir":"ltr","order":9,
     "guidance":"The teacher's own wondering — what she noticed, what surprised her, what she has been thinking about. First person, honest, unpolished in feeling."},

    {"key":"story_example","label":"Story or relatable example","required":true,"dir":"ltr","order":10,
     "guidance":"The concrete story, image or everyday scene from the SOURCE MATERIAL. Told simply and vividly. Never invent a story that is not in the source."},

    {"key":"spiritual_connection","label":"Connecting the example to the idea","required":true,"dir":"ltr","order":11,
     "guidance":"Turn the story toward the spiritual point. This is the pivot of the lesson — let it land gently rather than announcing it."},

    {"key":"supporting_source","label":"Supporting Torah source","required":false,"dir":"ltr","order":12,
     "guidance":"A pasuk, Gemara, midrash or teaching ONLY if it appears in the source material. Quote the Hebrew where the source gives Hebrew, then the translation. NEVER supply a source from memory, never adjust a citation, never attribute a teaching to a name the source did not name."},

    {"key":"reflection","label":"Deeper reflection","required":true,"dir":"ltr","order":13,
     "guidance":"Sit with the idea. Rhetorical questions are welcome here. 'Maybe that's what it means to...' constructions fit this voice."},

    {"key":"practical_takeaway","label":"Practical invitation","required":true,"dir":"ltr","order":14,
     "guidance":"One small, doable thing for the coming week. Framed as an invitation, never as an instruction. Often opens 'So this week, I'd like to invite you to try something.'"},

    {"key":"closing_blessing","label":"Closing blessing","required":true,"dir":"ltr","order":15,
     "guidance":"A short series of 'May Hashem...' blessings, rising toward the lesson's theme and closing on it."},

    {"key":"signoff","label":"Sign-off","required":true,"dir":"ltr","order":16,
     "max_words":20,
     "guidance":"A brief warm close, e.g. 'Shavua tov. Make it a wonderful week.' Add the configured signature if one is set."}
  ]$json$::jsonb,

  -- ---------------------------------------------------------- optional addons
  $json$[
    {"key":"whatsapp_summary","label":"WhatsApp summary","enabled_by_default":false,
     "dir":"ltr","target_words":130,
     "guidance":"A condensed, shareable recap for WhatsApp: the lesson header, the Hebrew phrase and transliteration, three or four of the strongest lines from the lesson, the practical step, and a one-line blessing."}
  ]$json$::jsonb,

  -- ------------------------------------------------------------- style guide
  $style$You are writing in the voice of a warm, thoughtful woman teaching a weekly Torah
lesson to a community she knows personally. She is not a lecturer. She is a friend
thinking out loud, sharing something that moved her this week.

VOICE
- Warm, personal, conversational, reflective. Speak TO the reader, not at them.
- First person. "I was thinking about this word..." "I found myself wondering..."
- Second person for the reader. "You've been davening." "Maybe you've caught yourself thinking..."
- Emotionally honest. Name real feelings: tired, waiting, disappointed, hopeful.
- Spiritually engaging but never preachy. Invite; do not instruct.
- Accessible. A woman reading this on her phone between school pickups should
  understand every sentence the first time.

RHYTHM  (this is the signature of the style — get it right)
- Short paragraphs. Often a single sentence stands alone on its own line.
- Use line breaks to create breath and emphasis, especially at emotional moments.
- Build with parallel short lines, then let one land:
      "For a child."
      "For a shidduch."
      "For healing."
- Ellipses create a pause before a turn: "And after a while... you don't even know what else to say."
- Vary the rhythm. Long reflective sentences make the short ones hit harder.
  A page of nothing but three-word lines becomes a gimmick.

TECHNIQUES
- Natural rhetorical questions that the reader is genuinely asking too.
- One concrete, sensory, everyday image, drawn from the source material.
- Smooth transitions. "But recently I heard an idea that really stayed with me."
- "Maybe that's what..." and "Perhaps that's one of the beautiful messages of..."
  for turning an observation into a spiritual insight.
- Close by rising, not by summarising. Blessing, not conclusion.

HEBREW
- Hebrew phrases appear in Hebrew script with nikud, exactly as in the source.
- Transliterate on first use, then use the transliterated form naturally in prose.
- Familiar Hebrew and Yiddish words stay untranslated when the community knows
  them: Hashem, shavua tov, neshamot, tefillah, davening, shidduch, parnassah,
  yeshuah, emunah, hakarat hatov, zechut, geulah, b'ezrat Hashem.
- Translate anything less common on first use.

NEVER
- Never write like a school essay or an AI assistant. No "In this lesson we will
  explore", no "In conclusion", no "Firstly/Secondly", no bullet-point lists of takeaways.
- Never reuse a memorable phrase from a previous lesson. The style is a rhythm,
  not a set of catchphrases. "Maybe for weeks. Maybe for months. Maybe for years."
  belongs to the lesson it was written for.
- Never invent a Torah source, a quotation, a statistic, a story, or an attribution.
  If the source material does not contain it, it does not go in the lesson.
- Never flatten the source's meaning into a generic message about gratitude.
  Preserve the specific idea the source is actually making.
- No em-dash-heavy AI cadence, no "it's not just X, it's Y" construction on repeat,
  no exclamation marks except in a genuine blessing.$style$,

  -- -------------------------------------------------------- formatting rules
  $json${
    "line_break_cadence":"frequent — one thought per line during emotional passages, fuller paragraphs during teaching passages",
    "paragraph_max_sentences":3,
    "emphasis_technique":"short standalone lines; deliberate ellipses for breath",
    "emoji_policy":"none in the body; at most one decorative emoji in a summary header",
    "rtl_blocks":["hebrew_phrase"],
    "quote_style":"English translations in double quotes on their own line",
    "avoid_phrases":["In conclusion","Let us explore","It is important to note","Firstly","In today's lesson","delve into","tapestry","testament to"]
  }$json$::jsonb,

  -- ------------------------------------------------------------- constraints
  $json${
    "min_words":450,
    "max_words":900,
    "content_policy":"strict_source_only",
    "creative_level":"moderate",
    "require_hebrew_verbatim":true,
    "allow_external_sources":false
  }$json$::jsonb,

  '— Rivkah',
  true,
  1
)
on conflict (id) do nothing;

-- >>>>>>>>>>>>>>>>>>>>>>>>>> 0003_import_rpc.sql <<<<<<<<<<<<<<<<<<<<<<<<<<

-- =============================================================================
-- Transactional lesson import.
--
-- Creating a lesson means three writes that must succeed or fail together:
-- the lesson row, its first version, and the pointers from the lesson back to
-- that version. Doing that over three REST calls leaves half-imported rows
-- behind whenever the network hiccups, so it lives here as one function.
--
-- Idempotent: re-running the importer with unchanged text is a no-op. Changed
-- text creates a NEW version and republishes it, which is exactly the
-- versioning behaviour the rest of the system relies on — imports never
-- rewrite history either.
-- =============================================================================

create or replace function import_lesson(
  p_series_id     uuid,
  p_template_id   uuid,
  p_lesson_number integer,
  p_sequence      integer,
  p_title         text,
  p_hebrew        text,
  p_translit      text,
  p_translation   text,
  p_summary       text,
  p_content       jsonb,
  p_content_text  text,
  p_word_count    integer,
  p_needs_review  boolean default false,
  p_review_notes  text default null,
  p_created_by    uuid default null
)
returns table (lesson_id uuid, action text)
language plpgsql
security definer
set search_path = public
as $$
declare
  v_lesson_id  uuid;
  v_version_id uuid;
  v_existing   text;
  v_next       integer;
begin
  select l.id into v_lesson_id
  from lessons l
  where l.series_id = p_series_id
    and l.lesson_number is not distinct from p_lesson_number
    and l.deleted_at is null;

  -- ---------------------------------------------------------- new lesson
  if v_lesson_id is null then
    insert into lessons (
      series_id, template_id, title, lesson_number, sequence_position,
      hebrew_phrase, transliteration, translation, summary,
      status, needs_review, review_notes, created_by
    ) values (
      p_series_id, p_template_id, p_title, p_lesson_number, p_sequence,
      p_hebrew, p_translit, p_translation, p_summary,
      'published', p_needs_review, p_review_notes, p_created_by
    )
    returning id into v_lesson_id;

    insert into lesson_versions (
      lesson_id, version_number, content, content_text, word_count,
      origin, created_by
    ) values (
      v_lesson_id, 1, p_content, p_content_text, p_word_count,
      'imported', p_created_by
    )
    returning id into v_version_id;

    update lessons
    set current_version_id   = v_version_id,
        published_version_id = v_version_id,
        published_at         = now()
    where id = v_lesson_id;

    return query select v_lesson_id, 'created'::text;
    return;
  end if;

  -- ------------------------------------------------- unchanged: no-op
  select lv.content_text into v_existing
  from lesson_versions lv
  join lessons l on l.published_version_id = lv.id
  where l.id = v_lesson_id;

  if v_existing is not distinct from p_content_text then
    update lessons
    set title            = p_title,
        hebrew_phrase    = p_hebrew,
        transliteration  = p_translit,
        translation      = p_translation,
        summary          = p_summary,
        sequence_position = p_sequence,
        needs_review     = p_needs_review,
        review_notes     = p_review_notes
    where id = v_lesson_id;

    return query select v_lesson_id, 'unchanged'::text;
    return;
  end if;

  -- --------------------------------------- changed: new version, publish
  select coalesce(max(lv.version_number), 0) + 1 into v_next
  from lesson_versions lv where lv.lesson_id = v_lesson_id;

  insert into lesson_versions (
    lesson_id, version_number, parent_version_id, content, content_text,
    word_count, origin, created_by
  ) values (
    v_lesson_id, v_next,
    (select published_version_id from lessons where id = v_lesson_id),
    p_content, p_content_text, p_word_count, 'imported', p_created_by
  )
  returning id into v_version_id;

  update lessons
  set current_version_id   = v_version_id,
      published_version_id = v_version_id,
      published_at         = now(),
      title                = p_title,
      hebrew_phrase        = p_hebrew,
      transliteration      = p_translit,
      translation          = p_translation,
      summary              = p_summary,
      sequence_position    = p_sequence,
      needs_review         = p_needs_review,
      review_notes         = p_review_notes,
      status               = 'published'
  where id = v_lesson_id;

  return query select v_lesson_id, 'updated'::text;
end;
$$;

-- Only the service role runs imports. Never expose this to anon/authenticated.
revoke all on function import_lesson from public, anon, authenticated;


-- =============================================================================
-- Style-example upsert, keyed on title so re-runs replace rather than duplicate.
-- =============================================================================

create or replace function upsert_style_example(
  p_title       text,
  p_source_text text,
  p_final_text  text,
  p_tags        text[],
  p_is_approved boolean,
  p_notes       text default null,
  p_lesson_id   uuid default null
)
returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare v_id uuid;
begin
  select id into v_id from style_examples where title = p_title;

  if v_id is null then
    insert into style_examples (title, source_text, final_text, tags, is_approved, notes, lesson_id)
    values (p_title, p_source_text, p_final_text, p_tags, p_is_approved, p_notes, p_lesson_id)
    returning id into v_id;
  else
    update style_examples
    set source_text = p_source_text,
        final_text  = p_final_text,
        tags        = p_tags,
        is_approved = p_is_approved,
        notes       = p_notes,
        lesson_id   = p_lesson_id
    where id = v_id;
  end if;

  return v_id;
end;
$$;

revoke all on function upsert_style_example from public, anon, authenticated;

-- >>>>>>>>>>>>>>>>>>>>>>>>>> 0004_job_queue.sql <<<<<<<<<<<<<<<<<<<<<<<<<<

-- =============================================================================
-- Postgres-backed job queue.
--
-- No Redis, no Celery. `FOR UPDATE SKIP LOCKED` gives us safe concurrent
-- claiming in ~40 lines of SQL, the queue survives a redeploy because it is
-- just a table, and job state is queryable with the same tools as everything
-- else. If throughput ever demands more, only `app/jobs/queue.py` changes.
-- =============================================================================

-- Claim exactly one queued job, atomically.
--
-- SKIP LOCKED is what makes this safe to run from several workers at once:
-- each transaction takes a different row instead of blocking on the same one.
create or replace function claim_job(
  p_worker text,
  p_types  text[] default null
)
returns setof jobs
language plpgsql
security definer
set search_path = public
as $$
begin
  return query
  update jobs
  set status     = 'running',
      locked_at  = now(),
      locked_by  = p_worker,
      attempts   = jobs.attempts + 1,
      updated_at = now()
  where jobs.id = (
    select j.id
    from jobs j
    where j.status = 'queued'
      and (p_types is null or j.type = any(p_types))
    order by j.created_at
    for update skip locked
    limit 1
  )
  returning jobs.*;
end;
$$;


create or replace function complete_job(
  p_job_id uuid,
  p_result jsonb default '{}'::jsonb
)
returns void
language sql
security definer
set search_path = public
as $$
  update jobs
  set status         = 'succeeded',
      result         = p_result,
      progress_pct   = 100,
      progress_stage = 'done',
      locked_at      = null,
      locked_by      = null,
      error          = null,
      updated_at     = now()
  where id = p_job_id;
$$;


-- Fail a job, retrying it if attempts remain.
--
-- `attempts` was already incremented at claim time, so a job that has used up
-- its allowance lands in 'failed' and stops; anything else goes back to the
-- queue for another worker.
create or replace function fail_job(
  p_job_id uuid,
  p_error  text,
  p_retry  boolean default true
)
returns text
language plpgsql
security definer
set search_path = public
as $$
declare
  v_attempts integer;
  v_max      integer;
  v_status   text;
begin
  select attempts, max_attempts into v_attempts, v_max
  from jobs where id = p_job_id;

  if v_attempts is null then
    return 'missing';
  end if;

  if p_retry and v_attempts < v_max then
    v_status := 'queued';
  else
    v_status := 'failed';
  end if;

  update jobs
  set status     = v_status::job_status,
      error      = left(p_error, 2000),
      locked_at  = null,
      locked_by  = null,
      updated_at = now()
  where id = p_job_id;

  return v_status;
end;
$$;


create or replace function update_job_progress(
  p_job_id uuid,
  p_stage  text,
  p_pct    integer default null
)
returns void
language sql
security definer
set search_path = public
as $$
  update jobs
  set progress_stage = p_stage,
      progress_pct   = coalesce(least(greatest(p_pct, 0), 100), progress_pct),
      updated_at     = now()
  where id = p_job_id;
$$;


-- Requeue jobs whose worker died mid-run.
--
-- Without this a crashed worker leaves its job 'running' forever and the
-- admin sees a spinner that never resolves.
create or replace function reap_stale_jobs(
  p_timeout_seconds integer default 900
)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  v_count integer;
begin
  with stale as (
    update jobs
    set status     = case
                       when attempts >= max_attempts then 'failed'::job_status
                       else 'queued'::job_status
                     end,
        error      = 'Worker stopped responding; job was requeued',
        locked_at  = null,
        locked_by  = null,
        updated_at = now()
    where status = 'running'
      and locked_at < now() - make_interval(secs => p_timeout_seconds)
    returning 1
  )
  select count(*) into v_count from stale;
  return v_count;
end;
$$;


-- Workers run as the service role. Nothing here is callable by a browser.
revoke all on function claim_job          from public, anon, authenticated;
revoke all on function complete_job       from public, anon, authenticated;
revoke all on function fail_job           from public, anon, authenticated;
revoke all on function update_job_progress from public, anon, authenticated;
revoke all on function reap_stale_jobs    from public, anon, authenticated;

-- >>>>>>>>>>>>>>>>>>>>>>>>>> 0005_fix_version_allocation.sql <<<<<<<<<<<<<<<<<<<<<<<<<<

-- =============================================================================
-- Fix: version-number allocation.
--
-- `next_version_number` in 0001 did this:
--
--     select coalesce(max(version_number), 0) + 1 into n
--     from lesson_versions where lesson_id = p_lesson_id
--     for update;
--
-- which Postgres rejects outright — FOR UPDATE cannot be combined with an
-- aggregate (SQLSTATE 0A000). Every attempt to save a new lesson version
-- failed with a database error.
--
-- Beyond the syntax, the shape was wrong. Allocating the number in one
-- request and inserting in another leaves a race between them: PostgREST runs
-- each call in its own transaction, so any lock taken during allocation is
-- released before the insert happens. Two admins saving at the same moment
-- would both be handed the same number and one would lose their work to a
-- unique-constraint violation.
--
-- Both problems disappear if allocation and insertion are the same statement.
-- =============================================================================

-- Allocate and insert atomically, and move the lesson's `current_version_id`
-- to point at the result. `published_version_id` is deliberately NOT touched:
-- saving an edit must never publish it.
create or replace function create_lesson_version(
  p_lesson_id     uuid,
  p_content       jsonb,
  p_content_text  text,
  p_word_count    integer,
  p_origin        version_origin,
  p_instruction   text default null,
  p_analysis      jsonb default null,
  p_quality       jsonb default null,
  p_model_meta    jsonb default '{}'::jsonb,
  p_created_by    uuid default null
)
returns lesson_versions
language plpgsql
security definer
set search_path = public
as $$
declare
  v_next    integer;
  v_parent  uuid;
  v_status  lesson_status;
  v_version lesson_versions;
begin
  -- Serialise version creation for this lesson only. Held for the rest of
  -- this transaction, which now covers the insert as well — so two concurrent
  -- saves queue instead of colliding.
  perform pg_advisory_xact_lock(hashtextextended(p_lesson_id::text, 0));

  select current_version_id, status into v_parent, v_status
  from lessons
  where id = p_lesson_id and deleted_at is null;

  if not found then
    raise exception 'lesson % does not exist', p_lesson_id
      using errcode = 'no_data_found';
  end if;

  select coalesce(max(version_number), 0) + 1 into v_next
  from lesson_versions
  where lesson_id = p_lesson_id;

  insert into lesson_versions (
    lesson_id, version_number, parent_version_id, content, content_text,
    word_count, structured_analysis, quality_report, model_metadata,
    origin, modification_instruction, created_by
  ) values (
    p_lesson_id, v_next, v_parent, p_content, p_content_text,
    p_word_count, p_analysis, p_quality, coalesce(p_model_meta, '{}'::jsonb),
    p_origin, p_instruction, p_created_by
  )
  returning * into v_version;

  update lessons
  set current_version_id = v_version.id,
      -- A published lesson stays published; the published pointer has not
      -- moved, so learners still see exactly what they saw before.
      status = case when v_status = 'published' then 'published' else 'review' end,
      updated_at = now()
  where id = p_lesson_id;

  return v_version;
end;
$$;

revoke all on function create_lesson_version from public, anon, authenticated;


-- Keep the old helper working for anything that calls it, minus the invalid
-- FOR UPDATE. It is advisory only — use create_lesson_version to actually
-- create a version.
create or replace function next_version_number(p_lesson_id uuid)
returns integer
language sql
stable
security definer
set search_path = public
as $$
  select coalesce(max(version_number), 0) + 1
  from lesson_versions
  where lesson_id = p_lesson_id;
$$;

-- >>>>>>>>>>>>>>>>>>>>>>>>>> 0006_fix_version_status_cast.sql <<<<<<<<<<<<<<<<<<<<<<<<<<

-- =============================================================================
-- Fix: enum cast in create_lesson_version.
--
-- 0005 wrote:
--
--     status = case when v_status = 'published' then 'published' else 'review' end
--
-- Both branches are untyped string literals, so the CASE resolves to `text`.
-- `lessons.status` is the `lesson_status` enum, and Postgres does not
-- implicitly cast text to an enum in an UPDATE ... SET. Every save failed with
--
--     42804: column "status" is of type lesson_status but expression is of
--            type text
--
-- Casting the CASE result fixes it. This is the only change from 0005.
-- =============================================================================

create or replace function create_lesson_version(
  p_lesson_id     uuid,
  p_content       jsonb,
  p_content_text  text,
  p_word_count    integer,
  p_origin        version_origin,
  p_instruction   text default null,
  p_analysis      jsonb default null,
  p_quality       jsonb default null,
  p_model_meta    jsonb default '{}'::jsonb,
  p_created_by    uuid default null
)
returns lesson_versions
language plpgsql
security definer
set search_path = public
as $$
declare
  v_next    integer;
  v_parent  uuid;
  v_status  lesson_status;
  v_version lesson_versions;
begin
  -- Serialise version creation for this lesson. Held for the rest of this
  -- transaction, which covers the insert too — so two concurrent saves queue
  -- instead of being handed the same version number.
  perform pg_advisory_xact_lock(hashtextextended(p_lesson_id::text, 0));

  select current_version_id, status into v_parent, v_status
  from lessons
  where id = p_lesson_id and deleted_at is null;

  if not found then
    raise exception 'lesson % does not exist', p_lesson_id
      using errcode = 'no_data_found';
  end if;

  select coalesce(max(version_number), 0) + 1 into v_next
  from lesson_versions
  where lesson_id = p_lesson_id;

  insert into lesson_versions (
    lesson_id, version_number, parent_version_id, content, content_text,
    word_count, structured_analysis, quality_report, model_metadata,
    origin, modification_instruction, created_by
  ) values (
    p_lesson_id, v_next, v_parent, p_content, p_content_text,
    p_word_count, p_analysis, p_quality, coalesce(p_model_meta, '{}'::jsonb),
    p_origin, p_instruction, p_created_by
  )
  returning * into v_version;

  update lessons
  set current_version_id = v_version.id,
      -- A published lesson stays published: the published pointer has not
      -- moved, so learners still see exactly what they saw before.
      status = (
        case when v_status = 'published' then 'published' else 'review' end
      )::lesson_status,
      updated_at = now()
  where id = p_lesson_id;

  return v_version;
end;
$$;

revoke all on function create_lesson_version from public, anon, authenticated;

-- >>>>>>>>>>>>>>>>>>>>>>>>>> 0007_search_similarity.sql <<<<<<<<<<<<<<<<<<<<<<<<<<

-- =============================================================================
-- Fix: the search function returned no usable relevance signal.
--
-- 0001 returned only a Reciprocal Rank Fusion score. Two problems with using
-- that to decide whether an answer is grounded:
--
--   1. SCALE. RRF with k=60 yields 1/(60+rank) per list, so the maximum
--      possible score — rank 1 in BOTH lists — is 2/61 = 0.0328. The
--      configured grounding threshold was 0.25, which no result could ever
--      reach. Every question was therefore answered "I don't have anything in
--      the lessons", including ones the corpus answers well.
--
--   2. MEANING. An RRF score encodes rank, not quality. The single best match
--      for "what is the best chocolate cake recipe" scores exactly the same as
--      the best match for "what does Moshia mean" — both are rank 1. Ranking
--      cannot distinguish a good answer from the least-bad of a bad set, which
--      is precisely what a grounding check has to do.
--
-- So the function now returns BOTH:
--   * `score`      — fused RRF, for ordering results against each other
--   * `similarity` — raw cosine similarity, an absolute measure of how close
--                    the passage actually is, for deciding whether to answer
--
-- Ordering and grounding are different questions and now use different numbers.
-- =============================================================================

drop function if exists search_published_chunks(vector, text, integer, uuid);

create or replace function search_published_chunks(
  query_embedding  vector(1536),
  query_text       text,
  match_count      integer default 6,
  filter_lesson_id uuid default null
)
returns table (
  chunk_id      uuid,
  lesson_id     uuid,
  lesson_title  text,
  lesson_number integer,
  section_key   text,
  chunk_text    text,
  metadata      jsonb,
  score         double precision,
  similarity    double precision
)
language sql
stable
security definer
set search_path = public
as $$
  with published as (
    select l.id, l.title, l.lesson_number, l.published_version_id
    from lessons l
    where l.status = 'published'
      and l.published_version_id is not null
      and l.deleted_at is null
      and (filter_lesson_id is null or l.id = filter_lesson_id)
  ),
  candidates as (
    select c.id, c.lesson_id, c.section_key, c.chunk_text, c.metadata,
           c.embedding, c.tsv
    from lesson_chunks c
    join published p
      on p.id = c.lesson_id
     and p.published_version_id = c.version_id
    where c.embedding is not null
  ),
  vector_hits as (
    select id,
           row_number() over (order by embedding <=> query_embedding) as rnk,
           -- pgvector's <=> is cosine DISTANCE; 1 - distance is similarity.
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
           coalesce(1.0 / (60 + v.rnk), 0.0)
         + coalesce(1.0 / (60 + t.rnk), 0.0) as score,
           v.similarity
    from vector_hits v
    full outer join text_hits t on t.id = v.id
  )
  select c.id, c.lesson_id, p.title, p.lesson_number,
         c.section_key, c.chunk_text, c.metadata,
         f.score,
         -- A lexical-only hit has no vector rank. Compute its similarity
         -- directly rather than reporting null, so grounding always has a
         -- number to work with.
         coalesce(f.similarity, 1 - (c.embedding <=> query_embedding)) as similarity
  from fused f
  join candidates c on c.id = f.id
  join published  p on p.id = c.lesson_id
  order by f.score desc
  limit match_count;
$$;

revoke all on function search_published_chunks from public, anon;

-- >>>>>>>>>>>>>>>>>>>>>>>>>> 0008_tuned_style_guide.sql <<<<<<<<<<<<<<<<<<<<<<<<<<

-- =============================================================================
-- Phase 6b: the style guide, tuned against measured evidence.
--
-- Every rule below came from measuring the client's 131 published lessons and
-- comparing generated output against them, not from taste:
--
--   metric                hers      before      after
--   median line length    8.5 w     18-25 w     9-12 w
--   lines of <= 6 words   40%       15-28%      22-32%
--   lines per 100 words   7.3       4.3-4.9     6.8-7.3
--   lesson length         ~572 w    609-775 w   497-757 w
--
-- Three failures were consistent across every generated lesson before this:
--   1. Lines roughly twice as long as hers. Line breaks are her punctuation,
--      so this was the single largest gap in voice.
--   2. "dear friends" as the address term. She says "beautiful neshamot",
--      "neshamot yekarot" or "everyone" -- never "dear friends".
--   3. The same Torah source quoted in two different sections.
--
-- This migration makes a fresh install match what the live database already
-- has. backend/scripts/tune_style.py applies the same content to an existing
-- project, and is the file to edit if this is revised again.
--
-- The style guide is DATA. Edit it at /admin/templates, not here.
-- =============================================================================

update lesson_templates
set style_guide = $style$You are writing in the voice of a warm, thoughtful woman teaching a weekly Torah
lesson to a community she knows personally. She is not a lecturer. She is a friend
thinking out loud, sharing something that moved her this week.

═══════════════════════════════════════════════════════════════════════
RHYTHM — the signature of this style, and the thing most often got wrong
═══════════════════════════════════════════════════════════════════════

HER LINES ARE SHORT. Measured across her published lessons: the median line is
about 8 words, and roughly 40% of lines are 6 words or fewer.

If your output reads as paragraphs of 18–25 word sentences, it is WRONG —
however good the content is. This is the single most common failure.

Break lines the way she breathes. Write this:

    When I hear the word "Savior," I naturally picture someone rescuing another person from danger.

    Someone falls...

    Someone rushes in to save them.

NOT this:

    When I hear the word "Savior," I picture someone rescuing another from danger — someone falls, and someone rushes in to save them.

Put a blank line between most thoughts. Build with parallel short lines, then
let one land:

    For a child.

    For a shidduch.

    For healing.

Vary it. A page of nothing but three-word lines becomes a gimmick — long
reflective sentences are what make the short ones hit.

Ellipses create a pause before a turn:
    "And after a while... you don't even know what else to say."

═══════════════════════════════════════════════════════════════════════
HOW SHE ADDRESSES HER LEARNERS
═══════════════════════════════════════════════════════════════════════

She calls them "beautiful neshamot", "neshamot yekarot", or "everyone".

NEVER "dear friends", "dear ones", "my friends", "dear neshamot yekarot" or
anything else. Those are not her words.

Her actual openings, in roughly her own frequency:
    "Shavua tov, beautiful neshamot."
    "Good morning, everyone."
    "Good morning, beautiful neshamot."
    "Shavua tov, neshamot yekarot."

Vary which you use. If the source itself opens with a greeting, follow its time
of day — "Good morning" if she recorded in the morning, "Shavua tov" for
Motzaei Shabbat.

═══════════════════════════════════════════════════════════════════════
VOICE
═══════════════════════════════════════════════════════════════════════

- Warm, personal, conversational, reflective. Speak TO the reader.
- First person about herself: "I was thinking about this word..."
- Second person to the reader: "You've been davening."
- Emotionally honest. Name real feelings: tired, waiting, disappointed, hopeful.
- Spiritually engaging, never preachy. Invite; do not instruct.
- Accessible. A woman reading on her phone between school pickups should
  understand every sentence the first time.
- One or two genuine rhetorical questions per lesson. Not more.

TECHNIQUES
- One concrete, sensory, everyday image — drawn from the source material.
- Smooth transitions: "But recently I heard an idea that really stayed with me."
- "Maybe that's what..." and "Perhaps that's one of the beautiful messages of..."
  to turn an observation into a spiritual insight.
- Close by rising, not by summarising. Blessing, not conclusion.
- Sign off simply: "Shavua tov. Make it a wonderful week."

HEBREW
- Hebrew appears in Hebrew script with nikud, exactly as in the source.
- Transliterate on first use, then use the transliterated form naturally.
- Familiar words stay untranslated: Hashem, shavua tov, neshamot, tefillah,
  davening, shidduch, parnassah, yeshuah, emunah, hakarat hatov, zechut,
  geulah, b'ezrat Hashem.
- Translate anything less common on first use.

═══════════════════════════════════════════════════════════════════════
LENGTH — match the source, never pad
═══════════════════════════════════════════════════════════════════════

Her lessons run about 570 words.

But length follows the SOURCE. A 200-word source produces a SHORT lesson, not a
padded one. Writing 600 words from 185 words of source means inventing 400
words — which is exactly what must never happen here. A short honest lesson is
a success. A long invented one is a failure.

═══════════════════════════════════════════════════════════════════════
EACH SECTION MUST EARN ITS PLACE
═══════════════════════════════════════════════════════════════════════

Do not repeat material across sections. If the Torah source has already been
quoted inside the story, do not quote it again in the supporting-source
section — refer to it in a phrase, or leave that section out entirely.

Overlapping sections are the second most common failure. Each one should move
the lesson forward.

═══════════════════════════════════════════════════════════════════════
NEVER
═══════════════════════════════════════════════════════════════════════

- Never write like a school essay or an AI assistant. No "In this lesson we
  will explore", no "In conclusion", no "Firstly/Secondly", no bullet lists of
  takeaways.
- Never reuse a memorable phrase from a previous lesson. The style is a rhythm,
  not a set of catchphrases.
- Never invent a Torah source, a quotation, a statistic, a story, or an
  attribution. If the source does not contain it, it does not go in the lesson.
- Never flatten the source's meaning into a generic message about gratitude.
  Preserve the specific idea the source is actually making.
- No em-dash-heavy AI cadence, no repeated "it's not just X, it's Y", no
  exclamation marks except in a genuine blessing.$style$,
    formatting_rules = $json${
  "line_break_cadence": "Short lines. Median about 8 words; roughly 40% of lines 6 words or fewer. Blank line between most thoughts.",
  "target_median_line_words": 8,
  "target_short_line_percentage": 40,
  "paragraph_max_sentences": 2,
  "emphasis_technique": "short standalone lines; deliberate ellipses for breath",
  "emoji_policy": "none in the body; at most one decorative emoji in a summary header",
  "rtl_blocks": [
    "hebrew_phrase"
  ],
  "quote_style": "English translations in double quotes on their own line",
  "address_terms": [
    "beautiful neshamot",
    "neshamot yekarot",
    "everyone"
  ],
  "avoid_phrases": [
    "dear friends",
    "dear ones",
    "my friends",
    "In conclusion",
    "Let us explore",
    "It is important to note",
    "Firstly",
    "In today's lesson",
    "delve into",
    "tapestry",
    "testament to",
    "Great question"
  ]
}$json$::jsonb,
    version = greatest(version, 2)
where id = '00000000-0000-0000-0000-000000000010';


-- ==========================================================================
-- >>>>>>>>>>>>>>>>>>>>>>>>>> 0009_reference_corpus.sql <<<<<<<<<<<<<<<<<<<<<<<<<<
-- ==========================================================================

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


-- ==========================================================================
-- >>>>>>>>>>>>>>>>>>>>>>>>>> 0010_hebrew_plain.sql <<<<<<<<<<<<<<<<<<<<<<<<<<
-- ==========================================================================

-- =============================================================================
-- Fix: quote verification welded words together, and so reported correct
-- quotations as fabrications.
--
-- 0009 reduced Hebrew to its consonantal skeleton by deleting every character
-- in U+0591-U+05C7. That range is not all vowel points. It also contains the
-- word SEPARATORS, and deleting a separator does not remove a mark — it joins
-- two words into one:
--
--     "kol-atzmotai"  ->  kolatzmotai      (maqaf U+05BE deleted)
--     "mi-chamocha"   ->  michamocha       (maqaf U+05BE deleted)
--
-- The consequence was the opposite of what the check exists for. Tehillim
-- 35:10 is quoted verbatim inside Nishmat, and `verify_hebrew_quote` could not
-- find it in the stored Psalms — so a lesson quoting that verse correctly would
-- have been flagged as having invented it. A grounding warning that fires on
-- correct quotations is worse than no warning at all: it teaches the admin to
-- ignore the warnings.
--
-- So separators become a SPACE and only true marks are deleted. The
-- normalisation now lives in ONE function used by both the stored column and
-- the lookup, because the two must agree exactly or nothing matches.
--
-- The two character classes below are literal characters, and most of them are
-- invisible combining marks — which is exactly how the maqaf ended up in the
-- delete set in the first place. So they are spelled out here instead, and a
-- test asserts the codepoints of each class rather than trusting the reading:
--
--   U+05BE maqaf        joins words          -> space
--   U+05C0 paseq        separates words      -> space
--   U+05C3 sof pasuq    ends a verse         -> space
--   U+05C6 nun hafukha  editorial mark       -> space
--   U+00A0, U+2000-200A, U+202F, U+205F, U+3000   exotic spaces -> space
--   everything else in U+0591-U+05C7, plus U+05F3/U+05F4        -> deleted
-- =============================================================================

create or replace function hebrew_plain(p_text text)
returns text
language sql
immutable
strict
parallel safe
set search_path = public
as $$
  select btrim(regexp_replace(
    regexp_replace(
      regexp_replace(
        p_text,
        '[־׀׃׆  -   　]',
        ' ',
        'g'
      ),
      '[֑-ׇֽֿׁׂׅׄ׳״]',
      '',
      'g'
    ),
    '\s+', ' ', 'g'
  ));
$$;

-- The column is generated, so it cannot be altered in place. Dropping and
-- re-adding recomputes it for every row — a few hundred here, and the only way
-- to be certain no row keeps the old shape.
alter table reference_chunks drop column if exists chunk_text_plain;

alter table reference_chunks
  add column chunk_text_plain text
  generated always as (hebrew_plain(chunk_text)) stored;

-- Rebuilt, because the column it indexed was replaced.
drop index if exists reference_chunks_plain_trgm_idx;
create index reference_chunks_plain_trgm_idx
  on reference_chunks using gin (chunk_text_plain gin_trgm_ops);

-- -----------------------------------------------------------------------------
-- Verification, now normalising the needle exactly as the haystack was
-- normalised. Previously each side carried its own copy of the expression,
-- which is how they came to disagree.
-- -----------------------------------------------------------------------------

create or replace function verify_hebrew_quote(
  p_quote text,
  p_kinds text[] default array['nishmat_text', 'scripture']
)
returns table (ref text, title text, variant text, kind text)
language sql stable security definer set search_path = public as $$
  with needle as (select hebrew_plain(p_quote) as text)
  select c.ref, d.title, d.variant, c.kind::text
  from reference_chunks c
  join reference_documents d on d.id = c.document_id
  cross join needle n
  where d.is_active
    and c.lesson_id is null
    and c.kind::text = any(p_kinds)
    and length(n.text) > 3
    and c.chunk_text_plain like '%' || n.text || '%'
  limit 5;
$$;

revoke all on function verify_hebrew_quote from public, anon;
