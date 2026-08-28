"use client";

import { useCallback, useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  FileAudio,
  FileImage,
  FileText,
  FileType2,
  Loader2,
  UploadCloud,
  X,
} from "lucide-react";

import { api, ApiError, pollJob, type JobStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

export interface UploadedSource {
  id: string;
  filename: string;
  kind: string;
  wordCount?: number;
  warnings: string[];
}

type Phase = "idle" | "uploading" | "processing" | "done" | "error";

interface Item {
  localId: string;
  filename: string;
  size: number;
  phase: Phase;
  stage: string;
  pct: number;
  sourceFileId?: string;
  kind?: string;
  message?: string;
  warnings: string[];
}

const KIND_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  pdf: FileType2,
  docx: FileText,
  text: FileText,
  audio: FileAudio,
  image: FileImage,
};

const ACCEPT =
  ".pdf,.docx,.doc,.txt,.md,.png,.jpg,.jpeg,.webp,.gif,.heic," +
  ".mp3,.m4a,.wav,.ogg,.oga,.opus,.mp4,.webm";

export function UploadPanel({
  onUploaded,
  lessonId,
}: {
  onUploaded: (source: UploadedSource) => void;
  lessonId?: string;
}) {
  const [items, setItems] = useState<Item[]>([]);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const patch = useCallback((localId: string, changes: Partial<Item>) => {
    setItems((current) =>
      current.map((item) =>
        item.localId === localId ? { ...item, ...changes } : item,
      ),
    );
  }, []);

  const handleFiles = useCallback(
    async (files: FileList | File[]) => {
      for (const file of Array.from(files)) {
        const localId = `${file.name}-${file.size}-${Math.random().toString(36).slice(2, 8)}`;

        setItems((current) => [
          ...current,
          {
            localId,
            filename: file.name,
            size: file.size,
            phase: "uploading",
            stage: "Uploading",
            pct: 5,
            warnings: [],
          },
        ]);

        try {
          const uploaded = await api.files.upload(file, lessonId);

          // An identical file was already processed — nothing to wait for.
          if (!uploaded.job_id) {
            patch(localId, {
              phase: "done",
              stage: "Already uploaded",
              pct: 100,
              sourceFileId: uploaded.source_file_id,
              kind: uploaded.kind,
              message: uploaded.message,
            });
            onUploaded({
              id: uploaded.source_file_id,
              filename: uploaded.filename,
              kind: uploaded.kind,
              warnings: [],
            });
            continue;
          }

          patch(localId, {
            phase: "processing",
            stage: "Queued",
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
              message: job.error ?? "We couldn't read that file.",
            });
            continue;
          }

          const warnings = (job.result?.warnings as string[]) ?? [];
          patch(localId, {
            phase: "done",
            stage: "Ready",
            pct: 100,
            warnings,
          });

          onUploaded({
            id: uploaded.source_file_id,
            filename: uploaded.filename,
            kind: uploaded.kind,
            wordCount: job.result?.word_count as number | undefined,
            warnings,
          });
        } catch (error) {
          patch(localId, {
            phase: "error",
            stage: "Failed",
            message:
              error instanceof ApiError
                ? error.message
                : "Something went wrong uploading that file.",
          });
        }
      }
    },
    [lessonId, onUploaded, patch],
  );

  return (
    <div>
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
        className={cn(
          "relative overflow-hidden rounded-xl3 border-2 border-dashed px-6 py-12 text-center transition-all duration-300",
          dragging
            ? "border-gold-300/60 bg-gold-300/[0.07]"
            : "border-white/12 bg-white/[0.02] hover:border-white/25",
        )}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPT}
          className="sr-only"
          onChange={(event) => {
            if (event.target.files?.length) handleFiles(event.target.files);
            event.target.value = "";
          }}
        />

        <span
          className="mx-auto grid h-14 w-14 place-items-center rounded-2xl"
          style={{
            background:
              "linear-gradient(140deg, rgba(237,201,106,0.18), rgba(167,139,250,0.12))",
            boxShadow: "inset 0 0 0 1px rgba(237,201,106,0.24)",
          }}
        >
          <UploadCloud className="h-6 w-6 text-gold-200" aria-hidden />
        </span>

        <h3 className="mt-5 font-display text-xl font-light text-ink-50">
          Drop your source material here
        </h3>
        <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-ink-400">
          A voice recording, a Word document, a PDF, or a photo of a page.
          Whatever the lesson started as.
        </p>

        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className="mt-6 rounded-full border border-white/15 px-5 py-2.5 text-sm text-ink-100
                     transition-all duration-300 hover:-translate-y-0.5 hover:border-gold-300/45
                     hover:bg-white/[0.06]"
        >
          Choose a file
        </button>

        <p className="mt-4 text-xs text-ink-500">
          Audio up to 100 MB · Documents up to 25 MB · Images up to 10 MB
        </p>
      </div>

      {items.length > 0 && (
        <ul className="mt-4 space-y-2.5">
          {items.map((item) => (
            <li
              key={item.localId}
              className={cn(
                "overflow-hidden rounded-xl border px-4 py-3",
                item.phase === "error"
                  ? "border-danger/25 bg-danger/[0.06]"
                  : item.phase === "done"
                    ? "border-success/20 bg-success/[0.05]"
                    : "border-white/[0.08] bg-white/[0.03]",
              )}
            >
              <div className="flex items-center gap-3">
                <FileIcon kind={item.kind} phase={item.phase} />

                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm text-ink-100">
                    {item.filename}
                  </span>
                  <span className="mt-0.5 block text-xs text-ink-500">
                    {item.stage}
                    {item.message ? ` · ${item.message}` : ""}
                  </span>
                </span>

                {item.phase === "done" && (
                  <Check className="h-4 w-4 shrink-0 text-success" aria-hidden />
                )}
                {item.phase === "error" && (
                  <button
                    type="button"
                    onClick={() =>
                      setItems((current) =>
                        current.filter((entry) => entry.localId !== item.localId),
                      )
                    }
                    className="shrink-0 rounded p-1 text-ink-400 hover:text-rose-300"
                    aria-label="Dismiss"
                  >
                    <X className="h-4 w-4" aria-hidden />
                  </button>
                )}
              </div>

              {(item.phase === "uploading" || item.phase === "processing") && (
                <div
                  className="mt-2.5 h-1 overflow-hidden rounded-full bg-white/[0.07]"
                  role="progressbar"
                  aria-valuenow={item.pct}
                  aria-valuemin={0}
                  aria-valuemax={100}
                >
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-gold-300 to-gold-200 transition-all duration-500"
                    style={{ width: `${item.pct}%` }}
                  />
                </div>
              )}

              {item.warnings.length > 0 && (
                <ul className="mt-2.5 space-y-1">
                  {item.warnings.map((warning, index) => (
                    <li
                      key={index}
                      className="flex items-start gap-1.5 text-xs leading-relaxed text-amber-200/90"
                    >
                      <AlertTriangle
                        className="mt-0.5 h-3 w-3 shrink-0"
                        aria-hidden
                      />
                      {warning}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function FileIcon({ kind, phase }: { kind?: string; phase: Phase }) {
  if (phase === "uploading" || phase === "processing") {
    return (
      <Loader2 className="h-5 w-5 shrink-0 animate-spin text-gold-200" aria-hidden />
    );
  }
  const Icon = (kind && KIND_ICONS[kind]) || FileText;
  return <Icon className="h-5 w-5 shrink-0 text-ink-400" />;
}
