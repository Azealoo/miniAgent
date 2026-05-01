"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowUp, Square } from "lucide-react";
import { quickStartItems } from "@/components/layout/workspace-data";
import type { InspectorTab } from "@/lib/types";
import { cn } from "@/lib/utils";

interface ChatInputProps {
  onSend: (text: string) => void;
  onStop: () => void;
  isStreaming: boolean;
  disabled?: boolean;
  disabledReason?: string;
  onOpenInspectorTab: (tab: InspectorTab) => void;
  onPrimeDraftMessage: (text: string) => void;
  prefillText?: string;
  prefillRevision?: number;
  clearPrefill?: () => void;
}

interface ComposerQuickAction {
  id: string;
  command: string;
  label: string;
  description: string;
  kind: "prompt" | "inspector";
  draftMessage?: string;
  inspectorTab?: InspectorTab;
}

const QUICK_ACTION_COMMANDS: Record<string, string> = {
  "find-papers": "/papers",
  "summarize-pdf": "/summarize",
  "design-primers": "/primers",
};

const COMPOSER_QUICK_ACTIONS: ComposerQuickAction[] = [
  ...quickStartItems.map((item) => ({
    id: item.id,
    command: QUICK_ACTION_COMMANDS[item.id] ?? `/${item.id}`,
    label: item.label,
    description: item.description,
    kind: "prompt" as const,
    draftMessage: item.draftMessage,
  })),
  {
    id: "inspect-sources",
    command: "/sources",
    label: "Inspect Sources",
    description: "Open the Sources inspector for the current turn and its supporting context.",
    kind: "inspector",
    inspectorTab: "sources",
  },
  {
    id: "turn-details",
    command: "/turns",
    label: "Turn Details",
    description: "Open the full turn-by-turn runtime trace in the inspector.",
    kind: "inspector",
    inspectorTab: "turns",
  },
  {
    id: "open-files",
    command: "/files",
    label: "Open Files",
    description: "Open the generated files inspector for the active session.",
    kind: "inspector",
    inspectorTab: "files",
  },
];

