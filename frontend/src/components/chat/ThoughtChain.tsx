"use client";

import { useState, type ReactNode } from "react";
import {
  ChevronDown,
  ChevronRight,
  Code2,
  FileText,
  Globe,
  Search,
  ShieldAlert,
  Terminal,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type {
  ComplianceReportArtifact,
  JsonValue,
  ToolCall,
  ToolResultEnvelope,
} from "@/lib/types";

const TOOL_ICONS: Record<string, ReactNode> = {
  compliance_preflight: <FileText size={12} />,
  evidence_review_gate: <ShieldAlert size={12} />,
  terminal: <Terminal size={12} />,
  python_repl: <Code2 size={12} />,
  fetch_url: <Globe size={12} />,
  read_file: <FileText size={12} />,
  search_knowledge_base: <Search size={12} />,
  slurm_tool: <Terminal size={12} />,
  ncbi_eutils: <Globe size={12} />,
  evidence_retrieval: <Search size={12} />,
  evidence_review: <ShieldAlert size={12} />,
  uniprot_api: <Globe size={12} />,
  ensembl_api: <Globe size={12} />,
  write_file: <FileText size={12} />,
};

const MAX_RENDERED_JSON_CHARS = 8_000;

function formatJsonValue(value: JsonValue | undefined): string {
  if (value === undefined) return "";
  const rendered =
    typeof value === "string" ? value : JSON.stringify(value, null, 2);
  if (rendered.length <= MAX_RENDERED_JSON_CHARS) {
    return rendered;
  }
  return `${rendered.slice(0, MAX_RENDERED_JSON_CHARS)}\n...[display truncated]`;
}

function humanizeUnderscoreValue(value?: string | null): string {
  if (!value) return "unknown";
  return value.replaceAll("_", " ");
}

function compactText(value?: string | null, maxLength = 120): string | null {
  if (!value) return null;
  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized) return null;
  if (normalized.length <= maxLength) return normalized;
  return `${normalized.slice(0, maxLength - 1)}…`;
}

function complianceRuntimeState(report: ComplianceReportArtifact | null): string | null {
  return typeof report?.runtime_state === "string" ? report.runtime_state : null;
}

function compliancePreflightDisposition(
  report: ComplianceReportArtifact | null
): string | null {
  return typeof report?.preflight_disposition === "string"
    ? report.preflight_disposition
    : null;
}

function complianceFinalDisposition(report: ComplianceReportArtifact | null): string | null {
  return typeof report?.final_disposition === "string" ? report.final_disposition : null;
}

function outcomeBadgeClass(result?: ToolResultEnvelope): string {
  if (!result) return "border-slate-200 bg-slate-100 text-slate-500";
  const reviewStatus = evidenceReviewStatus(result);
  if (evidenceReviewRequired(result)) return "border-amber-200 bg-amber-50 text-amber-700";
  if (evidenceReviewUnsupported(result)) return "border-rose-200 bg-rose-50 text-rose-700";
  if (reviewStatus === "mixed") return "border-amber-200 bg-amber-50 text-amber-700";
  if (reviewStatus === "supported") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  const complianceReport = getComplianceReport(result);
  const runtimeState = complianceRuntimeState(complianceReport);
  if (runtimeState === "approved_override") return "border-sky-200 bg-sky-50 text-sky-700";
  if (runtimeState === "approval_required") return "border-amber-200 bg-amber-50 text-amber-700";
  if (runtimeState === "blocked") return "border-rose-200 bg-rose-50 text-rose-700";
  if (runtimeState === "warning_issued") return "border-amber-200 bg-amber-50 text-amber-700";
  if (result.warnings.includes("approval_required")) {
    return "border-amber-200 bg-amber-50 text-amber-700";
  }
  if (result.warnings.includes("blocked_by_compliance")) {
    return "border-rose-200 bg-rose-50 text-rose-700";
  }
  if (result.warnings.includes("compliance_warning")) {
    return "border-amber-200 bg-amber-50 text-amber-700";
  }
  if (result.status === "error") return "border-rose-200 bg-rose-50 text-rose-700";
  if (result.outcome === "success_empty") return "border-amber-200 bg-amber-50 text-amber-700";
  return "border-emerald-200 bg-emerald-50 text-emerald-700";
}

