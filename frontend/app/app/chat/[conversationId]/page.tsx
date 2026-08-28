import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { createClient } from "@/lib/supabase/server";
import { ChatWindow } from "@/components/chat/ChatWindow";
import type { ChatMessage } from "@/lib/api";

interface PageProps {
  params: Promise<{ conversationId: string }>;
}

interface ConversationRow {
  id: string;
  title: string;
  lesson_id: string | null;
}

async function load(id: string) {
  const supabase = await createClient();

  // RLS restricts this to the signed-in learner's own conversations, so
  // someone else's id simply returns nothing.
  const { data: conversation } = await supabase
    .from("conversations")
    .select("id, title, lesson_id")
    .eq("id", id)
    .maybeSingle<ConversationRow>();

  if (!conversation) return null;

  const { data: messages } = await supabase
    .from("messages")
    .select("id, role, content, citations, created_at")
    .eq("conversation_id", id)
    .order("created_at", { ascending: true })
    .returns<ChatMessage[]>();

  let lessonTitle: string | null = null;
  if (conversation.lesson_id) {
    const { data: lesson } = await supabase
      .from("lessons")
      .select("title, lesson_number")
      .eq("id", conversation.lesson_id)
      .maybeSingle<{ title: string; lesson_number: number | null }>();
    if (lesson) {
      lessonTitle =
        lesson.lesson_number != null
          ? `Lesson #${lesson.lesson_number}`
          : lesson.title;
    }
  }

  return {
    conversation,
    // The API never stores system messages against a conversation, so
    // there is nothing to filter out here.
    messages: messages ?? [],
    lessonTitle,
  };
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { conversationId } = await params;
  const loaded = await load(conversationId);
  return { title: loaded?.conversation.title ?? "Ask a question" };
}

export default async function ConversationPage({ params }: PageProps) {
  const { conversationId } = await params;
  const loaded = await load(conversationId);

  if (!loaded) notFound();

  return (
    <ChatWindow
      conversationId={conversationId}
      initialMessages={loaded.messages}
      lessonTitle={loaded.lessonTitle}
    />
  );
}
