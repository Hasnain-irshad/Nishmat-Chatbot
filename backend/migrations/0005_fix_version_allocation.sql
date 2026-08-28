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
