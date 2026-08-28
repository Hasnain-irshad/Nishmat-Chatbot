export default function Loading() {
  return (
    <div className="flex min-h-svh items-center justify-center" role="status" aria-live="polite">
      <span className="sr-only">Loading</span>
      <span className="relative grid h-16 w-16 place-items-center">
        <span className="absolute h-16 w-16 animate-spin rounded-full border border-transparent border-t-gold-300/70" />
        <span
          className="absolute h-11 w-11 animate-spin rounded-full border border-transparent border-b-violet-400/60"
          style={{ animationDirection: "reverse", animationDuration: "1.6s" }}
        />
        <span className="h-2 w-2 animate-pulse-glow rounded-full bg-gold-200" />
      </span>
    </div>
  );
}
