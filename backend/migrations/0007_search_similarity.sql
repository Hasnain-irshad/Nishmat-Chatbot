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
