"use client";

import { useEffect, useRef } from "react";
import { MessageSquarePlus } from "lucide-react";
import { useApp } from "@/lib/store";
import ChatInput from "./ChatInput";
import ChatMessage from "./ChatMessage";

export default function ChatPanel() {
  const {
    accessByScope,
    hasExecutionAccess,
    messages,
    isStreaming,
    isReferenceUploading,
    isSessionLoading,
    sendMessage,
    selectedWorkflow,
    attachedIdentifiers,
    selectWorkflow,
    uploadAttachedReference,
    removeAttachedIdentifier,
    clearAttachedIdentifiers,
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

  const chatDisabled = isSessionLoading || !hasExecutionAccess;
  const chatDisabledReason = !hasExecutionAccess
    ? accessByScope.execution.detail
    : "Loading workspace";

  return (
    <section className="apex-panel flex h-full min-h-0 flex-col overflow-hidden rounded-[18px] shadow-[var(--panel-shadow-soft)]">
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-[linear-gradient(180deg,rgba(248,250,246,0.92)_0%,rgba(244,246,242,0.82)_100%)]">
        <div
          ref={containerRef}
          onScroll={handleScroll}
          className="flex-1 overflow-y-auto px-4 pt-4 sm:px-6 sm:pt-5 lg:px-8 lg:pt-7"
        >
          <div className="mx-auto flex min-h-full w-full max-w-[54rem] flex-col">
            {messages.length === 0 ? (
              <EmptyState />
            ) : (
              <div className="flex flex-col gap-5 pb-[11.75rem] sm:gap-6 sm:pb-[13rem]">
                {messages.map((message) => (
                  <ChatMessage key={message.id} message={message} />
                ))}
              </div>
            )}
            <div ref={bottomRef} className="h-px" />
          </div>
        </div>

        <div className="pointer-events-none h-8 bg-gradient-to-t from-[rgba(244,246,242,0.96)] via-[rgba(244,246,242,0.76)] to-transparent" />

        <div className="sticky bottom-0 z-10 px-3 pb-3 sm:px-5 sm:pb-4 lg:px-6 lg:pb-5">
          <div className="mx-auto w-full max-w-[56rem]">
            <ChatInput
              onSend={handleSend}
              isStreaming={isStreaming}
              isReferenceUploading={isReferenceUploading}
              disabled={chatDisabled}
              disabledReason={chatDisabledReason}
              selectedWorkflow={selectedWorkflow}
              onSelectWorkflow={selectWorkflow}
              attachedIdentifiers={attachedIdentifiers}
              onUploadReferenceFile={uploadAttachedReference}
              onRemoveAttachedIdentifier={removeAttachedIdentifier}
              onClearAttachedIdentifiers={clearAttachedIdentifiers}
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
