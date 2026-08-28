"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { createClient } from "@/lib/supabase/client";

export function GoogleButton({
  nextPath,
  onError,
}: {
  nextPath: string;
  onError: (msg: string) => void;
}) {
  const [loading, setLoading] = useState(false);

  async function signInWithGoogle() {
    setLoading(true);
    onError("");
    const supabase = createClient();

    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: `${window.location.origin}/auth/callback?next=${encodeURIComponent(nextPath)}`,
        queryParams: { access_type: "offline", prompt: "consent" },
      },
    });

    if (error) {
      setLoading(false);
      onError("We couldn't start Google sign-in. Please try again.");
    }
    // On success the browser navigates away — leave the spinner running.
  }

  return (
    <button
      type="button"
      onClick={signInWithGoogle}
      disabled={loading}
      className="group relative flex h-12 w-full items-center justify-center gap-3 overflow-hidden rounded-full
                 border border-white/12 bg-white/[0.05] px-6 text-[0.95rem] font-medium text-ink-50
                 transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]
                 hover:-translate-y-0.5 hover:border-white/25 hover:bg-white/[0.09]
                 hover:shadow-[0_12px_36px_-12px_rgba(255,255,255,0.25)]
                 active:scale-[0.985] disabled:pointer-events-none disabled:opacity-50"
    >
      {loading ? (
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
      ) : (
        <GoogleMark />
      )}
      {loading ? "Connecting to Google…" : "Continue with Google"}
    </button>
  );
}

function GoogleMark() {
  return (
    <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" aria-hidden>
      <path
        fill="#4285F4"
        d="M23.52 12.27c0-.79-.07-1.54-.2-2.27H12v4.51h6.47a5.53 5.53 0 0 1-2.4 3.63v3h3.87c2.26-2.09 3.58-5.17 3.58-8.87Z"
      />
      <path
        fill="#34A853"
        d="M12 24c3.24 0 5.96-1.08 7.94-2.91l-3.87-3c-1.08.72-2.45 1.16-4.07 1.16-3.13 0-5.78-2.11-6.73-4.96H1.28v3.09A12 12 0 0 0 12 24Z"
      />
      <path
        fill="#FBBC05"
        d="M5.27 14.29a7.2 7.2 0 0 1 0-4.58V6.62H1.28a12 12 0 0 0 0 10.76l3.99-3.09Z"
      />
      <path
        fill="#EA4335"
        d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.43-3.43C17.95 1.19 15.24 0 12 0A12 12 0 0 0 1.28 6.62l3.99 3.09C6.22 6.86 8.87 4.75 12 4.75Z"
      />
    </svg>
  );
}
