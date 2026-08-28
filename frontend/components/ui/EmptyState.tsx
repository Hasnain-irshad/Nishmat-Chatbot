import { cn } from "@/lib/utils";

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  description: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "glass flex flex-col items-center rounded-2xl px-6 py-16 text-center",
        className,
      )}
    >
      <span
        className="grid h-14 w-14 place-items-center rounded-2xl"
        style={{
          background:
            "linear-gradient(140deg, rgba(237,201,106,0.16), rgba(167,139,250,0.12))",
          boxShadow: "inset 0 0 0 1px rgba(237,201,106,0.22)",
        }}
      >
        <Icon className="h-6 w-6 text-gold-200/80" aria-hidden />
      </span>
      <h3 className="mt-5 font-display text-xl font-light text-ink-50">{title}</h3>
      <p className="mt-2 max-w-sm text-sm leading-relaxed text-ink-400">
        {description}
      </p>
      {action && <div className="mt-7">{action}</div>}
    </div>
  );
}
