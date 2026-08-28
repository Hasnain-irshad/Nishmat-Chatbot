/**
 * Client for the FastAPI backend.
 *
 * Where each call runs matters:
 *
 *   - Reads that just display data go straight to Supabase under RLS (see the
 *     server components). That avoids a second network hop.
 *   - Everything that MUTATES, and everything involving AI, goes through here
 *     — because that is where `require_admin` lives and where the OpenAI key
 *     lives. Neither may ever be in the browser.
 *
 * The backend re-checks the role on every call, so nothing here is trusted.
 */

import { createClient as createBrowserClient } from "@/lib/supabase/client";
import type { LessonStatus } from "@/types/database";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ||
  "https://nishmat-ai-production.up.railway.app";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
    readonly requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** True when retrying might plausibly succeed. */
  get isTransient(): boolean {
    return this.status === 503 || this.status === 429 || this.status >= 500;
  }
}

interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  /** Supply a token explicitly (server components); otherwise read the session. */
  token?: string;
  /** Multipart uploads set their own content type. */
  raw?: BodyInit;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, token, raw, headers, ...rest } = options;

  const authToken = token ?? (await getBrowserToken());

  const finalHeaders: Record<string, string> = {
    ...(headers as Record<string, string>),
  };
  if (authToken) finalHeaders.Authorization = `Bearer ${authToken}`;
  if (body !== undefined && !raw) finalHeaders["Content-Type"] = "application/json";

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      ...rest,
      headers: finalHeaders,
      body: raw ?? (body !== undefined ? JSON.stringify(body) : undefined),
      cache: "no-store",
    });
  } catch {
    throw new ApiError(
      "We couldn't reach the server. Check your connection and try again.",
      0,
      "network_error",
    );
  }

  if (response.status === 204) return undefined as T;

  const payload = await response.json().catch(() => null);

  if (!response.ok) {
    throw new ApiError(
      payload?.error ?? "Something went wrong. Please try again.",
      response.status,
      payload?.code,
      payload?.request_id ?? response.headers.get("X-Request-ID") ?? undefined,
    );
  }

  return payload as T;
}

async function getBrowserToken(): Promise<string | undefined> {
  if (typeof window === "undefined") return undefined;
  const supabase = createBrowserClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  return session?.access_token;
}

/* ------------------------------------------------------------------ types */

export interface LessonSummary {
  id: string;
  title: string;
  lesson_number: number | null;
  hebrew_phrase: string | null;
  transliteration: string | null;
  status: LessonStatus;
  needs_review: boolean;
  review_notes: string | null;
  published_at: string | null;
  updated_at: string;
  has_unpublished_changes: boolean;
}

export interface LessonSection {
  key: string;
  title: string | null;
  body: string;
  dir: "ltr" | "rtl";
  order: number;
}

export interface LessonVersionDetail {
  id: string;
  version_number: number;
  content: { sections: LessonSection[] };
  content_text: string;
  word_count: number;
  origin: string;
  modification_instruction: string | null;
  quality_report: unknown | null;
  /** Which sources the draft was written from, and by which prompt version. */
  model_metadata?: {
    prompt_version?: string;
    sources_used?: Record<string, string[]>;
    brief?: Record<string, string>;
    series_context?: { recent?: number[]; next?: number | null };
    estimated_cost_usd?: number;
  } | null;
  created_at: string;
}

/**
 * What a lesson is meant to teach.
 *
 * Every field optional and any one is enough — the client builds lessons
 * around a phrase, a single Hebrew word, a Psalm, or just "something for Elul",
 * and the form should not insist on more than she has.
 */
export interface GenerationBrief {
  phrase?: string | null;
  hebrew_word?: string | null;
  theme?: string | null;
  psalm?: string | null;
  commentator?: string | null;
  seasonal?: string | null;
  objective?: string | null;
  length?: "short" | "standard" | "long" | null;
  notes?: string | null;
}

export interface LessonDetail extends LessonSummary {
  series_id: string | null;
  template_id: string | null;
  translation: string | null;
  summary: string | null;
  current_version_id: string | null;
  published_version_id: string | null;
  created_at: string;
  current_version: LessonVersionDetail | null;
  generation_brief: GenerationBrief | null;
}

/** A page of a physical book, photographed and attached to one lesson. */
export interface ReferencePage {
  source_file_id: string;
  filename: string;
  kind: string;
  book: string | null;
  page: string | null;
  processing_status: "pending" | "processing" | "completed" | "failed";
  error_message: string | null;
  word_count: number | null;
  indexed_chunks: number;
  created_at: string;
}

