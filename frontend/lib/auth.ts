import { redirect } from "next/navigation";
import { cache } from "react";

import { createClient } from "@/lib/supabase/server";
import type { Profile } from "@/types/database";

/**
 * The signed-in person's profile, or null.
 *
 * `cache()` dedupes this across a single render pass, so a layout and the page
 * inside it share one round-trip rather than two.
 */
export const getProfile = cache(async (): Promise<Profile | null> => {
  const supabase = await createClient();

  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return null;

  const { data } = await supabase
    .from("profiles")
    .select("id, email, full_name, avatar_url, role, created_at")
    .eq("id", user.id)
    .single();

  return (data as Profile) ?? null;
});

/** Require any authenticated person. Redirects to sign-in otherwise. */
export async function requireUser(nextPath?: string): Promise<Profile> {
  const profile = await getProfile();
  if (!profile) {
    const qs = nextPath ? `?next=${encodeURIComponent(nextPath)}` : "";
    redirect(`/sign-in${qs}`);
  }
  return profile;
}

/**
 * Require an admin.
 *
 * This is the role gate for every /admin page. It reads the role from the
 * database, so hiding a nav item is never what keeps a learner out — and
 * the FastAPI backend performs the same check independently on every call.
 */
export async function requireAdmin(nextPath?: string): Promise<Profile> {
  const profile = await requireUser(nextPath);
  if (profile.role !== "admin") redirect("/app");
  return profile;
}
