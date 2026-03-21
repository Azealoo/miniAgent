"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { cn } from "@/lib/utils";
import ThoughtChain from "./ThoughtChain";
import RetrievalCard from "./RetrievalCard";
import type { Message } from "@/lib/types";

interface ChatMessageProps {
  message: Message;
}

export default function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === "user";

  if (isUser) {
    return (
      <div className="mb-4 flex justify-end">
        <div className="max-w-[72%] rounded-[22px] rounded-tr-md bg-[linear-gradient(135deg,var(--apex-accent),var(--apex-accent-strong))] px-4 py-3 text-sm leading-relaxed text-white shadow-[0_14px_28px_rgba(47,122,95,0.16)]">
          {message.content}
        </div>
      </div>
    );
  }

  // Assistant message
  return (
    <div className="mb-5 flex gap-3">
      <div className="mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full border border-[rgba(47,122,95,0.14)] bg-[linear-gradient(135deg,rgba(255,255,255,0.96),rgba(228,241,233,0.96))] text-xs font-bold text-[var(--apex-accent-strong)] shadow-sm">
        B
      </div>

      <div className="flex-1 min-w-0">
        {message.retrievals && message.retrievals.length > 0 && (
          <RetrievalCard results={message.retrievals} />
        )}

        {((message.tool_calls && message.tool_calls.length > 0) ||
          (message.workflow_events && message.workflow_events.length > 0) ||
          message.pendingTool) && (
          <ThoughtChain
            toolCalls={message.tool_calls ?? []}
            workflowEvents={message.workflow_events ?? []}
            pendingTool={message.pendingTool}
          />
        )}

        {(message.content || message.isStreaming) && (
          <div
            className={cn(
              "mt-2 text-sm text-slate-800",
              message.isStreaming && !message.content && "h-5"
            )}
          >
            {message.content ? (
              <div
                className={cn(
                  "prose prose-sm max-w-none prose-pre:bg-[#1e1e1e] prose-pre:text-gray-100",
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
              message.isStreaming && (
                <span className="inline-block h-4 w-0.5 animate-blink bg-[var(--apex-accent)]" />
              )
            )}
          </div>
        )}
      </div>
    </div>
  );
}