export interface CorpusDocument {
  id: string;
  title: string;
  kind: string;
  authority: string;
  variant: string | null;
  language: string | null;
  attribution: string | null;
  chunks: number | null;
  is_active: boolean;
  updated_at: string | null;
}

export interface CorpusStatus {
  documents: CorpusDocument[];
  /** What the pipeline is built to use but does not yet hold. */
  missing: string[];
}

export interface VersionSummary {
  id: string;
  version_number: number;
  origin: string;
  modification_instruction: string | null;
  word_count: number;
  created_at: string;
  created_by: string | null;
  is_published: boolean;
  is_current: boolean;
}

export interface JobStatus {
  id: string;
  type: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  progress_stage: string | null;
  progress_pct: number;
  error: string | null;
  result: Record<string, unknown> | null;
  lesson_id: string | null;
}

export interface Citation {
  lesson_id: string;
  lesson_number: number | null;
  title: string;
  section: string | null;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  created_at: string;
}

export interface Conversation {
  id: string;
  title: string;
  lesson_id: string | null;
  message_count: number;
  last_message_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail extends Conversation {
  messages: ChatMessage[];
}

export interface AnswerResult {
  question: ChatMessage;
  answer: ChatMessage;
  grounded: boolean;
  conversation_title: string;
}

export interface AdminOverview {
  lessons_total: number;
  lessons_published: number;
  lessons_needing_review: number;
  style_examples: number;
  ai_spend_usd: number;
  ai_spend_cap_usd: number;
}

/* ---------------------------------------------------------------- endpoints */

export const api = {
  overview: (token?: string) =>
    request<AdminOverview>("/admin/overview", { token }),

  lessons: {
    create: (
      payload: {
        // Both optional: the composer does not ask, and the backend derives
        // them from the uploaded source.
        title?: string;
        lesson_number?: number | null;
        template_id?: string | null;
        source_file_ids?: string[];
        note?: string;
        brief?: GenerationBrief;
      },
      token?: string,
    ) =>
      request<LessonDetail>("/admin/lessons", {
        method: "POST",
        body: payload,
        token,
      }),

    list: (
      params: {
        status?: string;
        q?: string;
        needs_review?: boolean;
        limit?: number;
        offset?: number;
      } = {},
      token?: string,
    ) => {
      const search = new URLSearchParams();
      for (const [key, value] of Object.entries(params)) {
        if (value !== undefined && value !== "") search.set(key, String(value));
      }
      const query = search.toString();
      return request<LessonSummary[]>(
        `/admin/lessons${query ? `?${query}` : ""}`,
        { token },
      );
    },

    get: (id: string, token?: string) =>
      request<LessonDetail>(`/admin/lessons/${id}`, { token }),

    update: (id: string, changes: Partial<LessonSummary>, token?: string) =>
      request<LessonSummary>(`/admin/lessons/${id}`, {
        method: "PATCH",
        body: changes,
        token,
      }),

    remove: (id: string, token?: string) =>
      request<void>(`/admin/lessons/${id}`, { method: "DELETE", token }),

    versions: (id: string, token?: string) =>
      request<VersionSummary[]>(`/admin/lessons/${id}/versions`, { token }),

    version: (id: string, versionId: string, token?: string) =>
      request<LessonVersionDetail>(
        `/admin/lessons/${id}/versions/${versionId}`,
        { token },
      ),

    saveVersion: (
      id: string,
      content: { sections: LessonSection[] },
      note?: string,
      token?: string,
    ) =>
      request<LessonVersionDetail>(`/admin/lessons/${id}/versions`, {
        method: "POST",
        body: { content, note },
        token,
      }),

    restoreVersion: (id: string, versionId: string, token?: string) =>
      request<LessonVersionDetail>(
        `/admin/lessons/${id}/versions/${versionId}/restore`,
        { method: "POST", token },
      ),

    /**
     * Queue a draft.
     *
     * Omitting `brief` keeps whatever brief is stored on the lesson — a plain
     * Regenerate must not silently clear the instructions the admin wrote.
     */
    generate: (
      id: string,
      note?: string,
      brief?: GenerationBrief,
      token?: string,
    ) =>
      request<{ job_id: string; already_running: boolean }>(
        `/admin/lessons/${id}/generate`,
        { method: "POST", body: { note, brief }, token },
      ),

    modify: (
      id: string,
      payload: {
        instruction: string;
        scope: "section" | "lesson";
        section_key?: string;
        selected_text?: string;
      },
      token?: string,
    ) =>
      request<{
        scope: string;
        section_key: string | null;
        original: string | null;
        revised: string | null;
        sections: LessonSection[] | null;
        warnings: string[];
        cost_usd: number;
      }>(`/admin/lessons/${id}/modify`, { method: "POST", body: payload, token }),

    publish: (id: string, versionId: string, token?: string) =>
      request<LessonSummary>(`/admin/lessons/${id}/publish`, {
        method: "POST",
        body: { version_id: versionId },
        token,
      }),

    unpublish: (id: string, token?: string) =>
      request<LessonSummary>(`/admin/lessons/${id}/unpublish`, {
        method: "POST",
        token,
      }),
  },

  templates: {
    list: (token?: string) => request<unknown[]>("/admin/templates", { token }),

    get: (id: string, token?: string) =>
      request<{ id: string; version: number }>(`/admin/templates/${id}`, { token }),

    update: (
      id: string,
      changes: {
        name?: string;
        series_title?: string | null;
        signoff?: string | null;
        style_guide?: string;
        sections?: unknown[];
      },
      token?: string,
    ) =>
      request<{ id: string; version: number }>(`/admin/templates/${id}`, {
        method: "PATCH",
        body: changes,
        token,
      }),
  },

  chat: {
    createConversation: (lessonId?: string) =>
      request<Conversation>("/chat/conversations", {
        method: "POST",
        body: { lesson_id: lessonId ?? null },
      }),

    listConversations: (token?: string) =>
      request<Conversation[]>("/chat/conversations", { token }),

    getConversation: (id: string, token?: string) =>
      request<ConversationDetail>(`/chat/conversations/${id}`, { token }),

    rename: (id: string, title: string) =>
      request<Conversation>(`/chat/conversations/${id}`, {
        method: "PATCH",
        body: { title },
      }),

    remove: (id: string) =>
      request<void>(`/chat/conversations/${id}`, { method: "DELETE" }),

    send: (id: string, content: string) =>
      request<AnswerResult>(`/chat/conversations/${id}/messages`, {
        method: "POST",
        body: { content },
      }),
  },

  files: {
    /**
     * `role` says what the file IS, not what format it is in.
     *
     *   lesson_source — the recording or document the lesson is made from.
     *   reference     — a photographed page of a book to consult while writing
     *                   it. Attributed, scoped to the lesson, never shown to a
     *                   learner.
     */
    upload: async (
      file: File,
      lessonId?: string,
      options: {
        role?: "lesson_source" | "reference";
        book?: string;
        page?: string;
      } = {},
    ) => {
      const form = new FormData();
      form.append("file", file);
      if (lessonId) form.append("lesson_id", lessonId);
      if (options.role) form.append("role", options.role);
      if (options.book) form.append("reference_book", options.book);
      if (options.page) form.append("reference_page", options.page);
      return request<{
        source_file_id: string;
        job_id: string | null;
        kind: string;
        filename: string;
        size_bytes: number;
        duplicate_of: string | null;
        message: string;
        role: string;
      }>("/admin/files/upload", { method: "POST", raw: form });
    },

    get: (id: string, token?: string) =>
      request<{
        id: string;
        original_filename: string;
        kind: string;
        processing_status: string;
        error_message: string | null;
        extracted_text: string | null;
        extraction_metadata: Record<string, unknown>;
      }>(`/admin/files/${id}`, { token }),

    correctText: (id: string, text: string) =>
      request(`/admin/files/${id}/text`, {
        method: "PATCH",
        body: { extracted_text: text },
      }),
  },

  references: {
    /** What the permanent corpus actually holds, and what it is missing. */
    corpus: (token?: string) =>
      request<CorpusStatus>("/admin/references/corpus", { token }),

    pages: (lessonId: string, token?: string) =>
      request<ReferencePage[]>(
        `/admin/references/lessons/${lessonId}/pages`,
        { token },
      ),

    removePage: (lessonId: string, sourceFileId: string, token?: string) =>
      request<void>(
        `/admin/references/lessons/${lessonId}/pages/${sourceFileId}`,
        { method: "DELETE", token },
      ),
  },

  jobs: {
    get: (id: string, token?: string) =>
      request<JobStatus>(`/jobs/${id}`, { token }),
  },
};

/**
 * Poll a job until it finishes.
 *
 * Polling rather than SSE: at a few dozen jobs a week the difference is
 * invisible to the user and this has far fewer failure modes.
 */
export async function pollJob(
  jobId: string,
  onProgress?: (job: JobStatus) => void,
  { intervalMs = 1500, timeoutMs = 300_000 }: { intervalMs?: number; timeoutMs?: number } = {},
): Promise<JobStatus> {
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    const job = await api.jobs.get(jobId);
    onProgress?.(job);

    if (job.status === "succeeded" || job.status === "failed" || job.status === "cancelled") {
      return job;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }

  throw new ApiError(
    "This is taking longer than expected. It may still be running — refresh in a moment.",
    408,
    "timeout",
  );
}
