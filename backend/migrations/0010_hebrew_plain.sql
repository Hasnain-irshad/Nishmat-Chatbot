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
