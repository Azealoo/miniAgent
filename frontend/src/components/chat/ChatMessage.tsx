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
      <div className="flex justify-end mb-4">
        <div className="max-w-[70%] bg-[#002FA7] text-white rounded-2xl rounded-tr-sm px-4 py-2.5 text-sm leading-relaxed shadow-sm">
          {message.content}
        </div>
      </div>
    );
  }

  // Assistant message
  return (
    <div className="flex gap-3 mb-4">
      {/* Avatar */}
      <div className="w-7 h-7 rounded-full bg-gradient-to-br from-[#002FA7] to-blue-400 flex items-center justify-center text-white text-xs font-bold flex-shrink-0 mt-0.5 shadow-sm">
        C
      </div>

      <div className="flex-1 min-w-0">
        {/* RAG retrieval results */}
        {message.retrievals && message.retrievals.length > 0 && (
          <RetrievalCard results={message.retrievals} />
        )}

        {/* Tool calls (thought chain) */}
        {((message.tool_calls && message.tool_calls.length > 0) ||
          message.pendingTool) && (
          <ThoughtChain
            toolCalls={message.tool_calls ?? []}
            pendingTool={message.pendingTool}
          />
        )}

        {/* Text content */}
        {(message.content || message.isStreaming) && (
          <div
            className={cn(
              "mt-2 text-sm text-gray-800",
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
                    // Inline code
                    code({ className, children, ...props }) {
                      const match = /language-(\w+)/.exec(className ?? "");
                      if (!match) {
                        return (
                          <code
                            className="bg-gray-100 text-[#c7254e] px-1 py-0.5 rounded text-[0.8em] font-mono"
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
                    // Tables
                    table({ children }) {
                      return (
                        <div className="overflow-x-auto my-3">
                          <table className="min-w-full border border-gray-200 rounded-lg overflow-hidden text-xs">
                            {children}
                          </table>
                        </div>
                      );
                    },
                    th({ children }) {
                      return (
                        <th className="bg-gray-50 border-b border-gray-200 px-3 py-2 text-left font-semibold text-gray-700">
                          {children}
                        </th>
                      );
                    },
                    td({ children }) {
                      return (
                        <td className="border-b border-gray-100 px-3 py-2 text-gray-600">
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
              // Empty streaming state — show blinking cursor
              message.isStreaming && (
                <span className="inline-block w-0.5 h-4 bg-[#002FA7] animate-blink" />
              )
            )}
          </div>
        )}
      </div>
    </div>
  );
}
