"use client";

import { useState, type ReactNode } from "react";
import {
  ChevronDown,
  ChevronRight,
  CircleCheck,
  Code2,
  FileText,
  GitBranch,
  Globe,
  Package,
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
  WorkflowArtifactEvent,
  WorkflowArtifactRef,
  WorkflowIssueDetail,
  WorkflowStreamEvent,
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
  return typeof report?.final_disposition === "string"
    ? report.final_disposition
    : null;
}

function outcomeBadgeClass(result?: ToolResultEnvelope): string {
  if (!result) return "bg-gray-100 text-gray-500";
  const reviewStatus = evidenceReviewStatus(result);
  if (evidenceReviewRequired(result)) return "bg-amber-100 text-amber-700";
  if (evidenceReviewUnsupported(result)) return "bg-red-100 text-red-700";
  if (reviewStatus === "mixed") return "bg-amber-100 text-amber-700";
  if (reviewStatus === "supported") return "bg-emerald-100 text-emerald-700";
  const complianceReport = getComplianceReport(result);
  const runtimeState = complianceRuntimeState(complianceReport);
  if (runtimeState === "approved_override") return "bg-sky-100 text-sky-700";
  if (runtimeState === "approval_required") return "bg-amber-100 text-amber-700";
  if (runtimeState === "blocked") return "bg-red-100 text-red-700";
  if (runtimeState === "warning_issued") return "bg-amber-100 text-amber-700";
  if (result.warnings.includes("approval_required")) return "bg-amber-100 text-amber-700";
  if (result.warnings.includes("blocked_by_compliance")) return "bg-red-100 text-red-700";
  if (result.warnings.includes("compliance_warning")) return "bg-amber-100 text-amber-700";
  if (result.status === "error") return "bg-red-100 text-red-700";
  if (result.outcome === "success_empty") return "bg-amber-100 text-amber-700";
  return "bg-emerald-100 text-emerald-700";
}

