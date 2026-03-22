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

export default function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === "user";
  const hasRetrievals = Boolean(message.retrievals && message.retrievals.length > 0);
  const hasWorkflowProgress = Boolean(
    message.workflow_events && message.workflow_events.length > 0
  );
  const hasTrace =
    Boolean(message.tool_calls && message.tool_calls.length > 0) ||
    hasWorkflowProgress ||
    Boolean(message.pendingTool);
  const hasSupport = hasRetrievals || hasTrace;
  const showAssistantShell = Boolean(message.content) || message.isStreaming || hasSupport;

  if (isUser) {
    return (
      <article className="flex justify-end">
        <div className="w-full max-w-[42rem] rounded-[22px] border border-[rgba(35,130,83,0.14)] bg-[linear-gradient(180deg,rgba(249,252,249,0.98),rgba(239,246,241,0.98))] px-4 py-3.5 shadow-[0_12px_28px_rgba(32,43,35,0.04)] sm:px-5">
          <div className="mb-2.5 flex items-center gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-[0.22em] text-[var(--apex-accent-strong)]">
              User
            </span>
            <span className="rounded-full border border-[rgba(35,130,83,0.14)] bg-white/75 px-2 py-0.5 text-[10px] uppercase tracking-[0.16em] text-[rgba(23,97,61,0.62)]">
              Request
            </span>
          </div>
          <p className="whitespace-pre-wrap text-[0.95rem] leading-[1.68] text-slate-800">
            {message.content}
          </p>
        </div>
      </article>
    );
  }

  return (
    <article className="grid grid-cols-[auto,minmax(0,1fr)] gap-3 sm:gap-4">
      <div className="mt-1 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-[16px] border border-[rgba(47,122,95,0.14)] bg-[linear-gradient(135deg,rgba(255,255,255,0.98),rgba(233,243,237,0.98))] text-[11px] font-bold uppercase tracking-[0.2em] text-[var(--apex-accent-strong)] shadow-[0_8px_16px_rgba(32,43,35,0.04)]">
        B
      </div>

      <div className="min-w-0">
        {showAssistantShell && (
          <div
            className={cn(
              "rounded-[24px] border border-[rgba(32,43,35,0.08)] bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(248,251,247,0.98))] px-5 py-4 shadow-[0_14px_30px_rgba(32,43,35,0.04)] sm:px-6 sm:py-5",
              !message.content && "min-h-[6rem]"
            )}
          >
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <span className="text-[10px] font-semibold uppercase tracking-[0.22em] text-[var(--apex-accent-strong)]">
                BioAPEX
              </span>
              <span className="rounded-full border border-[rgba(32,43,35,0.08)] bg-[rgba(247,249,246,0.92)] px-2 py-0.5 text-[10px] uppercase tracking-[0.16em] text-slate-500">
                Response
              </span>
              {message.isStreaming && (
                <span className="inline-flex items-center gap-1.5 rounded-full border border-[rgba(35,130,83,0.16)] bg-[rgba(35,130,83,0.08)] px-2 py-0.5 text-[10px] uppercase tracking-[0.16em] text-[var(--apex-accent-strong)]">
                  <span className="h-1.5 w-1.5 rounded-full bg-[var(--apex-accent)] animate-blink" />
                  Streaming
                </span>
              )}
            </div>
            {message.content ? (
              <div
                className={cn(
                  "apex-chat-prose prose prose-sm max-w-none prose-pre:bg-[#1e1e1e] prose-pre:text-gray-100",
                  message.isStreaming && "streaming-cursor"
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
                        <div className="overflow-x-auto my-3">
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
                  {message.content}
                </ReactMarkdown>
              </div>
            ) : (
              <>
                {message.isStreaming ? (
                  <div className="flex min-h-[1.5rem] items-center">
                    <span className="inline-block h-4 w-0.5 animate-blink bg-[var(--apex-accent)]" />
                  </div>
                ) : hasSupport ? (
                  <p className="text-sm leading-6 text-slate-500">
                    Structured results are available below.
                  </p>
                ) : null}
              </>
            )}
          </div>
        )}

        {hasSupport && (
          <div className="mt-3 space-y-2.5">
            {hasRetrievals && <RetrievalCard results={message.retrievals ?? []} />}
            {hasWorkflowProgress && (
              <WorkflowProgressCard events={message.workflow_events ?? []} />
            )}
            {hasTrace && (
              <ThoughtChain
                toolCalls={message.tool_calls ?? []}
                workflowEvents={message.workflow_events ?? []}
                pendingTool={message.pendingTool}
              />
            )}
          </div>
        )}
      </div>
    </article>
  );
}
