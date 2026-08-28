"use client";

import { useState } from "react";
import { Moon, Sun, Type } from "lucide-react";

import { cn, hasHebrew } from "@/lib/utils";
import type { LessonSection } from "@/types/database";

type Theme = "night" | "parchment";
type TextSize = "sm" | "md" | "lg";

const SIZE_CLASS: Record<TextSize, string> = {
  sm: "text-[0.95rem]",
  md: "text-[1.05rem]",
  lg: "text-[1.2rem]",
};

/**
 * Renders a lesson in the client's editorial format.
 *
 * The single most important detail here: this style uses line breaks as
 * punctuation. "Maybe for weeks. / Maybe for months. / Maybe for years."
 * is three lines, not one paragraph — collapsing them would destroy the
 * pacing that defines the voice. So every newline in a section body becomes
 * its own line, and blank lines become real vertical space.
 */
export function LessonReader({ sections }: { sections: LessonSection[] }) {
  const [theme, setTheme] = useState<Theme>("night");
  const [size, setSize] = useState<TextSize>("md");

  const ordered = [...sections].sort((a, b) => a.order - b.order);
  const parchment = theme === "parchment";

  return (
    <div>
      {/* --------------------------------------------------- reading controls */}
      <div className="mb-6 flex items-center justify-end gap-2">
        <div
          className="flex items-center gap-0.5 rounded-full border border-white/10 bg-white/[0.04] p-1"
          role="group"
          aria-label="Text size"
        >
          <Type className="ml-2 mr-1 h-3.5 w-3.5 text-ink-500" aria-hidden />
          {(["sm", "md", "lg"] as const).map((s) => (
            <button
              key={s}
              onClick={() => setSize(s)}
              aria-pressed={size === s}
              className={cn(
                "rounded-full px-2.5 py-1 text-xs transition-colors",
                size === s
                  ? "bg-gold-300/20 text-gold-100"
                  : "text-ink-400 hover:text-ink-100",
              )}
            >
              <span
                aria-hidden
                className={
                  s === "sm" ? "text-[0.65rem]" : s === "md" ? "text-xs" : "text-sm"
                }
              >
                A
              </span>
              <span className="sr-only">
                {s === "sm" ? "Small text" : s === "md" ? "Medium text" : "Large text"}
              </span>
            </button>
          ))}
        </div>

        <button
          onClick={() => setTheme(parchment ? "night" : "parchment")}
          className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] px-3.5 py-2
                     text-xs text-ink-300 transition-all duration-300 hover:border-gold-300/35 hover:text-ink-50"
        >
          {parchment ? (
            <Moon className="h-3.5 w-3.5" aria-hidden />
          ) : (
            <Sun className="h-3.5 w-3.5" aria-hidden />
          )}
          {parchment ? "Night" : "Parchment"}
        </button>
      </div>

      {/* ----------------------------------------------------------- article */}
      <article
        className={cn(
          "relative overflow-hidden rounded-xl3 px-6 py-10 transition-colors duration-500 sm:px-12 sm:py-14",
          parchment
            ? "bg-[#f6f0e4] text-[#2c2417] shadow-[0_30px_80px_-40px_rgba(0,0,0,0.8)]"
            : "glass glass-gold",
        )}
      >
        {/* Decorative top rule */}
        <div
          aria-hidden
          className={cn(
            "absolute inset-x-0 top-0 h-px",
            parchment
              ? "bg-gradient-to-r from-transparent via-[#c9a227]/40 to-transparent"
              : "rule-glow",
          )}
        />

        <div className={cn("mx-auto max-w-[36rem]", SIZE_CLASS[size])}>
          {ordered.map((section) => (
            <Section
              key={section.key + section.order}
              section={section}
              parchment={parchment}
            />
          ))}
        </div>
      </article>
    </div>
  );
}

/* ------------------------------------------------------------------ section */

