import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { Aurora } from "@/components/landing/Aurora";
import { Starfield } from "@/components/landing/Starfield";
import { Divider } from "@/components/landing/Divider";
import { Logo } from "@/components/ui/Logo";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <Aurora />
      <Starfield />

      <main className="grain relative z-10 flex min-h-svh flex-col items-center justify-center px-5 py-14">
        <Link
          href="/"
          className="group absolute left-5 top-6 inline-flex items-center gap-2 rounded-full px-3 py-2
                     text-sm text-ink-400 transition-colors hover:text-ink-100 sm:left-8 sm:top-8"
        >
          <ArrowLeft
            className="h-4 w-4 transition-transform duration-300 group-hover:-translate-x-0.5"
            aria-hidden
          />
          Back
        </Link>

        <div className="w-full max-w-md">
          {/* Mark */}
          <div className="mb-9 flex flex-col items-center text-center">
            <Logo size={56} glow />
            <p className="mt-4 font-display text-2xl font-light text-ink-50">
              Nishmat AI
            </p>
            <p className="mt-1 text-[0.65rem] uppercase tracking-[0.38em] text-ink-400">
              A Journey of Praise
            </p>
          </div>

          <div className="glass glass-gold rounded-xl3 px-6 py-8 shadow-panel sm:px-9 sm:py-10">
            {children}
          </div>

          <Divider className="mx-auto mt-10 max-w-[14rem]" mark="dot" />
          <p className="mt-5 text-center text-[0.7rem] leading-relaxed text-ink-500">
            By continuing you agree to use this space respectfully,
            <br />
            in the spirit of the learning it was created for.
          </p>
        </div>
      </main>
    </>
  );
}
