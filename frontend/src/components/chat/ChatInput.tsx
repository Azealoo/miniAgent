"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowUp, GitBranch, Paperclip, Plus, Square, X } from "lucide-react";
import { cn } from "@/lib/utils";

interface ChatInputProps {
  onSend: (text: string) => void;
  isStreaming: boolean;
  isReferenceUploading: boolean;
  disabled?: boolean;
  disabledReason?: string;
  selectedWorkflow: string | null;
  onSelectWorkflow: (workflowId: string | null) => void;
  attachedIdentifiers: string[];
  onUploadReferenceFile: (file: File) => Promise<void>;
  onRemoveAttachedIdentifier: (identifier: string) => void;
  onClearAttachedIdentifiers: () => void;
  prefillText?: string;
  prefillRevision?: number;
  clearPrefill?: () => void;
}

interface WorkflowOption {
  value: string;
  label: string;
}

const WORKFLOW_OPTIONS: WorkflowOption[] = [
  { value: "rnaseq_qc_de", label: "RNA-seq QC + DE" },
  { value: "rna-seq-qc", label: "RNA-seq QC" },
  { value: "perturb-seq-nextflow", label: "Perturb-seq Nextflow" },
];

function formatWorkflowLabel(value: string): string {
  return value.replaceAll("_", " ").replaceAll("-", " ");
}

function shortenIdentifier(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return value;

  const parts = trimmed.split("/").filter(Boolean);
  if (parts.length <= 2) return trimmed;
  return parts.slice(-2).join("/");
}

function ControlButton({
  active,
  disabled,
  title,
  onClick,
  children,
}: {
  active?: boolean;
  disabled?: boolean;
  title: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "inline-flex h-7 w-7 items-center justify-center rounded-full border transition-colors",
        disabled
          ? "cursor-not-allowed border-[var(--shell-border)] bg-[var(--panel-soft)] text-slate-400"
          : active
            ? "border-[rgba(35,130,83,0.18)] bg-[rgba(35,130,83,0.1)] text-[var(--apex-accent-strong)]"
            : "border-[rgba(211,219,210,0.96)] bg-white/88 text-slate-500 hover:border-[rgba(35,130,83,0.24)] hover:text-[var(--apex-accent-strong)]"
      )}
    >
      {children}
    </button>
  );
}

