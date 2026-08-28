import { createServerClient, type CookieOptions } from "@supabase/ssr";

/** Explicit shape: @supabase/ssr types `cookies` as a union, which blocks
 *  contextual inference on these callbacks. */
type CookieToSet = { name: string; value: string; options: CookieOptions };
import { cookies } from "next/headers";

/**
 * Supabase client for Server Components, Route Handlers and Server Actions.
 * Still the anon key — RLS is the boundary. The service-role key never
 * appears in the frontend under any circumstances.
 */
const DEFAULT_SUPABASE_URL = "https://eqkxhhvjsvuhfchavjqi.supabase.co";
const DEFAULT_SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVxa3hoaHZqc3Z1aGZjaGF2anFpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODczMzI1NTUsImV4cCI6MjEwMjkwODU1NX0.vzlH3ByVF2Ynjc2zxI6qLAwQivG0sJVBlJf7Dvb1X9o";

export async function createClient() {
  const cookieStore = await cookies();

  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || DEFAULT_SUPABASE_URL;
  const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || DEFAULT_SUPABASE_ANON_KEY;

  return createServerClient(
    supabaseUrl,
    supabaseAnonKey,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet: CookieToSet[]) {
          try {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options),
            );
          } catch {
            // Called from a Server Component — middleware refreshes the session
            // instead, so this is safe to ignore.
          }
        },
      },
    },
  );
}