function outcomeBadgeText(call: ToolCall): string {
  const result = call.result;
  if (!result) return "completed";
  if (evidenceReviewRequired(result)) return "review required";
  if (evidenceReviewUnsupported(result)) return "unsupported claims";
  const reviewStatus = evidenceReviewStatus(result);
  if (reviewStatus) return humanizeUnderscoreValue(reviewStatus);
  const complianceReport = getComplianceReport(result);
  const runtimeState = complianceRuntimeState(complianceReport);
  if (runtimeState) {
    return humanizeUnderscoreValue(runtimeState);
  }
  const finalDisposition = complianceFinalDisposition(complianceReport);
  if (finalDisposition) {
    return humanizeUnderscoreValue(finalDisposition);
  }
  if (call.tool === "compliance_preflight") {
    if (result.warnings.includes("approval_required")) return "approval required";
    if (result.warnings.includes("blocked_by_compliance")) return "blocked";
    if (result.warnings.includes("compliance_warning")) return "warning";
  }
  return result.outcome.replaceAll("_", " ");
}

function getComplianceReport(result?: ToolResultEnvelope): ComplianceReportArtifact | null {
  const payload = result?.structured_payload;
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return null;
  }
  const report = (payload as Record<string, JsonValue>).report;
  if (!report || typeof report !== "object" || Array.isArray(report)) {
    return null;
  }
  if ((report as Record<string, JsonValue>).artifact_type !== "compliance_report") {
    return null;
  }
  return report as unknown as ComplianceReportArtifact;
}

function getAuditLogPath(result?: ToolResultEnvelope): string | null {
  const payload = result?.structured_payload;
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return null;
  }
  const auditLogPath = (payload as Record<string, JsonValue>).audit_log_path;
  return typeof auditLogPath === "string" ? auditLogPath : null;
}

function getEvidenceReviewPayload(
  result?: ToolResultEnvelope
): Record<string, JsonValue> | null {
  const payload = result?.structured_payload;
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return null;
  }
  const record = payload as Record<string, JsonValue>;
  if (
    typeof record.review_status === "string" ||
    typeof record.requires_review === "boolean"
  ) {
    return record;
  }
  return null;
}

function evidenceReviewStatus(result?: ToolResultEnvelope): string | null {
  const payload = getEvidenceReviewPayload(result);
  const reviewStatus = payload?.review_status;
  return typeof reviewStatus === "string" ? reviewStatus : null;
}

function evidenceReviewUnsupported(result?: ToolResultEnvelope): boolean {
  const payload = getEvidenceReviewPayload(result);
  return payload?.unsupported_claims_present === true;
}

function evidenceReviewRequired(result?: ToolResultEnvelope): boolean {
  const payload = getEvidenceReviewPayload(result);
  return payload?.requires_review === true;
}

