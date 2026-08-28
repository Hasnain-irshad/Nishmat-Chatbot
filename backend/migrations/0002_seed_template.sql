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
