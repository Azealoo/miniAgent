"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import {
  messageHasProcessTrail,
  normalizeMessageContent,
} from "@/lib/message-blocks";
import { completedElapsedLabel } from "@/lib/message-duration";
import { splitStreamingMarkdown } from "@/lib/streaming-markdown";
import { useAppOptional } from "@/lib/store";
import { cn } from "@/lib/utils";
import TurnActivityFeed from "./TurnActivityFeed";
import type { Message } from "@/lib/types";

interface ChatMessageProps {
  message: Message;
}

function MessageMarker() {
  return (
    <span
      aria-hidden="true"
      className="mt-[0.45rem] flex h-4 w-4 flex-shrink-0 items-center justify-center"
    >
      <span className="h-1.5 w-1.5 rounded-full bg-[var(--apex-accent-strong)] shadow-[0_0_0_1px_rgba(23,97,61,0.1)]" />
    </span>
  );
}

function MarkdownContent({
  content,
  isStreaming,
}: {
  content: string;
  isStreaming?: boolean;
}) {
  return (
    <div
      className={cn(
        "apex-chat-prose prose prose-sm max-w-none prose-pre:bg-[#1e1e1e] prose-pre:text-gray-100",
        isStreaming && "streaming-cursor"
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          code({ className, children, ...props }) {
            const match = /language-(\w+)/.exec(className ?? "");
            if (!match) {
              return (
                <code
                  className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[0.8em] text-[#c7254e]"
                  {...props}
                >
                  {children}
                </code>
              );
            }
            return (
              <code className={className} {...props}>
                {children}
              </code>
            );
          },
          table({ children }) {
            return (
              <div className="my-3 overflow-x-auto">
                <table className="min-w-full overflow-hidden rounded-lg border border-slate-200 text-xs">
                  {children}
                </table>
              </div>
            );
          },
          th({ children }) {
            return (
              <th className="border-b border-slate-200 bg-slate-50 px-3 py-2 text-left font-semibold text-slate-700">
                {children}
              </th>
            );
          },
          td({ children }) {
            return (
              <td className="border-b border-slate-100 px-3 py-2 text-slate-600">
                {children}
              </td>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function StreamingMarkdownContent({
  content,
  isStreaming,
}: {
  content: string;
  isStreaming?: boolean;
}) {
  if (!isStreaming) {
    return <MarkdownContent content={content} />;
  }

  const { committed, pending } = splitStreamingMarkdown(content);
  const hasCommitted = committed.trim().length > 0;
  const hasPending = pending.trim().length > 0;

  if (!hasCommitted && !hasPending) {
    return null;
  }

  return (
    <div className="space-y-2">
      {hasCommitted ? (
        <MarkdownContent content={committed} isStreaming={!hasPending} />
      ) : null}

      {hasPending ? (
        <div className="apex-streaming-draft streaming-cursor whitespace-pre-wrap rounded-[14px] border px-3 py-2">
          {pending}
        </div>
      ) : null}
    </div>
  );
}

export default function ChatMessage({
  message,
}: ChatMessageProps) {
  const app = useAppOptional();
  const sessionId = app?.currentSessionId ?? null;
  const isUser = message.role === "user";
  const normalizedContent = normalizeMessageContent(message);
  const displayContent = normalizedContent.content;
  const hasContent = Boolean(displayContent);
  const hasPlanningBlock = normalizedContent.blocks.some(
    (block) => block.type === "plan"
  );
  const hasVerificationBlock = normalizedContent.blocks.some(
    (block) => block.type === "verification"
  );
  const hasVerificationActivity = normalizedContent.blocks.some(
    (block) =>
      (block.type === "tool_use" || block.type === "tool_result") &&
      block.tool === "verification_agent"
  );
  const hasProcessTrail = messageHasProcessTrail(message);
  const showTurnActivityBeforeContent =
    message.isStreaming || hasProcessTrail || hasPlanningBlock;
  const showTurnActivityAfterContent = false;
  const showStreamingContent = hasContent;
  const completedDuration = !message.isStreaming ? completedElapsedLabel(message) : null;

  if (isUser) {
    return (
      <article aria-label="User prompt" className="flex justify-end">
        <div className="max-w-[min(42rem,88%)] rounded-[22px] border border-[rgba(208,216,209,0.92)] bg-[rgba(248,250,246,0.96)] px-4 py-3 shadow-[0_10px_24px_rgba(29,42,33,0.04)]">
          <p className="whitespace-pre-wrap text-[0.92rem] leading-[1.72] text-slate-700">
            {message.content}
          </p>
        </div>
      </article>
    );
  }

  if (
    !hasContent &&
    !showTurnActivityBeforeContent
  ) {
    return null;
  }

  if (
    !message.isStreaming &&
    !hasContent &&
    !hasVerificationBlock &&
    !hasPlanningBlock &&
    !hasVerificationActivity
  ) {
    return null;
  }

  return (
    <article
      aria-label="Assistant response"
      className="apex-transcript-enter grid grid-cols-[1rem,minmax(0,1fr)] gap-3 sm:gap-4"
    >
      <MessageMarker />

      <div className="min-w-0 pt-0.5">
        {showTurnActivityBeforeContent ? (
          <TurnActivityFeed message={message} sessionId={sessionId} />
        ) : null}

        {hasContent && completedDuration ? (
          <p className="mb-2 pl-[1px] font-mono text-[10px] italic leading-5 text-slate-400">
            {completedDuration}
          </p>
        ) : null}

        {showStreamingContent ? (
          <StreamingMarkdownContent
            content={displayContent}
            isStreaming={message.isStreaming}
          />
        ) : null}

        {showTurnActivityAfterContent ? (
          <TurnActivityFeed message={message} sessionId={sessionId} />
        ) : null}
      </div>
    </article>
  );
}
