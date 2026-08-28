"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  CloudOff,
  Eye,
  History,
  Loader2,
  Plus,
  Save,
  Send,
  Sparkles,
  Undo2,
  Wand2,
} from "lucide-react";

import {
  api,
  ApiError,
  pollJob,
  type GenerationBrief,
  type JobStatus,
  type LessonDetail,
  type LessonSection,
  type VersionSummary,
} from "@/lib/api";
import { cn, formatDate } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { SectionEditor } from "@/components/admin/SectionEditor";
import { AiReviseDialog } from "@/components/admin/AiReviseDialog";
import { LessonBriefPanel } from "@/components/admin/LessonBriefPanel";
import { LessonReader } from "@/components/lesson/LessonReader";
import type { LessonStatus } from "@/types/database";

type Notice = { kind: "ok" | "error"; message: string } | null;

export function LessonEditor({
  lesson: initialLesson,
  versions: initialVersions,
}: {
  lesson: LessonDetail;
  versions: VersionSummary[];
}) {
  const router = useRouter();

  const [lesson, setLesson] = useState(initialLesson);
  const [versions, setVersions] = useState(initialVersions);
  const [sections, setSections] = useState<LessonSection[]>(
    () => initialLesson.current_version?.content.sections ?? [],
  );
  const [baseline, setBaseline] = useState(() =>
    JSON.stringify(initialLesson.current_version?.content.sections ?? []),
  );

  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [preview, setPreview] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [genStage, setGenStage] = useState<string | null>(null);
  const [brief, setBrief] = useState<GenerationBrief>(
    () => initialLesson.generation_brief ?? {},
  );
  const [revise, setRevise] = useState<{
    scope: "section" | "lesson";
    sectionKey?: string;
    sectionLabel?: string;
    selectedText?: string;
  } | null>(null);
  const [notice, setNotice] = useState<Notice>(null);

  const dirty = useMemo(
    () => JSON.stringify(sections) !== baseline,
    [sections, baseline],
  );

  // A half-finished lesson edit is real work — warn before it is discarded.
  useEffect(() => {
    if (!dirty) return;
    const handler = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), 6000);
    return () => clearTimeout(timer);
  }, [notice]);

  const updateSection = useCallback((index: number, next: LessonSection) => {
    setSections((current) =>
      current.map((section, i) => (i === index ? next : section)),
    );
  }, []);

  const removeSection = useCallback((index: number) => {
    setSections((current) =>
      current
        .filter((_, i) => i !== index)
        .map((section, i) => ({ ...section, order: i + 1 })),
    );
  }, []);

  const addSection = useCallback(() => {
    setSections((current) => [
      ...current,
      {
        key: `body_${current.filter((s) => s.key.startsWith("body_")).length + 1}`,
        title: null,
        body: "",
        dir: "ltr",
        order: current.length + 1,
      },
    ]);
  }, []);

  /**
   * Accept an AI revision into the editor.
   *
   * Deliberately does NOT save. The revision becomes an unsaved change like
   * any hand edit, so the admin still reads it in context and presses Save —
   * an AI suggestion never writes itself into the history.
   */
  const acceptSectionRevision = useCallback((key: string, body: string) => {
    setSections((current) =>
      current.map((section) =>
        section.key === key ? { ...section, body } : section,
      ),
    );
    setNotice({
      kind: "ok",
      message: "Revision applied. Read it through, then Save version to keep it.",
    });
  }, []);

  const acceptLessonRevision = useCallback(
    (revised: { key: string; title: string | null; body: string; dir: string }[] | null) => {
      if (!revised?.length) return;
      setSections(
        revised.map((section, index) => ({
          key: section.key,
          title: section.title,
          body: section.body,
          dir: (section.dir === "rtl" ? "rtl" : "ltr") as "ltr" | "rtl",
          order: index + 1,
        })),
      );
      setNotice({
        kind: "ok",
        message: "Whole lesson revised. Read it through, then Save version to keep it.",
      });
    },
    [],
  );

  async function handleSave() {
    setSaving(true);
    setNotice(null);
    try {
      const version = await api.lessons.saveVersion(lesson.id, {
        sections: sections.map((section, i) => ({ ...section, order: i + 1 })),
      });

      setBaseline(JSON.stringify(sections));
      setLesson((current) => ({
        ...current,
        current_version_id: version.id,
        current_version: version,
        status: current.status === "published" ? current.status : ("review" as LessonStatus),
      }));
      setVersions(await api.lessons.versions(lesson.id));
      setNotice({
        kind: "ok",
        message: `Saved as version ${version.version_number}. Learners still see the published version.`,
      });
      router.refresh();
    } catch (error) {
      setNotice({ kind: "error", message: messageFor(error) });
    } finally {
      setSaving(false);
    }
  }

  async function handlePublish() {
    if (dirty) {
      setNotice({
        kind: "error",
        message: "Save your changes first — publishing sends the last saved version.",
      });
      return;
    }
    if (!lesson.current_version_id) return;

    setPublishing(true);
    setNotice(null);
    try {
      const updated = await api.lessons.publish(lesson.id, lesson.current_version_id);
      setLesson((current) => ({
        ...current,
        status: updated.status as LessonStatus,
        published_version_id: current.current_version_id,
        published_at: updated.published_at,
      }));
      setVersions(await api.lessons.versions(lesson.id));
      setNotice({ kind: "ok", message: "Published. This is now live for learners." });
      router.refresh();
    } catch (error) {
      setNotice({ kind: "error", message: messageFor(error) });
    } finally {
      setPublishing(false);
    }
  }

  async function handleUnpublish() {
    setPublishing(true);
    setNotice(null);
    try {
      const updated = await api.lessons.unpublish(lesson.id);
      setLesson((current) => ({
        ...current,
        status: updated.status as LessonStatus,
        published_version_id: null,
        published_at: null,
      }));
      setNotice({
        kind: "ok",
        message: "Withdrawn. It is no longer visible to learners, or to the chatbot.",
      });
      router.refresh();
    } catch (error) {
      setNotice({ kind: "error", message: messageFor(error) });
    } finally {
      setPublishing(false);
    }
  }

  async function handleGenerate() {
    if (dirty && !confirm("You have unsaved edits. Generating creates a new version — continue?")) {
      return;
    }

    setGenerating(true);
    setGenStage("Starting");
    setNotice(null);

    try {
      const { job_id } = await api.lessons.generate(lesson.id, undefined, brief);

      const job = await pollJob(
        job_id,
        (progress: JobStatus) => setGenStage(progress.progress_stage ?? "Working"),
        { intervalMs: 2000, timeoutMs: 420_000 },
      );

      if (job.status !== "succeeded") {
        setNotice({
          kind: "error",
          message: job.error ?? "The draft couldn't be generated.",
        });
        return;
      }

      // Reload rather than patching state — generation rewrites the lesson's
      // Hebrew, transliteration and review notes as well as its content.
      const [fresh, freshVersions] = await Promise.all([
        api.lessons.get(lesson.id),
        api.lessons.versions(lesson.id),
      ]);

      setLesson(fresh);
      setVersions(freshVersions);
      const next = fresh.current_version?.content.sections ?? [];
      setSections(next);
      setBaseline(JSON.stringify(next));

      const verdict = job.result?.verdict as string | undefined;
      const cost = job.result?.cost_usd as number | undefined;
      const sources = job.result?.sources as string | undefined;
      setNotice({
        kind: verdict === "FAIL" ? "error" : "ok",
        message:
          verdict === "PASS"
            ? `Draft ready — ${job.result?.word_count} words.`
              + (sources ? ` Written from ${sources}.` : "")
              + " Read it through before publishing."
            : `Draft ready, but the check flagged ${job.result?.issues} thing(s) to look at.`
            + (sources ? ` Written from ${sources}.` : "")
            + (cost ? ` Cost $${cost.toFixed(3)}.` : ""),
      });
      router.refresh();
    } catch (error) {
      setNotice({ kind: "error", message: messageFor(error) });
    } finally {
      setGenerating(false);
      setGenStage(null);
    }
  }

  async function handleRestore(versionId: string) {
    setSaving(true);
    try {
      const version = await api.lessons.restoreVersion(lesson.id, versionId);
      setSections(version.content.sections);
      setBaseline(JSON.stringify(version.content.sections));
      setLesson((current) => ({
        ...current,
        current_version_id: version.id,
        current_version: version,
      }));
      setVersions(await api.lessons.versions(lesson.id));
      setNotice({
        kind: "ok",
        message: `Restored as version ${version.version_number}. Nothing was overwritten.`,
      });
      router.refresh();
    } catch (error) {
      setNotice({ kind: "error", message: messageFor(error) });
    } finally {
      setSaving(false);
    }
  }

  const isPublished = lesson.status === "published";
  const hasUnpublishedEdits =
    Boolean(lesson.published_version_id) &&
    lesson.current_version_id !== lesson.published_version_id;

  return (
    <div className="mx-auto max-w-6xl pb-20">
      {/* ---------------------------------------------------------- header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <Link
            href="/admin/lessons"
            className="group inline-flex items-center gap-2 text-sm text-ink-400 transition-colors hover:text-ink-100"
          >
            <ArrowLeft
              className="h-4 w-4 transition-transform group-hover:-translate-x-0.5"
              aria-hidden
            />
            All lessons
          </Link>

          <h1 className="mt-3 flex flex-wrap items-center gap-3 font-display text-3xl font-light text-ink-50">
            {lesson.lesson_number != null && (
              <span className="text-gold-200">#{lesson.lesson_number}</span>
            )}
            <span className="min-w-0 truncate">{lesson.title}</span>
          </h1>

          <div className="mt-2.5 flex flex-wrap items-center gap-2.5 text-xs text-ink-500">
            <StatusBadge status={lesson.status} />
            {lesson.current_version && (
              <span>Editing v{lesson.current_version.version_number}</span>
            )}
            {isPublished && lesson.published_at && (
              <span>· Published {formatDate(lesson.published_at)}</span>
            )}
            {dirty && (
              <span className="inline-flex items-center gap-1 text-amber-300">
                <CloudOff className="h-3 w-3" aria-hidden />
                Unsaved changes
              </span>
            )}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setPreview((p) => !p)}
            aria-pressed={preview}
          >
            <Eye className="h-4 w-4" aria-hidden />
            {preview ? "Edit" : "Preview"}
          </Button>

          {sections.length > 0 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setRevise({ scope: "lesson" })}
              disabled={generating || saving}
            >
              <Wand2 className="h-4 w-4" aria-hidden />
              Revise all
            </Button>
          )}

          <Button
            variant="secondary"
            size="sm"
            onClick={handleGenerate}
            loading={generating}
            disabled={generating || saving}
          >
            <Sparkles className="h-4 w-4" aria-hidden />
            {generating ? (genStage ?? "Generating") : sections.length ? "Regenerate" : "Generate draft"}
          </Button>

          <Button
            variant="outline"
            size="sm"
            onClick={handleSave}
            loading={saving}
            disabled={!dirty || preview}
          >
            <Save className="h-4 w-4" aria-hidden />
            Save version
          </Button>

          {isPublished ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={handleUnpublish}
              loading={publishing}
            >
              Withdraw
            </Button>
          ) : null}

          <Button
            size="sm"
            onClick={handlePublish}
            loading={publishing}
            disabled={dirty || !lesson.current_version_id}
          >
            <Send className="h-4 w-4" aria-hidden />
            {isPublished ? "Publish update" : "Publish"}
          </Button>
        </div>
      </div>

      {/* ---------------------------------------------------------- notices */}
      {notice && (
        <div
          role={notice.kind === "error" ? "alert" : "status"}
          className={cn(
            "mt-5 flex items-start gap-2.5 rounded-xl px-4 py-3 text-sm",
            notice.kind === "error"
              ? "border border-danger/25 bg-danger/[0.08] text-rose-200"
              : "border border-success/25 bg-success/[0.08] text-green-200",
          )}
        >
          {notice.kind === "error" ? (
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          ) : (
            <Check className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          )}
          {notice.message}
        </div>
      )}

      {hasUnpublishedEdits && !notice && (
        <div className="mt-5 flex items-start gap-2.5 rounded-xl border border-violet-400/25 bg-violet-500/[0.08] px-4 py-3 text-sm text-violet-100">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          You have saved edits that are not published yet. Learners still see the
          published version until you press Publish update.
        </div>
      )}

      {lesson.needs_review && lesson.review_notes && (
        <div className="mt-5 rounded-xl border border-amber-400/25 bg-warning/[0.07] px-4 py-3 text-sm text-amber-100">
          <p className="flex items-center gap-2 font-medium">
            <AlertTriangle className="h-4 w-4" aria-hidden />
            Flagged during import
          </p>
          <ul className="mt-2 space-y-1 pl-6 text-amber-100/80">
            {lesson.review_notes.split("\n").filter(Boolean).map((note, i) => (
              <li key={i} className="list-disc text-[0.82rem]">
                {note}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* --------------------------------------------- brief and references */}
      <div className="mt-6">
        <LessonBriefPanel
          lessonId={lesson.id}
          brief={brief}
          onBriefChange={setBrief}
          disabled={generating}
        />
      </div>

      {/* ------------------------------------------------------------ body */}
      <div className="mt-7 grid gap-6 lg:grid-cols-[1fr_18rem]">
        <div>
          {preview ? (
            <LessonReader sections={sections} />
          ) : (
            <>
              <div className="space-y-3">
                {sections.map((section, index) => (
                  <SectionEditor
                    key={`${section.key}-${index}`}
                    section={section}
                    disabled={saving}
                    onChange={(next) => updateSection(index, next)}
                    onRemove={
                      sections.length > 1 ? () => removeSection(index) : undefined
                    }
                    onAskAi={(selectedText) =>
                      setRevise({
                        scope: "section",
                        sectionKey: section.key,
                        sectionLabel: section.title ?? section.key.replace(/_/g, " "),
                        selectedText,
                      })
                    }
                  />
                ))}
              </div>

              <button
                type="button"
                onClick={addSection}
                className="mt-4 flex w-full items-center justify-center gap-2 rounded-2xl border border-dashed
                           border-white/12 py-3.5 text-sm text-ink-400 transition-colors
                           hover:border-gold-300/35 hover:text-ink-100"
              >
                <Plus className="h-4 w-4" aria-hidden />
                Add a section
              </button>
            </>
          )}
        </div>

        <VersionHistory
          versions={versions}
          onRestore={handleRestore}
          busy={saving || publishing}
        />
      </div>

      <AiReviseDialog
        open={Boolean(revise)}
        onClose={() => setRevise(null)}
        lessonId={lesson.id}
        scope={revise?.scope ?? "section"}
        sectionKey={revise?.sectionKey}
        sectionLabel={revise?.sectionLabel}
        selectedText={revise?.selectedText}
        onAcceptSection={acceptSectionRevision}
        onAcceptLesson={acceptLessonRevision}
      />
    </div>
  );
}

/* --------------------------------------------------------------- history */

function VersionHistory({
  versions,
  onRestore,
  busy,
}: {
  versions: VersionSummary[];
  onRestore: (versionId: string) => void;
  busy: boolean;
}) {
  const ORIGIN_LABELS: Record<string, string> = {
    ai_generated: "AI draft",
    ai_modified: "AI revision",
    manual_edit: "Manual edit",
    imported: "Imported",
  };

  return (
    <aside className="lg:sticky lg:top-24 lg:self-start">
      <h2 className="flex items-center gap-2 text-sm font-medium text-ink-200">
        <History className="h-4 w-4 text-ink-400" aria-hidden />
        Version history
      </h2>

      <ul className="mt-3 space-y-1.5">
        {versions.map((version) => (
          <li
            key={version.id}
            className={cn(
              "rounded-xl border px-3.5 py-3 text-sm transition-colors",
              version.is_current
                ? "border-gold-300/30 bg-gold-300/[0.07]"
                : "border-white/[0.07] bg-white/[0.02]",
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium text-ink-100">
                v{version.version_number}
              </span>
              <span className="flex items-center gap-1.5">
                {version.is_published && (
                  <span className="rounded-full bg-gold-300/15 px-2 py-0.5 text-[0.6rem] font-medium uppercase tracking-wide text-gold-200">
                    Live
                  </span>
                )}
                {version.is_current && !version.is_published && (
                  <span className="rounded-full bg-violet-500/15 px-2 py-0.5 text-[0.6rem] font-medium uppercase tracking-wide text-violet-200">
                    Editing
                  </span>
                )}
              </span>
            </div>

            <p className="mt-1 text-xs text-ink-500">
              {ORIGIN_LABELS[version.origin] ?? version.origin} ·{" "}
              {version.word_count} words
            </p>
            <p className="text-xs text-ink-500">{formatDate(version.created_at)}</p>

            {version.modification_instruction && (
              <p className="mt-1.5 line-clamp-2 text-xs italic text-ink-400">
                “{version.modification_instruction}”
              </p>
            )}

            {!version.is_current && (
              <button
                type="button"
                onClick={() => onRestore(version.id)}
                disabled={busy}
                className="mt-2 inline-flex items-center gap-1.5 text-xs text-gold-200
                           transition-colors hover:text-gold-100 disabled:opacity-40"
              >
                {busy ? (
                  <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
                ) : (
                  <Undo2 className="h-3 w-3" aria-hidden />
                )}
                Restore this version
              </button>
            )}
          </li>
        ))}
      </ul>

      <p className="mt-4 text-xs leading-relaxed text-ink-500">
        Restoring creates a new version. Nothing is ever overwritten.
      </p>
    </aside>
  );
}

function messageFor(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "Something went wrong. Please try again.";
}
