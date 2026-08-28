"use client";

import Link from "next/link";
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "outline" | "danger";
type Size = "sm" | "md" | "lg";

const base =
  "relative inline-flex items-center justify-center gap-2 overflow-hidden rounded-full font-medium " +
  "transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] " +
  "disabled:pointer-events-none disabled:opacity-45 " +
  "active:scale-[0.975] whitespace-nowrap";

const variants: Record<Variant, string> = {
  primary:
    "shimmer bg-gradient-to-r from-gold-200 via-gold-300 to-gold-400 text-night-950 " +
    "shadow-[0_8px_30px_-8px_rgba(237,201,106,0.6)] " +
    "hover:shadow-[0_14px_44px_-10px_rgba(237,201,106,0.75)] hover:-translate-y-0.5",
  secondary:
    "bg-violet-500/85 text-ink-50 hover:bg-violet-500 " +
    "shadow-[0_8px_30px_-10px_rgba(139,92,246,0.7)] hover:-translate-y-0.5",
  ghost: "text-ink-200 hover:bg-white/[0.07] hover:text-ink-50",
  outline:
    "glass text-ink-50 border-white/15 hover:border-gold-300/45 " +
    "hover:bg-white/[0.07] hover:-translate-y-0.5",
  danger: "bg-danger/90 text-white hover:bg-danger",
};

const sizes: Record<Size, string> = {
  sm: "h-9 px-4 text-sm",
  md: "h-11 px-6 text-[0.95rem]",
  lg: "h-13 px-8 text-base",
};

interface CommonProps {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  className?: string;
  children: ReactNode;
}

export const Button = forwardRef<
  HTMLButtonElement,
  CommonProps & Omit<ButtonHTMLAttributes<HTMLButtonElement>, "className" | "children">
>(function Button(
  { variant = "primary", size = "md", loading, className, children, disabled, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cn(base, variants[variant], sizes[size], className)}
      {...props}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
      <span className="relative z-10 inline-flex items-center gap-2">{children}</span>
    </button>
  );
});

export function ButtonLink({
  href,
  variant = "primary",
  size = "md",
  className,
  children,
  ...props
}: CommonProps & { href: string } & Omit<
    React.ComponentProps<typeof Link>,
    "href" | "className" | "children"
  >) {
  return (
    <Link
      href={href}
      className={cn(base, variants[variant], sizes[size], className)}
      {...props}
    >
      <span className="relative z-10 inline-flex items-center gap-2">{children}</span>
    </Link>
  );
}
