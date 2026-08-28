import { Suspense } from "react";
import type { Metadata } from "next";
import { AuthForm } from "@/components/auth/AuthForm";
import { getAuthSettings } from "@/lib/auth-settings";

export const metadata: Metadata = {
  title: "Create your account",
  description: "Join the Nishmat learning community.",
};

export default async function SignUpPage() {
  const providers = await getAuthSettings();

  return (
    <>
      <div className="mb-7 text-center">
        <h1 className="font-display text-3xl font-light text-ink-50">
          Join the journey
        </h1>
        <p className="mt-2 text-sm text-ink-400">
          One word at a time, one week at a time.
        </p>
      </div>
      <Suspense fallback={<div className="h-80 animate-pulse rounded-xl bg-white/5" />}>
        <AuthForm mode="sign-up" providers={providers} />
      </Suspense>
    </>
  );
}
