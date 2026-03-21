import type {
  ComplianceDisposition,
  ComplianceReportArtifact,
  JsonValue,
  Message,
  ToolCall,
  ToolResultEnvelope,
  WorkflowStreamEvent,
} from "./types";

export interface WorkflowSummary {
  workflowId: string | null;
  workflowName: string | null;
  status: "idle" | "running" | "blocked" | "completed";
  totalSteps: number | null;
  completedSteps: number;
  observedSteps: number;
  currentStep: string | null;
  blockedReason: string | null;
  events: WorkflowStreamEvent[];
}

export type ReadinessState =
  | "ready"
  | "reviewing"
  | "warning"
  | "approval_required"
  | "approved"
  | "blocked";

export interface ReadinessSummary {
  state: ReadinessState;
  label: string;
  detail: string | null;
}

export function getWorkflowSummary(messages: Message[]): WorkflowSummary {
  const events = messages.flatMap((message) => message.workflow_events ?? []);
  const latestRunId = events.at(-1)?.run_id ?? null;
  const runEvents = latestRunId
    ? events.filter((event) => event.run_id === latestRunId)
    : [];
  const startedSteps = new Map<string, string>();
  const finishedSteps = new Map<string, { label: string; status: string }>();

  let workflowId: string | null = null;
  let workflowName: string | null = null;
  let status: WorkflowSummary["status"] = "idle";
  let currentStep: string | null = null;
  let totalSteps: number | null = null;
  let completedSteps = 0;
  let blockedReason: string | null = null;

  for (const event of runEvents) {
    workflowId = event.workflow_id;

    if (event.type === "workflow_start") {
      workflowName = event.workflow_name;
      status = event.lifecycle_status === "blocked" ? "blocked" : "running";
    }

    if (event.type === "workflow_step_start") {
      startedSteps.set(event.step_id, event.step_label);
      currentStep = event.step_label;
      status = "running";
    }

    if (event.type === "workflow_step_end") {
      finishedSteps.set(event.step_id, {
        label: event.step_label,
        status: event.status,
      });

      if (currentStep === event.step_label) {
        currentStep = null;
      }

      if (event.status === "blocked") {
        status = "blocked";
      }
    }

    if (event.type === "workflow_blocked") {
      status = "blocked";
      currentStep = event.step_label ?? currentStep;
      blockedReason = event.reason;
    }

    if (event.type === "workflow_done") {
      status = event.lifecycle_status === "blocked" ? "blocked" : "completed";
      totalSteps = event.total_steps;
      completedSteps = event.completed_steps;
      currentStep = null;
    }
  }

  const observedSteps = Math.max(startedSteps.size, finishedSteps.size);
  const observedCompletedSteps = Array.from(finishedSteps.values()).filter(
    (step) => step.status === "completed"
  ).length;

  return {
    workflowId,
    workflowName,
    status,
    totalSteps,
    completedSteps: totalSteps === null ? observedCompletedSteps : completedSteps,
    observedSteps,
    currentStep,
    blockedReason,
    events: runEvents,
  };
}

export function getLatestSelectedWorkflow(messages: Message[]): string | null {
  const latestRequestMessages = getLatestRequestMessages(messages);
  const selectedWorkflow = findSelectedWorkflowInMessages(latestRequestMessages);

  if (selectedWorkflow) {
    return selectedWorkflow;
  }

  const workflowSummary = getWorkflowSummary(messages);
  if (workflowSummary.status === "running" || workflowSummary.status === "blocked") {
    return workflowSummary.workflowId;
  }

  return null;
}

export function getReadinessSummary(
  messages: Message[],
  options?: {
    workflowSummary?: WorkflowSummary;
    isStreaming?: boolean;
  }
): ReadinessSummary {
  const workflowSummary = options?.workflowSummary ?? getWorkflowSummary(messages);
  const latestRequestMessages = getLatestRequestMessages(messages);

  if (workflowSummary.status === "blocked") {
    return {
      state: "blocked",
      label: "Blocked",
      detail: workflowSummary.blockedReason ?? "Workflow execution is blocked.",
    };
  }

  if (workflowSummary.status === "running") {
    return {
      state: "reviewing",
      label: "Reviewing",
      detail:
        workflowSummary.currentStep ??
        workflowSummary.workflowName ??
        "Evaluating the latest request.",
    };
  }

  const latestRequestSummary = summarizeReadinessFromMessages(latestRequestMessages);
  if (latestRequestSummary) {
    return latestRequestSummary;
  }

  if (options?.isStreaming) {
    return {
      state: "reviewing",
      label: "Reviewing",
      detail:
        workflowSummary.currentStep ??
        workflowSummary.workflowName ??
        "Evaluating the latest request.",
    };
  }

  return {
    state: "ready",
    label: "Ready",
    detail: workflowSummary.workflowName
      ? `${workflowSummary.workflowName} has no active warnings.`
      : "No active readiness warnings in this workspace.",
  };
}

function getLatestRequestMessages(messages: Message[]): Message[] {
  const latestAssistantBlock = getLatestAssistantBlock(messages);

  if (latestAssistantBlock.some((message) => !message.request_id)) {
    return latestAssistantBlock;
  }

  const latestRequestId = findLatestRequestId(messages);

  if (latestRequestId) {
    return messages.filter((message) => message.request_id === latestRequestId);
  }

  return latestAssistantBlock;
}

