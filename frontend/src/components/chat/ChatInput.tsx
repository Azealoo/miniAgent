"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowUp, Square } from "lucide-react";
import { cn } from "@/lib/utils";

interface ChatInputProps {
  onSend: (text: string) => void;
  isStreaming: boolean;
  disabled?: boolean;
  prefillText?: string;
  prefillRevision?: number;
  clearPrefill?: () => void;
}

export default function ChatInput({
  onSend,
  isStreaming,
  disabled,
  prefillText = "",
  prefillRevision = 0,
  clearPrefill,
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

  useEffect(() => {
    setText(prefillText);

    if (!prefillText) return;

    requestAnimationFrame(() => {
      const el = textareaRef.current;
      if (!el) return;
      el.focus();
      const cursor = el.value.length;
      el.setSelectionRange(cursor, cursor);
    });
  }, [prefillText, prefillRevision]);

  const handleSend = useCallback(() => {
    const trimmed = text.trim();
    if (!trimmed || isStreaming || disabled) return;
    onSend(trimmed);
    setText("");
    clearPrefill?.();
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  }, [text, isStreaming, disabled, onSend, clearPrefill]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="w-full">
      <div
        className={cn(
          "flex items-end gap-3 rounded-[16px] border bg-white px-4 py-3 transition-all",
          "border-[var(--shell-border)] focus-within:border-[var(--apex-accent)] focus-within:shadow-[0_0_0_3px_rgba(35,130,83,0.1)]",
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
              : "Message BioAPEX… (Enter to send, Shift+Enter for newline)"
          }
          disabled={disabled || isStreaming}
          className="max-h-40 flex-1 resize-none overflow-y-auto bg-transparent text-sm leading-relaxed text-slate-800 outline-none placeholder:text-slate-400 disabled:cursor-not-allowed"
        />

        <button
          onClick={handleSend}
          disabled={!text.trim() || isStreaming || disabled}
          className={cn(
            "flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full transition-colors",
            text.trim() && !isStreaming && !disabled
              ? "bg-[var(--apex-accent)] text-white hover:bg-[var(--apex-accent-strong)]"
              : "bg-slate-200 text-slate-400 cursor-not-allowed"
          )}
        >
          {isStreaming ? (
            <Square size={13} className="fill-current" />
          ) : (
            <ArrowUp size={14} strokeWidth={2.5} />
          )}
        </button>
      </div>
      <p className="mt-2 px-1 text-[11px] text-slate-400">
        BioAPEX can make mistakes. Verify important scientific and operational details.
      </p>
    </div>
  );
}
