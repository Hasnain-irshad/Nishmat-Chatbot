import { createClient } from "@/lib/supabase/server";
import { ChatSidebar } from "@/components/chat/ChatSidebar";
import type { Conversation } from "@/lib/api";

/**
 * Chat shell: saved conversations on the left, the active one on the right.
 *
 * The list is read straight from Supabase under RLS — a learner's policy only
 * ever matches their own rows, so there is no way to see anyone else's.
 */
export default async function ChatLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const supabase = await createClient();

  const { data } = await supabase
    .from("conversations")
    .select(
      "id, title, lesson_id, message_count, last_message_at, created_at, updated_at",
    )
    .is("archived_at", null)
    .order("last_message_at", { ascending: false, nullsFirst: false })
    .limit(100)
    .returns<Conversation[]>();

  return (
    <div className="-mx-4 -my-7 flex h-[calc(100svh-4rem)] sm:-mx-6 lg:-mx-8 lg:-my-9">
      <div className="hidden w-64 shrink-0 md:block">
        <ChatSidebar conversations={data ?? []} />
      </div>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
