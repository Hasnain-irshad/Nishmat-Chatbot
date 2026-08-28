import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { createClient } from "@/lib/supabase/server";
import { LessonComposer } from "@/components/admin/LessonComposer";

export const metadata: Metadata = { title: "Create lesson" };

/**
 * The lesson composer page.
 *
 * Nothing is asked for up front — no title, no lesson number. Attach the
 * recording and press send; the backend derives both from the source and they
 * stay editable in the editor.
 */
export default async function NewLessonPage() {
  const supabase = await createClient();

  // Shown as a hint so the admin knows where this will land in the series.
  const { data } = await supabase
    .from("lessons")
    .select("lesson_number")
    .is("deleted_at", null)
    .not("lesson_number", "is", null)
    .order("lesson_number", { ascending: false })
    .limit(1)
    .returns<{ lesson_number: number }[]>();

  const nextNumber = data?.[0]?.lesson_number ? data[0].lesson_number + 1 : 1;

  return (
    <div className="mx-auto flex min-h-[calc(100svh-9rem)] max-w-2xl flex-col">
      <Link
        href="/admin/lessons"
        className="group inline-flex items-center gap-2 self-start text-sm text-ink-400 transition-colors hover:text-ink-100"
      >
        <ArrowLeft
          className="h-4 w-4 transition-transform group-hover:-translate-x-0.5"
          aria-hidden
        />
        All lessons
      </Link>

      <div className="flex flex-1 flex-col justify-center py-10">
        <div className="mb-8 text-center">
          <h1 className="font-display text-4xl font-light text-ink-50 sm:text-[2.6rem]">
            What are we <span className="text-gilded">learning</span> this week?
          </h1>
          <p className="mx-auto mt-3 max-w-md text-[0.95rem] leading-relaxed text-ink-400">
            Attach the recording, the document, or a photo of the page — or just
            start typing.
          </p>
        </div>

        <LessonComposer nextNumber={nextNumber} />
      </div>
    </div>
  );
}
