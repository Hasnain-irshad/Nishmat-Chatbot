import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Format a date into the "Today / Yesterday / This week / Earlier" buckets. */
export function relativeBucket(date: string | Date): string {
  const d = typeof date === "string" ? new Date(date) : date;
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const diffDays = Math.floor((startOfToday.getTime() - d.getTime()) / 86_400_000);

  if (d >= startOfToday) return "Today";
  if (diffDays < 1) return "Yesterday";
  if (diffDays < 7) return "This week";
  if (diffDays < 30) return "This month";
  return "Earlier";
}

export function formatDate(date: string | Date): string {
  const d = typeof date === "string" ? new Date(date) : date;
  return d.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

/** True when the string contains Hebrew codepoints. */
export function hasHebrew(text: string): boolean {
  return /[\u0590-\u05FF]/.test(text);
}

/**
 * Initials for an avatar fallback.
 * Lives here rather than in lib/auth so client components can use it without
 * dragging `next/headers` into the browser bundle.
 */
export function initialsOf(profile: {
  full_name?: string | null;
  email: string;
}): string {
  const source = profile.full_name?.trim() || profile.email;
  const parts = source.split(/[\s@._-]+/).filter(Boolean);
  return (parts[0]?.[0] ?? "?").concat(parts[1]?.[0] ?? "").toUpperCase();
}
