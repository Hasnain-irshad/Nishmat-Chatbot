"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, Check, Sparkles, Wand2, X } from "lucide-react";

import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/Button";

/**
 * Ask the AI to revise a passage, then show a diff before anything is kept.
 *
 * The revision is a PROPOSAL. Nothing is written until "Use this" is pressed,
 * and even then it only lands in the editor — saving a version is still a
 * separate, deliberate act. A revision she dislikes leaves no trace.
 */

const SECTION_PRESETS = [
  "Make this warmer.",
  "Break this into shorter lines.",
  "Make this shorter.",
  "Make this easier to understand.",
  "Add a relatable everyday example.",
];

const LESSON_PRESETS = [
  "Make the whole lesson warmer.",
  "Shorten the whole lesson by about a fifth.",
  "Make the closing blessing more powerful.",
  "Use shorter lines throughout.",
];

interface Proposal {
  scope: string;
  section_key: string | null;
  original: string | null;
  revised: string | null;
  sections: { key: string; title: string | null; body: string; dir: string }[] | null;
  warnings: string[];
  cost_usd: number;
}

export function AiReviseDialog({
  open,
  onClose,
  lessonId,
  scope,
  sectionKey,
  sectionLabel,
  selectedText,
  onAcceptSection,
  onAcceptLesson,
}: {
  open: boolean;
  onClose: () => void;
  lessonId: string;
  scope: "section" | "lesson";
  sectionKey?: string;
  sectionLabel?: string;
  selectedText?: string;
  onAcceptSection: (sectionKey: string, body: string) => void;
  onAcceptLesson: (sections: Proposal["sections"]) => void;
}) {
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (open) {
      setInstruction("");
      setProposal(null);
      setError(null);
      setTimeout(() => inputRef.current?.focus(), 80);
    }
  }, [open]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape" && !busy) onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  async function run() {
    const text = instruction.trim();
    if (!text || busy) return;

    setBusy(true);
    setError(null);
    try {
      const result = await api.lessons.modify(lessonId, {
        instruction: text,
        scope,
        section_key: scope === "section" ? sectionKey : undefined,
        selected_text: selectedText || undefined,
      });
      setProposal(result as Proposal);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "The revision couldn't be made. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  function accept() {
    if (!proposal) return;
    if (proposal.scope === "lesson" && proposal.sections) {
      onAcceptLesson(proposal.sections);
    } else if (proposal.section_key && proposal.revised) {
      onAcceptSection(proposal.section_key, proposal.revised);
    }
    onClose();
  }

  const presets = scope === "section" ? SECTION_PRESETS : LESSON_PRESETS;

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => !busy && onClose()}
            className="fixed inset-0 z-50 bg-night-950/80 backdrop-blur-sm"
            aria-hidden
          />
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-label="Ask AI to revise"
            initial={{ opacity: 0, y: 16, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 16, scale: 0.98 }}
            transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
            className="fixed inset-x-3 top-[6vh] z-50 mx-auto flex max-h-[88vh] max-w-3xl
                       flex-col overflow-hidden rounded-xl3 border border-white/12
                       bg-night-900 shadow-panel sm:inset-x-6"
          >
            {/* -------------------------------------------------- header */}
            <div className="flex items-center gap-3 border-b border-white/[0.08] px-5 py-4">
              <span className="grid h-8 w-8 place-items-center rounded-lg bg-violet-500/20 text-violet-200">
                <Wand2 className="h-4 w-4" aria-hidden />
              </span>
              <div className="min-w-0 flex-1">
                <h2 className="font-display text-lg font-medium text-ink-50">
                  Ask AI to revise
                </h2>
                <p className="truncate text-xs text-ink-400">
                  {scope === "lesson"
                    ? "The whole lesson"
                    : selectedText
                      ? `The selected passage in ${sectionLabel ?? "this section"}`
                      : sectionLabel ?? "This section"}
                </p>
              </div>
              <button
                type="button"
                onClick={onClose}
                disabled={busy}
                className="rounded-lg p-2 text-ink-400 transition-colors hover:bg-white/[0.07] hover:text-ink-50 disabled:opacity-40"
                aria-label="Close"
              >
                <X className="h-4 w-4" aria-hidden />
              </button>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
              {!proposal ? (
                <>
                  <label
                    htmlFor="revise-instruction"
                    className="mb-2 block text-xs font-medium uppercase tracking-wider text-ink-400"
                  >
                    What should change?
                  </label>
                  <textarea
                    ref={inputRef}
                    id="revise-instruction"
                    value={instruction}
                    onChange={(e) => setInstruction(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) run();
                    }}
                    rows={3}
                    placeholder="Say it the way you would to a person — “make this warmer”, “this is too long”…"
                    className="w-full resize-none rounded-xl border border-white/10 bg-white/[0.04]
                               px-3.5 py-3 text-[0.95rem] leading-relaxed text-ink-50 outline-none
                               transition-colors placeholder:text-ink-500/70 focus:border-gold-300/45"
                  />

                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {presets.map((preset) => (
                      <button
                        key={preset}
                        type="button"
                        onClick={() => setInstruction(preset)}
                        className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1.5
                                   text-xs text-ink-300 transition-colors
                                   hover:border-gold-300/35 hover:text-ink-50"
                      >
                        {preset}
                      </button>
                    ))}
                  </div>

                  {selectedText && (
                    <div className="mt-4 rounded-xl border border-white/[0.08] bg-white/[0.02] p-3">
                      <p className="mb-1.5 text-[0.68rem] uppercase tracking-wider text-ink-500">
                        Only this will be revised
                      </p>
                      <p className="line-clamp-4 text-sm leading-relaxed text-ink-300">
                        {selectedText}
                      </p>
                    </div>
                  )}
                </>
              ) : (
                <Diff proposal={proposal} />
              )}

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

            {/* -------------------------------------------------- footer */}
            <div className="flex items-center gap-3 border-t border-white/[0.08] px-5 py-4">
              {proposal ? (
                <>
                  <Button size="sm" onClick={accept}>
                    <Check className="h-4 w-4" aria-hidden />
                    Use this
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setProposal(null)}
                  >
                    Try a different instruction
                  </Button>
                  <span className="ml-auto text-xs text-ink-500">
                    ${proposal.cost_usd.toFixed(4)} · nothing saved yet
                  </span>
                </>
              ) : (
                <>
                  <Button
                    size="sm"
                    onClick={run}
                    loading={busy}
                    disabled={!instruction.trim()}
                  >
                    <Sparkles className="h-4 w-4" aria-hidden />
                    {busy ? "Revising" : "Revise"}
                  </Button>
                  <span className="ml-auto text-xs text-ink-500">
                    You&rsquo;ll see the change before anything is kept
                  </span>
                </>
              )}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

