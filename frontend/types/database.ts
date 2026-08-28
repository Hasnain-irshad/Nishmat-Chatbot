export type UserRole = "admin" | "user";

export type LessonStatus =
  | "draft"
  | "processing"
  | "generated"
  | "review"
  | "approved"
  | "published"
  | "archived"
  | "failed";

export type VersionOrigin =
  | "ai_generated"
  | "ai_modified"
  | "manual_edit"
  | "imported";

export type SourceKind = "pdf" | "docx" | "audio" | "image" | "text";

export type JobStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface Profile {
  id: string;
  email: string;
  full_name: string | null;
  avatar_url: string | null;
  role: UserRole;
  created_at: string;
}

export interface LessonSection {
  key: string;
  title: string | null;
  body: string;
  dir: "ltr" | "rtl";
  order: number;
}

export interface LessonContent {
  sections: LessonSection[];
}

export interface Lesson {
  id: string;
  title: string;
  lesson_number: number | null;
  sequence_position: number | null;
  hebrew_phrase: string | null;
  transliteration: string | null;
  translation: string | null;
  summary: string | null;
  status: LessonStatus;
  published_at: string | null;
  updated_at: string;
}

export interface LessonVersion {
  id: string;
  lesson_id: string;
  version_number: number;
  content: LessonContent;
  content_text: string;
  word_count: number;
  origin: VersionOrigin;
  modification_instruction: string | null;
  quality_report: QualityReport | null;
  model_metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface QualityIssue {
  severity: "low" | "medium" | "high";
  section: string | null;
  message: string;
  suggestion: string | null;
}

export interface QualityReport {
  verdict: "PASS" | "WARN" | "FAIL";
  checks: Record<string, boolean>;
  issues: QualityIssue[];
}

export interface Citation {
  lesson_id: string;
  lesson_number: number | null;
  title: string;
  section: string | null;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "system";
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

export interface Job {
  id: string;
  type: string;
  status: JobStatus;
  progress_stage: string | null;
  progress_pct: number;
  error: string | null;
}

/* ------------------------------------------------------------------ rows
 *
 * Explicit shapes for the columns we select.
 *
 * supabase-js infers result types by parsing the `.select()` string as a type
 * literal. A string built with `+` across several lines is not a literal, so
 * inference collapses to GenericStringError. Declaring the shape and using
 * `.returns<T>()` is both a fix and a clearer contract than relying on the
 * parser — and it keeps the select strings readable.
 *
 * These can be replaced by `supabase gen types typescript` output later
 * without changing any call site.
 */

export interface AdminLessonListRow {
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
  current_version_id: string | null;
  published_version_id: string | null;
}

export interface AdminLessonRowFull extends AdminLessonListRow {
  series_id: string | null;
  template_id: string | null;
  translation: string | null;
  summary: string | null;
  created_at: string;
  /** What the admin asked this lesson to teach. Null until they say. */
  generation_brief: Record<string, string> | null;
}

export interface LessonVersionRow {
  id: string;
  version_number: number;
  content: LessonContent;
  content_text: string;
  word_count: number;
  origin: VersionOrigin;
  modification_instruction: string | null;
  quality_report: QualityReport | null;
  model_metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface LessonVersionListRow {
  id: string;
  version_number: number;
  origin: VersionOrigin;
  modification_instruction: string | null;
  word_count: number;
  created_at: string;
  created_by: string | null;
}