function metadataNumber(result: ToolResultEnvelope | undefined, key: string): number | null {
  const value = result?.metadata?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function formatDuration(seconds: number): string {
  if (seconds >= 60) {
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = Math.round(seconds % 60);
    return `${minutes}m ${remainingSeconds}s`;
  }
  if (seconds >= 10) {
    return `${Math.round(seconds)}s`;
  }
  return `${seconds.toFixed(1)}s`;
}

function formatCountMetric(value: number, noun: string): string {
  const rounded = Number.isInteger(value) ? value : Math.round(value);
  return `${rounded.toLocaleString()} ${noun}${rounded === 1 ? "" : "s"}`;
}

function toolMetric(call: ToolCall): string | null {
  const result = call.result;
  if (!result) return null;

  const durationSeconds = metadataNumber(result, "duration_seconds");
  if (durationSeconds !== null && durationSeconds >= 0) {
    return formatDuration(durationSeconds);
  }

  const durationMs = metadataNumber(result, "duration_ms");
  if (durationMs !== null && durationMs >= 0) {
    return durationMs >= 1000
      ? formatDuration(durationMs / 1000)
      : `${Math.round(durationMs)}ms`;
  }

  const countMetrics: Array<[string, string]> = [
    ["result_count", "result"],
    ["artifact_count", "artifact"],
    ["character_count", "char"],
    ["byte_count", "byte"],
    ["line_count", "line"],
    ["row_count", "row"],
    ["token_count", "token"],
    ["total_tokens", "token"],
  ];

  for (const [key, noun] of countMetrics) {
    const value = metadataNumber(result, key);
    if (value !== null && value >= 0) {
      return formatCountMetric(value, noun);
    }
  }

  if (result.artifact_refs.length > 0) {
    return formatCountMetric(result.artifact_refs.length, "artifact");
  }

  return null;
}

function toolSummary(call: ToolCall): string | null {
  return compactText(call.result?.error?.message ?? call.result?.summary ?? call.input, 132);
}

function ToolIcon({ name }: { name: string }) {
  return (
    <span className="text-slate-500">
      {TOOL_ICONS[name] ?? <Terminal size={12} />}
    </span>
  );
}

function DetailSection({
  label,
  tone = "default",
  children,
}: {
  label: string;
  tone?: "default" | "warning" | "error";
  children: ReactNode;
}) {
  const toneClass =
    tone === "warning"
      ? "border-amber-200 bg-amber-50/80 text-amber-800"
      : tone === "error"
        ? "border-rose-200 bg-rose-50/85 text-rose-800"
        : "border-[rgba(32,43,35,0.08)] bg-white text-slate-700";

  return (
    <div className={cn("rounded-[14px] border px-3 py-2.5", toneClass)}>
      <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
        {label}
      </p>
      {children}
    </div>
  );
}

interface SingleCallProps {
  call: ToolCall;
}

function SingleCall({ call }: SingleCallProps) {
  const [open, setOpen] = useState(false);
  const structuredPayload = call.result?.structured_payload;
  const artifactRefs = call.result?.artifact_refs ?? [];
  const warnings = call.result?.warnings ?? [];
  const sourcePayload = call.result?.source_payload;
  const complianceReport = getComplianceReport(call.result);
  const auditLogPath = getAuditLogPath(call.result);
  const evidenceReview = getEvidenceReviewPayload(call.result);
  const metric = toolMetric(call);
  const summary = toolSummary(call);

  return (
    <div className="border-b border-[rgba(32,43,35,0.06)] last:border-b-0">
      <button
        onClick={() => setOpen((value) => !value)}
        className={cn(
          "flex w-full items-start gap-3 px-3 py-3 text-left transition-colors sm:px-4",
          open ? "bg-[rgba(246,249,245,0.82)]" : "hover:bg-[rgba(248,250,247,0.9)]"
        )}
      >
        <span className="mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full border border-[rgba(32,43,35,0.08)] bg-white/90">
          <ToolIcon name={call.tool} />
        </span>

        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold text-slate-700 font-mono">
              {call.tool}
            </span>
            <span
              className={cn(
                "rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em]",
                outcomeBadgeClass(call.result)
              )}
            >
              {outcomeBadgeText(call)}
            </span>
            {metric && <span className="text-[11px] text-slate-400">{metric}</span>}
          </span>
          {summary && (
            <span className="mt-1 block text-[11px] leading-5 text-slate-500">
              {summary}
            </span>
          )}
        </span>

        {open ? (
          <ChevronDown size={14} className="mt-1 flex-shrink-0 text-slate-400" />
        ) : (
          <ChevronRight size={14} className="mt-1 flex-shrink-0 text-slate-400" />
        )}
      </button>

      {open && (
        <div className="space-y-2.5 px-3 pb-3 pl-[3.4rem] sm:px-4 sm:pl-[4rem]">
          <DetailSection label="Input">
            <pre className="whitespace-pre-wrap break-all text-xs font-mono">
              {call.input}
            </pre>
          </DetailSection>

          <DetailSection label="Output">
            <pre className="max-h-48 overflow-y-auto whitespace-pre-wrap break-all text-xs font-mono text-slate-600">
              {call.output || "(no output)"}
            </pre>
          </DetailSection>

          {call.result?.error && (
            <DetailSection label="Error" tone="error">
              <pre className="whitespace-pre-wrap break-all text-xs font-mono">
                {call.result.error.code}: {call.result.error.message}
              </pre>
            </DetailSection>
          )}

          {complianceReport && (
            <DetailSection label="Compliance Decision">
              <div className="space-y-1 text-xs">
                <div>
                  <span className="text-slate-400">State:</span>{" "}
                  {humanizeUnderscoreValue(complianceRuntimeState(complianceReport))}
                </div>
                <div>
                  <span className="text-slate-400">Preflight:</span>{" "}
                  {humanizeUnderscoreValue(
                    compliancePreflightDisposition(complianceReport)
                  )}
                </div>
                <div>
                  <span className="text-slate-400">Final:</span>{" "}
                  {humanizeUnderscoreValue(
                    complianceFinalDisposition(complianceReport)
                  )}
                </div>
                <div>
                  <span className="text-slate-400">Rules hit:</span>{" "}
                  {complianceReport.triggered_rules.length}
                </div>
                {complianceReport.approval_scope && (
                  <div>
                    <span className="text-slate-400">Approval scope:</span>{" "}
                    {complianceReport.approval_scope}
                  </div>
                )}
                {complianceReport.approval && (
                  <div>
                    <span className="text-slate-400">Approved by:</span>{" "}
                    {complianceReport.approval.approved_by}
                  </div>
                )}
                {complianceReport.approval?.rationale && (
                  <div>
                    <span className="text-slate-400">Rationale:</span>{" "}
                    {complianceReport.approval.rationale}
                  </div>
                )}
                {auditLogPath && (
                  <div>
                    <span className="text-slate-400">Audit log:</span> {auditLogPath}
                  </div>
                )}
              </div>
            </DetailSection>
          )}

          {evidenceReview && (
            <DetailSection label="Evidence Review">
              <div className="space-y-1 text-xs">
                {typeof evidenceReview.requires_review === "boolean" && (
                  <div>
                    <span className="text-slate-400">Required:</span>{" "}
                    {evidenceReview.requires_review ? "yes" : "no"}
                  </div>
                )}
                {typeof evidenceReview.review_status === "string" && (
                  <div>
                    <span className="text-slate-400">Status:</span>{" "}
                    {humanizeUnderscoreValue(evidenceReview.review_status)}
                  </div>
                )}
                {typeof evidenceReview.confidence === "string" && (
                  <div>
                    <span className="text-slate-400">Confidence:</span>{" "}
                    {evidenceReview.confidence}
                  </div>
                )}
                {typeof evidenceReview.question === "string" && (
                  <div>
                    <span className="text-slate-400">Question:</span>{" "}
                    {evidenceReview.question}
                  </div>
                )}
                {typeof evidenceReview.unsupported_claims_present === "boolean" && (
                  <div>
                    <span className="text-slate-400">Unsupported claims:</span>{" "}
                    {evidenceReview.unsupported_claims_present ? "yes" : "no"}
                  </div>
                )}
                {Array.isArray(evidenceReview.evidence_included) && (
                  <div>
                    <span className="text-slate-400">Included evidence:</span>{" "}
                    {evidenceReview.evidence_included.length}
                  </div>
                )}
                {Array.isArray(evidenceReview.evidence_excluded) && (
                  <div>
                    <span className="text-slate-400">Excluded evidence:</span>{" "}
                    {evidenceReview.evidence_excluded.length}
                  </div>
                )}
                {Array.isArray(evidenceReview.reasons) && evidenceReview.reasons.length > 0 && (
                  <div>
                    <span className="text-slate-400">Reasons:</span>{" "}
                    {evidenceReview.reasons.join(", ")}
                  </div>
                )}
              </div>
            </DetailSection>
          )}

          {warnings.length > 0 && (
            <DetailSection label="Warnings" tone="warning">
              <pre className="whitespace-pre-wrap break-all text-xs font-mono">
                {warnings.join("\n")}
              </pre>
            </DetailSection>
          )}

          {artifactRefs.length > 0 && (
            <DetailSection label="Artifact Refs">
              <pre className="max-h-40 overflow-y-auto whitespace-pre-wrap break-all text-xs font-mono">
                {artifactRefs
                  .map((ref) => ref.path || ref.identifier || ref.label || "(unnamed ref)")
                  .join("\n")}
              </pre>
            </DetailSection>
          )}

          {structuredPayload !== undefined && (
            <DetailSection label="Structured Payload">
              <pre className="max-h-56 overflow-y-auto whitespace-pre-wrap break-all text-xs font-mono">
                {formatJsonValue(structuredPayload)}
              </pre>
            </DetailSection>
          )}

          {sourcePayload !== undefined && (
            <DetailSection label="Source Payload">
              <pre className="max-h-56 overflow-y-auto whitespace-pre-wrap break-all text-xs font-mono">
                {formatJsonValue(sourcePayload)}
              </pre>
            </DetailSection>
          )}
        </div>
      )}
    </div>
  );
}

function PendingToolRow({
  pendingTool,
}: {
  pendingTool: { tool: string; input: string; runId: string };
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="border-b border-[rgba(32,43,35,0.06)] last:border-b-0">
      <button
        onClick={() => setOpen((value) => !value)}
        className={cn(
          "flex w-full items-start gap-3 px-3 py-3 text-left transition-colors sm:px-4",
          open ? "bg-[rgba(241,248,244,0.92)]" : "hover:bg-[rgba(246,250,247,0.92)]"
        )}
      >
        <span className="mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full border border-[rgba(35,130,83,0.16)] bg-[rgba(35,130,83,0.08)]">
          <ToolIcon name={pendingTool.tool} />
        </span>

        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold text-slate-700 font-mono">
              {pendingTool.tool}
            </span>
            <span className="rounded-full border border-[rgba(35,130,83,0.18)] bg-[rgba(35,130,83,0.1)] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--apex-accent-strong)]">
              running
            </span>
            <span className="flex items-center gap-0.5">
              {[0, 1, 2].map((index) => (
                <span
                  key={index}
                  className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--apex-accent)] animate-bounce"
                  style={{ animationDelay: `${index * 150}ms` }}
                />
              ))}
            </span>
          </span>
          {compactText(pendingTool.input, 132) && (
            <span className="mt-1 block text-[11px] leading-5 text-slate-500">
              {compactText(pendingTool.input, 132)}
            </span>
          )}
        </span>

        {open ? (
          <ChevronDown size={14} className="mt-1 flex-shrink-0 text-slate-400" />
        ) : (
          <ChevronRight size={14} className="mt-1 flex-shrink-0 text-slate-400" />
        )}
      </button>

      {open && (
        <div className="space-y-2.5 px-3 pb-3 pl-[3.4rem] sm:px-4 sm:pl-[4rem]">
          <DetailSection label="Input">
            <pre className="whitespace-pre-wrap break-all text-xs font-mono">
              {pendingTool.input}
            </pre>
          </DetailSection>
        </div>
      )}
    </div>
  );
}

