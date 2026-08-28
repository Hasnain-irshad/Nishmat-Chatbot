import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { createClient } from "@/lib/supabase/server";
import { LessonEditor } from "@/components/admin/LessonEditor";
import type { LessonDetail, LessonVersionDetail, VersionSummary } from "@/lib/api";
import type {
  AdminLessonRowFull,
  LessonVersionListRow,
  LessonVersionRow,
} from "@/types/database";

interface PageProps {
  params: Promise<{ id: string }>;
}

/**
 * Reads go straight to Supabase under the admin RLS policy — the same pattern
 * as the lesson list. Every mutation the editor performs goes through the
 * FastAPI backend, where `require_admin` and the versioning rules live.
 */
async function loadLesson(id: string) {
  const supabase = await createClient();

  const { data: lesson } = await supabase
    .from("lessons")
    .select(
      "id, series_id, template_id, title, lesson_number, hebrew_phrase, " +
        "transliteration, translation, summary, status, needs_review, " +
        "review_notes, current_version_id, published_version_id, " +
        "published_at, created_at, updated_at, generation_brief",
    )
    .eq("id", id)
    .is("deleted_at", null)
    .returns<AdminLessonRowFull[]>()
    .maybeSingle();

  if (!lesson) return null;

  const [currentVersion, allVersions] = await Promise.all([
    lesson.current_version_id
      ? supabase
          .from("lesson_versions")
          .select(
            "id, version_number, content, content_text, word_count, origin, " +
              "modification_instruction, quality_report, model_metadata, " +
              "created_at",
          )
          .eq("id", lesson.current_version_id)
          .returns<LessonVersionRow[]>()
          .maybeSingle()
      : Promise.resolve({ data: null }),
    supabase
      .from("lesson_versions")
      .select(
        "id, version_number, origin, modification_instruction, word_count, " +
          "created_at, created_by",
      )
      .eq("lesson_id", id)
      .order("version_number", { ascending: false })
      .returns<LessonVersionListRow[]>(),
  ]);

  const versions: VersionSummary[] = (allVersions.data ?? []).map((version) => ({
    ...version,
    is_published: version.id === lesson.published_version_id,
    is_current: version.id === lesson.current_version_id,
  }));

  const detail: LessonDetail = {
    ...lesson,
    has_unpublished_changes: Boolean(
      lesson.published_version_id &&
        lesson.current_version_id &&
        lesson.current_version_id !== lesson.published_version_id,
    ),
    current_version: (currentVersion.data as LessonVersionDetail | null) ?? null,
    generation_brief: lesson.generation_brief ?? null,
  };

  return { detail, versions };
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { id } = await params;
  const loaded = await loadLesson(id);
  if (!loaded) return { title: "Lesson not found" };

  const { detail } = loaded;
  return {
    title:
      detail.lesson_number != null
        ? `#${detail.lesson_number} ${detail.title}`
        : detail.title,
  };
}

export default async function AdminLessonPage({ params }: PageProps) {
  const { id } = await params;
  const loaded = await loadLesson(id);

  if (!loaded) notFound();

  return <LessonEditor lesson={loaded.detail} versions={loaded.versions} />;
}
