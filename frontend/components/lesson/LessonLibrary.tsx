"use client";

import { useMemo, useState, useDeferredValue } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import { BookOpen, Search, X, ArrowUpRight } from "lucide-react";

import { cn } from "@/lib/utils";
import { EmptyState } from "@/components/ui/EmptyState";
import type { Lesson } from "@/types/database";

/**
 * The lesson grid with client-side search.
 *
 * The whole series is a few hundred rows of short metadata, so filtering in
 * the browser is instant and avoids a round-trip per keystroke. If the corpus
 * ever grows past a few thousand lessons this should move to a server query.
 */
export function LessonLibrary({
  lessons,
  className,
}: {
  lessons: Lesson[];
  className?: string;
}) {
  const [query, setQuery] = useState("");
  const deferred = useDeferredValue(query);

  const filtered = useMemo(() => {
    const q = deferred.trim().toLowerCase();
    if (!q) return lessons;
    return lessons.filter((l) =>
      [
        l.title,
        l.hebrew_phrase,
        l.transliteration,
        l.translation,
        l.summary,
        l.lesson_number != null ? `lesson ${l.lesson_number} #${l.lesson_number}` : null,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(q),
    );
  }, [lessons, deferred]);

  if (lessons.length === 0) {
    return (
      <EmptyState
        className={className}
        icon={BookOpen}
        title="No lessons yet"
        description="The first lessons will appear here as soon as they are published."
      />
    );
  }

  return (
    <div className={className}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <label className="relative block w-full sm:max-w-sm">
          <span className="sr-only">Search lessons</span>
          <Search
            className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-500"
            aria-hidden
          />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by word, phrase or number…"
            className="h-11 w-full rounded-full border border-white/10 bg-white/[0.04] pl-10 pr-10
                       text-sm text-ink-50 outline-none transition-all duration-300
                       placeholder:text-ink-500/80
                       focus:border-gold-300/45 focus:bg-white/[0.06]
                       focus:shadow-[0_0_0_4px_rgba(237,201,106,0.08)]"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery("")}
              className="absolute right-3 top-1/2 -translate-y-1/2 rounded-full p-1 text-ink-500 transition-colors hover:text-ink-200"
              aria-label="Clear search"
            >
              <X className="h-3.5 w-3.5" aria-hidden />
            </button>
          )}
        </label>

        <p className="text-sm text-ink-500" aria-live="polite">
          {filtered.length === lessons.length
            ? `${lessons.length} lessons`
            : `${filtered.length} of ${lessons.length}`}
        </p>
      </div>

      {filtered.length === 0 ? (
        <EmptyState
          className="mt-8"
          icon={Search}
          title="Nothing matched"
          description={`No lesson mentions “${deferred.trim()}”. Try a different word, or ask the question directly in the chat.`}
        />
      ) : (
        <ul className="mt-7 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {filtered.map((lesson, i) => (
            <motion.li
              key={lesson.id}
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{
                // Stagger only the first screenful — beyond that it just
                // delays content the person is already scrolling toward.
                delay: Math.min(i, 11) * 0.035,
                duration: 0.45,
                ease: [0.16, 1, 0.3, 1],
              }}
            >
              <LessonCard lesson={lesson} />
            </motion.li>
          ))}
        </ul>
      )}
    </div>
  );
}

function LessonCard({ lesson }: { lesson: Lesson }) {
  return (
    <Link
      href={`/app/lessons/${lesson.id}`}
      className={cn(
        "glass group relative flex h-full flex-col overflow-hidden rounded-2xl p-5",
        "transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]",
        "hover:-translate-y-1 hover:border-gold-300/30",
        "hover:shadow-[0_22px_54px_-26px_rgba(237,201,106,0.45)]",
      )}
    >
      {/* Hover wash */}
      <span
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-500 group-hover:opacity-100"
        style={{
          background:
            "radial-gradient(120% 90% at 50% 0%, rgba(237,201,106,0.11), transparent 62%)",
        }}
      />

      <div className="relative flex items-start justify-between gap-3">
        {lesson.lesson_number != null ? (
          <span className="inline-flex items-baseline gap-1 rounded-full bg-gold-300/12 px-2.5 py-1 text-[0.7rem] font-medium tracking-wide text-gold-200 ring-1 ring-inset ring-gold-300/25">
            Lesson
            <span className="font-display text-sm">#{lesson.lesson_number}</span>
          </span>
        ) : (
          <span className="rounded-full bg-white/[0.06] px-2.5 py-1 text-[0.7rem] text-ink-400">
            Introduction
          </span>
        )}

        <ArrowUpRight
          className="h-4 w-4 shrink-0 text-ink-500 transition-all duration-300 group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-gold-200"
          aria-hidden
        />
      </div>

      {lesson.hebrew_phrase && (
        <p
          lang="he"
          dir="rtl"
          className="hebrew relative mt-4 line-clamp-2 text-[1.15rem] leading-[1.9] text-gold-100/90"
        >
          {lesson.hebrew_phrase}
        </p>
      )}

      {lesson.transliteration && (
        <p className="relative mt-1.5 line-clamp-1 text-sm italic text-ink-300">
          {lesson.transliteration}
        </p>
      )}

      <h3 className="relative mt-3 font-display text-lg font-medium leading-snug text-ink-50">
        {lesson.title}
      </h3>

      {lesson.summary && (
        <p className="relative mt-2 line-clamp-3 text-sm leading-relaxed text-ink-400">
          {lesson.summary}
        </p>
      )}

      <span className="relative mt-auto pt-4 text-xs text-ink-500">
        {lesson.translation ? (
          <span className="line-clamp-1 italic">{lesson.translation}</span>
        ) : null}
      </span>
    </Link>
  );
}