export default function ChatInput({
  onSend,
  isStreaming,
  isReferenceUploading,
  disabled,
  disabledReason,
  selectedWorkflow,
  onSelectWorkflow,
  attachedIdentifiers,
  onUploadReferenceFile,
  onRemoveAttachedIdentifier,
  onClearAttachedIdentifiers,
  prefillText = "",
  prefillRevision = 0,
  clearPrefill,
}: ChatInputProps) {
  const [text, setText] = useState("");
  const [showWorkflowPicker, setShowWorkflowPicker] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const hasContextChips = Boolean(selectedWorkflow) || attachedIdentifiers.length > 0;
  const requestLocked = disabled || isStreaming || isReferenceUploading;

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;

    el.style.height = "auto";
    el.style.height = `${Math.min(Math.max(el.scrollHeight, 48), 72)}px`;
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
    if (!trimmed || requestLocked) return;

    onSend(trimmed);
    setText("");
    clearPrefill?.();
    setShowWorkflowPicker(false);

    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, [clearPrefill, onSend, requestLocked, text]);

  const handleTextKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const toggleWorkflowPicker = () => {
    if (requestLocked) return;
    setShowWorkflowPicker((value) => !value);
  };

  const openFilePicker = () => {
    if (requestLocked) return;
    setUploadError(null);
    fileInputRef.current?.click();
  };

  const handleFileSelected = useCallback(
    async (event: React.ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      event.target.value = "";
      if (!file || disabled || isStreaming || isReferenceUploading) return;

      setShowWorkflowPicker(false);
      setUploadError(null);

      try {
        await onUploadReferenceFile(file);
      } catch (error) {
        const message =
          error instanceof Error
            ? error.message
            : "Unable to upload that reference file right now.";
        setUploadError(message);
      }
    },
    [disabled, isReferenceUploading, isStreaming, onUploadReferenceFile]
  );

  const helperText = disabled
    ? disabledReason ?? "Loading workspace"
    : isReferenceUploading
      ? "Uploading reference..."
      : uploadError
        ? uploadError
        : isStreaming
          ? "Streaming response"
          : "Shift+Enter for newline";

  return (
    <div
      className={cn(
        "w-full rounded-[20px] border border-[rgba(210,219,211,0.95)] bg-[linear-gradient(180deg,rgba(255,255,255,0.97)_0%,rgba(247,249,246,0.98)_100%)] px-3 py-2 shadow-[0_14px_28px_rgba(29,42,33,0.06)] backdrop-blur-sm transition-all",
        "focus-within:border-[rgba(35,130,83,0.24)] focus-within:shadow-[0_18px_36px_rgba(29,42,33,0.08)]",
        disabled && "opacity-70"
      )}
    >
      {hasContextChips ? (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {selectedWorkflow ? (
            <span className="inline-flex items-center gap-1 rounded-full border border-[rgba(35,130,83,0.14)] bg-[rgba(35,130,83,0.08)] px-2 py-1 text-[10px] font-medium text-[var(--apex-accent-strong)]">
              <GitBranch size={11} />
              <span>{formatWorkflowLabel(selectedWorkflow)}</span>
              <button
                type="button"
                onClick={() => onSelectWorkflow(null)}
                disabled={requestLocked}
                className={cn(
                  "inline-flex h-3.5 w-3.5 items-center justify-center rounded-full",
                  requestLocked
                    ? "cursor-not-allowed text-slate-400"
                    : "hover:bg-[rgba(35,130,83,0.14)]"
                )}
              >
                <X size={10} />
              </button>
            </span>
          ) : null}

          {attachedIdentifiers.map((identifier) => (
            <span
              key={identifier}
              className="inline-flex max-w-full items-center gap-1 rounded-full border border-[rgba(35,130,83,0.14)] bg-[rgba(35,130,83,0.08)] px-2 py-1 text-[10px] font-medium text-[var(--apex-accent-strong)]"
              title={identifier}
            >
              <Paperclip size={11} />
              <span className="max-w-[11rem] truncate">{shortenIdentifier(identifier)}</span>
              <button
                type="button"
                onClick={() => onRemoveAttachedIdentifier(identifier)}
                disabled={requestLocked}
                className={cn(
                  "inline-flex h-3.5 w-3.5 items-center justify-center rounded-full",
                  requestLocked
                    ? "cursor-not-allowed text-slate-400"
                    : "hover:bg-[rgba(35,130,83,0.14)]"
                )}
              >
                <X size={10} />
              </button>
            </span>
          ))}

          {attachedIdentifiers.length > 1 ? (
            <button
              type="button"
              onClick={onClearAttachedIdentifiers}
              disabled={requestLocked}
              className={cn(
                "inline-flex items-center rounded-full border px-2 py-1 text-[10px] font-medium transition-colors",
                requestLocked
                  ? "cursor-not-allowed border-[var(--shell-border)] bg-[var(--panel-soft)] text-slate-400"
                  : "border-[rgba(211,219,210,0.92)] bg-white/88 text-slate-500 hover:bg-[var(--panel-soft)] hover:text-slate-700"
              )}
            >
              Clear
            </button>
          ) : null}
        </div>
      ) : null}

      {showWorkflowPicker ? (
        <div className="mb-2 rounded-[16px] border border-[rgba(211,219,210,0.92)] bg-white/88 p-2">
          <div className="flex flex-wrap gap-1.5">
            <button
              type="button"
              onClick={() => {
                onSelectWorkflow(null);
                setShowWorkflowPicker(false);
              }}
              className={cn(
                "rounded-full border px-2.5 py-1 text-[10px] font-medium transition-colors",
                !selectedWorkflow
                  ? "border-[rgba(35,130,83,0.18)] bg-[rgba(35,130,83,0.1)] text-[var(--apex-accent-strong)]"
                  : "border-[rgba(211,219,210,0.96)] bg-white text-slate-600 hover:border-[rgba(35,130,83,0.24)]"
              )}
            >
              No workflow
            </button>
            {WORKFLOW_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => {
                  onSelectWorkflow(option.value);
                  setShowWorkflowPicker(false);
                }}
                className={cn(
                  "rounded-full border px-2.5 py-1 text-[10px] font-medium transition-colors",
                  selectedWorkflow === option.value
                    ? "border-[rgba(35,130,83,0.18)] bg-[rgba(35,130,83,0.1)] text-[var(--apex-accent-strong)]"
                    : "border-[rgba(211,219,210,0.96)] bg-white text-slate-600 hover:border-[rgba(35,130,83,0.24)]"
                )}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      <textarea
        ref={textareaRef}
        rows={2}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleTextKeyDown}
        placeholder={
          disabled
            ? disabledReason ??
              "The workspace is still loading. Input will unlock once the session is ready."
            : "Describe the scientific question, workflow step, or evidence task you want BioAPEX to handle."
        }
        disabled={disabled || isStreaming}
        className="min-h-[48px] max-h-[72px] w-full resize-none overflow-y-auto bg-transparent text-[15px] leading-6 text-slate-800 outline-none placeholder:text-slate-400 disabled:cursor-not-allowed"
      />

      <input
        ref={fileInputRef}
        type="file"
        accept="text/*,.csv,.tsv,.json,.yaml,.yml,.md,.fa,.fasta,.fq,.fastq,.bed,.gtf,.gff,.sam,.vcf"
        onChange={(event) => {
          void handleFileSelected(event);
        }}
        className="hidden"
        tabIndex={-1}
      />

      <div className="mt-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <ControlButton
            title={selectedWorkflow ? "Change workflow" : "Choose workflow"}
            onClick={toggleWorkflowPicker}
            active={showWorkflowPicker || Boolean(selectedWorkflow)}
            disabled={requestLocked}
          >
            <GitBranch size={13} />
          </ControlButton>

          <ControlButton
            title="Upload reference file"
            onClick={openFilePicker}
            active={isReferenceUploading || attachedIdentifiers.length > 0}
            disabled={requestLocked}
          >
            <Plus size={13} />
          </ControlButton>

          <span
            className={cn(
              "max-w-[12rem] truncate text-[10px] sm:max-w-[16rem]",
              uploadError ? "text-rose-500" : "text-slate-400"
            )}
          >
            {helperText}
          </span>
        </div>

        <button
          type="button"
          title={
            isReferenceUploading
              ? "Waiting for reference upload"
              : isStreaming
                ? "Streaming"
                : "Send message"
          }
          onClick={handleSend}
          disabled={!text.trim() || requestLocked}
          className={cn(
            "inline-flex h-8 w-8 items-center justify-center rounded-full transition-colors",
            !text.trim() || requestLocked
              ? "cursor-not-allowed bg-slate-200 text-slate-400"
              : "bg-[var(--apex-accent)] text-white hover:bg-[var(--apex-accent-strong)]"
          )}
        >
          {isStreaming ? (
            <Square size={11} className="fill-current" />
          ) : (
            <ArrowUp size={13} strokeWidth={2.5} />
          )}
        </button>
      </div>

      <p className="mt-1.5 px-0.5 text-[10px] text-slate-400">
        BioAPEX can make mistakes. Verify important scientific and operational details.
      </p>
    </div>
  );
}
