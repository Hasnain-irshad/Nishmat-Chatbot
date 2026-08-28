import { cn } from "@/lib/utils";

/**
 * The ornamental rule from the client's reference design: a glowing hairline
 * broken in the middle by a small gold mark.
 */
export function Divider({
  className,
  mark = "diamond",
}: {
  className?: string;
  mark?: "diamond" | "flame" | "dot";
}) {
  return (
    <div
      aria-hidden
      className={cn("flex w-full items-center justify-center gap-4", className)}
    >
      <span className="rule-glow flex-1" />
      <span className="shrink-0 text-gold-300/70">
        {mark === "diamond" && (
          <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor">
            <path d="M5 0 6.4 3.6 10 5 6.4 6.4 5 10 3.6 6.4 0 5 3.6 3.6Z" />
          </svg>
        )}
        {mark === "dot" && (
          <svg width="6" height="6" viewBox="0 0 6 6" fill="currentColor">
            <circle cx="3" cy="3" r="3" />
          </svg>
        )}
        {mark === "flame" && (
          <svg width="10" height="14" viewBox="0 0 10 14" fill="currentColor">
            <path d="M5 0c3 3.4 5 6 5 8.6A5 5 0 0 1 0 8.6C0 6 2 3.4 5 0Z" />
          </svg>
        )}
      </span>
      <span className="rule-glow flex-1" />
    </div>
  );
}
