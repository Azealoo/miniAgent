"use client";

import { useEffect, useRef } from "react";
import { MessageSquarePlus } from "lucide-react";
import { useApp } from "@/lib/store";
import ChatMessage from "./ChatMessage";
import ChatInput from "./ChatInput";

export default function ChatPanel() {
  const { messages, isStreaming, currentSessionId, sendMessage } = useApp();

  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const isNearBottomRef = useRef(true);

  // Track whether user has scrolled up
  const handleScroll = () => {
    const el = containerRef.current;
    if (!el) return;
    const threshold = 80;
    isNearBottomRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < threshold;
  };

  // Auto-scroll when messages change (only if near bottom)
  useEffect(() => {
    if (isNearBottomRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  const handleSend = async (text: string) => {
    // sendMessage auto-creates a session if none exists
    await sendMessage(text);
  };

  return (
    <div className="flex flex-col h-full bg-[#fafafa]">
      {/* Messages */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-6 py-6"
      >
        {messages.length === 0 ? (
          <EmptyState />
        ) : (
          <>
            {messages.map((msg) => (
              <ChatMessage key={msg.id} message={msg} />
            ))}
          </>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <ChatInput
        onSend={handleSend}
        isStreaming={isStreaming}
      />
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center px-8">
      <div className="w-12 h-12 rounded-2xl bg-[#002FA7]/10 flex items-center justify-center mb-4">
        <MessageSquarePlus size={22} className="text-[#002FA7]" />
      </div>
      <h2 className="text-base font-semibold text-gray-700 mb-1">
        Start a conversation
      </h2>
      <p className="text-sm text-gray-400 max-w-xs">
        Ask Claw anything. Use skills for complex tasks, or let it use its
        built-in tools directly.
      </p>
    </div>
  );
}
