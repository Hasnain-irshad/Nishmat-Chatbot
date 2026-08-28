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
