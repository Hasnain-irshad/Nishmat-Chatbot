import { cn } from "@/lib/utils";

export function Card({
  className,
  children,
  interactive,
}: {
  className?: string;
  children: React.ReactNode;
  interactive?: boolean;
}) {
  return (
    <div
      className={cn(
        "glass rounded-2xl",
        interactive &&
          "transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] hover:-translate-y-1 " +
            "hover:border-gold-300/30 hover:shadow-[0_20px_50px_-24px_rgba(237,201,106,0.4)]",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 px-6 pt-5">
      <div>
        <h2 className="font-display text-lg font-medium text-ink-50">{title}</h2>
        {description && (
          <p className="mt-1 text-sm text-ink-400">{description}</p>
        )}
      </div>
      {action}
    </div>
  );
}
