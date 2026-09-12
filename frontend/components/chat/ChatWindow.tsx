"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, ArrowUp, BookOpen, Loader2, Sparkles } from "lucide-react";

import { api, ApiError, type ChatMessage, type Citation } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Markdown } from "@/components/chat/Markdown";

const SUGGESTIONS = [
  "What does the word Moshia mean?",
  "What do the lessons say about gratitude when life is hard?",
  "I find it difficult to daven lately. Is there anything on that?",
  "Tell me about the story with Rabbi Besser.",
];

export function ChatWindow({
  conversationId,
  initialMessages,
  lessonTitle,
}: {
  conversationId: string;
  initialMessages: ChatMessage[];
  lessonTitle?: string | null;
}) {
  const router = useRouter();

  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const endRef = useRef<HTMLDivElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);

  useLayoutEffect(() => {
    endRef.current?.scrollIntoView({ behavior: messages.length > 2 ? "smooth" : "auto" });
  }, [messages, pending]);

  useEffect(() => {
    const element = textRef.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 200)}px`;
  }, [draft]);

  async function send(text: string) {
    const question = text.trim();
    if (!question || pending) return;

    setDraft("");
    setPending(question);
    setError(null);

    try {
      const result = await api.chat.send(conversationId, question);
      setMessages((current) => [...current, result.question, result.answer]);
      // The first exchange names the conversation — refresh so the sidebar
      // stops saying "New conversation".
      router.refresh();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Something went wrong. Please try again.",
      );
      setDraft(question);
    } finally {
      setPending(null);
    }
  }

  const empty = messages.length === 0 && !pending;

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 overflow-y-auto px-4 sm:px-6">
        <div className="mx-auto max-w-2xl py-6">
          {empty ? (
            <Welcome lessonTitle={lessonTitle} onPick={send} />
          ) : (
            <div className="space-y-6">
              {messages.map((message) => (
                <Bubble key={message.id} message={message} />
              ))}

              {pending && (
                <>
                  <Bubble
                    message={{
                      id: "pending-q",
                      role: "user",
                      content: pending,
                      citations: [],
                      created_at: new Date().toISOString(),
                    }}
                  />
                  <Thinking />
                </>
              )}
            </div>
          )}

          {error && (
            <p
              role="alert"
              className="mt-5 flex items-start gap-2 rounded-xl border border-danger/25 bg-danger/[0.08] px-4 py-3 text-sm text-rose-200"
            >
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              {error}
            </p>
          )}

          <div ref={endRef} />
        </div>
      </div>

      {/* ------------------------------------------------------- composer */}
      <div className="border-t border-white/[0.07] bg-night-950/60 px-4 py-4 backdrop-blur-xl sm:px-6">
        <div className="mx-auto max-w-2xl">
          <div className="flex items-end gap-2 rounded-xl3 border border-white/12 bg-white/[0.04] p-2.5 transition-colors focus-within:border-gold-300/40">
            <textarea
              ref={textRef}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  send(draft);
                }
              }}
              rows={1}
              disabled={Boolean(pending)}
              placeholder={
                lessonTitle
                  ? `Ask about ${lessonTitle}…`
                  : "Ask anything about the lessons…"
              }
              className="max-h-[200px] flex-1 resize-none bg-transparent px-2 py-2 text-[0.98rem]
                         leading-relaxed text-ink-50 outline-none placeholder:text-ink-500/70
                         disabled:opacity-60"
            />

            <button
              type="button"
              onClick={() => send(draft)}
              disabled={!draft.trim() || Boolean(pending)}
              aria-label="Send"
              className={cn(
                "grid h-10 w-10 shrink-0 place-items-center rounded-full transition-all duration-300",
                draft.trim() && !pending
                  ? "bg-gradient-to-br from-gold-200 to-gold-400 text-night-950 hover:-translate-y-0.5"
                  : "bg-white/[0.07] text-ink-500",
              )}
            >
              {pending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <ArrowUp className="h-4 w-4" aria-hidden />
              )}
            </button>
          </div>

          <p className="mt-2 px-1 text-center text-[0.7rem] text-ink-500">
            Answers come only from published lessons. If something isn&rsquo;t
            covered, it will say so.
          </p>
        </div>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- pieces */

function Welcome({
  lessonTitle,
  onPick,
}: {
  lessonTitle?: string | null;
  onPick: (text: string) => void;
}) {
  return (
    <div className="py-10 text-center">
      <span
        className="mx-auto grid h-14 w-14 place-items-center rounded-2xl"
        style={{
          background:
            "linear-gradient(140deg, rgba(237,201,106,0.2), rgba(167,139,250,0.14))",
          boxShadow: "inset 0 0 0 1px rgba(237,201,106,0.26)",
        }}
      >
        <Sparkles className="h-6 w-6 text-gold-200" aria-hidden />
      </span>

      <h2 className="mt-5 font-display text-2xl font-light text-ink-50">
        {lessonTitle ? `Ask about ${lessonTitle}` : "What are you wondering about?"}
      </h2>
      <p className="mx-auto mt-2.5 max-w-sm text-sm leading-relaxed text-ink-400">
        Ask anything about the lessons. Answers come from what has actually been
        taught — nothing else.
      </p>

      {!lessonTitle && (
        <ul className="mx-auto mt-8 grid max-w-lg gap-2 text-left">
          {SUGGESTIONS.map((suggestion) => (
            <li key={suggestion}>
              <button
                type="button"
                onClick={() => onPick(suggestion)}
                className="w-full rounded-xl border border-white/[0.08] bg-white/[0.02] px-4 py-3
                           text-sm text-ink-200 transition-all duration-300
                           hover:-translate-y-0.5 hover:border-gold-300/30 hover:bg-white/[0.05]"
              >
                {suggestion}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Bubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
      className={cn("flex", isUser ? "justify-end" : "justify-start")}
    >
      <div className={cn("max-w-[85%]", isUser && "max-w-[80%]")}>
        <div
          className={cn(
            "rounded-2xl px-4 py-3",
            isUser
              ? "bg-gradient-to-br from-violet-500/25 to-violet-600/15 text-ink-50 ring-1 ring-inset ring-violet-400/20"
              : "glass text-ink-100",
          )}
        >
          <Markdown text={message.content} />
        </div>

        {!isUser && message.citations.length > 0 && (
          <Citations citations={message.citations} />
        )}
      </div>
    </motion.div>
  );
}

/**
 * Renders the answer paragraph by paragraph, isolating any Hebrew.
 * A bare Hebrew word inside an English sentence drags the surrounding
 * punctuation to the wrong side unless it is wrapped and marked RTL.
 */

function Citations({ citations }: { citations: Citation[] }) {
  return (
    <div className="mt-2.5 flex flex-wrap gap-1.5">
      <span className="self-center text-[0.68rem] uppercase tracking-wider text-ink-500">
        From
      </span>
      {citations.map((citation) => (
        <Link
          key={citation.lesson_id}
          href={`/app/lessons/${citation.lesson_id}`}
          className="inline-flex items-center gap-1.5 rounded-full border border-gold-300/20
                     bg-gold-300/[0.07] px-2.5 py-1 text-[0.7rem] text-gold-200
                     transition-colors hover:border-gold-300/45 hover:bg-gold-300/[0.13]"
        >
          <BookOpen className="h-3 w-3" aria-hidden />
          {citation.lesson_number != null
            ? `#${citation.lesson_number}`
            : citation.title.slice(0, 24)}
        </Link>
      ))}
    </div>
  );
}

function Thinking() {
  return (
    <div className="flex justify-start">
      <div className="glass flex items-center gap-2 rounded-2xl px-4 py-3">
        <AnimatePresence>
          {[0, 1, 2].map((index) => (
            <motion.span
              key={index}
              className="h-1.5 w-1.5 rounded-full bg-gold-200/70"
              animate={{ opacity: [0.3, 1, 0.3] }}
              transition={{
                duration: 1.2,
                repeat: Infinity,
                delay: index * 0.18,
                ease: "easeInOut",
              }}
            />
          ))}
        </AnimatePresence>
        <span className="ml-1 text-xs text-ink-400">Looking through the lessons</span>
      </div>
    </div>
  );
}
