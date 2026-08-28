"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  ArrowUp,
  Check,
  FileAudio,
  FileImage,
  FileText,
  FileType2,
  Loader2,
  Mic,
  Paperclip,
  Plus,
  Sparkles,
  X,
} from "lucide-react";

import {
  api,
  ApiError,
  pollJob,
  type GenerationBrief,
  type JobStatus,
} from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The lesson composer.
 *
 * Modelled on a chat composer at the client's request: type, or press "+" to
 * attach. Deliberately does NOT ask for a title or a lesson number — the
 * backend derives both from the source, and they stay editable in the editor.
 * Asking someone to name a lesson before they have read it is a question with
 * no good answer.
 */

type Phase = "uploading" | "processing" | "ready" | "error";

interface Attachment {
  localId: string;
  filename: string;
  kind?: string;
  phase: Phase;
  stage: string;
  pct: number;
  sourceFileId?: string;
  words?: number;
  warnings: string[];
  error?: string;
}

const ACCEPT: Record<string, string> = {
  document: ".pdf,.docx,.doc,.txt,.md",
  audio: ".mp3,.m4a,.wav,.ogg,.oga,.opus,.mp4,.webm,.mpga",
  image: ".png,.jpg,.jpeg,.webp,.gif,.heic",
  any: "",
};

// Any Hebrew letter. Present means the admin pasted from a siddur, and the
// stanza can be matched exactly rather than searched for.
const HEBREW = /[֐-׿]/;

const KIND_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  pdf: FileType2,
  docx: FileText,
  text: FileText,
  audio: FileAudio,
  image: FileImage,
};