function outcomeBadgeText(call: ToolCall): string {
  const result = call.result;
  if (!result) return "";
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

function ToolIcon({ name }: { name: string }) {
  return (
    <span className="text-gray-500">
      {TOOL_ICONS[name] ?? <Terminal size={12} />}
    </span>
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

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 bg-gray-50 hover:bg-gray-100 transition-colors text-left"
      >
        <ToolIcon name={call.tool} />
        <span className="text-xs font-medium text-gray-700 font-mono">
          {call.tool}
        </span>
        <span className="flex-1 text-xs text-gray-400 truncate">{call.input}</span>
        {call.result && (
          <span
            className={cn(
              "rounded-full px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide",
              outcomeBadgeClass(call.result)
            )}
          >
            {outcomeBadgeText(call)}
          </span>
        )}
        {open ? (
          <ChevronDown size={12} className="text-gray-400 flex-shrink-0" />
        ) : (
          <ChevronRight size={12} className="text-gray-400 flex-shrink-0" />
        )}
      </button>

      {open && (
        <div className="divide-y divide-gray-200">
          <div className="px-3 py-2">
            <p className="text-[10px] uppercase tracking-wide text-gray-400 mb-1">
              Input
            </p>
            <pre className="text-xs font-mono text-gray-700 whitespace-pre-wrap break-all bg-gray-50 p-2 rounded">
              {call.input}
            </pre>
          </div>
          <div className="px-3 py-2">
            <p className="text-[10px] uppercase tracking-wide text-gray-400 mb-1">
              Output
            </p>
            <pre className="text-xs font-mono text-gray-600 whitespace-pre-wrap break-all bg-gray-50 p-2 rounded max-h-48 overflow-y-auto">
              {call.output || "(no output)"}
            </pre>
          </div>
          {call.result?.error && (
            <div className="px-3 py-2">
              <p className="text-[10px] uppercase tracking-wide text-gray-400 mb-1">
                Error
              </p>
              <pre className="text-xs font-mono text-red-700 whitespace-pre-wrap break-all bg-red-50 p-2 rounded">
                {call.result.error.code}: {call.result.error.message}
              </pre>
            </div>
          )}
          {complianceReport && (
            <div className="px-3 py-2">
              <p className="text-[10px] uppercase tracking-wide text-gray-400 mb-1">
                Compliance Decision
              </p>
              <div className="bg-slate-50 rounded p-2 text-xs text-gray-700 space-y-1">
                <div>
                  <span className="text-gray-400">State:</span>{" "}
                  {humanizeUnderscoreValue(complianceRuntimeState(complianceReport))}
                </div>
                <div>
                  <span className="text-gray-400">Preflight:</span>{" "}
                  {humanizeUnderscoreValue(
                    compliancePreflightDisposition(complianceReport)
                  )}
                </div>
                <div>
                  <span className="text-gray-400">Final:</span>{" "}
                  {humanizeUnderscoreValue(
                    complianceFinalDisposition(complianceReport)
                  )}
                </div>
                <div>
                  <span className="text-gray-400">Rules hit:</span>{" "}
                  {complianceReport.triggered_rules.length}
                </div>
                {complianceReport.approval_scope && (
                  <div>
                    <span className="text-gray-400">Approval scope:</span>{" "}
                    {complianceReport.approval_scope}
                  </div>
                )}
                {complianceReport.approval && (
                  <div>
                    <span className="text-gray-400">Approved by:</span>{" "}
                    {complianceReport.approval.approved_by}
                  </div>
                )}
                {complianceReport.approval?.rationale && (
                  <div>
                    <span className="text-gray-400">Rationale:</span>{" "}
                    {complianceReport.approval.rationale}
                  </div>
                )}
                {auditLogPath && (
                  <div>
                    <span className="text-gray-400">Audit log:</span>{" "}
                    {auditLogPath}
                  </div>
                )}
              </div>
            </div>
          )}
          {evidenceReview && (
            <div className="px-3 py-2">
              <p className="text-[10px] uppercase tracking-wide text-gray-400 mb-1">
                Evidence Review
              </p>
              <div className="bg-slate-50 rounded p-2 text-xs text-gray-700 space-y-1">
                {typeof evidenceReview.requires_review === "boolean" && (
                  <div>
                    <span className="text-gray-400">Required:</span>{" "}
                    {evidenceReview.requires_review ? "yes" : "no"}
                  </div>
                )}
                {typeof evidenceReview.review_status === "string" && (
                  <div>
                    <span className="text-gray-400">Status:</span>{" "}
                    {humanizeUnderscoreValue(evidenceReview.review_status)}
                  </div>
                )}
                {typeof evidenceReview.confidence === "string" && (
                  <div>
                    <span className="text-gray-400">Confidence:</span>{" "}
                    {evidenceReview.confidence}
                  </div>
                )}
                {typeof evidenceReview.question === "string" && (
                  <div>
                    <span className="text-gray-400">Question:</span>{" "}
                    {evidenceReview.question}
                  </div>
                )}
                {typeof evidenceReview.unsupported_claims_present === "boolean" && (
                  <div>
                    <span className="text-gray-400">Unsupported claims:</span>{" "}
                    {evidenceReview.unsupported_claims_present ? "yes" : "no"}
                  </div>
                )}
                {Array.isArray(evidenceReview.evidence_included) && (
                  <div>
                    <span className="text-gray-400">Included evidence:</span>{" "}
                    {evidenceReview.evidence_included.length}
                  </div>
                )}
                {Array.isArray(evidenceReview.evidence_excluded) && (
                  <div>
                    <span className="text-gray-400">Excluded evidence:</span>{" "}
                    {evidenceReview.evidence_excluded.length}
                  </div>
                )}
                {Array.isArray(evidenceReview.reasons) && evidenceReview.reasons.length > 0 && (
                  <div>
                    <span className="text-gray-400">Reasons:</span>{" "}
                    {evidenceReview.reasons.join(", ")}
                  </div>
                )}
              </div>
            </div>
          )}
          {warnings.length > 0 && (
            <div className="px-3 py-2">
              <p className="text-[10px] uppercase tracking-wide text-gray-400 mb-1">
                Warnings
              </p>
              <pre className="text-xs font-mono text-amber-700 whitespace-pre-wrap break-all bg-amber-50 p-2 rounded">
                {warnings.join("\n")}
              </pre>
            </div>
          )}
          {artifactRefs.length > 0 && (
            <div className="px-3 py-2">
              <p className="text-[10px] uppercase tracking-wide text-gray-400 mb-1">
                Artifact Refs
              </p>
              <pre className="text-xs font-mono text-gray-700 whitespace-pre-wrap break-all bg-gray-50 p-2 rounded max-h-40 overflow-y-auto">
                {artifactRefs
                  .map((ref) => ref.path || ref.identifier || ref.label || "(unnamed ref)")
                  .join("\n")}
              </pre>
            </div>
          )}
          {structuredPayload !== undefined && (
            <div className="px-3 py-2">
              <p className="text-[10px] uppercase tracking-wide text-gray-400 mb-1">
                Structured Payload
              </p>
              <pre className="text-xs font-mono text-gray-700 whitespace-pre-wrap break-all bg-gray-50 p-2 rounded max-h-56 overflow-y-auto">
                {formatJsonValue(structuredPayload)}
              </pre>
            </div>
          )}
          {sourcePayload !== undefined && (
            <div className="px-3 py-2">
              <p className="text-[10px] uppercase tracking-wide text-gray-400 mb-1">
                Source Payload
              </p>
              <pre className="text-xs font-mono text-gray-700 whitespace-pre-wrap break-all bg-gray-50 p-2 rounded max-h-56 overflow-y-auto">
                {formatJsonValue(sourcePayload)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface WorkflowArtifactTrace {
  artifact: WorkflowArtifactRef;
  scope: WorkflowArtifactEvent["scope"];
  stepId?: string | null;
  outputName?: string | null;
}

interface WorkflowStepTrace {
  stepId: string;
  stepLabel: string;
  status: string;
  executorType?: string;
  engineName?: string | null;
  prerequisiteStepIds: string[];
  artifacts: WorkflowArtifactRef[];
  warnings: string[];
  warningDetails: WorkflowIssueDetail[];
  errors: string[];
  errorDetails: WorkflowIssueDetail[];
}

interface WorkflowRunTrace {
  runId: string;
  workflowId: string;
  workflowName: string;
  status: string;
  resumed: boolean;
  runRecordPath?: string;
  blockedReason?: string;
  blockedIssueDetails: WorkflowIssueDetail[];
  blockedStage?: string;
  blockingSource?: string;
  completedSteps?: number;
  totalSteps?: number;
  warningCount?: number;
  steps: WorkflowStepTrace[];
  artifacts: WorkflowArtifactTrace[];
}

function pushUniqueArtifact(
  current: WorkflowArtifactRef[],
  artifact: WorkflowArtifactRef
): WorkflowArtifactRef[] {
  if (
    current.some(
      (existing) =>
        existing.path === artifact.path &&
        existing.artifact_type === artifact.artifact_type
    )
  ) {
    return current;
  }
  return [...current, artifact];
}

function pushUniqueIssueDetail(
  current: WorkflowIssueDetail[],
  detail: WorkflowIssueDetail
): WorkflowIssueDetail[] {
  if (
    current.some(
      (existing) =>
        existing.code === detail.code &&
        existing.message === detail.message &&
        existing.field_path === detail.field_path &&
        existing.path === detail.path
    )
  ) {
    return current;
  }
  return [...current, detail];
}

function pushUniqueIssueDetails(
  current: WorkflowIssueDetail[],
  details: WorkflowIssueDetail[]
): WorkflowIssueDetail[] {
  return details.reduce(pushUniqueIssueDetail, current);
}

function formatWorkflowIssueDetail(detail: WorkflowIssueDetail): string {
  const location = detail.field_path ?? "manifest";
  const pathSuffix = detail.path ? ` (${detail.path})` : "";
  return `${location}${pathSuffix}: ${detail.message}`;
}

function buildWorkflowRuns(events: WorkflowStreamEvent[]): WorkflowRunTrace[] {
  const runs = new Map<string, WorkflowRunTrace>();
  const steps = new Map<string, Map<string, WorkflowStepTrace>>();
  const order: string[] = [];

  function ensureRun(event: WorkflowStreamEvent): WorkflowRunTrace {
    const existing = runs.get(event.run_id);
    if (existing) return existing;
    const created: WorkflowRunTrace = {
      runId: event.run_id,
      workflowId: event.workflow_id,
      workflowName: event.workflow_id,
      status: "created",
      resumed: false,
      blockedIssueDetails: [],
      steps: [],
      artifacts: [],
    };
    runs.set(event.run_id, created);
    steps.set(event.run_id, new Map());
    order.push(event.run_id);
    return created;
  }

  function ensureStep(
    run: WorkflowRunTrace,
    stepId: string,
    stepLabel: string
  ): WorkflowStepTrace {
    const runSteps = steps.get(run.runId) ?? new Map<string, WorkflowStepTrace>();
    steps.set(run.runId, runSteps);
    const existing = runSteps.get(stepId);
    if (existing) {
      existing.stepLabel = stepLabel;
      return existing;
    }
    const created: WorkflowStepTrace = {
      stepId,
      stepLabel,
      status: "created",
      prerequisiteStepIds: [],
      artifacts: [],
      warnings: [],
      warningDetails: [],
      errors: [],
      errorDetails: [],
    };
    runSteps.set(stepId, created);
    run.steps.push(created);
    return created;
  }

  for (const event of events) {
    const run = ensureRun(event);

    switch (event.type) {
      case "workflow_start":
        run.workflowName = event.workflow_name;
        run.status = event.lifecycle_status;
        run.resumed = event.resumed;
        run.runRecordPath = event.run_record_path;
        break;
      case "workflow_step_start": {
        const step = ensureStep(run, event.step_id, event.step_label);
        step.status = event.status;
        step.executorType = event.executor_type;
        step.engineName = event.engine_name ?? null;
        step.prerequisiteStepIds = event.prerequisite_step_ids;
        break;
      }
      case "workflow_artifact": {
        if (
          !run.artifacts.some(
            (existing) =>
              existing.scope === event.scope &&
              existing.stepId === event.step_id &&
              existing.outputName === event.output_name &&
              existing.artifact.path === event.artifact.path
          )
        ) {
          run.artifacts.push({
            artifact: event.artifact,
            scope: event.scope,
            stepId: event.step_id,
            outputName: event.output_name,
          });
        }
        if (event.step_id && event.step_label) {
          const step = ensureStep(run, event.step_id, event.step_label);
          step.artifacts = pushUniqueArtifact(step.artifacts, event.artifact);
        }
        break;
      }
      case "workflow_step_end": {
        const step = ensureStep(run, event.step_id, event.step_label);
        if (step.status !== "blocked") {
          step.status = event.status;
        }
        step.warnings = Array.from(new Set([...step.warnings, ...event.warnings]));
        step.warningDetails = pushUniqueIssueDetails(step.warningDetails, event.warning_details);
        step.errors = Array.from(new Set([...step.errors, ...event.errors]));
        step.errorDetails = pushUniqueIssueDetails(step.errorDetails, event.error_details);
        for (const artifact of event.artifact_refs) {
          step.artifacts = pushUniqueArtifact(step.artifacts, artifact);
        }
        break;
      }
      case "workflow_blocked":
        run.status = event.lifecycle_status;
        run.blockedReason = event.reason;
        run.blockedIssueDetails = pushUniqueIssueDetails(
          run.blockedIssueDetails,
          event.issue_details
        );
        run.blockedStage = event.stage;
        run.blockingSource = event.blocking_source;
        if (event.step_id && event.step_label) {
          const step = ensureStep(run, event.step_id, event.step_label);
          step.status = "blocked";
          step.errorDetails = pushUniqueIssueDetails(step.errorDetails, event.issue_details);
          if (!step.errors.includes(event.reason)) {
            step.errors = [...step.errors, event.reason];
          }
        }
        break;
      case "workflow_done":
        run.status = event.lifecycle_status;
        run.runRecordPath = event.run_record_path;
        run.completedSteps = event.completed_steps;
        run.totalSteps = event.total_steps;
        run.warningCount = event.warning_count;
        break;
    }
  }

  return order.map((runId) => runs.get(runId)).filter(Boolean) as WorkflowRunTrace[];
}

function workflowStatusBadgeClass(status: string): string {
  if (status === "completed") return "bg-emerald-100 text-emerald-700";
  if (status === "blocked" || status === "failed") return "bg-red-100 text-red-700";
  if (status === "running" || status === "preflight_checked") return "bg-sky-100 text-sky-700";
  if (status === "waiting") return "bg-amber-100 text-amber-700";
  return "bg-slate-100 text-slate-600";
}

function WorkflowStatusIcon({ status }: { status: string }) {
  if (status === "completed") {
    return <CircleCheck size={14} className="text-emerald-600" />;
  }
  if (status === "blocked" || status === "failed") {
    return <ShieldAlert size={14} className="text-red-600" />;
  }
  return <GitBranch size={14} className="text-sky-700" />;
}

function formatWorkflowArtifact(artifact: WorkflowArtifactRef): string {
  return `${artifact.artifact_type} - ${artifact.path}`;
}

function WorkflowRunCard({ run }: { run: WorkflowRunTrace }) {
  const runArtifacts = run.artifacts.filter((artifact) => !artifact.stepId);

  return (
    <div className="border border-slate-200 rounded-lg overflow-hidden bg-white">
      <div className="px-3 py-2 bg-slate-50 border-b border-slate-200">
        <div className="flex items-start gap-2">
          <span className="mt-0.5">
            <WorkflowStatusIcon status={run.status} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs font-medium text-slate-700">
                {run.workflowName}
              </span>
              <span
                className={cn(
                  "rounded-full px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide",
                  workflowStatusBadgeClass(run.status)
                )}
              >
                {humanizeUnderscoreValue(run.status)}
              </span>
              {run.resumed && (
                <span className="rounded-full px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide bg-slate-100 text-slate-600">
                  resumed
                </span>
              )}
            </div>
            <div className="mt-1 text-[11px] text-slate-500 font-mono break-all">
              {run.runId}
            </div>
            {run.runRecordPath && (
              <div className="text-[11px] text-slate-500 break-all">
                run record: {run.runRecordPath}
              </div>
            )}
            {typeof run.completedSteps === "number" &&
              typeof run.totalSteps === "number" && (
                <div className="text-[11px] text-slate-500">
                  steps: {run.completedSteps}/{run.totalSteps} completed
                  {typeof run.warningCount === "number"
                    ? ` - ${run.warningCount} warning${run.warningCount === 1 ? "" : "s"}`
                    : ""}
                </div>
              )}
            {run.blockedReason && (
              <div className="mt-1 text-xs text-red-700">
                {run.blockedReason}
                {run.blockedStage
                  ? ` (${humanizeUnderscoreValue(run.blockedStage)} via ${humanizeUnderscoreValue(
                      run.blockingSource
                    )})`
                  : ""}
              </div>
            )}
            {run.blockedIssueDetails.length > 0 && (
              <pre className="mt-2 text-xs font-mono text-red-700 whitespace-pre-wrap break-all bg-red-50 p-2 rounded">
                {run.blockedIssueDetails.map(formatWorkflowIssueDetail).join("\n")}
              </pre>
            )}
          </div>
        </div>
      </div>

      <div className="px-3 py-2 space-y-2">
        {run.steps.map((step) => (
          <div
            key={step.stepId}
            className="rounded-md border border-slate-200 bg-white px-2.5 py-2"
          >
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs font-medium text-slate-700">
                {step.stepLabel}
              </span>
              <span
                className={cn(
                  "rounded-full px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide",
                  workflowStatusBadgeClass(step.status)
                )}
              >
                {humanizeUnderscoreValue(step.status)}
              </span>
              {step.engineName && (
                <span className="rounded-full px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide bg-slate-100 text-slate-600">
                  {step.engineName}
                </span>
              )}
              {!step.engineName && step.executorType && (
                <span className="rounded-full px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide bg-slate-100 text-slate-600">
                  {step.executorType}
                </span>
              )}
              {step.status === "running" && (
                <span className="ml-auto flex gap-0.5">
                  {[0, 1, 2].map((index) => (
                    <span
                      key={index}
                      className="inline-block w-1 h-1 rounded-full bg-[var(--apex-accent)] animate-bounce"
                      style={{ animationDelay: `${index * 150}ms` }}
                    />
                  ))}
                </span>
              )}
            </div>

            {step.prerequisiteStepIds.length > 0 && (
              <div className="mt-1 text-[11px] text-slate-500">
                after: {step.prerequisiteStepIds.join(", ")}
              </div>
            )}

            {step.artifacts.length > 0 && (
              <div className="mt-2 space-y-1">
                {step.artifacts.map((artifact, index) => (
                  <div
                    key={`${artifact.path}-${index}`}
                    className="flex items-start gap-2 rounded bg-slate-50 px-2 py-1.5"
                  >
                    <Package size={12} className="text-slate-500 mt-0.5 flex-shrink-0" />
                    <span className="text-[11px] text-slate-600 break-all">
                      {formatWorkflowArtifact(artifact)}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {step.warnings.length > 0 && (
              <pre className="mt-2 text-xs font-mono text-amber-700 whitespace-pre-wrap break-all bg-amber-50 p-2 rounded">
                {step.warnings.join("\n")}
              </pre>
            )}

            {step.warningDetails.length > 0 && (
              <pre className="mt-2 text-xs font-mono text-amber-700 whitespace-pre-wrap break-all bg-amber-50 p-2 rounded">
                {step.warningDetails.map(formatWorkflowIssueDetail).join("\n")}
              </pre>
            )}

            {step.errors.length > 0 && (
              <pre className="mt-2 text-xs font-mono text-red-700 whitespace-pre-wrap break-all bg-red-50 p-2 rounded">
                {step.errors.join("\n")}
              </pre>
            )}

            {step.errorDetails.length > 0 && (
              <pre className="mt-2 text-xs font-mono text-red-700 whitespace-pre-wrap break-all bg-red-50 p-2 rounded">
                {step.errorDetails.map(formatWorkflowIssueDetail).join("\n")}
              </pre>
            )}
          </div>
        ))}

        {runArtifacts.length > 0 && (
          <div className="rounded-md border border-slate-200 bg-slate-50 px-2.5 py-2">
            <p className="text-[10px] uppercase tracking-wide text-slate-400 mb-2">
              Run Artifacts
            </p>
            <div className="space-y-1">
              {runArtifacts.map((artifact, index) => (
                <div
                  key={`${artifact.artifact.path}-${artifact.scope}-${index}`}
                  className="flex items-start gap-2"
                >
                  <Package size={12} className="text-slate-500 mt-0.5 flex-shrink-0" />
                  <div className="min-w-0">
                    <div className="text-[10px] uppercase tracking-wide text-slate-400">
                      {humanizeUnderscoreValue(artifact.scope)}
                    </div>
                    <div className="text-[11px] text-slate-600 break-all">
                      {formatWorkflowArtifact(artifact.artifact)}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

interface ThoughtChainProps {
  toolCalls: ToolCall[];
  workflowEvents?: WorkflowStreamEvent[];
  pendingTool?: { tool: string; input: string } | null;
}

export default function ThoughtChain({
  toolCalls,
  workflowEvents = [],
  pendingTool,
}: ThoughtChainProps) {
  const [collapsed, setCollapsed] = useState(false);
  const workflowRuns = buildWorkflowRuns(workflowEvents);
  const toolCount = toolCalls.length + (pendingTool ? 1 : 0);

  const hasItems = workflowRuns.length > 0 || toolCalls.length > 0 || !!pendingTool;
  if (!hasItems) return null;

  return (
    <div className="overflow-hidden rounded-[16px] border border-[rgba(32,43,35,0.1)] bg-[linear-gradient(180deg,rgba(252,253,251,0.98),rgba(245,248,244,0.98))] shadow-[0_8px_18px_rgba(32,43,35,0.03)]">
      <button
        onClick={() => setCollapsed((v) => !v)}
        className="w-full flex items-center gap-2 px-3.5 py-2.5 bg-[rgba(247,249,246,0.92)] text-left transition-colors hover:bg-[rgba(240,243,239,0.96)]"
      >
        {collapsed ? (
          <ChevronRight size={13} className="text-gray-400" />
        ) : (
          <ChevronDown size={13} className="text-gray-400" />
        )}
        <div className="min-w-0">
          <span className="block text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-600">
            Execution Trace
          </span>
          <span className="block text-[11px] text-slate-400">
            {workflowRuns.length} workflow{workflowRuns.length === 1 ? "" : "s"} · {toolCount} tool
            {toolCount === 1 ? "" : "s"}
          </span>
        </div>
      </button>

      {!collapsed && (
        <div className="space-y-3 px-3.5 pb-3 pt-1.5">
          {workflowRuns.length > 0 && (
            <div className="space-y-2">
              <p className="text-[10px] uppercase tracking-wide text-gray-400">
                Workflow Runs
              </p>
              {workflowRuns.map((run) => (
                <WorkflowRunCard key={run.runId} run={run} />
              ))}
            </div>
          )}

          {(toolCalls.length > 0 || pendingTool) && (
            <div className="space-y-2">
              <p className="text-[10px] uppercase tracking-wide text-gray-400">
                Tool Calls
              </p>
              {toolCalls.map((call, index) => (
                <SingleCall key={call.run_id ?? `${call.tool}-${index}`} call={call} />
              ))}

              {pendingTool && (
                <div className="flex items-center gap-2 rounded-lg border border-dashed border-[rgba(47,122,95,0.4)] px-3 py-2">
                  <ToolIcon name={pendingTool.tool} />
                  <span className="text-xs font-mono text-[var(--apex-accent)]">
                    {pendingTool.tool}
                  </span>
                  <span className="text-xs text-gray-400 truncate">
                    {pendingTool.input}
                  </span>
                  <span className="ml-auto flex gap-0.5">
                    {[0, 1, 2].map((index) => (
                      <span
                        key={index}
                        className="inline-block w-1 h-1 rounded-full bg-[var(--apex-accent)] animate-bounce"
                        style={{ animationDelay: `${index * 150}ms` }}
                      />
                    ))}
                  </span>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