export default function ChatInput({
  onSend,
  onStop,
  isStreaming,
  disabled,
  disabledReason,
  onOpenInspectorTab,
  onPrimeDraftMessage,
  prefillText = "",
  prefillRevision = 0,
  clearPrefill,
}: ChatInputProps) {
  const [text, setText] = useState("");
  const [activeSlashActionIndex, setActiveSlashActionIndex] = useState(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const composerDisabled = Boolean(disabled);
  const normalizedText = text.trim().toLowerCase();
  const showSlashCommands =
    !composerDisabled && !isStreaming && text.trimStart().startsWith("/");
  const matchingSlashActions = showSlashCommands
    ? COMPOSER_QUICK_ACTIONS.filter((action) =>
        action.command.startsWith(normalizedText)
      )
    : [];
  const exactSlashAction = showSlashCommands
    ? matchingSlashActions.find((action) => action.command === normalizedText) ?? null
    : null;

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;

    el.style.height = "auto";
    el.style.height = `${Math.min(Math.max(el.scrollHeight, 36), 60)}px`;
  }, [text]);

  useEffect(() => {
    setText(prefillText);

    if (!prefillText) return;

    const rafId = requestAnimationFrame(() => {
      const el = textareaRef.current;
      if (!el) return;
      el.focus();
      const cursor = el.value.length;
      el.setSelectionRange(cursor, cursor);
    });

    return () => cancelAnimationFrame(rafId);
  }, [prefillText, prefillRevision]);

  useEffect(() => {
    setActiveSlashActionIndex(0);
  }, [normalizedText]);

  const handleSend = useCallback(() => {
    const trimmed = text.trim();
    if (!trimmed || composerDisabled || isStreaming) return;

    onSend(trimmed);
    setText("");
    setActiveSlashActionIndex(0);
    clearPrefill?.();

    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, [clearPrefill, composerDisabled, isStreaming, onSend, text]);

  const runComposerAction = useCallback(
    (action: ComposerQuickAction) => {
      setActiveSlashActionIndex(0);

      if (action.kind === "prompt" && action.draftMessage) {
        onPrimeDraftMessage(action.draftMessage);
        setText(action.draftMessage);
        requestAnimationFrame(() => {
          const el = textareaRef.current;
          if (!el) return;
          el.focus();
          const cursor = action.draftMessage?.length ?? 0;
          el.setSelectionRange(cursor, cursor);
        });
        return;
      }

      setText("");

      if (action.kind === "inspector" && action.inspectorTab) {
        onOpenInspectorTab(action.inspectorTab);
        return;
      }
    },
    [onOpenInspectorTab, onPrimeDraftMessage]
  );

  const handleTextKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (showSlashCommands && matchingSlashActions.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveSlashActionIndex((value) =>
          (value + 1) % matchingSlashActions.length
        );
        return;
      }

      if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveSlashActionIndex((value) =>
          value === 0 ? matchingSlashActions.length - 1 : value - 1
        );
        return;
      }

      if (e.key === "Tab" && !e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault();
        setText(matchingSlashActions[activeSlashActionIndex]?.command ?? text);
        return;
      }
    }

    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (exactSlashAction) {
        runComposerAction(exactSlashAction);
        return;
      }
      handleSend();
    }
  };
  const helperText = disabled ? disabledReason ?? "Loading workspace" : null;

  return (
    <div
      className={cn(
        "w-full rounded-[20px] border border-[rgba(208,216,209,0.92)] bg-[rgba(252,253,250,0.98)] px-3 py-2 shadow-[0_10px_30px_rgba(29,42,33,0.05)] backdrop-blur-sm transition-all",
        "focus-within:border-[rgba(35,130,83,0.18)]",
        disabled && "opacity-70"
      )}
    >
      {showSlashCommands ? (
        <div className="mb-2.5 border-l border-[rgba(211,219,210,0.92)] pl-3">
          <div className="flex items-center justify-between gap-2">
            <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
              Matching Commands
            </p>
            <span className="text-[10px] text-slate-400">Tab to complete</span>
          </div>

          {matchingSlashActions.length > 0 ? (
            <div className="mt-1.5 space-y-1">
              {matchingSlashActions.map((action, index) => {
                const active = index === activeSlashActionIndex;

                return (
                  <button
                    key={action.id}
                    type="button"
                    onClick={() => runComposerAction(action)}
                    className={cn(
                      "flex w-full items-start gap-3 rounded-[12px] border-l-2 px-3 py-1.5 text-left transition-colors",
                      active
                        ? "border-[rgba(35,130,83,0.28)] bg-[rgba(35,130,83,0.06)]"
                        : "border-transparent hover:border-[rgba(35,130,83,0.18)] hover:bg-[rgba(35,130,83,0.03)]"
                    )}
                  >
                    <span className="mt-[1px] font-mono text-[11px] font-semibold text-[var(--apex-accent-strong)]">
                      {action.command}
                    </span>
                    <span className="min-w-0">
                      <span className="block text-[11px] font-medium text-slate-700">
                        {action.label}
                      </span>
                      <span className="mt-1 block truncate text-[11px] text-slate-500">
                        {action.description}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          ) : (
            <p className="mt-1.5 text-[11px] text-slate-500">
              No matching commands. Try /papers, /summarize, /primers, /sources,
              /turns, or /files.
            </p>
          )}
        </div>
      ) : null}

      <textarea
        ref={textareaRef}
        rows={1}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleTextKeyDown}
        placeholder={
          disabled
            ? disabledReason ??
              "The workspace is still loading. Input will unlock once the session is ready."
            : "Ask any biology related questions"
        }
        disabled={disabled || isStreaming}
        className="min-h-[36px] max-h-[72px] w-full resize-none overflow-y-auto bg-transparent py-0.5 font-mono text-[14px] leading-[1.45] text-slate-800 outline-none placeholder:text-slate-400 disabled:cursor-not-allowed"
      />

      <div
        className={cn(
          "mt-1 flex items-center gap-2",
          helperText ? "justify-between" : "justify-end"
        )}
      >
        {helperText ? (
          <span className="min-w-0 truncate font-mono text-[10px] text-slate-400">
            {helperText}
          </span>
        ) : null}
        <button
          type="button"
          title={isStreaming ? "Stop response" : "Send message"}
          aria-label={isStreaming ? "Stop response" : "Send message"}
          onClick={isStreaming ? onStop : handleSend}
          disabled={isStreaming ? composerDisabled : !text.trim() || composerDisabled}
          className={cn(
            "inline-flex h-8 w-8 items-center justify-center rounded-full border transition-colors",
            (isStreaming ? composerDisabled : !text.trim() || composerDisabled)
              ? "cursor-not-allowed border-[rgba(211,219,210,0.92)] bg-[rgba(243,245,242,0.9)] text-slate-400"
              : "border-[rgba(35,130,83,0.18)] bg-[rgba(35,130,83,0.06)] text-[var(--apex-accent-strong)] hover:bg-[rgba(35,130,83,0.1)]"
          )}
        >
          {isStreaming ? (
            <Square size={11} className="fill-current" />
          ) : (
            <ArrowUp size={13} strokeWidth={2.5} />
          )}
        </button>
      </div>
    </div>
  );
}
