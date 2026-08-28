import type { Metadata } from "next";
import { FilePlus2 } from "lucide-react";

import { createClient } from "@/lib/supabase/server";
import { LessonTable, type AdminLessonRow } from "@/components/admin/LessonTable";
import type { AdminLessonListRow } from "@/types/database";
import { ButtonLink } from "@/components/ui/Button";

export const metadata: Metadata = { title: "All lessons" };

export default async function AdminLessonsPage() {
  const supabase = await createClient();

  // Read directly under RLS: the admin policy grants full access, and this
  // saves a hop for a page that only displays data. Every *mutation* on this
  // page still goes through the backend, where require_admin lives.
  const { data, error } = await supabase
    .from("lessons")
    .select(
      "id, title, lesson_number, hebrew_phrase, transliteration, status, " +
        "needs_review, review_notes, published_at, updated_at, " +
        "current_version_id, published_version_id",
    )
    .is("deleted_at", null)
    .order("lesson_number", { ascending: true, nullsFirst: false })
    .limit(500)
    .returns<AdminLessonListRow[]>();

  const lessons: AdminLessonRow[] = (data ?? []).map((lesson) => ({
    id: lesson.id,
    title: lesson.title,
    lesson_number: lesson.lesson_number,
    hebrew_phrase: lesson.hebrew_phrase,
    transliteration: lesson.transliteration,
    status: lesson.status,
    needs_review: lesson.needs_review,
    review_notes: lesson.review_notes,
    published_at: lesson.published_at,
    updated_at: lesson.updated_at,
    has_unpublished_changes: Boolean(
      lesson.published_version_id &&
        lesson.current_version_id &&
        lesson.current_version_id !== lesson.published_version_id,
    ),
  }));

  return (
    <div className="mx-auto max-w-6xl">
      <div className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-[0.7rem] font-medium uppercase tracking-[0.3em] text-gold-300/75">
            Lessons
          </p>
          <h1 className="mt-2.5 font-display text-4xl font-light text-ink-50">
            The whole series
          </h1>
          <p className="mt-2 text-[0.95rem] text-ink-400">
            {lessons.length} lesson{lessons.length === 1 ? "" : "s"}, in order.
          </p>
        </div>

        <ButtonLink href="/admin/lessons/new" size="md">
          <FilePlus2 className="h-4 w-4" aria-hidden />
          Create lesson
        </ButtonLink>
      </div>

      {error ? (
        <div
          role="alert"
          className="mt-10 rounded-2xl border border-danger/25 bg-danger/[0.07] px-5 py-4 text-sm text-rose-300"
        >
          We couldn&rsquo;t load the lessons. Please refresh in a moment.
        </div>
      ) : (
        <LessonTable lessons={lessons} className="mt-9" />
      )}
    </div>
  );
}
