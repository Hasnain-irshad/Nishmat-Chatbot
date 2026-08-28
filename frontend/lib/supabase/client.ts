"use client";

import { createBrowserClient } from "@supabase/ssr";

/** Supabase client for Client Components. Uses the anon key — RLS applies. */
const DEFAULT_SUPABASE_URL = "https://eqkxhhvjsvuhfchavjqi.supabase.co";
const DEFAULT_SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVxa3hoaHZqc3Z1aGZjaGF2anFpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODczMzI1NTUsImV4cCI6MjEwMjkwODU1NX0.vzlH3ByVF2Ynjc2zxI6qLAwQivG0sJVBlJf7Dvb1X9o";

export function createClient() {
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || DEFAULT_SUPABASE_URL;
  const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || DEFAULT_SUPABASE_ANON_KEY;

  return createBrowserClient(
    supabaseUrl,
    supabaseAnonKey,
  );
}
