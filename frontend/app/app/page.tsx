import type { Metadata } from "next";
import { MessagesSquare, ArrowRight } from "lucide-react";

import { createClient } from "@/lib/supabase/server";
import { getProfile } from "@/lib/auth";
import { LessonLibrary } from "@/components/lesson/LessonLibrary";
import { ButtonLink } from "@/components/ui/Button";
import type { Lesson } from "@/types/database";

export const metadata: Metadata = { title: "Lessons" };

export default async function LearnerHome() {
  const profile = await getProfile();
  const supabase = await createClient();

  // RLS restricts this to published lessons with a published version — the
  // filter below is belt-and-braces, not the security boundary.
  const { data, error } = await supabase
    .from("lessons")
    .select(
      "id, title, lesson_number, sequence_position, hebrew_phrase, transliteration, translation, summary, status, published_at, updated_at",
    )
    .eq("status", "published")
    .order("lesson_number", { ascending: true, nullsFirst: false });

  const lessons = (data ?? []) as Lesson[];
  const firstName = profile?.full_name?.trim().split(/\s+/)[0];

  return (
    <div className="mx-auto max-w-6xl">
      {/* ------------------------------------------------------- header */}
      <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-[0.7rem] font-medium uppercase tracking-[0.3em] text-gold-300/75">
            Nishmat: A Journey of Praise
          </p>
          <h1 className="mt-2.5 font-display text-4xl font-light text-ink-50 sm:text-[2.75rem]">
            {firstName ? (
              <>
                Shalom, <span className="text-gilded">{firstName}</span>
              </>
            ) : (
              "The lessons"
            )}
          </h1>
          <p className="mt-2 max-w-lg text-[0.95rem] leading-relaxed text-ink-400">
            One word at a time, through the tefillah of Nishmat Kol Chai.
          </p>
        </div>

        <ButtonLink href="/app/chat" variant="outline" size="md">
          <MessagesSquare className="h-4 w-4" aria-hidden />
          Ask a question
          <ArrowRight className="h-3.5 w-3.5" aria-hidden />
        </ButtonLink>
      </div>

      {error ? (
        <div
          role="alert"
          className="mt-10 rounded-2xl border border-danger/25 bg-danger/[0.07] px-5 py-4 text-sm text-rose-300"
        >
          We couldn&rsquo;t load the lessons just now. Please refresh in a moment.
        </div>
      ) : (
        <LessonLibrary lessons={lessons} className="mt-10" />
      )}
    </div>
  );
}
