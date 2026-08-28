"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronUp,
  GripVertical,
  Plus,
  Save,
  Trash2,
} from "lucide-react";

import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/Button";

export interface TemplateSection {
  key: string;
  label: string;
  required: boolean;
  dir: "ltr" | "rtl";
  order: number;
  guidance?: string | null;
  max_words?: number | null;
}

export interface Template {
  id: string;
  name: string;
  description: string | null;
  series_title: string | null;
  sections: TemplateSection[];
  optional_addons: { key: string; label: string; guidance?: string }[];
  style_guide: string;
  formatting_rules: Record<string, unknown>;
  constraints: Record<string, unknown>;
  signoff: string | null;
  version: number;
  is_default: boolean;
}

type Tab = "structure" | "style" | "rules";

export function TemplateEditor({ template: initial }: { template: Template }) {
  const router = useRouter();

  const [tab, setTab] = useState<Tab>("structure");
  const [seriesTitle, setSeriesTitle] = useState(initial.series_title ?? "");
  const [signoff, setSignoff] = useState(initial.signoff ?? "");
  const [sections, setSections] = useState<TemplateSection[]>(initial.sections);
  const [styleGuide, setStyleGuide] = useState(initial.style_guide);
  const [version, setVersion] = useState(initial.version);

  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(
    null,
  );

  const dirty = useMemo(
    () =>
      seriesTitle !== (initial.series_title ?? "") ||
      signoff !== (initial.signoff ?? "") ||
      styleGuide !== initial.style_guide ||
      JSON.stringify(sections) !== JSON.stringify(initial.sections),
    [seriesTitle, signoff, styleGuide, sections, initial],
  );

  function move(index: number, direction: -1 | 1) {
    const target = index + direction;
    if (target < 0 || target >= sections.length) return;
    setSections((current) => {
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next.map((section, i) => ({ ...section, order: i + 1 }));
    });
  }

  function update(index: number, changes: Partial<TemplateSection>) {
    setSections((current) =>
      current.map((section, i) => (i === index ? { ...section, ...changes } : section)),
    );
  }

  function remove(index: number) {
    setSections((current) =>
      current.filter((_, i) => i !== index).map((s, i) => ({ ...s, order: i + 1 })),
    );
  }

  function add() {
    setSections((current) => [
      ...current,
      {
        key: `section_${current.length + 1}`,
        label: "New section",
        required: false,
        dir: "ltr",
        order: current.length + 1,
        guidance: "",
      },
    ]);
  }

  async function save() {
    setSaving(true);
    setNotice(null);
    try {
      const updated = await api.templates.update(initial.id, {
        series_title: seriesTitle || null,
        signoff: signoff || null,
        style_guide: styleGuide,
        sections,
      });
      setVersion(updated.version);
      setNotice({
        kind: "ok",
        text: `Saved as version ${updated.version}. The previous version was kept.`,
      });
      router.refresh();
    } catch (error) {
      setNotice({
        kind: "error",
        text:
          error instanceof ApiError
            ? error.message
            : "We couldn't save the template.",
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mx-auto max-w-4xl pb-20">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-[0.7rem] font-medium uppercase tracking-[0.3em] text-gold-300/75">
            Lesson format
          </p>
          <h1 className="mt-2.5 font-display text-4xl font-light text-ink-50">
            {initial.name}
          </h1>
          <p className="mt-2 max-w-xl text-[0.95rem] leading-relaxed text-ink-400">
            The structure and the voice, stored as data. Change them here and
            every new lesson follows — no code involved.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <span className="text-xs text-ink-500">v{version}</span>
          <Button onClick={save} loading={saving} disabled={!dirty} size="md">
            <Save className="h-4 w-4" aria-hidden />
            Save
          </Button>
        </div>
      </div>

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
          {notice.text}
        </div>
      )}

      {/* ------------------------------------------------------------- tabs */}
      <div className="mt-8 flex gap-1.5" role="tablist">
        {(
          [
            ["structure", "Structure"],
            ["style", "Writing style"],
            ["rules", "Rules"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={cn(
              "rounded-full px-4 py-2 text-sm transition-colors",
              tab === key
                ? "bg-gradient-to-r from-gold-200 to-gold-300 text-night-950"
                : "text-ink-300 hover:bg-white/[0.06] hover:text-ink-50",
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {/* -------------------------------------------------------- structure */}
      {tab === "structure" && (
        <div className="mt-6">
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField
              id="series-title"
              label="Series title"
              value={seriesTitle}
              onChange={setSeriesTitle}
              placeholder="Nishmat: A Journey of Praise"
            />
            <TextField
              id="signoff"
              label="Sign-off"
              value={signoff}
              onChange={setSignoff}
              placeholder="— Rivkah"
            />
          </div>

          <h2 className="mt-8 text-sm font-medium text-ink-200">
            Sections, in order
          </h2>
          <p className="mt-1 text-xs text-ink-500">
            The guidance under each section is what the AI is told about it.
          </p>

          <ul className="mt-4 space-y-2.5">
            {sections.map((section, index) => (
              <li
                key={`${section.key}-${index}`}
                className="group rounded-2xl border border-white/[0.08] bg-white/[0.02] p-4"
              >
                <div className="flex items-start gap-3">
                  <span className="mt-1.5 flex flex-col gap-0.5">
                    <button
                      type="button"
                      onClick={() => move(index, -1)}
                      disabled={index === 0}
                      className="rounded p-0.5 text-ink-500 hover:text-ink-100 disabled:opacity-20"
                      aria-label="Move up"
                    >
                      <ChevronUp className="h-3.5 w-3.5" aria-hidden />
                    </button>
                    <GripVertical
                      className="h-3 w-3 text-ink-500/40"
                      aria-hidden
                    />
                    <button
                      type="button"
                      onClick={() => move(index, 1)}
                      disabled={index === sections.length - 1}
                      className="rounded p-0.5 text-ink-500 hover:text-ink-100 disabled:opacity-20"
                      aria-label="Move down"
                    >
                      <ChevronDown className="h-3.5 w-3.5" aria-hidden />
                    </button>
                  </span>

                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <input
                        value={section.label}
                        onChange={(e) => update(index, { label: e.target.value })}
                        className="min-w-0 flex-1 rounded-lg border border-transparent bg-transparent
                                   px-2 py-1 text-[0.95rem] text-ink-50 outline-none
                                   hover:border-white/10 focus:border-gold-300/40 focus:bg-white/[0.04]"
                      />
                      <code className="rounded bg-white/[0.05] px-1.5 py-0.5 font-mono text-[0.65rem] text-ink-500">
                        {section.key}
                      </code>

                      <label className="flex items-center gap-1.5 text-[0.7rem] text-ink-400">
                        <input
                          type="checkbox"
                          checked={section.required}
                          onChange={(e) =>
                            update(index, { required: e.target.checked })
                          }
                          className="accent-gold-300"
                        />
                        Required
                      </label>

                      <button
                        type="button"
                        onClick={() =>
                          update(index, {
                            dir: section.dir === "rtl" ? "ltr" : "rtl",
                          })
                        }
                        className={cn(
                          "rounded-full px-2 py-0.5 text-[0.65rem] font-medium transition-colors",
                          section.dir === "rtl"
                            ? "bg-gold-300/15 text-gold-200"
                            : "bg-white/[0.06] text-ink-400 hover:text-ink-100",
                        )}
                      >
                        {section.dir.toUpperCase()}
                      </button>

                      <button
                        type="button"
                        onClick={() => remove(index)}
                        className="rounded p-1 text-ink-500 opacity-0 transition-opacity hover:text-rose-300 group-hover:opacity-100"
                        aria-label={`Remove ${section.label}`}
                      >
                        <Trash2 className="h-3.5 w-3.5" aria-hidden />
                      </button>
                    </div>

                    <textarea
                      value={section.guidance ?? ""}
                      onChange={(e) => update(index, { guidance: e.target.value })}
                      rows={2}
                      placeholder="What should this section contain?"
                      className="mt-2 w-full resize-y rounded-lg border border-white/[0.07] bg-white/[0.02]
                                 px-3 py-2 text-xs leading-relaxed text-ink-300 outline-none
                                 placeholder:text-ink-500/60 focus:border-gold-300/35"
                    />
                  </div>
                </div>
              </li>
            ))}
          </ul>

          <button
            type="button"
            onClick={add}
            className="mt-4 flex w-full items-center justify-center gap-2 rounded-2xl border
                       border-dashed border-white/12 py-3 text-sm text-ink-400
                       transition-colors hover:border-gold-300/35 hover:text-ink-100"
          >
            <Plus className="h-4 w-4" aria-hidden />
            Add a section
          </button>
        </div>
      )}

      {/* ------------------------------------------------------------ style */}
      {tab === "style" && (
        <div className="mt-6">
          <label
            htmlFor="style-guide"
            className="text-sm font-medium text-ink-200"
          >
            Writing style instructions
          </label>
          <p className="mt-1 text-xs leading-relaxed text-ink-500">
            This text is given to the AI verbatim. It is the single biggest
            influence on whether a generated lesson sounds like the client.
          </p>
          <textarea
            id="style-guide"
            value={styleGuide}
            onChange={(event) => setStyleGuide(event.target.value)}
            rows={28}
            className="mt-3 w-full resize-y rounded-2xl border border-white/[0.08] bg-white/[0.02]
                       p-4 font-mono text-[0.8rem] leading-relaxed text-ink-200 outline-none
                       focus:border-gold-300/35"
          />
          <p className="mt-2 text-xs text-ink-500">
            {styleGuide.split(/\s+/).filter(Boolean).length} words
          </p>
        </div>
      )}

      {/* ------------------------------------------------------------ rules */}
      {tab === "rules" && (
        <div className="mt-6 space-y-4">
          <ReadOnlyBlock title="Formatting rules" value={initial.formatting_rules} />
          <ReadOnlyBlock title="Constraints" value={initial.constraints} />
          <p className="text-xs leading-relaxed text-ink-500">
            These are edited as data for now. A form for them arrives with the
            generation pipeline, once their effect on output can be seen
            directly.
          </p>
        </div>
      )}
    </div>
  );
}

/* ----------------------------------------------------------------- pieces */

function TextField({
  id,
  label,
  value,
  onChange,
  placeholder,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <div>
      <label
        htmlFor={id}
        className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-ink-400"
      >
        {label}
      </label>
      <input
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="h-11 w-full rounded-xl border border-white/10 bg-white/[0.04] px-3.5
                   text-[0.95rem] text-ink-50 outline-none transition-all
                   placeholder:text-ink-500/70 focus:border-gold-300/50 focus:bg-white/[0.06]"
      />
    </div>
  );
}

function ReadOnlyBlock({ title, value }: { title: string; value: unknown }) {
  return (
    <div className="rounded-2xl border border-white/[0.08] bg-white/[0.02] p-4">
      <h3 className="text-sm font-medium text-ink-200">{title}</h3>
      <pre className="mt-2 overflow-x-auto rounded-lg bg-night-950/50 p-3 font-mono text-[0.72rem] leading-relaxed text-ink-300">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}
