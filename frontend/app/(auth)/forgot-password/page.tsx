import type { Metadata } from "next";
import { ForgotPasswordForm } from "@/components/auth/ForgotPasswordForm";

export const metadata: Metadata = { title: "Reset your password" };

export default function ForgotPasswordPage() {
  return (
    <>
      <div className="mb-7 text-center">
        <h1 className="font-display text-3xl font-light text-ink-50">
          Reset your password
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-ink-400">
          Enter your email and we&rsquo;ll send you a link to set a new one.
        </p>
      </div>
      <ForgotPasswordForm />
    </>
  );
}