interface ThoughtChainProps {
  toolCalls: ToolCall[];
  pendingTool?: { tool: string; input: string; runId: string } | null;
}

export default function ThoughtChain({ toolCalls, pendingTool }: ThoughtChainProps) {
  const [collapsed, setCollapsed] = useState(false);
  const toolCount = toolCalls.length + (pendingTool ? 1 : 0);

  if (toolCount === 0) return null;

  return (
    <section className="overflow-hidden rounded-[18px] border border-[rgba(32,43,35,0.08)] bg-[linear-gradient(180deg,rgba(252,253,251,0.98),rgba(247,249,246,0.98))] shadow-[0_8px_20px_rgba(32,43,35,0.03)]">
      <button
        onClick={() => setCollapsed((value) => !value)}
        className="flex w-full items-center gap-3 border-b border-[rgba(32,43,35,0.06)] bg-[rgba(248,250,247,0.94)] px-3.5 py-3 text-left transition-colors hover:bg-[rgba(244,247,243,0.96)]"
      >
        {collapsed ? (
          <ChevronRight size={14} className="text-slate-400" />
        ) : (
          <ChevronDown size={14} className="text-slate-400" />
        )}

        <span className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full border border-[rgba(32,43,35,0.08)] bg-white/88 text-slate-500">
          <Terminal size={14} />
        </span>

        <span className="min-w-0 flex-1">
          <span className="block text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-600">
            Tool Trace
          </span>
          <span className="block text-[11px] text-slate-400">
            {toolCount} tool{toolCount === 1 ? "" : "s"}
            {pendingTool ? " · 1 running" : ""}
          </span>
        </span>
      </button>

      {!collapsed && (
        <div>
          {toolCalls.map((call, index) => (
            <SingleCall key={call.run_id ?? `${call.tool}-${index}`} call={call} />
          ))}
          {pendingTool && <PendingToolRow pendingTool={pendingTool} />}
        </div>
      )}
    </section>
  );
}
