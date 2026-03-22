"use client";

import { useEffect, useRef } from "react";
import { MessageSquarePlus } from "lucide-react";
import { useApp } from "@/lib/store";
import ChatInput from "./ChatInput";
import ChatMessage from "./ChatMessage";

export default function ChatPanel() {
  const {
    messages,
    isStreaming,
    sendMessage,
    draftMessage,
    draftRevision,
    clearDraftMessage,
  } = useApp();

  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const isNearBottomRef = useRef(true);

  const handleScroll = () => {
    const el = containerRef.current;
    if (!el) return;

    const threshold = 80;
    isNearBottomRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < threshold;
  };

  useEffect(() => {
    if (isNearBottomRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  const handleSend = async (text: string) => {
    await sendMessage(text);
  };

  return (
    <section className="apex-panel flex h-full min-h-0 flex-col overflow-hidden rounded-[18px] shadow-[var(--panel-shadow-soft)]">
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <div
          ref={containerRef}
          onScroll={handleScroll}
          className="flex-1 overflow-y-auto px-4 py-4 sm:px-6 sm:py-5 lg:px-8 lg:py-7"
        >
          <div className="mx-auto flex min-h-full w-full max-w-[54rem] flex-col">
            {messages.length === 0 ? (
              <EmptyState />
            ) : (
              <div className="flex flex-col gap-6 pb-2 sm:gap-7">
                {messages.map((message) => (
                  <ChatMessage key={message.id} message={message} />
                ))}
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        </div>

        <div className="border-t border-[var(--shell-border)] bg-[var(--panel-muted)] px-4 py-4 sm:px-5 lg:px-6">
          <div className="mx-auto w-full max-w-[54rem]">
            <ChatInput
              onSend={handleSend}
              isStreaming={isStreaming}
              prefillText={draftMessage}
              prefillRevision={draftRevision}
              clearPrefill={clearDraftMessage}
            />
          </div>
        </div>
      </div>
    </section>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center px-8 py-16 text-center">
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-[16px] bg-[var(--apex-accent-soft)]">
        <MessageSquarePlus size={24} className="text-[var(--apex-accent)]" />
      </div>
      <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-[var(--apex-accent-strong)]">
        Conversation Workspace
      </p>
      <h2 className="mt-3 text-[1.05rem] font-semibold tracking-[-0.01em] text-slate-800">
        Start a BioAPEX conversation
      </h2>
      <p className="mt-2 max-w-lg text-sm leading-6 text-slate-500">
        Ask about a workflow, a dataset, or the next step in a scientific task. The center workspace is ready for the active conversation.
      </p>
    </div>
  );
}
