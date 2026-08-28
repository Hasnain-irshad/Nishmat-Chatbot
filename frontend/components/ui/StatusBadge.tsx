import { cn } from "@/lib/utils";
import type { LessonStatus } from "@/types/database";

const STYLES: Record<LessonStatus, { label: string; className: string }> = {
  draft:      { label: "Draft",       className: "bg-white/[0.07] text-ink-300 ring-white/10" },
  processing: { label: "Processing",  className: "bg-violet-500/15 text-violet-200 ring-violet-400/25" },
  generated:  { label: "Generated",   className: "bg-violet-500/15 text-violet-200 ring-violet-400/25" },
  review:     { label: "In review",   className: "bg-warning/12 text-amber-200 ring-amber-400/25" },
  approved:   { label: "Approved",    className: "bg-success/12 text-green-300 ring-green-400/25" },
  published:  { label: "Published",   className: "bg-gold-300/15 text-gold-200 ring-gold-300/30" },
  archived:   { label: "Archived",    className: "bg-white/[0.05] text-ink-500 ring-white/[0.08]" },
  failed:     { label: "Failed",      className: "bg-danger/12 text-rose-300 ring-rose-400/25" },
};

export function StatusBadge({
  status,
  className,
}: {
  status: LessonStatus;
  className?: string;
}) {
  const s = STYLES[status] ?? STYLES.draft;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[0.7rem] font-medium ring-1 ring-inset",
        s.className,
        className,
      )}
    >
      {(status === "processing" || status === "generated") && (
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" aria-hidden />
      )}
      {s.label}
    </span>
  );
}
