"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertCircle, CheckCircle2, Eye, EyeOff, Mail, Lock, User } from "lucide-react";

import { createClient } from "@/lib/supabase/client";
import { Button } from "@/components/ui/Button";
import { GoogleButton } from "@/components/auth/GoogleButton";
import { cn } from "@/lib/utils";

type Mode = "sign-in" | "sign-up";

const MIN_PASSWORD = 8;

export function AuthForm({
  mode,
  providers,
}: {
  mode: Mode;
  /** Which methods this project actually has enabled. */
  providers: { google: boolean; requiresEmailConfirmation: boolean };
}) {
  const router = useRouter();
  const params = useSearchParams();
  const nextPath = params.get("next") ?? "/app";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const isSignUp = mode === "sign-up";

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);

    if (isSignUp && password.length < MIN_PASSWORD) {
      setError(`Please choose a password of at least ${MIN_PASSWORD} characters.`);
      return;
    }

    setLoading(true);
    const supabase = createClient();

    try {
      if (isSignUp) {
        const { data, error } = await supabase.auth.signUp({
          email: email.trim(),
          password,
          options: {
            // `role` is deliberately NOT sent. It is set by the database
            // trigger and can never be chosen by the person signing up.
            data: { full_name: fullName.trim() || null },
            emailRedirectTo: `${window.location.origin}/auth/callback?next=${encodeURIComponent(nextPath)}`,
          },
        });
        if (error) throw error;

        // Supabase returns a user with no identities when the address already
        // exists but confirmation is pending — do not leak which it was.
        if (data.user && data.user.identities?.length === 0) {
          setNotice("Check your inbox — we've sent you a confirmation link.");
          return;
        }
        if (!data.session) {
          setNotice("Almost there. Check your inbox to confirm your address.");
          return;
        }
        router.push("/auth/callback?next=" + encodeURIComponent(nextPath));
        router.refresh();
      } else {
        const { error } = await supabase.auth.signInWithPassword({
          email: email.trim(),
          password,
        });
        if (error) throw error;
        router.push("/auth/callback?next=" + encodeURIComponent(nextPath));
        router.refresh();
      }
    } catch (err) {
      setError(friendlyAuthError(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="w-full">
      {providers.google && (
        <>
          <GoogleButton nextPath={nextPath} onError={setError} />

          <div className="my-6 flex items-center gap-4">
            <span className="rule-glow flex-1" />
            <span className="text-[0.7rem] uppercase tracking-[0.25em] text-ink-500">
              or
            </span>
            <span className="rule-glow flex-1" />
          </div>
        </>
      )}

      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        {isSignUp && (
          <Field
            id="fullName"
            label="Your name"
            icon={User}
            type="text"
            value={fullName}
            onChange={setFullName}
            placeholder="Rivkah"
            autoComplete="name"
          />
        )}

        <Field
          id="email"
          label="Email"
          icon={Mail}
          type="email"
          value={email}
          onChange={setEmail}
          placeholder="you@example.com"
          autoComplete="email"
          required
        />

        <div>
          <Field
            id="password"
            label="Password"
            icon={Lock}
            type={showPassword ? "text" : "password"}
            value={password}
            onChange={setPassword}
            placeholder={isSignUp ? `At least ${MIN_PASSWORD} characters` : "••••••••"}
            autoComplete={isSignUp ? "new-password" : "current-password"}
            required
            trailing={
              <button
                type="button"
                onClick={() => setShowPassword((s) => !s)}
                className="rounded-md p-1 text-ink-400 transition-colors hover:text-ink-200"
                aria-label={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? (
                  <EyeOff className="h-4 w-4" aria-hidden />
                ) : (
                  <Eye className="h-4 w-4" aria-hidden />
                )}
              </button>
            }
          />
          {!isSignUp && (
            <div className="mt-2 text-right">
              <Link
                href="/forgot-password"
                className="text-xs text-ink-400 transition-colors hover:text-gold-200"
              >
                Forgot your password?
              </Link>
            </div>
          )}
        </div>

        {error && (
          <p
            role="alert"
            className="flex items-start gap-2 rounded-xl border border-danger/25 bg-danger/10 px-3.5 py-2.5 text-sm text-rose-300"
          >
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            {error}
          </p>
        )}

        {notice && (
          <p
            role="status"
            className="flex items-start gap-2 rounded-xl border border-success/25 bg-success/10 px-3.5 py-2.5 text-sm text-green-300"
          >
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            {notice}
          </p>
        )}

        <Button type="submit" size="lg" loading={loading} className="w-full">
          {isSignUp ? "Create my account" : "Sign in"}
        </Button>
      </form>

      <p className="mt-7 text-center text-sm text-ink-400">
        {isSignUp ? "Already have an account?" : "New here?"}{" "}
        <Link
          href={isSignUp ? "/sign-in" : "/sign-up"}
          className="font-medium text-gold-200 underline-offset-4 transition-colors hover:text-gold-100 hover:underline"
        >
          {isSignUp ? "Sign in" : "Create an account"}
        </Link>
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ field */

interface FieldProps {
  id: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  type: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  autoComplete?: string;
  required?: boolean;
  trailing?: React.ReactNode;
}

function Field({
  id,
  label,
  icon: Icon,
  type,
  value,
  onChange,
  placeholder,
  autoComplete,
  required,
  trailing,
}: FieldProps) {
  return (
    <div>
      <label
        htmlFor={id}
        className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-ink-400"
      >
        {label}
      </label>
      <div
        className={cn(
          "group flex items-center gap-2.5 rounded-xl border border-white/10 bg-white/[0.04] px-3.5",
          "transition-all duration-300 focus-within:border-gold-300/50 focus-within:bg-white/[0.06]",
          "focus-within:shadow-[0_0_0_4px_rgba(237,201,106,0.09)]",
        )}
      >
        <Icon className="h-4 w-4 shrink-0 text-ink-500 transition-colors group-focus-within:text-gold-300" />
        <input
          id={id}
          name={id}
          type={type}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          autoComplete={autoComplete}
          required={required}
          className="h-11 w-full bg-transparent text-[0.95rem] text-ink-50 outline-none placeholder:text-ink-500/70"
        />
        {trailing}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ errors */

/**
 * Supabase error strings are developer-facing. Map the common ones to
 * something a person can act on, and never confirm whether an address exists.
 */
function friendlyAuthError(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err);
  const m = raw.toLowerCase();

  if (m.includes("invalid login credentials"))
    return "That email and password don't match. Please try again.";
  if (m.includes("email not confirmed"))
    return "Please confirm your email address first — check your inbox for the link.";
  if (m.includes("user already registered") || m.includes("already been registered"))
    return "An account with that email already exists. Try signing in instead.";
  if (m.includes("password should be at least"))
    return `Please choose a password of at least ${MIN_PASSWORD} characters.`;
  if (m.includes("rate limit") || m.includes("too many"))
    return "Too many attempts. Please wait a moment and try again.";
  if (m.includes("network") || m.includes("fetch"))
    return "We couldn't reach the server. Check your connection and try again.";

  return "Something went wrong. Please try again in a moment.";
}
