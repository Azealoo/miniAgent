"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { cn } from "@/lib/utils";
import ThoughtChain from "./ThoughtChain";
import RetrievalCard from "./RetrievalCard";
import WorkflowProgressCard from "./WorkflowProgressCard";
import type { Message } from "@/lib/types";

interface ChatMessageProps {
  message: Message;
}

function MessageAvatar({
  label,
  tone,
}: {
  label: string;
  tone: "user" | "assistant";
}) {
  return (
    <div
      className={cn(
        "mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full text-[10px] font-semibold uppercase tracking-[0.16em]",
        tone === "assistant"
          ? "bg-[rgba(35,130,83,0.14)] text-[var(--apex-accent-strong)]"
          : "bg-[rgba(23,97,61,0.92)] text-white"
      )}
    >
      {label}
    </div>
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

export default function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === "user";
  const hasRetrievals = Boolean(message.retrievals && message.retrievals.length > 0);
  const hasWorkflowProgress = Boolean(
    message.workflow_events && message.workflow_events.length > 0
  );
  const hasToolTrace =
    Boolean(message.tool_calls && message.tool_calls.length > 0) ||
    Boolean(message.pendingTool);
  const hasSupport = hasRetrievals || hasWorkflowProgress || hasToolTrace;
  const hasContent = Boolean(message.content);

  if (isUser) {
    return (
      <article className="grid grid-cols-[auto,minmax(0,1fr)] gap-3 sm:gap-4">
        <MessageAvatar label="U" tone="user" />
        <div className="min-w-0 pt-0.5">
          <p className="whitespace-pre-wrap text-[1rem] leading-[1.72] text-slate-800">
            {message.content}
          </p>
        </div>
      </article>
    );
  }

  return (
    <article className="grid grid-cols-[auto,minmax(0,1fr)] gap-3 sm:gap-4">
      <MessageAvatar label="B" tone="assistant" />

      <div className="min-w-0 pt-0.5">
        {hasContent ? (
          <MarkdownContent content={message.content} isStreaming={message.isStreaming} />
        ) : message.isStreaming ? (
          <div className="flex min-h-[1.5rem] items-center">
            <span className="inline-block h-4 w-0.5 animate-blink bg-[var(--apex-accent)]" />
          </div>
        ) : hasSupport ? (
          <p className="text-sm leading-6 text-slate-500">
            Structured results are available below.
          </p>
        ) : null}

        {hasSupport && (
          <div className="mt-3 space-y-2.5">
            {hasRetrievals && <RetrievalCard results={message.retrievals ?? []} />}
            {hasWorkflowProgress && (
              <WorkflowProgressCard events={message.workflow_events ?? []} />
            )}
            {hasToolTrace && (
              <ThoughtChain
                toolCalls={message.tool_calls ?? []}
                pendingTool={message.pendingTool}
              />
            )}
          </div>
        )}
      </div>
    </article>
  );
}