function Section({
  section,
  parchment,
}: {
  section: LessonSection;
  parchment: boolean;
}) {
  const body = section.body?.trim();
  if (!body) return null;

  const muted = parchment ? "text-[#7a6a4f]" : "text-ink-400";
  const strong = parchment ? "text-[#1f1a10]" : "text-ink-50";
  const accent = parchment ? "text-[#8a6d1f]" : "text-gold-200";

  switch (section.key) {
    case "series_title":
      return (
        <p
          className={cn(
            "text-center font-display text-[1.6em] font-light leading-tight",
            parchment ? "text-[#1f1a10]" : "text-gilded",
          )}
        >
          {body}
        </p>
      );

    case "lesson_number":
      return (
        <p
          className={cn(
            "mt-3 text-center text-[0.72em] font-medium uppercase tracking-[0.32em]",
            muted,
          )}
        >
          {body}
        </p>
      );

    case "hebrew_phrase":
      return (
        <p
          lang="he"
          dir="rtl"
          className={cn(
            "hebrew mt-9 text-center text-[1.5em] leading-[2.1]",
            parchment ? "text-[#6b5518]" : "text-gold-100",
          )}
        >
          {body}
        </p>
      );

    case "transliteration":
      return (
        <p className={cn("mt-4 text-center text-[0.98em] italic", accent)}>
          {body}
        </p>
      );

    case "translation":
      return (
        <p
          className={cn(
            "mt-3 text-center text-[0.98em] leading-relaxed",
            parchment ? "text-[#4a3f2c]" : "text-ink-200",
          )}
        >
          {body}
        </p>
      );

    case "signoff":
      return (
        <>
          <div
            aria-hidden
            className={cn(
              "mx-auto mt-12 h-px w-24",
              parchment
                ? "bg-[#c9a227]/40"
                : "bg-gradient-to-r from-transparent via-gold-300/45 to-transparent",
            )}
          />
          <div className={cn("mt-8 text-center font-display text-[1.1em]", strong)}>
            <Lines text={body} />
          </div>
        </>
      );

    case "closing_blessing":
      return (
        <div
          className={cn(
            "mt-10 rounded-2xl px-6 py-7",
            parchment
              ? "bg-[#efe6d2] ring-1 ring-[#c9a227]/25"
              : "bg-white/[0.04] ring-1 ring-inset ring-gold-300/18",
          )}
        >
          <div
            className={cn(
              "space-y-3 text-center leading-[1.85]",
              parchment ? "text-[#3b3222]" : "text-ink-100",
            )}
          >
            <Lines text={body} />
          </div>
        </div>
      );

    default:
      return (
        <div
          className={cn(
            "mt-8 space-y-[0.85em] leading-[1.85]",
            parchment ? "text-[#3b3222]" : "text-ink-200",
          )}
        >
          {section.title && (
            <h2
              className={cn(
                "!mt-10 font-display text-[1.25em] font-medium leading-snug",
                strong,
              )}
            >
              {section.title}
            </h2>
          )}
          <Lines text={body} />
        </div>
      );
  }
}

/**
 * Splits a body into visual lines, preserving the deliberate pacing.
 * A blank line in the source becomes a larger gap; a single newline becomes
 * a new line at normal spacing.
 */
function Lines({ text }: { text: string }) {
  const blocks = text.split(/\n\s*\n/);

  return (
    <>
      {blocks.map((block, bi) => (
        <div key={bi} className={bi > 0 ? "pt-[0.85em]" : undefined}>
          {block.split("\n").map((line, li) => {
            const trimmed = line.trim();
            if (!trimmed) return null;
            const rtl = hasHebrew(trimmed) && !/[A-Za-z]/.test(trimmed);
            return (
              <p
                key={li}
                dir={rtl ? "rtl" : "auto"}
                lang={rtl ? "he" : undefined}
                className={rtl ? "hebrew my-2 text-[1.1em]" : undefined}
              >
                {trimmed}
              </p>
            );
          })}
        </div>
      ))}
    </>
  );
}