/* ------------------------------------------------------------------ diff */

function Diff({ proposal }: { proposal: Proposal }) {
  if (proposal.scope === "lesson") {
    return (
      <div>
        <Warnings items={proposal.warnings} />
        <p className="mb-3 text-sm text-ink-400">
          {proposal.sections?.length} sections revised. Review in the editor
          after accepting.
        </p>
        <div className="space-y-3">
          {proposal.sections?.map((section) => (
            <div
              key={section.key}
              className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-3"
            >
              <p className="mb-1.5 text-[0.68rem] uppercase tracking-wider text-ink-500">
                {section.key.replace(/_/g, " ")}
              </p>
              <p className="whitespace-pre-wrap text-sm leading-[1.7] text-ink-200">
                {section.body}
              </p>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div>
      <Warnings items={proposal.warnings} />
      <div className="grid gap-3 md:grid-cols-2">
        <Pane label="Now" tone="before" text={proposal.original ?? ""} />
        <Pane label="Proposed" tone="after" text={proposal.revised ?? ""} />
      </div>
    </div>
  );
}

function Pane({
  label,
  tone,
  text,
}: {
  label: string;
  tone: "before" | "after";
  text: string;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border p-3.5",
        tone === "after"
          ? "border-success/25 bg-success/[0.05]"
          : "border-white/[0.08] bg-white/[0.02]",
      )}
    >
      <p
        className={cn(
          "mb-2 text-[0.68rem] font-medium uppercase tracking-wider",
          tone === "after" ? "text-green-300" : "text-ink-500",
        )}
      >
        {label}
      </p>
      {/* whitespace-pre-wrap matters: the line breaks ARE the writing */}
      <p className="whitespace-pre-wrap text-sm leading-[1.75] text-ink-100">
        {text}
      </p>
    </div>
  );
}

function Warnings({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <ul className="mb-4 space-y-1.5">
      {items.map((warning, index) => (
        <li
          key={index}
          className="flex items-start gap-2 rounded-xl border border-amber-400/25 bg-warning/[0.07] px-3.5 py-2.5 text-sm text-amber-100"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          {warning}
        </li>
      ))}
    </ul>
  );
}
