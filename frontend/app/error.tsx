"use client";

import { useEffect } from "react";
import { RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/Button";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Surfaced to the browser console only; never rendered to the person.
    console.error("Unhandled UI error:", error);
  }, [error]);

  return (
    <main className="flex min-h-svh flex-col items-center justify-center px-6 text-center">
      <h1 className="font-display text-3xl font-light text-ink-50">
        Something went wrong
      </h1>
      <p className="mt-3 max-w-sm text-sm leading-relaxed text-ink-400">
        We hit an unexpected problem. Trying again usually helps.
      </p>
      {error.digest && (
        <p className="mt-4 font-mono text-[0.7rem] text-ink-500">
          Reference: {error.digest}
        </p>
      )}
      <Button onClick={reset} className="mt-8">
        <RotateCcw className="h-4 w-4" aria-hidden />
        Try again
      </Button>
    </main>
  );
}
