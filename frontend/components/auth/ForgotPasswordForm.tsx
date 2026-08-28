"use client";

import { useState } from "react";
import Link from "next/link";
import { CheckCircle2, Mail } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { Button } from "@/components/ui/Button";

export function ForgotPasswordForm() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);

    const supabase = createClient();
    await supabase.auth.resetPasswordForEmail(email.trim(), {
      redirectTo: `${window.location.origin}/auth/callback?next=/app/settings`,
    });

    // Always report success — telling the caller whether an address exists
    // would let anyone enumerate the user list.
    setLoading(false);
    setSent(true);
  }

  if (sent) {
    return (
      <div className="text-center">
        <CheckCircle2 className="mx-auto h-10 w-10 text-success" aria-hidden />
        <p className="mt-4 text-sm leading-relaxed text-ink-200">
          If an account exists for <strong className="text-ink-50">{email}</strong>,
          a reset link is on its way.
        </p>
        <Link
          href="/sign-in"
          className="mt-6 inline-block text-sm font-medium text-gold-200 hover:underline"
        >
          Back to sign in
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label
          htmlFor="reset-email"
          className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-ink-400"
        >
          Email
        </label>
        <div className="group flex items-center gap-2.5 rounded-xl border border-white/10 bg-white/[0.04] px-3.5
                        transition-all duration-300 focus-within:border-gold-300/50 focus-within:bg-white/[0.06]">
          <Mail className="h-4 w-4 shrink-0 text-ink-500 group-focus-within:text-gold-300" />
          <input
            id="reset-email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            autoComplete="email"
            className="h-11 w-full bg-transparent text-[0.95rem] text-ink-50 outline-none placeholder:text-ink-500/70"
          />
        </div>
      </div>

      <Button type="submit" size="lg" loading={loading} className="w-full">
        Send reset link
      </Button>

      <p className="pt-2 text-center text-sm text-ink-400">
        Remembered it?{" "}
        <Link href="/sign-in" className="font-medium text-gold-200 hover:underline">
          Sign in
        </Link>
      </p>
    </form>
  );
}
