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
