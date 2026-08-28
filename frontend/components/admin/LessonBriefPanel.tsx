"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  BookOpen,
  Check,
  ChevronDown,
  FileImage,
  Info,
  Loader2,
  Plus,
  Trash2,
} from "lucide-react";

import {
  api,
  ApiError,
  pollJob,
  type CorpusStatus,
  type GenerationBrief,
  type JobStatus,
  type ReferencePage,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/Button";

/**
 * What this lesson should teach, and what to teach it from.
 *
 * Two halves, and the split is deliberate.
 *
 * The BRIEF is how a lesson gets written without a recording: a phrase of the
 * prayer, a Hebrew word, a Psalm, a theme. Until now the only way to ask for a
 * lesson was to upload something for it to summarise, which is not how this
 * series is actually written.
 *
 * The PAGES are photographs of books the client owns on paper — ArtScroll,
 * Nishmas: Song of the Soul. They are read, attributed, used for this lesson,
 * and go no further: not into the permanent corpus, not to a learner. Which is
 * why they are attached here to one lesson rather than uploaded to a library.
 */

const BOOK_SUGGESTIONS = [
  "ArtScroll Tehillim — Rabbi Avrohom Chaim Feuer",
  "Nishmas: Song of the Soul — Rabbi Yisroel Besser",
];

type Notice = { kind: "ok" | "error"; message: string } | null;

interface Upload {
  localId: string;
  filename: string;
  stage: string;
  pct: number;
  error?: string;
}

export function LessonBriefPanel({
  lessonId,
  brief,
  onBriefChange,
  disabled = false,
}: {
  lessonId: string;
  brief: GenerationBrief;
  onBriefChange: (brief: GenerationBrief) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(() => hasContent(brief));
  const [pages, setPages] = useState<ReferencePage[]>([]);
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [corpus, setCorpus] = useState<CorpusStatus | null>(null);
  const [book, setBook] = useState("");
  const [page, setPage] = useState("");
  const [notice, setNotice] = useState<Notice>(null);
  const [loading, setLoading] = useState(true);

  const inputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await api.references.pages(lessonId);
      setPages(next);
    } catch {
      // A listing that fails is not worth an error banner over the editor —
      // the panel simply shows nothing attached, and the next action retries.
    } finally {
      setLoading(false);
    }
  }, [lessonId]);

  useEffect(() => {
    refresh();
    api.references.corpus().then(setCorpus).catch(() => setCorpus(null));
  }, [refresh]);

  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), 6000);
    return () => clearTimeout(timer);
  }, [notice]);

  function set<K extends keyof GenerationBrief>(key: K, value: GenerationBrief[K]) {
    onBriefChange({ ...brief, [key]: value });
  }

  const handleFiles = useCallback(
    async (files: FileList | File[]) => {
      setNotice(null);
      const label = book.trim();

      for (const file of Array.from(files)) {
        const localId = `${file.name}-${Math.random().toString(36).slice(2, 8)}`;
        setUploads((current) => [
          ...current,
          { localId, filename: file.name, stage: "Uploading", pct: 5 },
        ]);

        const patch = (changes: Partial<Upload>) =>
          setUploads((current) =>
            current.map((u) => (u.localId === localId ? { ...u, ...changes } : u)),
          );

        try {
          const uploaded = await api.files.upload(file, lessonId, {
            role: "reference",
            book: label || undefined,
            page: page.trim() || undefined,
          });

          if (uploaded.job_id) {
            patch({ stage: "Reading the page", pct: 20 });
            const job = await pollJob(
              uploaded.job_id,
              (progress: JobStatus) =>
                patch({
                  stage: progress.progress_stage ?? "Reading",
                  pct: Math.max(progress.progress_pct, 20),
                }),
              { intervalMs: 2000, timeoutMs: 300_000 },
            );

            if (job.status !== "succeeded") {
              patch({
                stage: "Failed",
                error: job.error ?? "We couldn't read that page.",
              });
              continue;
            }
          }

          setUploads((current) => current.filter((u) => u.localId !== localId));
          await refresh();
        } catch (err) {
          patch({
            stage: "Failed",
            error:
              err instanceof ApiError
                ? err.message
                : "Something went wrong uploading that page.",
          });
        }
      }

      // The page number belongs to the page just sent; the book usually
      // carries over to the next few, so only one of them is cleared.
      setPage("");
    },
    [book, page, lessonId, refresh],
  );

  async function handleRemove(sourceFileId: string) {
    try {
      await api.references.removePage(lessonId, sourceFileId);
      setPages((current) =>
        current.filter((p) => p.source_file_id !== sourceFileId),
      );
      setNotice({ kind: "ok", message: "Page removed." });
    } catch (err) {
      setNotice({
        kind: "error",
        message:
          err instanceof ApiError ? err.message : "We couldn't remove that page.",
      });
    }
  }

  const attached = pages.length;
  const filled = countFilled(brief);

  return (
    <section className="rounded-xl3 border border-white/[0.09] bg-white/[0.03]">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-5 py-4 text-left"
      >
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-white/[0.06] text-gold-200/90">
          <BookOpen className="h-4 w-4" aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm text-ink-50">
            What this lesson teaches, and what from
          </span>
          <span className="mt-0.5 block truncate text-xs text-ink-500">
            {summarise(brief, attached)}
          </span>
        </span>
        {(filled > 0 || attached > 0) && (
          <span className="shrink-0 rounded-full bg-gold-300/15 px-2.5 py-0.5 text-xs text-gold-100">
            {filled + attached}
          </span>
        )}
        <ChevronDown
          className={cn(
            "h-4 w-4 shrink-0 text-ink-400 transition-transform duration-300",
            open && "rotate-180",
          )}
          aria-hidden
        />
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <div className="space-y-6 border-t border-white/[0.07] px-5 py-5">
              {/* ------------------------------------------------ the brief */}
              <div className="grid gap-3 sm:grid-cols-2">
                <Field
                  label="Nishmat phrase"
                  hint="Hebrew or transliterated — the exact stanza is looked up"
                  value={brief.phrase ?? ""}
                  onChange={(v) => set("phrase", v)}
                  disabled={disabled}
                  className="sm:col-span-2"
                />
                <Field
                  label="Hebrew word"
                  value={brief.hebrew_word ?? ""}
                  onChange={(v) => set("hebrew_word", v)}
                  disabled={disabled}
                />
                <Field
                  label="Psalm"
                  hint="e.g. 34 or 34:19"
                  value={brief.psalm ?? ""}
                  onChange={(v) => set("psalm", v)}
                  disabled={disabled}
                />
                <Field
                  label="Theme"
                  value={brief.theme ?? ""}
                  onChange={(v) => set("theme", v)}
                  disabled={disabled}
                />
                <Field
                  label="Commentator or source"
                  value={brief.commentator ?? ""}
                  onChange={(v) => set("commentator", v)}
                  disabled={disabled}
                />
                <Field
                  label="Time of year"
                  hint="Elul, Pesach, a yahrzeit…"
                  value={brief.seasonal ?? ""}
                  onChange={(v) => set("seasonal", v)}
                  disabled={disabled}
                />
                <label className="block">
                  <span className="mb-1.5 block text-xs text-ink-400">Length</span>
                  <select
                    value={brief.length ?? "standard"}
                    onChange={(event) =>
                      set("length", event.target.value as GenerationBrief["length"])
                    }
                    disabled={disabled}
                    className="w-full rounded-xl border border-white/[0.1] bg-night-950/60 px-3 py-2 text-sm text-ink-50 outline-none focus:border-gold-300/40"
                  >
                    <option value="short">Short</option>
                    <option value="standard">Standard</option>
                    <option value="long">Long</option>
                  </select>
                </label>
                <Field
                  label="What this lesson should do"
                  value={brief.objective ?? ""}
                  onChange={(v) => set("objective", v)}
                  disabled={disabled}
                  multiline
                  className="sm:col-span-2"
                />
              </div>

              {/* ------------------------------------------------- the pages */}
              <div>
                <div className="mb-3 flex items-baseline justify-between gap-3">
                  <h3 className="text-sm text-ink-100">Pages from books</h3>
                  <span className="text-xs text-ink-500">
                    Used for this lesson only
                  </span>
                </div>

                <p className="mb-3 flex items-start gap-2 rounded-xl border border-white/[0.07] bg-white/[0.02] px-3.5 py-2.5 text-xs leading-relaxed text-ink-400">
                  <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                  Photograph the pages you want it to draw on — ArtScroll,
                  Nishmas: Song of the Soul, anything else on your shelf. They are
                  read, attributed, and used while this lesson is written. They
                  are never added to the permanent library and never reach a
                  learner.
                </p>

                <div className="mb-3 grid gap-2 sm:grid-cols-[2fr_1fr]">
                  <label className="block">
                    <span className="mb-1.5 block text-xs text-ink-400">
                      Which book
                    </span>
                    <input
                      list="reference-books"
                      value={book}
                      onChange={(event) => setBook(event.target.value)}
                      placeholder="ArtScroll Tehillim — Rabbi Avrohom Chaim Feuer"
                      disabled={disabled}
                      className="w-full rounded-xl border border-white/[0.1] bg-night-950/60 px-3 py-2 text-sm text-ink-50 outline-none placeholder:text-ink-500/60 focus:border-gold-300/40"
                    />
                    <datalist id="reference-books">
                      {BOOK_SUGGESTIONS.map((suggestion) => (
                        <option key={suggestion} value={suggestion} />
                      ))}
                    </datalist>
                  </label>
                  <label className="block">
                    <span className="mb-1.5 block text-xs text-ink-400">Page</span>
                    <input
                      value={page}
                      onChange={(event) => setPage(event.target.value)}
                      placeholder="412"
                      disabled={disabled}
                      className="w-full rounded-xl border border-white/[0.1] bg-night-950/60 px-3 py-2 text-sm text-ink-50 outline-none placeholder:text-ink-500/60 focus:border-gold-300/40"
                    />
                  </label>
                </div>

                <input
                  ref={inputRef}
                  type="file"
                  multiple
                  accept=".png,.jpg,.jpeg,.webp,.gif,.heic,.pdf"
                  className="sr-only"
                  onChange={(event) => {
                    if (event.target.files?.length) handleFiles(event.target.files);
                    event.target.value = "";
                  }}
                />

                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => inputRef.current?.click()}
                  disabled={disabled}
                >
                  <Plus className="h-4 w-4" aria-hidden />
                  Add pages
                </Button>

                <ul className="mt-3 space-y-2">
                  {uploads.map((upload) => (
                    <li
                      key={upload.localId}
                      className={cn(
                        "rounded-xl border px-3.5 py-2.5",
                        upload.error
                          ? "border-danger/25 bg-danger/[0.06]"
                          : "border-white/[0.09] bg-white/[0.03]",
                      )}
                    >
                      <div className="flex items-center gap-2.5">
                        {upload.error ? (
                          <AlertTriangle
                            className="h-4 w-4 shrink-0 text-rose-300"
                            aria-hidden
                          />
                        ) : (
                          <Loader2
                            className="h-4 w-4 shrink-0 animate-spin text-gold-200"
                            aria-hidden
                          />
                        )}
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm text-ink-100">
                            {upload.filename}
                          </span>
                          <span className="block truncate text-xs text-ink-500">
                            {upload.error ?? upload.stage}
                          </span>
                        </span>
                      </div>
                      {!upload.error && (
                        <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/[0.07]">
                          <div
                            className="h-full rounded-full bg-gradient-to-r from-gold-300 to-gold-200 transition-all duration-500"
                            style={{ width: `${upload.pct}%` }}
                          />
                        </div>
                      )}
                    </li>
                  ))}

                  {pages.map((item) => (
                    <li
                      key={item.source_file_id}
                      className="flex items-center gap-2.5 rounded-xl border border-white/[0.09] bg-white/[0.03] px-3.5 py-2.5"
                    >
                      <PageIcon page={item} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm text-ink-100">
                          {item.book ?? item.filename}
                          {item.page ? `, p. ${item.page}` : ""}
                        </span>
                        <span className="block truncate text-xs text-ink-500">
                          {describePage(item)}
                        </span>
                      </span>
                      <button
                        type="button"
                        onClick={() => handleRemove(item.source_file_id)}
                        disabled={disabled}
                        aria-label={`Remove ${item.filename}`}
                        className="shrink-0 rounded-lg p-1.5 text-ink-500 transition-colors hover:bg-white/[0.07] hover:text-rose-300"
                      >
                        <Trash2 className="h-3.5 w-3.5" aria-hidden />
                      </button>
                    </li>
                  ))}
                </ul>

                {!loading && pages.length === 0 && uploads.length === 0 && (
                  <p className="mt-3 text-xs text-ink-500">
                    No pages attached. The lesson will be written from the Nishmat
                    text, Tehillim and the reference material already loaded.
                  </p>
                )}
              </div>

              {/* --------------------------------------- what the system has */}
              {corpus && (
                <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-3.5 py-3">
                  <p className="text-xs text-ink-400">
                    Always available:{" "}
                    {corpus.documents.length > 0
                      ? corpus.documents
                          .map(
                            (doc) =>
                              `${doc.title}${doc.chunks ? ` (${doc.chunks})` : ""}`,
                          )
                          .join(" · ")
                      : "nothing yet — the reference corpus has not been loaded."}
                  </p>
                  {corpus.missing.length > 0 && (
                    <p className="mt-1.5 text-xs text-ink-500">
                      Not held: {corpus.missing.join(" · ")}. Lessons will not
                      quote from these.
                    </p>
                  )}
                </div>
              )}

              {notice && (
                <p
                  role="status"
                  className={cn(
                    "rounded-xl px-3.5 py-2.5 text-sm",
                    notice.kind === "ok"
                      ? "bg-success/[0.08] text-emerald-200"
                      : "bg-danger/[0.08] text-rose-200",
                  )}
                >
                  {notice.message}
                </p>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}

/* ----------------------------------------------------------------- pieces */

function Field({
  label,
  hint,
  value,
  onChange,
  disabled,
  multiline = false,
  className,
}: {
  label: string;
  hint?: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  multiline?: boolean;
  className?: string;
}) {
  const shared =
    "w-full rounded-xl border border-white/[0.1] bg-night-950/60 px-3 py-2 text-sm text-ink-50 outline-none placeholder:text-ink-500/60 focus:border-gold-300/40";

  return (
    <label className={cn("block", className)}>
      <span className="mb-1.5 block text-xs text-ink-400">
        {label}
        {hint && <span className="ml-1.5 text-ink-500/80">· {hint}</span>}
      </span>
      {multiline ? (
        <textarea
          rows={2}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled}
          className={cn(shared, "resize-none")}
        />
      ) : (
        <input
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled}
          className={shared}
        />
      )}
    </label>
  );
}

