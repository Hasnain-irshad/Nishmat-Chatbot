import { cache } from "react";

/**
 * Which sign-in methods this Supabase project actually has enabled.
 *
 * Supabase publishes this at `/auth/v1/settings`. Reading it means the UI can
 * only offer what will actually work — previously the Google button was always
 * shown, and clicking it navigated the browser straight to a raw Supabase
 * error page:
 *
 *     {"code":400,"error_code":"validation_failed",
 *      "msg":"Unsupported provider: provider is not enabled"}
 *
 * That failure cannot be caught in our code, because `signInWithOAuth`
 * redirects away before anything comes back. The only real fix is to not
 * render the button unless the provider is live.
 */

export interface AuthSettings {
  google: boolean;
  emailPassword: boolean;
  /** true when Supabase sends a confirmation link instead of signing in directly */
  requiresEmailConfirmation: boolean;
}

const FALLBACK: AuthSettings = {
  google: false,
  emailPassword: true,
  requiresEmailConfirmation: true,
};

export const getAuthSettings = cache(async (): Promise<AuthSettings> => {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anonKey) return FALLBACK;

  try {
    const response = await fetch(`${url.replace(/\/$/, "")}/auth/v1/settings`, {
      headers: { apikey: anonKey },
      // Providers change rarely; a short cache avoids a request per page view
      // without making a config change take effect only after a redeploy.
      next: { revalidate: 300 },
    });

    if (!response.ok) return FALLBACK;

    const data = (await response.json()) as {
      external?: Record<string, boolean>;
      mailer_autoconfirm?: boolean;
    };

    return {
      google: data.external?.google === true,
      emailPassword: data.external?.email !== false,
      requiresEmailConfirmation: data.mailer_autoconfirm !== true,
    };
  } catch {
    // Never let a settings lookup break the sign-in page — fall back to the
    // method that is always available.
    return FALLBACK;
  }
});
