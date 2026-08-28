import { NextResponse, type NextRequest } from "next/server";
import { createClient } from "@/lib/supabase/server";

/**
 * OAuth / magic-link landing point, and the single place where a signed-in
 * person is routed to the dashboard that matches their role.
 *
 * The role is read from `profiles` — never from a URL parameter and never from
 * client-supplied metadata.
 */
export async function GET(request: NextRequest) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");
  const requestedNext = searchParams.get("next");
  const authError = searchParams.get("error_description") ?? searchParams.get("error");

  if (authError) {
    return NextResponse.redirect(
      `${origin}/sign-in?error=${encodeURIComponent("Sign-in was cancelled or failed. Please try again.")}`,
    );
  }

  const supabase = await createClient();

  // OAuth and email links arrive with a code to exchange. A plain password
  // sign-in redirects here with a session already established.
  if (code) {
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (error) {
      return NextResponse.redirect(
        `${origin}/sign-in?error=${encodeURIComponent("That sign-in link is no longer valid. Please try again.")}`,
      );
    }
  }

  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.redirect(`${origin}/sign-in`);
  }

  const { data: profile } = await supabase
    .from("profiles")
    .select("role")
    .eq("id", user.id)
    .single();

  const isAdmin = profile?.role === "admin";
  const home = isAdmin ? "/admin" : "/app";

  // Honour `next` only when it is a safe same-origin path the person may see.
  const next = safeNext(requestedNext, isAdmin) ?? home;

  return NextResponse.redirect(`${origin}${next}`);
}

/**
 * Guards against open-redirects (`next=https://evil.example`) and against a
 * learner being bounced into an admin route they will only be rejected from.
 */
function safeNext(next: string | null, isAdmin: boolean): string | null {
  if (!next) return null;
  if (!next.startsWith("/") || next.startsWith("//")) return null;
  if (next.startsWith("/admin") && !isAdmin) return null;
  if (next === "/sign-in" || next === "/sign-up") return null;
  return next;
}