function findLatestRequestId(messages: Message[]): string | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const requestId = messages[index]?.request_id;
    if (requestId) {
      return requestId;
    }
  }

  return null;
}

function getLatestAssistantBlock(messages: Message[]): Message[] {
  let end = -1;

  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index]?.role === "assistant") {
      end = index;
      break;
    }
  }

  if (end === -1) {
    return [];
  }

  let start = end;
  while (start - 1 >= 0 && messages[start - 1]?.role === "assistant") {
    start -= 1;
  }

  return messages.slice(start, end + 1);
}

function getToolCallsNewestFirst(messages: Message[]): ToolCall[] {
  const calls: ToolCall[] = [];

  for (let messageIndex = messages.length - 1; messageIndex >= 0; messageIndex -= 1) {
    const toolCalls = messages[messageIndex]?.tool_calls ?? [];
    for (let callIndex = toolCalls.length - 1; callIndex >= 0; callIndex -= 1) {
      calls.push(toolCalls[callIndex]);
    }
  }

  return calls;
}

function summarizeReadinessFromMessages(messages: Message[]): ReadinessSummary | null {
  for (const call of getToolCallsNewestFirst(messages)) {
    const summary = summarizeReadinessFromToolCall(call);
    if (summary) {
      return summary;
    }
  }

  return null;
}

function findSelectedWorkflowInMessages(messages: Message[]): string | null {
  for (const call of getToolCallsNewestFirst(messages)) {
    const selectedWorkflow = getSelectedWorkflowFromResult(call.result);
    if (selectedWorkflow) {
      return selectedWorkflow;
    }
  }

  return null;
}

function summarizeReadinessFromToolCall(call: ToolCall): ReadinessSummary | null {
  const result = call.result;
  if (!result) return null;

  const complianceReport = getComplianceReport(result);
  if (complianceReport) {
    return summarizeReadinessFromReport(complianceReport);
  }

  if (result.warnings.includes("blocked_by_compliance")) {
    return {
      state: "blocked",
      label: "Blocked",
      detail: "Compliance blocked the latest action.",
    };
  }

  if (result.warnings.includes("approval_required")) {
    return {
      state: "approval_required",
      label: "Approval",
      detail: "The latest action requires approval before it can proceed.",
    };
  }

  if (result.warnings.includes("compliance_warning")) {
    return {
      state: "warning",
      label: "Warning",
      detail: "The latest action raised a compliance warning.",
    };
  }

  return null;
}

function summarizeReadinessFromReport(
  report: ComplianceReportArtifact
): ReadinessSummary {
  const runtimeState =
    typeof report.runtime_state === "string" ? report.runtime_state : null;
  const finalDisposition = normalizeDisposition(report.final_disposition);
  const preflightDisposition = normalizeDisposition(report.preflight_disposition);
  const triggeredRules = report.triggered_rules.length;
  const rulesLabel =
    triggeredRules === 1 ? "1 rule triggered." : `${triggeredRules} rules triggered.`;

  if (runtimeState === "blocked" || finalDisposition === "block" || preflightDisposition === "block") {
    return {
      state: "blocked",
      label: "Blocked",
      detail: triggeredRules > 0 ? rulesLabel : "Compliance blocked this action.",
    };
  }

  if (
    runtimeState === "approval_required" ||
    finalDisposition === "require_approval" ||
    preflightDisposition === "require_approval" ||
    report.human_approval_required
  ) {
    return {
      state: "approval_required",
      label: "Approval",
      detail: triggeredRules > 0 ? rulesLabel : "Approval is required before proceeding.",
    };
  }

  if (runtimeState === "approved_override") {
    return {
      state: "approved",
      label: "Approved",
      detail: report.approval?.rationale ?? "Approval override recorded.",
    };
  }

  if (
    runtimeState === "warning_issued" ||
    finalDisposition === "allow_with_warning" ||
    preflightDisposition === "allow_with_warning"
  ) {
    return {
      state: "warning",
      label: "Warning",
      detail: triggeredRules > 0 ? rulesLabel : "Compliance warning issued.",
    };
  }

  if (runtimeState === "preflight_pending") {
    return {
      state: "reviewing",
      label: "Reviewing",
      detail: "Compliance preflight is still running.",
    };
  }

  return {
    state: "ready",
    label: "Ready",
    detail: triggeredRules > 0 ? rulesLabel : "Compliance checks are clear.",
  };
}

function normalizeDisposition(
  disposition?: ComplianceDisposition | null
): ComplianceDisposition | null {
  return disposition ?? null;
}

function getComplianceReport(
  result?: ToolResultEnvelope
): ComplianceReportArtifact | null {
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

function getSelectedWorkflowFromResult(
  result?: ToolResultEnvelope
): string | null {
  const complianceReport = getComplianceReport(result);
  const selectedWorkflow = complianceReport?.request_context.selected_workflow;

  return typeof selectedWorkflow === "string" && selectedWorkflow.length > 0
    ? selectedWorkflow
    : null;
}
