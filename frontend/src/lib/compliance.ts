import type {
  ComplianceDisposition,
  ComplianceReportArtifact,
  JsonValue,
  Message,
  ToolCall,
  ToolResultEnvelope,
} from "./types";

export type ComplianceSurfaceState =
  | "reviewing"
  | "ready"
  | "warning"
  | "approval_required"
  | "approved"
  | "blocked";

export interface ComplianceSurfaceSummary {
  state: ComplianceSurfaceState;
  label: string;
  detail: string;
  runtimeLabel: string | null;
  preflightLabel: string | null;
  finalDispositionLabel: string | null;
  riskLabel: string | null;
  approvalLabel: string;
  triggeredRuleCount: number;
  actionLabel: string | null;
  actionDetail: string | null;
}

function asRecord(
  value: JsonValue | undefined | null
): Record<string, JsonValue> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }

  return value as Record<string, JsonValue>;
}

function asString(value: JsonValue | undefined): string | null {
  return typeof value === "string" ? value : null;
}

function pluralize(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

export function humanizeComplianceValue(value?: string | null): string | null {
  if (!value) {
    return null;
  }

  return value.replaceAll("_", " ").replaceAll("-", " ");
}

export function labelizeComplianceValue(value?: string | null): string | null {
  const humanized = humanizeComplianceValue(value);
  if (!humanized) {
    return null;
  }

  return humanized.charAt(0).toUpperCase() + humanized.slice(1);
}

export function getComplianceReport(
  result?: ToolResultEnvelope
): ComplianceReportArtifact | null {
  const payload = asRecord(result?.structured_payload);
  if (!payload) {
    return null;
  }

  const report = asRecord(payload.report);
  if (!report || report.artifact_type !== "compliance_report") {
    return null;
  }

  return report as unknown as ComplianceReportArtifact;
}

export function getAuditLogPath(result?: ToolResultEnvelope): string | null {
  const payload = asRecord(result?.structured_payload);
  if (!payload) {
    return null;
  }

  return asString(payload.audit_log_path);
}

export function getLatestComplianceToolCall(toolCalls: ToolCall[]): ToolCall | null {
  for (let index = toolCalls.length - 1; index >= 0; index -= 1) {
    const call = toolCalls[index];
    if (getComplianceReport(call.result)) {
      return call;
    }
  }

  return null;
}

export function getLatestComplianceToolCallFromMessages(
  messages: Message[]
): ToolCall | null {
  for (let messageIndex = messages.length - 1; messageIndex >= 0; messageIndex -= 1) {
    const toolCalls = messages[messageIndex]?.tool_calls ?? [];
    const complianceCall = getLatestComplianceToolCall(toolCalls);
    if (complianceCall) {
      return complianceCall;
    }
  }

  return null;
}

export function getLatestComplianceReportFromMessages(
  messages: Message[]
): ComplianceReportArtifact | null {
  const toolCall = getLatestComplianceToolCallFromMessages(messages);
  return toolCall ? getComplianceReport(toolCall.result) : null;
}

export function getLatestComplianceToolCallForWorkflow(
  messages: Message[],
  workflowId: string | null
): ToolCall | null {
  if (!workflowId) {
    return null;
  }

  for (let messageIndex = messages.length - 1; messageIndex >= 0; messageIndex -= 1) {
    const toolCalls = messages[messageIndex]?.tool_calls ?? [];
    for (let callIndex = toolCalls.length - 1; callIndex >= 0; callIndex -= 1) {
      const call = toolCalls[callIndex];
      const report = getComplianceReport(call.result);
      if (report && reportAppliesToWorkflow(report, workflowId)) {
        return call;
      }
    }
  }

  return null;
}

function normalizeDisposition(
  disposition?: ComplianceDisposition | null
): ComplianceDisposition | null {
  return disposition ?? null;
}

export function getComplianceSurfaceState(
  report: ComplianceReportArtifact
): ComplianceSurfaceState {
  const runtimeState = report.runtime_state;
  const finalDisposition = normalizeDisposition(report.final_disposition);
  const preflightDisposition = normalizeDisposition(report.preflight_disposition);

  if (runtimeState === "blocked" || finalDisposition === "block" || preflightDisposition === "block") {
    return "blocked";
  }

  if (
    runtimeState === "approval_required" ||
    finalDisposition === "require_approval" ||
    preflightDisposition === "require_approval" ||
    report.human_approval_required
  ) {
    return "approval_required";
  }

  if (runtimeState === "approved_override") {
    return "approved";
  }

  if (
    runtimeState === "warning_issued" ||
    finalDisposition === "allow_with_warning" ||
    preflightDisposition === "allow_with_warning"
  ) {
    return "warning";
  }

  if (runtimeState === "preflight_pending") {
    return "reviewing";
  }

  return "ready";
}

function summaryLabel(state: ComplianceSurfaceState): string {
  if (state === "approval_required") {
    return "Approval required";
  }

  if (state === "approved") {
    return "Approved";
  }

  if (state === "blocked") {
    return "Blocked";
  }

  if (state === "warning") {
    return "Warning";
  }

  if (state === "reviewing") {
    return "Reviewing";
  }

  return "Allowed";
}

function summaryDetail(
  report: ComplianceReportArtifact,
  state: ComplianceSurfaceState
): string {
  const ruleCount = report.triggered_rules.length;
  const rulesLabel =
    ruleCount > 0
      ? `${pluralize(ruleCount, "rule")} triggered during compliance review.`
      : null;

  if (state === "blocked") {
    return rulesLabel
      ? `${rulesLabel} BioAPEX did not continue past the compliance gate.`
      : "BioAPEX did not continue past the compliance gate.";
  }

  if (state === "approval_required") {
    return rulesLabel
      ? `${rulesLabel} Operator approval is required before work can continue.`
      : "Operator approval is required before work can continue.";
  }

  if (state === "approved") {
    if (report.approval?.rationale) {
      return report.approval.rationale;
    }

    return "Approval override recorded under audit.";
  }

  if (state === "warning") {
    return rulesLabel
      ? `${rulesLabel} Execution can continue with extra review and caution.`
      : "Execution can continue with extra review and caution.";
  }

  if (state === "reviewing") {
    return "Compliance preflight is still evaluating this request.";
  }

  return rulesLabel
    ? `${rulesLabel} Final disposition still allows execution.`
    : "Compliance checks are clear for this request.";
}

function approvalLabel(
  report: ComplianceReportArtifact,
  state: ComplianceSurfaceState
): string {
  if (state === "approved" && report.approval?.approved_by) {
    return `Approved by ${report.approval.approved_by}`;
  }

  if (report.human_approval_required || state === "approval_required") {
    const scope = labelizeComplianceValue(report.approval_scope);
    return scope ? `Required (${scope})` : "Required";
  }

  return "Not required";
}

function actionLabel(state: ComplianceSurfaceState): string | null {
  if (state === "approval_required") {
    return "Operator action";
  }

  if (state === "blocked") {
    return "Next step";
  }

  return null;
}

function actionDetail(
  report: ComplianceReportArtifact,
  state: ComplianceSurfaceState
): string | null {
  if (state === "approval_required") {
    const scope = labelizeComplianceValue(report.approval_scope) ?? "request";
    return `Approval controls are not wired yet. Review the triggered rules, capture the approver for this ${scope.toLowerCase()}, and resume once approval is recorded.`;
  }

  if (state === "blocked") {
    return "Resolve the blocking rule conditions or narrow the request before retrying.";
  }

  return null;
}

export function summarizeComplianceReport(
  report: ComplianceReportArtifact
): ComplianceSurfaceSummary {
  const state = getComplianceSurfaceState(report);

  return {
    state,
    label: summaryLabel(state),
    detail: summaryDetail(report, state),
    runtimeLabel: labelizeComplianceValue(report.runtime_state),
    preflightLabel: labelizeComplianceValue(report.preflight_disposition),
    finalDispositionLabel: labelizeComplianceValue(report.final_disposition),
    riskLabel: labelizeComplianceValue(report.risk_category),
    approvalLabel: approvalLabel(report, state),
    triggeredRuleCount: report.triggered_rules.length,
    actionLabel: actionLabel(state),
    actionDetail: actionDetail(report, state),
  };
}

export function complianceWarningsState(
  warnings: string[]
): ComplianceSurfaceState | null {
  if (warnings.includes("blocked_by_compliance")) {
    return "blocked";
  }

  if (warnings.includes("approval_required")) {
    return "approval_required";
  }

  if (warnings.includes("approved_override")) {
    return "approved";
  }

  if (warnings.includes("compliance_warning")) {
    return "warning";
  }

  return null;
}

export function reportAppliesToWorkflow(
  report: ComplianceReportArtifact,
  workflowId: string | null
): boolean {
  const selectedWorkflow = report.request_context.selected_workflow;

  if (!workflowId) {
    return true;
  }

  return !selectedWorkflow || selectedWorkflow === workflowId;
}
