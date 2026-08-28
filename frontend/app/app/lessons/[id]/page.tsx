import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, MessagesSquare, ChevronLeft, ChevronRight } from "lucide-react";

import { createClient } from "@/lib/supabase/server";
import { LessonReader } from "@/components/lesson/LessonReader";
import { ButtonLink } from "@/components/ui/Button";
import type { LessonContent } from "@/types/database";

interface PageProps {
  params: Promise<{ id: string }>;
}

/** Shape returned by the lesson + published-version join. */
interface PublishedLesson {
  id: string;
  title: string;
  lesson_number: number | null;
  hebrew_phrase: string | null;
  published_version: { content: LessonContent } | null;
}

async function loadLesson(id: string) {
  const supabase = await createClient();

  // The embedded select follows `published_version_id`, so an unpublished
  // draft simply has nothing to return — a learner cannot reach it even by
  // guessing the lesson id.
  const { data } = await supabase
    .from("lessons")
    .select(
      `id, title, lesson_number, hebrew_phrase,
       published_version:lesson_versions!lessons_published_version_fk(content)`,
    )
    .eq("id", id)
    .eq("status", "published")
    .maybeSingle();

  return data as PublishedLesson | null;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { id } = await params;
  const lesson = await loadLesson(id);
  if (!lesson) return { title: "Lesson not found" };
  return {
    title:
      lesson.lesson_number != null
        ? `Lesson #${lesson.lesson_number} — ${lesson.title}`
        : lesson.title,
  };
}

export default async function LessonPage({ params }: PageProps) {
  const { id } = await params;
  const lesson = await loadLesson(id);

  if (!lesson || !lesson.published_version) notFound();

  const sections = lesson.published_version.content?.sections ?? [];

  // Neighbours for the "previous / next lesson" links. The series is
  // sequential, so this is genuinely useful navigation, not decoration.
  const supabase = await createClient();
  const [prev, next] = await Promise.all([
    lesson.lesson_number == null
      ? Promise.resolve({ data: null })
      : supabase
          .from("lessons")
          .select("id, lesson_number, title")
          .eq("status", "published")
          .lt("lesson_number", lesson.lesson_number)
          .order("lesson_number", { ascending: false })
          .limit(1)
          .maybeSingle(),
    lesson.lesson_number == null
      ? Promise.resolve({ data: null })
      : supabase
          .from("lessons")
          .select("id, lesson_number, title")
          .eq("status", "published")
          .gt("lesson_number", lesson.lesson_number)
          .order("lesson_number", { ascending: true })
          .limit(1)
          .maybeSingle(),
  ]);

  return (
    <div className="mx-auto max-w-3xl pb-16">
      <div className="mb-7 flex items-center justify-between gap-4">
        <Link
          href="/app"
          className="group inline-flex items-center gap-2 text-sm text-ink-400 transition-colors hover:text-ink-100"
        >
          <ArrowLeft
            className="h-4 w-4 transition-transform duration-300 group-hover:-translate-x-0.5"
            aria-hidden
          />
          All lessons
        </Link>

        <ButtonLink
          href={`/app/chat?lesson=${lesson.id}`}
          variant="outline"
          size="sm"
        >
          <MessagesSquare className="h-3.5 w-3.5" aria-hidden />
          Ask about this lesson
        </ButtonLink>
      </div>

      {sections.length === 0 ? (
        <p className="glass rounded-2xl px-6 py-12 text-center text-sm text-ink-400">
          This lesson has no content to display yet.
        </p>
      ) : (
        <LessonReader sections={sections} />
      )}

      {/* ------------------------------------------------- prev / next */}
      <nav
        className="mt-10 grid gap-3 sm:grid-cols-2"
        aria-label="Lesson navigation"
      >
        <NeighbourLink
          lesson={prev.data as NeighbourLesson | null}
          direction="prev"
        />
        <NeighbourLink
          lesson={next.data as NeighbourLesson | null}
          direction="next"
        />
      </nav>
    </div>
  );
}

interface NeighbourLesson {
  id: string;
  lesson_number: number | null;
  title: string;
}

function NeighbourLink({
  lesson,
  direction,
}: {
  lesson: NeighbourLesson | null;
  direction: "prev" | "next";
}) {
  if (!lesson) return <span aria-hidden />;
  const isPrev = direction === "prev";

  return (
    <Link
      href={`/app/lessons/${lesson.id}`}
      className={`glass group flex items-center gap-3 rounded-2xl px-5 py-4 transition-all duration-300
                  hover:-translate-y-0.5 hover:border-gold-300/30 ${isPrev ? "" : "sm:col-start-2 sm:text-right"}`}
    >
      {isPrev && (
        <ChevronLeft
          className="h-4 w-4 shrink-0 text-ink-500 transition-transform duration-300 group-hover:-translate-x-0.5"
          aria-hidden
        />
      )}
      <span className={`min-w-0 flex-1 ${isPrev ? "" : "sm:order-first"}`}>
        <span className="block text-[0.7rem] uppercase tracking-wider text-ink-500">
          {isPrev ? "Previous" : "Next"}
          {lesson.lesson_number != null && ` · #${lesson.lesson_number}`}
        </span>
        <span className="mt-0.5 block truncate text-sm text-ink-100">
          {lesson.title}
        </span>
      </span>
      {!isPrev && (
        <ChevronRight
          className="h-4 w-4 shrink-0 text-ink-500 transition-transform duration-300 group-hover:translate-x-0.5"
          aria-hidden
        />
      )}
    </Link>
  );
}