export function LessonComposer({ nextNumber }: { nextNumber: number | null }) {
  const router = useRouter();

  const [note, setNote] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  // A lesson can start from a phrase of the prayer rather than from a
  // recording — which is how most of this series is actually written. The
  // fuller brief, and the book pages, live in the editor; this is just enough
  // to create the lesson and get there.
  const [subject, setSubject] = useState("");
  const [showSubject, setShowSubject] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const inputRef = useRef<HTMLInputElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // Grow the box with the text, up to a point.
  useEffect(() => {
    const element = textRef.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 260)}px`;
  }, [note]);

  useEffect(() => {
    function onPointerDown(event: PointerEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setMenuOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, []);

  const patch = useCallback((localId: string, changes: Partial<Attachment>) => {
    setAttachments((current) =>
      current.map((item) =>
        item.localId === localId ? { ...item, ...changes } : item,
      ),
    );
  }, []);

  const handleFiles = useCallback(
    async (files: FileList | File[]) => {
      setError(null);

      for (const file of Array.from(files)) {
        const localId = `${file.name}-${Math.random().toString(36).slice(2, 8)}`;

        setAttachments((current) => [
          ...current,
          {
            localId,
            filename: file.name,
            phase: "uploading",
            stage: "Uploading",
            pct: 5,
            warnings: [],
          },
        ]);

        try {
          const uploaded = await api.files.upload(file);

          if (!uploaded.job_id) {
            patch(localId, {
              phase: "ready",
              stage: "Already uploaded",
              pct: 100,
              sourceFileId: uploaded.source_file_id,
              kind: uploaded.kind,
            });
            continue;
          }

          patch(localId, {
            phase: "processing",
            stage: "Reading",
            pct: 15,
            sourceFileId: uploaded.source_file_id,
            kind: uploaded.kind,
          });

          const job = await pollJob(uploaded.job_id, (progress: JobStatus) =>
            patch(localId, {
              stage: progress.progress_stage ?? "Processing",
              pct: Math.max(progress.progress_pct, 15),
            }),
          );

          if (job.status !== "succeeded") {
            patch(localId, {
              phase: "error",
              stage: "Failed",
              error: job.error ?? "We couldn't read that file.",
            });
            continue;
          }

          patch(localId, {
            phase: "ready",
            stage: "Ready",
            pct: 100,
            words: job.result?.word_count as number | undefined,
            warnings: (job.result?.warnings as string[]) ?? [],
          });
        } catch (err) {
          patch(localId, {
            phase: "error",
            stage: "Failed",
            error:
              err instanceof ApiError
                ? err.message
                : "Something went wrong uploading that file.",
          });
        }
      }
    },
    [patch],
  );

  function pick(kind: keyof typeof ACCEPT) {
    setMenuOpen(false);
    if (inputRef.current) {
      inputRef.current.accept = ACCEPT[kind];
      inputRef.current.click();
    }
  }

  const ready = attachments.filter((a) => a.phase === "ready");
  const busy = attachments.some(
    (a) => a.phase === "uploading" || a.phase === "processing",
  );
  const canSend =
    (ready.length > 0 || note.trim().length > 20 || subject.trim().length > 2) &&
    !busy &&
    !creating;

  async function handleSend() {
    if (!canSend) return;
    setCreating(true);
    setError(null);

    try {
      const topic = subject.trim();
      const brief: GenerationBrief | undefined = topic
        ? // Hebrew means she pasted a phrase from the siddur, which is looked
          // up exactly; anything else is a theme to retrieve against.
          HEBREW.test(topic)
          ? { phrase: topic }
          : { theme: topic }
        : undefined;

      const lesson = await api.lessons.create({
        source_file_ids: ready.map((a) => a.sourceFileId!).filter(Boolean),
        note: note.trim() || undefined,
        brief,
      });
      router.push(`/admin/lessons/${lesson.id}`);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "We couldn't create the lesson. Please try again.",
      );
      setCreating(false);
    }
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends; Shift+Enter makes a new line — the convention people expect.
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSend();
    }
  }

  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        if (event.dataTransfer.files.length) handleFiles(event.dataTransfer.files);
      }}
    >
      <input
        ref={inputRef}
        type="file"
        multiple
        className="sr-only"
        onChange={(event) => {
          if (event.target.files?.length) handleFiles(event.target.files);
          event.target.value = "";
        }}
      />

      {/* ------------------------------------------------------- attachments */}
      <AnimatePresence>
        {attachments.length > 0 && (
          <motion.ul
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="mb-3 space-y-2"
          >
            {attachments.map((item) => (
              <motion.li
                key={item.localId}
                layout
                initial={{ opacity: 0, scale: 0.97 }}
                animate={{ opacity: 1, scale: 1 }}
                className={cn(
                  "overflow-hidden rounded-2xl border px-4 py-3",
                  item.phase === "error"
                    ? "border-danger/25 bg-danger/[0.06]"
                    : item.phase === "ready"
                      ? "border-success/20 bg-success/[0.05]"
                      : "border-white/[0.09] bg-white/[0.03]",
                )}
              >
                <div className="flex items-center gap-3">
                  <AttachmentIcon item={item} />

                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm text-ink-100">
                      {item.filename}
                    </span>
                    <span className="mt-0.5 block truncate text-xs text-ink-500">
                      {item.error ?? item.stage}
                      {item.words ? ` · ${item.words} words` : ""}
                    </span>
                  </span>

                  <button
                    type="button"
                    onClick={() =>
                      setAttachments((current) =>
                        current.filter((a) => a.localId !== item.localId),
                      )
                    }
                    className="shrink-0 rounded-lg p-1.5 text-ink-500 transition-colors hover:bg-white/[0.07] hover:text-ink-100"
                    aria-label={`Remove ${item.filename}`}
                  >
                    <X className="h-3.5 w-3.5" aria-hidden />
                  </button>
                </div>

                {(item.phase === "uploading" || item.phase === "processing") && (
                  <div className="mt-2.5 h-1 overflow-hidden rounded-full bg-white/[0.07]">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-gold-300 to-gold-200 transition-all duration-500"
                      style={{ width: `${item.pct}%` }}
                    />
                  </div>
                )}

                {item.warnings.map((warning, index) => (
                  <p
                    key={index}
                    className="mt-2 flex items-start gap-1.5 text-xs leading-relaxed text-amber-200/90"
                  >
                    <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
                    {warning}
                  </p>
                ))}
              </motion.li>
            ))}
          </motion.ul>
        )}
      </AnimatePresence>

      {/* ------------------------------------------------------ the subject */}
      <AnimatePresence>
        {showSubject && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            className="mb-3"
          >
            <label className="block rounded-2xl border border-white/[0.09] bg-white/[0.03] px-4 py-3">
              <span className="mb-1.5 block text-xs text-ink-400">
                What should this lesson teach?
              </span>
              <input
                value={subject}
                onChange={(event) => setSubject(event.target.value)}
                autoFocus
                placeholder="A Nishmat phrase, a Hebrew word, or a theme"
                className="w-full bg-transparent text-[0.95rem] text-ink-50 outline-none placeholder:text-ink-500/70"
              />
              <span className="mt-1.5 block text-xs text-ink-500">
                The prayer text and the Psalms are looked up for you. Add pages
                from your books in the editor.
              </span>
            </label>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ---------------------------------------------------------- composer */}
      <div
        className={cn(
          "relative rounded-xl3 border transition-all duration-300",
          dragging
            ? "border-gold-300/60 bg-gold-300/[0.06]"
            : "border-white/12 bg-white/[0.04] focus-within:border-gold-300/40",
        )}
      >
        {dragging && (
          <div className="pointer-events-none absolute inset-0 z-10 grid place-items-center rounded-xl3 bg-night-950/70">
            <span className="flex items-center gap-2 text-sm text-gold-100">
              <Paperclip className="h-4 w-4" aria-hidden />
              Drop to attach
            </span>
          </div>
        )}

        <div className="flex items-end gap-2 p-2.5">
          {/* ---- the "+" menu ---- */}
          <div ref={menuRef} className="relative shrink-0">
            <button
              type="button"
              onClick={() => setMenuOpen((open) => !open)}
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              aria-label="Attach a file"
              className={cn(
                "grid h-10 w-10 place-items-center rounded-full transition-all duration-300",
                menuOpen
                  ? "bg-gold-300/20 text-gold-100"
                  : "text-ink-300 hover:bg-white/[0.08] hover:text-ink-50",
              )}
            >
              <Plus
                className={cn(
                  "h-5 w-5 transition-transform duration-300",
                  menuOpen && "rotate-45",
                )}
                aria-hidden
              />
            </button>

            <AnimatePresence>
              {menuOpen && (
                <motion.div
                  role="menu"
                  initial={{ opacity: 0, y: 8, scale: 0.96 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: 8, scale: 0.96 }}
                  transition={{ duration: 0.16, ease: [0.16, 1, 0.3, 1] }}
                  className="glass glass-gold absolute bottom-[calc(100%+0.6rem)] left-0 z-20 w-60 overflow-hidden rounded-2xl p-1.5 shadow-panel"
                >
                  <MenuItem
                    icon={Mic}
                    title="Audio recording"
                    hint="A WhatsApp voice note"
                    onClick={() => pick("audio")}
                  />
                  <MenuItem
                    icon={FileText}
                    title="Document"
                    hint="Word, PDF or text"
                    onClick={() => pick("document")}
                  />
                  <MenuItem
                    icon={FileImage}
                    title="Photo"
                    hint="A picture of a page"
                    onClick={() => pick("image")}
                  />
                  <div className="my-1 h-px bg-white/[0.08]" />
                  <MenuItem
                    icon={Sparkles}
                    title="A subject to teach"
                    hint="A phrase, a word, a theme"
                    onClick={() => {
                      setMenuOpen(false);
                      setShowSubject(true);
                    }}
                  />
                  <MenuItem
                    icon={Paperclip}
                    title="Any file"
                    hint="Browse everything"
                    onClick={() => pick("any")}
                  />
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {/* ---- the text box ---- */}
          <textarea
            ref={textRef}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            onKeyDown={onKeyDown}
            rows={1}
            placeholder="Attach a recording, or type the lesson here…"
            className="max-h-[260px] flex-1 resize-none bg-transparent py-2.5 text-[0.98rem]
                       leading-relaxed text-ink-50 outline-none placeholder:text-ink-500/70"
          />

          {/* ---- send ---- */}
          <button
            type="button"
            onClick={handleSend}
            disabled={!canSend}
            aria-label="Create lesson"
            className={cn(
              "grid h-10 w-10 shrink-0 place-items-center rounded-full transition-all duration-300",
              canSend
                ? "bg-gradient-to-br from-gold-200 to-gold-400 text-night-950 shadow-[0_6px_20px_-6px_rgba(237,201,106,0.7)] hover:-translate-y-0.5"
                : "bg-white/[0.07] text-ink-500",
            )}
          >
            {creating ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <ArrowUp className="h-4.5 w-4.5" aria-hidden />
            )}
          </button>
        </div>
      </div>

      {/* ------------------------------------------------------------ footer */}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 px-1 text-xs text-ink-500">
        <span>
          {busy
            ? "Reading your file…"
            : ready.length > 0
              ? `${ready.length} file${ready.length === 1 ? "" : "s"} ready`
              : "Enter to create · Shift + Enter for a new line"}
        </span>
        {nextNumber !== null && (
          <span>
            Will be saved as <strong className="text-ink-300">Lesson #{nextNumber}</strong>
          </span>
        )}
      </div>

      {error && (
        <p
          role="alert"
          className="mt-4 flex items-start gap-2 rounded-xl border border-danger/25 bg-danger/[0.08] px-4 py-3 text-sm text-rose-200"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          {error}
        </p>
      )}
    </div>
  );
}

/* ----------------------------------------------------------------- pieces */

function MenuItem({
  icon: Icon,
  title,
  hint,
  onClick,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  hint: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors hover:bg-white/[0.07]"
    >
      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-white/[0.06] text-gold-200/90">
        <Icon className="h-4 w-4" aria-hidden />
      </span>
      <span className="min-w-0">
        <span className="block text-sm text-ink-50">{title}</span>
        <span className="block text-xs text-ink-500">{hint}</span>
      </span>
    </button>
  );
}

function AttachmentIcon({ item }: { item: Attachment }) {
  if (item.phase === "uploading" || item.phase === "processing") {
    return <Loader2 className="h-5 w-5 shrink-0 animate-spin text-gold-200" aria-hidden />;
  }
  if (item.phase === "error") {
    return <AlertTriangle className="h-5 w-5 shrink-0 text-rose-300" aria-hidden />;
  }
  if (item.phase === "ready") {
    return <Check className="h-5 w-5 shrink-0 text-success" aria-hidden />;
  }
  const Icon = (item.kind && KIND_ICONS[item.kind]) || FileText;
  return <Icon className="h-5 w-5 shrink-0 text-ink-400" />;
}
