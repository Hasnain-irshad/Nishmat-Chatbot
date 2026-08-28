"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ButtonLink } from "@/components/ui/Button";
import { Logo } from "@/components/ui/Logo";
import { cn } from "@/lib/utils";

export function LandingNav() {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header
      className={cn(
        "fixed inset-x-0 top-0 z-50 transition-all duration-500 ease-[cubic-bezier(0.16,1,0.3,1)]",
        scrolled ? "py-3" : "py-5",
      )}
    >
      <nav
        className={cn(
          "mx-auto flex max-w-5xl items-center justify-between rounded-full px-4 py-2 transition-all duration-500 sm:px-5",
          scrolled
            ? "glass glass-gold w-[calc(100%-1.5rem)] shadow-panel"
            : "w-[calc(100%-1.5rem)] border border-transparent bg-transparent",
        )}
      >
        <Link
          href="/"
          className="group flex items-center gap-2.5 rounded-full pr-3"
          aria-label="Nishmat AI home"
        >
          <Logo size={32} className="transition-transform duration-500 group-hover:rotate-[8deg]" />
          <span className="font-display text-lg font-medium tracking-wide text-ink-50">
            Nishmat AI
          </span>
        </Link>

        <div className="flex items-center gap-1.5 sm:gap-2">
          <ButtonLink href="/sign-in" variant="ghost" size="sm">
            Sign in
          </ButtonLink>
          <ButtonLink href="/sign-up" variant="primary" size="sm">
            Create account
          </ButtonLink>
        </div>
      </nav>
    </header>
  );
}