function PageIcon({ page }: { page: ReferencePage }) {
  if (page.processing_status === "failed") {
    return <AlertTriangle className="h-4 w-4 shrink-0 text-rose-300" aria-hidden />;
  }
  if (page.processing_status === "completed") {
    return <Check className="h-4 w-4 shrink-0 text-success" aria-hidden />;
  }
  return <FileImage className="h-4 w-4 shrink-0 text-ink-400" aria-hidden />;
}

function describePage(page: ReferencePage): string {
  if (page.processing_status === "failed") {
    return page.error_message ?? "Couldn't be read";
  }
  if (page.processing_status !== "completed") return "Reading…";
  if (page.indexed_chunks === 0) {
    return "Read, but nothing was indexed — it may not be used";
  }
  return `${page.word_count ?? "?"} words · ready`;
}

function countFilled(brief: GenerationBrief): number {
  return Object.entries(brief).filter(
    ([key, value]) =>
      key !== "length" && typeof value === "string" && value.trim().length > 0,
  ).length;
}

function hasContent(brief: GenerationBrief): boolean {
  return countFilled(brief) > 0;
}

function summarise(brief: GenerationBrief, pages: number): string {
  const parts: string[] = [];
  const subject =
    brief.phrase ?? brief.hebrew_word ?? brief.theme ?? brief.objective ?? null;
  if (subject) parts.push(subject.length > 60 ? `${subject.slice(0, 60)}…` : subject);
  if (brief.psalm) parts.push(`Tehillim ${brief.psalm}`);
  if (pages > 0) parts.push(`${pages} page${pages === 1 ? "" : "s"} attached`);

  return parts.length
    ? parts.join(" · ")
    : "Name a phrase, a theme or a Psalm, and attach pages from your books";
}
