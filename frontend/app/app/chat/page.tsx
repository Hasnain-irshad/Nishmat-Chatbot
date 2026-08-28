import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { createClient } from "@/lib/supabase/server";

export const metadata: Metadata = { title: "Ask a question" };

interface PageProps {
  searchParams: Promise<{ lesson?: string }>;
}

/**
 * Entry point for chat.
 *
 * `?lesson=<id>` arrives from the "Ask about this lesson" button in the reader
 * and always starts a fresh, lesson-scoped conversation — retrieval is then
 * confined to that lesson, so "explain the second idea" means *this* lesson's
 * second idea.
 *
 * Otherwise it reopens the most recent conversation, or starts one. Landing on
 * an empty screen and having to press "new" first is a needless step.
 */
export default async function ChatIndexPage({ searchParams }: PageProps) {
  const { lesson } = await searchParams;
  const supabase = await createClient();

  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/sign-in?next=/app/chat");

  if (lesson) {
    const { data: published } = await supabase
      .from("lessons")
      .select("id")
      .eq("id", lesson)
      .eq("status", "published")
      .maybeSingle<{ id: string }>();

    if (published) {
      const { data: scoped } = await supabase
        .from("conversations")
        .insert({
          user_id: user.id,
          lesson_id: published.id,
          title: "New conversation",
        })
        .select("id")
        .single();

      if (scoped) redirect(`/app/chat/${scoped.id}`);
    }
  }

  const { data: recent } = await supabase
    .from("conversations")
    .select("id")
    .is("archived_at", null)
    .order("last_message_at", { ascending: false, nullsFirst: false })
    .limit(1)
    .returns<{ id: string }[]>();

  if (recent?.[0]) redirect(`/app/chat/${recent[0].id}`);

  const { data: created } = await supabase
    .from("conversations")
    .insert({ user_id: user.id, title: "New conversation" })
    .select("id")
    .single();

  redirect(created ? `/app/chat/${created.id}` : "/app");
}
