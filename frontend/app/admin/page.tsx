import type { Metadata } from "next";
import Link from "next/link";
import {
  FilePlus2,
  Library,
  BookCheck,
  PencilLine,
  AlertTriangle,
  Coins,
  ArrowUpRight,
  Sparkles,
} from "lucide-react";

import { createClient } from "@/lib/supabase/server";
import { getProfile } from "@/lib/auth";
import { Card } from "@/components/ui/Card";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { EmptyState } from "@/components/ui/EmptyState";
import { ButtonLink } from "@/components/ui/Button";
import { Reveal } from "@/components/ui/Reveal";
import { formatDate } from "@/lib/utils";
import type { LessonStatus } from "@/types/database";

export const metadata: Metadata = { title: "Dashboard" };

interface RecentLesson {
  id: string;
  title: string;
  lesson_number: number | null;
  status: LessonStatus;
  updated_at: string;
  hebrew_phrase: string | null;
}

export default async function AdminDashboard() {
  const profile = await getProfile();
  const supabase = await createClient();

  // `head: true` with an exact count returns the number without the rows.
  const countFor = (status: LessonStatus | LessonStatus[]) => {
    const q = supabase
      .from("lessons")
      .select("id", { count: "exact", head: true })
      .is("deleted_at", null);
    return Array.isArray(status) ? q.in("status", status) : q.eq("status", status);
  };

  const [published, drafts, inReview, failed, recent, spend] = await Promise.all([
    countFor("published"),
    countFor(["draft", "generated", "processing"]),
    countFor(["review", "approved"]),
    countFor("failed"),
    supabase
      .from("lessons")
      .select("id, title, lesson_number, status, updated_at, hebrew_phrase")
      .is("deleted_at", null)
      .order("updated_at", { ascending: false })
      .limit(6),
    supabase.from("ai_usage").select("estimated_cost"),
  ]);

  const totalSpend = (spend.data ?? []).reduce(
    (sum, row: { estimated_cost: number | string | null }) =>
      sum + Number(row.estimated_cost ?? 0),
    0,
  );

  const recentLessons = (recent.data ?? []) as RecentLesson[];
  const firstName = profile?.full_name?.trim().split(/\s+/)[0];

  return (
    <div className="mx-auto max-w-6xl">
      {/* ------------------------------------------------------- header */}
      <div className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-[0.7rem] font-medium uppercase tracking-[0.3em] text-gold-300/75">
            Admin
          </p>
          <h1 className="mt-2.5 font-display text-4xl font-light text-ink-50">
            {firstName ? (
              <>
                Welcome back, <span className="text-gilded">{firstName}</span>
              </>
            ) : (
              "Dashboard"
            )}
          </h1>
          <p className="mt-2 text-[0.95rem] text-ink-400">
            Everything about the series, in one place.
          </p>
        </div>

        <ButtonLink href="/admin/lessons/new" size="md">
          <FilePlus2 className="h-4 w-4" aria-hidden />
          Create lesson
        </ButtonLink>
      </div>

      {/* -------------------------------------------------------- stats */}
      <div className="mt-9 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          icon={BookCheck}
          label="Published"
          value={published.count ?? 0}
          hint="Live for learners"
          tone="gold"
          href="/admin/lessons?status=published"
          delay={0}
        />
        <Stat
          icon={PencilLine}
          label="Drafts"
          value={drafts.count ?? 0}
          hint="Not yet reviewed"
          tone="violet"
          href="/admin/lessons?status=draft"
          delay={0.06}
        />
        <Stat
          icon={Library}
          label="Awaiting publish"
          value={inReview.count ?? 0}
          hint="Reviewed or approved"
          tone="violet"
          href="/admin/lessons?status=review"
          delay={0.12}
        />
        <Stat
          icon={Coins}
          label="AI spend"
          value={`$${totalSpend.toFixed(2)}`}
          hint="Total to date"
          tone={totalSpend > 8 ? "danger" : "neutral"}
          delay={0.18}
        />
      </div>

      {(failed.count ?? 0) > 0 && (
        <Reveal>
          <Link
            href="/admin/lessons?status=failed"
            className="mt-4 flex items-center gap-3 rounded-2xl border border-danger/25 bg-danger/[0.07] px-5 py-4
                       text-sm text-rose-200 transition-colors hover:bg-danger/[0.12]"
          >
            <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden />
            <span>
              <strong className="font-medium">{failed.count}</strong>{" "}
              {failed.count === 1 ? "lesson" : "lessons"} failed during processing.
            </span>
            <ArrowUpRight className="ml-auto h-4 w-4" aria-hidden />
          </Link>
        </Reveal>
      )}

      {/* ------------------------------------------------------- recent */}
      <div className="mt-10 grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-display text-xl font-light text-ink-50">
              Recently worked on
            </h2>
            <Link
              href="/admin/lessons"
              className="text-sm text-ink-400 transition-colors hover:text-gold-200"
            >
              View all
            </Link>
          </div>

          {recentLessons.length === 0 ? (
            <EmptyState
              icon={Library}
              title="No lessons yet"
              description="Upload a recording, a document or a photo and the first lesson will start here."
              action={
                <ButtonLink href="/admin/lessons/new">
                  <FilePlus2 className="h-4 w-4" aria-hidden />
                  Create your first lesson
                </ButtonLink>
              }
            />
          ) : (
            <Card className="divide-y divide-white/[0.06] overflow-hidden">
              {recentLessons.map((lesson) => (
                <Link
                  key={lesson.id}
                  href={`/admin/lessons/${lesson.id}`}
                  className="group flex items-center gap-4 px-5 py-4 transition-colors hover:bg-white/[0.04]"
                >
                  <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-white/[0.05] font-display text-sm text-gold-200">
                    {lesson.lesson_number != null ? `#${lesson.lesson_number}` : "—"}
                  </span>

                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[0.95rem] text-ink-50">
                      {lesson.title}
                    </span>
                    <span className="mt-0.5 block truncate text-xs text-ink-500">
                      Updated {formatDate(lesson.updated_at)}
                    </span>
                  </span>

                  <StatusBadge status={lesson.status} />
                  <ArrowUpRight
                    className="h-4 w-4 shrink-0 text-ink-500 opacity-0 transition-opacity group-hover:opacity-100"
                    aria-hidden
                  />
                </Link>
              ))}
            </Card>
          )}
        </div>

        {/* -------------------------------------------------- quick start */}
        <div>
          <h2 className="mb-4 font-display text-xl font-light text-ink-50">
            Quick actions
          </h2>
          <Card className="space-y-1 p-3">
            <QuickAction
              href="/admin/lessons/new"
              icon={FilePlus2}
              title="New lesson"
              body="Upload a source and generate a draft"
            />
            <QuickAction
              href="/admin/templates"
              icon={Sparkles}
              title="Lesson format"
              body="Adjust the structure and the writing style"
            />
            <QuickAction
              href="/admin/style-examples"
              icon={Library}
              title="Style library"
              body="Approve examples the AI writes from"
            />
          </Card>

          <Card className="mt-5 p-5">
            <p className="text-xs font-medium uppercase tracking-wider text-ink-500">
              Remember
            </p>
            <p className="mt-2.5 text-sm leading-relaxed text-ink-300">
              Nothing reaches learners until you press{" "}
              <strong className="font-medium text-gold-200">Publish</strong>. Drafts
              are invisible to them, and the chatbot never reads from them.
            </p>
          </Card>
        </div>
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- pieces */

const TONES = {
  gold: "from-gold-300/18 to-gold-400/[0.04] text-gold-200",
  violet: "from-violet-500/18 to-violet-500/[0.04] text-violet-200",
  danger: "from-danger/18 to-danger/[0.04] text-rose-300",
  neutral: "from-white/[0.08] to-white/[0.02] text-ink-200",
} as const;

function Stat({
  icon: Icon,
  label,
  value,
  hint,
  tone,
  href,
  delay,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: number | string;
  hint: string;
  tone: keyof typeof TONES;
  href?: string;
  delay: number;
}) {
  const body = (
    <Card interactive={!!href} className="h-full p-5">
      <div className="flex items-start justify-between">
        <span
          className={`grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br ${TONES[tone]}`}
        >
          <Icon className="h-[1.1rem] w-[1.1rem]" aria-hidden />
        </span>
        {href && (
          <ArrowUpRight className="h-4 w-4 text-ink-500" aria-hidden />
        )}
      </div>
      <p className="mt-4 font-display text-3xl font-light text-ink-50">{value}</p>
      <p className="mt-0.5 text-sm text-ink-300">{label}</p>
      <p className="mt-1 text-xs text-ink-500">{hint}</p>
    </Card>
  );

  return (
    <Reveal delay={delay}>
      {href ? (
        <Link href={href} className="block h-full">
          {body}
        </Link>
      ) : (
        body
      )}
    </Reveal>
  );
}

function QuickAction({
  href,
  icon: Icon,
  title,
  body,
}: {
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  body: string;
}) {
  return (
    <Link
      href={href}
      className="group flex items-start gap-3 rounded-xl px-3 py-3 transition-colors hover:bg-white/[0.05]"
    >
      <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-white/[0.06] text-gold-200/90">
        <Icon className="h-4 w-4" aria-hidden />
      </span>
      <span>
        <span className="block text-sm font-medium text-ink-50">{title}</span>
        <span className="mt-0.5 block text-xs leading-relaxed text-ink-500">
          {body}
        </span>
      </span>
    </Link>
  );
}
