"use client";

import { Fragment, type ReactNode } from "react";

import { cn, hasHebrew } from "@/lib/utils";

/**
 * Renders a chat answer.
 *
 * The model writes markdown — headings, bold, bullet lists, rules — and until
 * now this surface printed it raw, so a learner saw literal asterisks around
 * every lesson title.
 *
 * Three constraints shaped this rather than reaching for a library:
 *
 * 1. **No `dangerouslySetInnerHTML`, ever.** This renders text produced by a
 *    language model from documents an admin uploaded. Building React elements
 *    means untrusted content cannot become markup, so there is no HTML
 *    sanitisation to get wrong.
 *
 * 2. **Single newlines survive.** In this corpus a line break IS punctuation —
 *    the teacher builds emphasis by breaking a thought across short lines.
 *    Standard markdown collapses those into flowing prose, which silently
 *    destroys the voice while leaving every character present. So paragraphs
 *    keep `whitespace-pre-wrap`.
 *
 * 3. **No ordered lists.** Deliberate. The chatbot returns complete stored
 *    lessons verbatim, and reformatting one is the same class of silent
 *    corruption as truncating it. Every one of the 131 published lessons was
 *    scanned: none contains bold markers, headings, rules or bullet syntax, but
 *    one opens a line with "1. ". Supporting ordered lists would restyle that
 *    line inside an otherwise byte-exact lesson. A model-written "1." simply
 *    renders as text, which reads fine; a mangled lesson does not.
 */

type Block =
  | { kind: "heading"; level: 2 | 3; text: string }
  | { kind: "list"; items: string[] }
  | { kind: "rule" }
  | { kind: "para"; text: string };

const BULLET = /^\s*[-*•]\s+(.*)$/;
const HEADING = /^\s*(#{1,6})\s+(.*)$/;
const RULE = /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/;

function parse(source: string): Block[] {
  const blocks: Block[] = [];

  for (const chunk of source.split(/\n{2,}/)) {
    const raw = chunk.replace(/\s+$/, "");
    if (!raw.trim()) continue;

    const lines = raw.split("\n");

    // A block whose FIRST line is a bullet becomes a list.
    //
    // Lines in between that are not bullets are continuations of the item
    // above, not a reason to abandon the list — an item routinely carries a
    // second line ("19 mentions · 693 words"). Requiring every line to match
    // dropped the whole block back to a paragraph and printed raw "-" markers.
    if (BULLET.test(lines[0])) {
      const items: string[] = [];
      for (const line of lines) {
        const bullet = line.match(BULLET);
        if (bullet) {
          items.push(bullet[1].trim());
        } else if (line.trim() && items.length) {
          items[items.length - 1] += `\n${line.trim()}`;
        }
      }
      if (items.length) {
        blocks.push({ kind: "list", items });
        continue;
      }
    }

    // A lone heading or rule on its own line.
    if (lines.length === 1) {
      if (RULE.test(lines[0])) {
        blocks.push({ kind: "rule" });
        continue;
      }
      const heading = lines[0].match(HEADING);
      if (heading) {
        blocks.push({
          kind: "heading",
          level: heading[1].length <= 2 ? 2 : 3,
          text: heading[2].trim(),
        });
        continue;
      }
    }

    blocks.push({ kind: "para", text: raw });
  }

  return blocks;
}

/**
 * Inline emphasis, as React nodes.
 *
 * Ordered so the longest marker wins: `**bold**` must be consumed before a
 * single `*` could match half of it.
 */
const INLINE = /(\*\*[^*\n]+\*\*|`[^`\n]+`|(?<![\w*])\*[^*\n]+\*(?![\w*]))/g;

function inline(text: string, keyPrefix: string): ReactNode[] {
  const out: ReactNode[] = [];

  text.split(INLINE).forEach((part, index) => {
    if (!part) return;
    const key = `${keyPrefix}-${index}`;

    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      out.push(
        <strong key={key} className="font-semibold text-ink-50">
          {part.slice(2, -2)}
        </strong>,
      );
      return;
    }
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      out.push(
        <code
          key={key}
          className="rounded bg-white/[0.08] px-1 py-0.5 text-[0.9em] text-gold-100"
        >
          {part.slice(1, -1)}
        </code>,
      );
      return;
    }
    if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
      out.push(
        <em key={key} className="italic text-ink-200">
          {part.slice(1, -1)}
        </em>,
      );
      return;
    }

    out.push(<Fragment key={key}>{part}</Fragment>);
  });

  return out;
}

/** Hebrew that stands alone is set right-to-left; mixed text is left to bidi. */
function direction(text: string) {
  const rtl = hasHebrew(text) && !/[A-Za-z]/.test(text);
  return {
    dir: rtl ? ("rtl" as const) : ("auto" as const),
    lang: rtl ? "he" : undefined,
    rtl,
  };
}

export function Markdown({ text }: { text: string }) {
  const blocks = parse(text);

  return (
    <div className="space-y-2.5 text-[0.95rem] leading-[1.7]">
      {blocks.map((block, index) => {
        const key = `b${index}`;

        if (block.kind === "rule") {
          return <hr key={key} className="my-3 border-white/[0.09]" />;
        }

        if (block.kind === "heading") {
          const { dir, lang, rtl } = direction(block.text);
          return (
            <p
              key={key}
              dir={dir}
              lang={lang}
              className={cn(
                "font-display text-ink-50",
                block.level === 2 ? "pt-1 text-[1.08em]" : "text-[1.02em]",
                rtl && "hebrew",
              )}
            >
              {inline(block.text, key)}
            </p>
          );
        }

        if (block.kind === "list") {
          return (
            <ul key={key} className="space-y-1.5 pl-1">
              {block.items.map((item, i) => {
                const { dir, lang, rtl } = direction(item);
                return (
                  <li
                    key={`${key}-${i}`}
                    dir={dir}
                    lang={lang}
                    className={cn(
                      "flex gap-2.5",
                      rtl && "hebrew flex-row-reverse text-[1.05em]",
                    )}
                  >
                    <span
                      aria-hidden
                      className="mt-[0.62em] h-1 w-1 shrink-0 rounded-full bg-gold-300/70"
                    />
                    <span className="min-w-0 flex-1 whitespace-pre-wrap">
                      {inline(item, `${key}-${i}`)}
                    </span>
                  </li>
                );
              })}
            </ul>
          );
        }

        const { dir, lang, rtl } = direction(block.text);
        return (
          <p
            key={key}
            dir={dir}
            lang={lang}
            className={cn("whitespace-pre-wrap", rtl && "hebrew text-[1.1em]")}
          >
            {inline(block.text, key)}
          </p>
        );
      })}
    </div>
  );
}
