"use client";

import { useMemo, useState } from "react";
import { useAppOptional } from "@/lib/store";
import type { SessionApprovalGateBlock } from "@/lib/types";

interface ApprovalGateProps {
  block: SessionApprovalGateBlock;
  sessionId: string | null;
}

const MAX_INLINE_PREVIEW_CHARS = 320;

function compactPreview(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return "(no arguments)";
  if (trimmed.length <= MAX_INLINE_PREVIEW_CHARS) {
    return trimmed;
  }
  return trimmed.slice(0, MAX_INLINE_PREVIEW_CHARS - 1) + "…";
}

function humanizeTool(name: string): string {
  return name.replace(/_/g, " ");
}

interface DecisionRecord {
  decision: "approve" | "deny";
  actor: string;
  rationale: string | null;
  recorded_at?: string;
}

function readPersistedDecision(
  block: SessionApprovalGateBlock
): DecisionRecord | null {
  // When the session is reloaded after POST /api/chat/approval, the backend
  // does not rewrite the approval_gate block with the decision — it keeps the
  // gate transparent as a record of "this is what was asked." The store tracks
  // the decision separately, so we return null here and fall back to local UI
  // state (see `localDecision`).
  void block;
  return null;
}

export default function ApprovalGate({ block, sessionId }: ApprovalGateProps) {
  const app = useAppOptional();
  const submitApprovalDecision = app?.submitApprovalDecision ?? null;
  const isStreaming = app?.isStreaming ?? false;
  const hasExecutionAccess = app?.hasExecutionAccess ?? false;
  const persistedDecision = useMemo(() => readPersistedDecision(block), [block]);
  const [localDecision, setLocalDecision] = useState<DecisionRecord | null>(
    persistedDecision
  );
  const [rationale, setRationale] = useState("");
  const [submitting, setSubmitting] = useState<null | "approve" | "deny">(null);
  const [error, setError] = useState<string | null>(null);

  const decided = localDecision !== null;
  const preview = compactPreview(block.input);
  const disabled =
    !sessionId ||
    !hasExecutionAccess ||
    !submitApprovalDecision ||
    submitting !== null ||
    isStreaming;

  const handleDecision = async (decision: "approve" | "deny") => {
    if (!sessionId || !submitApprovalDecision || disabled) return;
    setSubmitting(decision);
    setError(null);
    try {
      await submitApprovalDecision({
        sessionId,
        runId: block.run_id,
        toolName: block.tool,
        decision,
        rationale: rationale.trim() || null,
      });
      setLocalDecision({
        decision,
        actor: "ui-user",
        rationale: rationale.trim() || null,
      });
    } catch (exc) {
      setError(
        exc instanceof Error
          ? exc.message
          : "Failed to record the approval decision."
      );
    } finally {
      setSubmitting(null);
    }
  };

  const toolLabel = humanizeTool(block.tool);

  if (decided && localDecision) {
    const phrase =
      localDecision.decision === "approve"
        ? `Approved ${toolLabel}`
        : `Denied ${toolLabel}`;
    const tone =
      localDecision.decision === "approve"
        ? "border-emerald-200 bg-emerald-50/90 text-emerald-900"
        : "border-rose-200 bg-rose-50/90 text-rose-900";
    return (
      <div
        className={`rounded-[12px] border px-3 py-2 text-[12px] leading-5 shadow-[0_1px_2px_rgba(32,43,35,0.04)] ${tone}`}
        role="status"
        aria-live="polite"
      >
        <p className="font-semibold">{phrase}</p>
        {localDecision.rationale ? (
          <p className="mt-1 text-[11px] italic">
            Note: {localDecision.rationale}
          </p>
        ) : null}
        {localDecision.decision === "approve" ? (
          <p className="mt-1 text-[11px] text-emerald-700">
            Resuming the turn with the reviewer-approved call.
          </p>
        ) : (
          <p className="mt-1 text-[11px] text-rose-700">
            The reviewer blocked this call. Send a new message to continue
            without it.
          </p>
        )}
      </div>
    );
  }

  return (
    <section
      aria-label={`Approval required for ${toolLabel}`}
      className="space-y-2 rounded-[14px] border border-amber-200 bg-amber-50/90 px-3 py-3 shadow-[0_1px_2px_rgba(32,43,35,0.04)]"
      role="group"
    >
      <header className="flex flex-wrap items-center gap-2">
        <span className="rounded-full border border-amber-300 bg-amber-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-800">
          Approval required
        </span>
        <span className="font-mono text-[12px] font-semibold text-amber-900">
          {toolLabel}
        </span>
        <span className="text-[10px] text-amber-700">
          reason: {block.reason.replace(/_/g, " ")}
        </span>
      </header>

      {block.message ? (
        <p className="text-[12px] leading-5 text-amber-900">{block.message}</p>
      ) : null}

      <details className="rounded-[10px] border border-amber-200 bg-white/70 px-2 py-1.5 text-[11px] leading-5 text-slate-700">
        <summary className="cursor-pointer select-none font-semibold text-slate-800">
          Argument preview
        </summary>
        <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-words font-mono text-[10.5px] leading-5 text-slate-700">
          {preview}
        </pre>
      </details>

      <label className="block text-[11px] leading-5 text-slate-700">
        <span className="font-semibold text-slate-800">
          Rationale (optional)
        </span>
        <textarea
          className="mt-1 block w-full resize-y rounded-[10px] border border-amber-200 bg-white/90 px-2 py-1.5 text-[12px] leading-5 text-slate-800 focus:border-amber-400 focus:outline-none"
          rows={2}
          value={rationale}
          onChange={(event) => setRationale(event.target.value)}
          placeholder="Why are you approving or denying?"
          disabled={disabled}
          maxLength={2000}
        />
      </label>

      {error ? (
        <p className="text-[11px] leading-5 text-rose-700" role="alert">
          {error}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-2 pt-0.5">
        <button
          type="button"
          onClick={() => handleDecision("approve")}
          disabled={disabled}
          className="inline-flex items-center gap-1 rounded-full border border-emerald-300 bg-emerald-600 px-3 py-1 text-[12px] font-semibold text-white shadow-sm transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-60"
          aria-keyshortcuts="Alt+A"
        >
          {submitting === "approve" ? "Approving…" : "Approve"}
        </button>
        <button
          type="button"
          onClick={() => handleDecision("deny")}
          disabled={disabled}
          className="inline-flex items-center gap-1 rounded-full border border-rose-300 bg-white px-3 py-1 text-[12px] font-semibold text-rose-700 shadow-sm transition hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-60"
          aria-keyshortcuts="Alt+D"
        >
          {submitting === "deny" ? "Denying…" : "Deny"}
        </button>
        {!hasExecutionAccess ? (
          <span className="text-[10px] italic text-amber-800">
            Execution access is required to record decisions.
          </span>
        ) : null}
      </div>
    </section>
  );
}
