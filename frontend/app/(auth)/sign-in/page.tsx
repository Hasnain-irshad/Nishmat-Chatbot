import { Suspense } from "react";
import type { Metadata } from "next";
import { AuthForm } from "@/components/auth/AuthForm";
import { getAuthSettings } from "@/lib/auth-settings";

export const metadata: Metadata = {
  title: "Sign in",
  description: "Sign in to continue your journey through Nishmat.",
};

export default async function SignInPage() {
  const providers = await getAuthSettings();

  return (
    <>
      <div className="mb-7 text-center">
        <h1 className="font-display text-3xl font-light text-ink-50">
          Welcome back
        </h1>
        <p className="mt-2 text-sm text-ink-400">
          Continue where you left off.
        </p>
      </div>
      <Suspense fallback={<FormSkeleton />}>
        <AuthForm mode="sign-in" providers={providers} />
      </Suspense>
    </>
  );
}

function FormSkeleton() {
  return (
    <div className="space-y-4" aria-hidden>
      <div className="h-12 animate-pulse rounded-full bg-white/5" />
      <div className="h-4" />
      <div className="h-16 animate-pulse rounded-xl bg-white/5" />
      <div className="h-16 animate-pulse rounded-xl bg-white/5" />
      <div className="h-12 animate-pulse rounded-full bg-white/5" />
    </div>
  );
}
