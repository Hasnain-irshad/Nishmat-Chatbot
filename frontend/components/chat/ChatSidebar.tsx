"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { MessageSquare, Plus, Trash2 } from "lucide-react";

import { api, type Conversation } from "@/lib/api";
import { cn, relativeBucket } from "@/lib/utils";

/**
 * Saved conversations, grouped by when they last moved.
 *
 * Grouping by recency rather than listing by date: someone looking for a
 * conversation remembers "the one from yesterday", not its timestamp.
 */
export function ChatSidebar({
  conversations,
}: {
  conversations: Conversation[];
}) {
  const router = useRouter();
  // Read the active conversation from the URL rather than threading it down
  // from a server layout — the layout does not know which child rendered.
  const pathname = usePathname();
  const activeId = pathname.split("/app/chat/")[1]?.split("/")[0];
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);

  const groups = groupByRecency(conversations);

  async function startNew() {
    setCreating(true);
    try {
      const conversation = await api.chat.createConversation();
      router.push(`/app/chat/${conversation.id}`);
      router.refresh();
    } finally {
      setCreating(false);
    }
  }

  async function remove(id: string) {
    if (!confirm("Delete this conversation? This cannot be undone.")) return;
    setDeleting(id);
    try {
      await api.chat.remove(id);
      if (id === activeId) router.push("/app/chat");
      router.refresh();
    } finally {
      setDeleting(null);
    }
  }

  return (
    <aside className="flex h-full flex-col border-r border-white/[0.07]">
      <div className="p-3">
        <button
          type="button"
          onClick={startNew}
          disabled={creating}
          className="flex w-full items-center justify-center gap-2 rounded-xl border border-white/12
                     bg-white/[0.04] px-4 py-2.5 text-sm text-ink-100 transition-all duration-300
                     hover:border-gold-300/40 hover:bg-white/[0.07] disabled:opacity-50"
        >
          <Plus className="h-4 w-4" aria-hidden />
          New conversation
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 pb-4">
        {conversations.length === 0 ? (
          <p className="px-3 py-6 text-center text-xs leading-relaxed text-ink-500">
            Your conversations will be saved here, so you can come back to them.
          </p>
        ) : (
          groups.map(([bucket, items]) => (
            <div key={bucket} className="mb-4">
              <p className="px-3 py-1.5 text-[0.65rem] font-medium uppercase tracking-[0.16em] text-ink-500">
                {bucket}
              </p>
              <ul className="space-y-0.5">
                {items.map((conversation) => {
                  const active = conversation.id === activeId;
                  return (
                    <li key={conversation.id} className="group relative">
                      <Link
                        href={`/app/chat/${conversation.id}`}
                        className={cn(
                          "flex items-center gap-2.5 rounded-lg py-2 pl-3 pr-8 text-sm transition-colors",
                          active
                            ? "bg-gradient-to-r from-gold-300/15 to-transparent text-ink-50"
                            : "text-ink-300 hover:bg-white/[0.05] hover:text-ink-50",
                        )}
                      >
                        <MessageSquare
                          className={cn(
                            "h-3.5 w-3.5 shrink-0",
                            active ? "text-gold-200" : "text-ink-500",
                          )}
                          aria-hidden
                        />
                        <span className="truncate">{conversation.title}</span>
                      </Link>

                      <button
                        type="button"
                        onClick={() => remove(conversation.id)}
                        disabled={deleting === conversation.id}
                        aria-label={`Delete ${conversation.title}`}
                        className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-1.5
                                   text-ink-500 opacity-0 transition-opacity
                                   hover:text-rose-300 focus-visible:opacity-100
                                   group-hover:opacity-100"
                      >
                        <Trash2 className="h-3.5 w-3.5" aria-hidden />
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))
        )}
      </nav>
    </aside>
  );
}

const ORDER = ["Today", "Yesterday", "This week", "This month", "Earlier"];

function groupByRecency(
  conversations: Conversation[],
): [string, Conversation[]][] {
  const buckets = new Map<string, Conversation[]>();

  for (const conversation of conversations) {
    const when = conversation.last_message_at ?? conversation.created_at;
    const bucket = relativeBucket(when);
    const list = buckets.get(bucket) ?? [];
    list.push(conversation);
    buckets.set(bucket, list);
  }

  return ORDER.filter((bucket) => buckets.has(bucket)).map((bucket) => [
    bucket,
    buckets.get(bucket)!,
  ]);
}
