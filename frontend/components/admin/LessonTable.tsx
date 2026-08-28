"use client";

import { useMemo, useState, useDeferredValue } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import { AlertTriangle, ArrowUpRight, Pencil, Search, X } from "lucide-react";

import { cn, formatDate } from "@/lib/utils";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { EmptyState } from "@/components/ui/EmptyState";
import type { LessonStatus } from "@/types/database";

export interface AdminLessonRow {
  id: string;
  title: string;
  lesson_number: number | null;
  hebrew_phrase: string | null;
  transliteration: string | null;
  status: LessonStatus;
  needs_review: boolean;
  review_notes: string | null;
  published_at: string | null;
  updated_at: string;
  has_unpublished_changes: boolean;
}

type Tab = "all" | "published" | "drafts" | "review" | "flagged";

const TABS: { key: Tab; label: string }[] = [
  { key: "all", label: "All" },
  { key: "published", label: "Published" },
  { key: "drafts", label: "Drafts" },
  { key: "review", label: "Awaiting publish" },
  { key: "flagged", label: "Needs review" },
];

const DRAFT_STATUSES = new Set(["draft", "generated", "processing", "failed"]);
const REVIEW_STATUSES = new Set(["review", "approved"]);

export function LessonTable({
  lessons,
  className,
}: {
  lessons: AdminLessonRow[];
  className?: string;
}) {
  const [tab, setTab] = useState<Tab>("all");
  const [query, setQuery] = useState("");
  const deferred = useDeferredValue(query);

  const counts = useMemo(
    () => ({
      all: lessons.length,
      published: lessons.filter((l) => l.status === "published").length,
      drafts: lessons.filter((l) => DRAFT_STATUSES.has(l.status)).length,
      review: lessons.filter((l) => REVIEW_STATUSES.has(l.status)).length,
      flagged: lessons.filter((l) => l.needs_review).length,
    }),
    [lessons],
  );

  const visible = useMemo(() => {
    const needle = deferred.trim().toLowerCase();

    return lessons.filter((lesson) => {
      const matchesTab =
        tab === "all" ||
        (tab === "published" && lesson.status === "published") ||
        (tab === "drafts" && DRAFT_STATUSES.has(lesson.status)) ||
        (tab === "review" && REVIEW_STATUSES.has(lesson.status)) ||
        (tab === "flagged" && lesson.needs_review);

      if (!matchesTab) return false;
      if (!needle) return true;

      return [
        lesson.title,
        lesson.transliteration,
        lesson.hebrew_phrase,
        lesson.lesson_number != null ? `#${lesson.lesson_number}` : null,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(needle);
    });
  }, [lessons, tab, deferred]);

  return (
    <div className={className}>
      {/* ------------------------------------------------------- controls */}
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div
          className="flex flex-wrap gap-1.5"
          role="tablist"
          aria-label="Filter lessons"
        >
          {TABS.map((entry) => {
            const active = tab === entry.key;
            const count = counts[entry.key];
            return (
              <button
                key={entry.key}
                role="tab"
                aria-selected={active}
                onClick={() => setTab(entry.key)}
                className={cn(
                  "relative rounded-full px-3.5 py-1.5 text-sm transition-colors",
                  active ? "text-night-950" : "text-ink-300 hover:text-ink-50",
                )}
              >
                {active && (
                  <motion.span
                    layoutId="lesson-tab"
                    className="absolute inset-0 rounded-full bg-gradient-to-r from-gold-200 to-gold-300"
                    transition={{ type: "spring", stiffness: 380, damping: 32 }}
                  />
                )}
                <span className="relative z-10">
                  {entry.label}
                  <span
                    className={cn(
                      "ml-1.5 text-xs",
                      active ? "text-night-950/60" : "text-ink-500",
                    )}
                  >
                    {count}
                  </span>
                </span>
              </button>
            );
          })}
        </div>

        <label className="relative block w-full lg:max-w-xs">
          <span className="sr-only">Search lessons</span>
          <Search
            className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-500"
            aria-hidden
          />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search by word or number…"
            className="h-10 w-full rounded-full border border-white/10 bg-white/[0.04] pl-10 pr-9
                       text-sm text-ink-50 outline-none transition-all duration-300
                       placeholder:text-ink-500/80 focus:border-gold-300/45 focus:bg-white/[0.06]"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery("")}
              className="absolute right-3 top-1/2 -translate-y-1/2 rounded-full p-1 text-ink-500 hover:text-ink-200"
              aria-label="Clear search"
            >
              <X className="h-3.5 w-3.5" aria-hidden />
            </button>
          )}
        </label>
      </div>

      {/* ---------------------------------------------------------- list */}
      {visible.length === 0 ? (
        <EmptyState
          className="mt-8"
          icon={Search}
          title="Nothing here"
          description={
            query
              ? `No lesson matches “${query.trim()}”.`
              : "No lessons in this view yet."
          }
        />
      ) : (
        <>
          <p className="mt-5 text-sm text-ink-500" aria-live="polite">
            Showing {visible.length} of {lessons.length}
          </p>

          <ul className="mt-3 divide-y divide-white/[0.06] overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.02]">
            {visible.map((lesson) => (
              <li key={lesson.id}>
                <Link
                  href={`/admin/lessons/${lesson.id}`}
                  className="group flex items-center gap-4 px-4 py-3.5 transition-colors hover:bg-white/[0.04] sm:px-5"
                >
                  <span className="grid h-10 w-12 shrink-0 place-items-center rounded-xl bg-white/[0.05] font-display text-sm text-gold-200">
                    {lesson.lesson_number != null ? `#${lesson.lesson_number}` : "—"}
                  </span>

                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <span className="truncate text-[0.95rem] text-ink-50">
                        {lesson.title}
                      </span>
                      {lesson.needs_review && (
                        <span
                          className="inline-flex items-center gap-1 rounded-full bg-warning/12 px-2 py-0.5 text-[0.65rem] text-amber-200 ring-1 ring-inset ring-amber-400/25"
                          title={lesson.review_notes ?? undefined}
                        >
                          <AlertTriangle className="h-2.5 w-2.5" aria-hidden />
                          Review
                        </span>
                      )}
                      {lesson.has_unpublished_changes && (
                        <span className="inline-flex items-center gap-1 rounded-full bg-violet-500/15 px-2 py-0.5 text-[0.65rem] text-violet-200 ring-1 ring-inset ring-violet-400/25">
                          <Pencil className="h-2.5 w-2.5" aria-hidden />
                          Unpublished edits
                        </span>
                      )}
                    </span>

                    <span className="mt-1 flex items-center gap-3 text-xs text-ink-500">
                      {lesson.hebrew_phrase && (
                        <span
                          lang="he"
                          dir="rtl"
                          className="heb-inline truncate text-gold-200/50"
                        >
                          {lesson.hebrew_phrase}
                        </span>
                      )}
                      <span className="shrink-0">
                        Updated {formatDate(lesson.updated_at)}
                      </span>
                    </span>
                  </span>

                  <StatusBadge status={lesson.status} className="hidden sm:inline-flex" />
                  <ArrowUpRight
                    className="h-4 w-4 shrink-0 text-ink-500 opacity-0 transition-opacity group-hover:opacity-100"
                    aria-hidden
                  />
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
