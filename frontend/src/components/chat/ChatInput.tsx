"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowUp, Square } from "lucide-react";
import { cn } from "@/lib/utils";

interface ChatInputProps {
  onSend: (text: string) => void;
  isStreaming: boolean;
  disabled?: boolean;
}

export default function ChatInput({
  onSend,
  isStreaming,
  disabled,
}: ChatInputProps) {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  }, [text]);

  const handleSend = useCallback(() => {
    const trimmed = text.trim();
    if (!trimmed || isStreaming || disabled) return;
    onSend(trimmed);
    setText("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  }, [text, isStreaming, disabled, onSend]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="border-t border-gray-200 bg-white/90 backdrop-blur px-4 py-3">
      <div
        className={cn(
          "flex items-end gap-3 border rounded-2xl px-4 py-2.5 transition-shadow",
          "border-gray-300 focus-within:border-[#002FA7] focus-within:shadow-[0_0_0_3px_rgba(0,47,167,0.1)]",
          disabled && "opacity-50"
        )}
      >
        <textarea
          ref={textareaRef}
          rows={1}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            disabled
              ? "Select or create a session first…"
              : "Message Claw… (Enter to send, Shift+Enter for newline)"
          }
          disabled={disabled || isStreaming}
          className="flex-1 resize-none bg-transparent text-sm text-gray-800 placeholder:text-gray-400 outline-none max-h-40 overflow-y-auto leading-relaxed disabled:cursor-not-allowed"
        />

        <button
          onClick={handleSend}
          disabled={!text.trim() || isStreaming || disabled}
          className={cn(
            "w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 transition-colors",
            text.trim() && !isStreaming && !disabled
              ? "bg-[#002FA7] text-white hover:bg-[#001F7A]"
              : "bg-gray-200 text-gray-400 cursor-not-allowed"
          )}
        >
          {isStreaming ? (
            <Square size={13} className="fill-current" />
          ) : (
            <ArrowUp size={14} strokeWidth={2.5} />
          )}
        </button>
      </div>
      <p className="text-[10px] text-gray-400 text-center mt-1.5">
        Claw can make mistakes. Verify important information.
      </p>
    </div>
  );
}
