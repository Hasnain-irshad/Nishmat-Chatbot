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
