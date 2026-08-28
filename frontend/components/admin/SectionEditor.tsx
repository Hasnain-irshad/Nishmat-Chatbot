"use client";

import { useEffect, useRef } from "react";
import { GripVertical, Trash2, Wand2 } from "lucide-react";

import { cn, hasHebrew } from "@/lib/utils";
import type { LessonSection } from "@/lib/api";

/**
 * One editable lesson section.
 *
 * A plain textarea, deliberately.
 *
 * This client's style uses line breaks as punctuation — "Maybe for weeks. /
 * Maybe for months. / Maybe for years." is three lines, and that spacing IS
 * the writing. A rich-text editor normalises whitespace, converts blank lines
 * into paragraph nodes, and generally fights to "tidy" exactly the thing that
 * must be preserved byte for byte. A textarea stores what was typed.
 */

const SECTION_LABELS: Record<string, string> = {
  series_title: "Series title",
  lesson_number: "Lesson number",
  hebrew_phrase: "Hebrew phrase",
  transliteration: "Transliteration",
  translation: "English translation",
  greeting: "Greeting",
  introduction: "Introduction",
  central_concept: "Central concept",
  personal_hook: "Personal hook",
  story_example: "Story or example",
  spiritual_connection: "Connection to the idea",
  supporting_source: "Supporting source",
  reflection: "Reflection",
  practical_takeaway: "Practical invitation",
  closing_blessing: "Closing blessing",
  signoff: "Sign-off",
  whatsapp_summary: "WhatsApp summary",
};

function labelFor(section: LessonSection): string {
  if (section.title) return section.title;
  if (SECTION_LABELS[section.key]) return SECTION_LABELS[section.key];
  if (section.key.startsWith("body_")) {
    return `Body ${section.key.replace("body_", "")}`;
  }
  return section.key;
}

export function SectionEditor({
  section,
  onChange,
  onRemove,
  onAskAi,
  disabled,
}: {
  section: LessonSection;
  onChange: (next: LessonSection) => void;
  onRemove?: () => void;
  /** Opens the revise dialog. `selection` is set when text is highlighted. */
  onAskAi?: (selection: string | undefined) => void;
  disabled?: boolean;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);

  // Grow to fit the content — a scrollbar inside a lesson section makes the
  // pacing impossible to see while editing.
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${element.scrollHeight}px`;
  }, [section.body]);

  // Hebrew sections are marked RTL in the template, but a section that has
  // become Hebrew-only through editing should follow.
  const isRtl =
    section.dir === "rtl" ||
    (hasHebrew(section.body) && !/[A-Za-z]/.test(section.body));

  const lineCount = section.body.split("\n").length;
  const wordCount = section.body.trim() ? section.body.trim().split(/\s+/).length : 0;

  return (
    <div className="group/section rounded-2xl border border-white/[0.08] bg-white/[0.02] transition-colors focus-within:border-gold-300/30">
      <div className="flex items-center gap-2 px-4 pt-3">
        <GripVertical
          className="h-3.5 w-3.5 shrink-0 text-ink-500/50"
          aria-hidden
        />
        <span className="text-[0.7rem] font-medium uppercase tracking-wider text-ink-400">
          {labelFor(section)}
        </span>
        {isRtl && (
          <span className="rounded-full bg-gold-300/12 px-1.5 py-0.5 text-[0.6rem] font-medium text-gold-200">
            RTL
          </span>
        )}

        <span className="ml-auto flex items-center gap-2 text-[0.68rem] text-ink-500">
          {onAskAi && (
            <button
              type="button"
              disabled={disabled}
              onClick={() => {
                // If the admin highlighted text, revise only that. Otherwise
                // the whole section.
                const el = ref.current;
                const picked =
                  el && el.selectionStart !== el.selectionEnd
                    ? el.value.slice(el.selectionStart, el.selectionEnd).trim()
                    : undefined;
                onAskAi(picked || undefined);
              }}
              className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-violet-300
                         opacity-0 transition-all hover:bg-violet-500/15 hover:text-violet-200
                         focus-visible:opacity-100 group-hover/section:opacity-100
                         disabled:opacity-30"
              title="Ask AI to revise this section, or highlight part of it first"
            >
              <Wand2 className="h-3.5 w-3.5" aria-hidden />
              Ask AI
            </button>
          )}
          <span>
            {wordCount} word{wordCount === 1 ? "" : "s"} · {lineCount} line
            {lineCount === 1 ? "" : "s"}
          </span>
          {onRemove && (
            <button
              type="button"
              onClick={onRemove}
              disabled={disabled}
              className="rounded p-1 text-ink-500 opacity-0 transition-all hover:text-rose-300 group-hover/section:opacity-100 disabled:opacity-30"
              aria-label={`Remove ${labelFor(section)}`}
            >
              <Trash2 className="h-3.5 w-3.5" aria-hidden />
            </button>
          )}
        </span>
      </div>

      <textarea
        ref={ref}
        value={section.body}
        disabled={disabled}
        dir={isRtl ? "rtl" : "auto"}
        lang={isRtl ? "he" : undefined}
        onChange={(event) => onChange({ ...section, body: event.target.value })}
        spellCheck={!isRtl}
        className={cn(
          "w-full resize-none bg-transparent px-4 pb-4 pt-2 text-[0.95rem] leading-[1.85]",
          "text-ink-100 outline-none placeholder:text-ink-500/60 disabled:opacity-60",
          isRtl && "hebrew text-[1.15rem] leading-[2]",
        )}
        placeholder="Write this section…"
        rows={1}
      />
    </div>
  );
}
