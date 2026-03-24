"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Check,
  CircleOff,
  Clock3,
  FileJson,
  Filter,
  Gauge,
  LayoutDashboard,
  MessageSquare,
  Play,
  Plug,
  RefreshCw,
  Route,
  Save,
  ShieldCheck,
  X,
  type LucideIcon,
} from "lucide-react";
import {
  getApiErrorBodyText,
  getConnectorRegistryAdminDetail,
  getConnectorRegistryDetail,
  getObservabilityDashboardDefinitions,
  getObservabilityOverview,
  listAuditEvents,
  listConnectorRegistry,
  listObservabilityMetrics,
  listObservabilityTraces,
  runConnectorRegistryAction,
  updateConnectorRegistryEntry,
  validateConnectorRegistryEntry,
} from "@/lib/api";
import { classifyAccessError } from "@/lib/access-control";
import { useApp } from "@/lib/store";
import type {
  AccessScope,
  AccessScopeState,
  AuditEventRecord,
  AuditEventsQuery,
  AuditEventType,
  ConnectorAction,
  ConnectorActionResult,
  ConnectorExecutionAction,
  ConnectorRegistryEntry,
  JsonObject,
  JsonValue,
  ObservabilityDashboardDefinition,
  ObservabilityMetricRecord,
  ObservabilityMetricsQuery,
  ObservabilityOverview,
  ObservabilityOverviewQuery,
  ObservabilityRateSummary,
  ObservabilityTraceRecord,
  ObservabilityTraceStatus,
  ObservabilityTracesQuery,
  RetentionPolicy,
} from "@/lib/types";
import { cn, formatRelativeTime } from "@/lib/utils";

type OpsView =
  | "overview"
  | "metrics"
  | "traces"
  | "audit"
  | "connectors"
  | "dashboards";
type OpsWorkspaceStatus = "idle" | "loading" | "ready" | "error";

interface ConnectorActionReceipt {
  action: ConnectorAction;
  kind: "success" | "error";
  message: string;
  recordedAt: string;
}

interface OpsWorkspaceFilters {
  days: string;
  limit: string;
  eventType: string;
  requestId: string;
  sessionId: string;
  runId: string;
  stepId: string;
  jobId: string;
  workflowId: string;
  traceId: string;
  toolName: string;
  connectorName: string;
  outcome: string;
}

interface FilterChip {
  key: keyof OpsWorkspaceFilters;
  label: string;
  value: string;
}

const DEFAULT_OPS_FILTERS: OpsWorkspaceFilters = {
  days: "7",
  limit: "100",
  eventType: "",
  requestId: "",
  sessionId: "",
  runId: "",
  stepId: "",
  jobId: "",
  workflowId: "",
  traceId: "",
  toolName: "",
  connectorName: "",
  outcome: "",
};

const FILTER_LABELS: Record<keyof OpsWorkspaceFilters, string> = {
  days: "Window",
  limit: "List Limit",
  eventType: "Event Type",
  requestId: "Request ID",
  sessionId: "Session ID",
  runId: "Run ID",
  stepId: "Step ID",
  jobId: "Job ID",
  workflowId: "Workflow ID",
  traceId: "Trace ID",
  toolName: "Tool",
  connectorName: "Connector",
  outcome: "Outcome",
};

const MAX_OPS_LIST_LIMIT = 500;
const AUDIT_LIMIT_INCREMENT = 100;
const AUDIT_EVENT_TYPE_OPTIONS: AuditEventType[] = [
  "chat_request_received",
  "compliance_decision",
  "workflow_started",
  "workflow_finished",
  "tool_invoked",
  "connector_action",
  "file_written",
  "job_submitted",
  "export_generated",
];
const CONNECTOR_EXECUTION_ACTIONS: ConnectorExecutionAction[] = [
  "import",
  "export",
  "sync_status",
];

const VIEW_CONFIG: Record<
  OpsView,
  {
    label: string;
    description: string;
    icon: LucideIcon;
    supportedFilters: Array<keyof OpsWorkspaceFilters>;
  }
> = {
  overview: {
    label: "Overview",
    description: "Health, latency, workflow delivery, and quality summaries.",
    icon: Gauge,
    supportedFilters: ["days", "requestId", "sessionId", "workflowId"],
  },
  metrics: {
    label: "Metrics",
    description: "Recent metric records grouped by runtime identifiers.",
    icon: Activity,
    supportedFilters: [
      "limit",
      "requestId",
      "sessionId",
      "runId",
      "stepId",
      "jobId",
      "workflowId",
      "traceId",
    ],
  },
  traces: {
    label: "Traces",
    description: "Trace and span activity for workflow and tool debugging.",
    icon: Route,
    supportedFilters: [
      "limit",
      "requestId",
      "sessionId",
      "runId",
      "stepId",
      "jobId",
      "workflowId",
      "traceId",
    ],
  },
  audit: {
    label: "Audit",
    description: "Chronological audit events across runs, tools, connectors, and blocked actions.",
    icon: ShieldCheck,
    supportedFilters: [
      "limit",
      "eventType",
      "sessionId",
      "runId",
      "stepId",
      "jobId",
      "workflowId",
      "toolName",
      "connectorName",
      "outcome",
    ],
  },
  connectors: {
    label: "Connectors",
    description: "Registry inspection and admin-only runtime controls for external integration points.",
    icon: Plug,
    supportedFilters: ["connectorName"],
  },
  dashboards: {
    label: "Dashboards",
    description: "Backend dashboard definitions and static panel filters.",
    icon: LayoutDashboard,
    supportedFilters: [],
  },
};

function compactText(value: string, maxLength = 160): string {
  const trimmed = value.trim();
  if (trimmed.length <= maxLength) {
    return trimmed;
  }
  return `${trimmed.slice(0, maxLength - 1).trimEnd()}…`;
}

function normalizeFilterValue(value: string): string | undefined {
  const trimmed = value.trim();
  return trimmed ? trimmed : undefined;
}

function parsePositiveInteger(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) {
    return undefined;
  }

  const parsed = Number.parseInt(trimmed, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return undefined;
  }

  return parsed;
}

function resolveListLimit(value: string, fallback = 100): number {
  const resolvedLimit = parsePositiveInteger(value) ?? fallback;
  return Math.min(resolvedLimit, MAX_OPS_LIST_LIMIT);
}

function normalizeOpsFilters(filters: OpsWorkspaceFilters): OpsWorkspaceFilters {
  return {
    ...filters,
    limit: String(resolveListLimit(filters.limit)),
  };
}

function humanizeToken(value?: string | null): string | null {
  if (!value) {
    return null;
  }
  return value.replaceAll("_", " ").replaceAll("-", " ");
}

function toTitleCase(value: string): string {
  return value.replace(/\b\w/g, (match) => match.toUpperCase());
}

function formatTokenLabel(value?: string | null): string | null {
  const humanized = humanizeToken(value);
  if (!humanized) {
    return null;
  }
  return toTitleCase(humanized);
}

function normalizeAuditEventType(value: string): AuditEventType | undefined {
  const trimmed = value.trim();
  if (!trimmed) {
    return undefined;
  }
  return AUDIT_EVENT_TYPE_OPTIONS.find((eventType) => eventType === trimmed);
}

function formatNumber(value: number, maximumFractionDigits = 2): string {
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits,
  }).format(value);
}

function formatInteger(value: number): string {
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 0,
  }).format(value);
}

function formatDurationSeconds(value?: number | null): string {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "No data";
  }

  const absoluteValue = Math.abs(value);
  if (absoluteValue < 1) {
    return `${Math.round(value * 1000)} ms`;
  }
  if (absoluteValue < 10) {
    return `${value.toFixed(2)} s`;
  }
  if (absoluteValue < 60) {
    return `${value.toFixed(1)} s`;
  }
  if (absoluteValue < 3600) {
    const minutes = value / 60;
    return `${minutes.toFixed(minutes >= 10 ? 0 : 1)} min`;
  }

  const hours = value / 3600;
  return `${hours.toFixed(hours >= 10 ? 0 : 1)} hr`;
}

function formatRateSummaryValue(summary: ObservabilityRateSummary): string {
  if (summary.average === null || Number.isNaN(summary.average)) {
    return "No data";
  }

  const percent = summary.average <= 1 ? summary.average * 100 : summary.average;
  return `${percent.toFixed(percent >= 10 ? 0 : 1)}%`;
}

function formatMetricValue(record: ObservabilityMetricRecord): string {
  const formattedValue = formatNumber(record.value, 3);
  return record.unit ? `${formattedValue} ${record.unit}` : formattedValue;
}

function formatRelativeIsoTime(value?: string | null): string {
  if (!value) {
    return "Unknown time";
  }

  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp) ? value : formatRelativeTime(timestamp);
}

function formatAbsoluteIsoTime(value?: string | null): string {
  if (!value) {
    return "Unknown time";
  }

  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp) ? value : new Date(timestamp).toLocaleString();
}

function shortenIdentifier(value?: string | null, head = 8, tail = 6): string | null {
  if (!value) {
    return null;
  }
  if (value.length <= head + tail + 1) {
    return value;
  }
  return `${value.slice(0, head)}…${value.slice(-tail)}`;
}

function formatJsonValue(value: JsonValue | undefined): string {
  if (value === undefined) {
    return "{}";
  }

  return JSON.stringify(value, null, 2);
}

function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseJsonObjectEditor(
  value: string,
  label: string
): { value: JsonObject | null; error: string | null } {
  const trimmed = value.trim();
  if (!trimmed) {
    return { value: null, error: null };
  }

  try {
    const parsed: unknown = JSON.parse(trimmed);
    if (!isJsonObject(parsed)) {
      return {
        value: null,
      error: `${label} must be a JSON object.`,
      };
    }
    return {
      value: parsed,
      error: null,
    };
  } catch {
    return {
      value: null,
      error: `${label} must be valid JSON.`,
    };
  }
}

function isConnectorActionResult(value: unknown): value is ConnectorActionResult {
  return (
    isJsonObject(value) &&
    typeof value.connector_name === "string" &&
    typeof value.action === "string" &&
    typeof value.status === "string" &&
    typeof value.outcome === "string" &&
    typeof value.summary === "string" &&
    Array.isArray(value.issues)
  );
}

function parseConnectorActionResultFromError(
  error: unknown
): ConnectorActionResult | null {
  const rawMessage = getApiErrorBodyText(error);
  if (!rawMessage) {
    return null;
  }

  try {
    const parsed: unknown = JSON.parse(rawMessage);
    if (isConnectorActionResult(parsed)) {
      return parsed;
    }
    if (isJsonObject(parsed) && isConnectorActionResult(parsed.detail)) {
      return parsed.detail;
    }
  } catch {
    return null;
  }

  return null;
}

function getScopedAccessErrorMessage(
  scope: AccessScope,
  accessState: AccessScopeState,
  error: unknown,
  fallbackMessage: string
): string {
  const scopedState = classifyAccessError(scope, error, accessState.hasToken);
  if (scopedState.status !== "unavailable") {
    return scopedState.detail;
  }

  const rawMessage =
    error instanceof Error ? error.message.trim() : fallbackMessage;
  const compactMessage = compactText(rawMessage, 160);
  return compactMessage || fallbackMessage;
}

function getConnectorMutationErrorMessage(
  error: unknown,
  adminAccessState: AccessScopeState
): string {
  const rawMessage = getApiErrorBodyText(error) || "Could not complete the connector action.";
  const message = rawMessage.toLowerCase();

  if (
    message.includes("disabled by production hardening policy") ||
    message.includes("policy_disabled")
  ) {
    return "This connector action is blocked by the current production hardening policy.";
  }

  return getScopedAccessErrorMessage(
    "admin",
    adminAccessState,
    error,
    "Could not complete the connector action."
  );
}

function isFilterActive(
  key: keyof OpsWorkspaceFilters,
  value: string
): boolean {
  if (key === "days") {
    return value.trim() !== DEFAULT_OPS_FILTERS.days;
  }
  if (key === "limit") {
    return value.trim() !== DEFAULT_OPS_FILTERS.limit;
  }
  return value.trim().length > 0;
}

function getAppliedFilterChips(filters: OpsWorkspaceFilters): FilterChip[] {
  return (Object.keys(filters) as Array<keyof OpsWorkspaceFilters>)
    .filter((key) => isFilterActive(key, filters[key]))
    .map((key) => ({
      key,
      label: FILTER_LABELS[key],
      value:
        key === "days"
          ? `${filters[key].trim()} days`
          : key === "eventType"
            ? formatTokenLabel(filters[key]) ?? filters[key].trim()
          : key === "limit"
            ? filters[key].trim()
            : filters[key].trim(),
    }));
}

function getIgnoredFilterChips(
  view: OpsView,
  filters: OpsWorkspaceFilters
): FilterChip[] {
  const supported = new Set(VIEW_CONFIG[view].supportedFilters);
  return getAppliedFilterChips(filters).filter((chip) => !supported.has(chip.key));
}

function buildOverviewQuery(filters: OpsWorkspaceFilters): ObservabilityOverviewQuery {
  return {
    days: parsePositiveInteger(filters.days) ?? 7,
    request_id: normalizeFilterValue(filters.requestId),
    session_id: normalizeFilterValue(filters.sessionId),
    workflow_id: normalizeFilterValue(filters.workflowId),
  };
}

function buildMetricsQuery(filters: OpsWorkspaceFilters): ObservabilityMetricsQuery {
  return {
    request_id: normalizeFilterValue(filters.requestId),
    session_id: normalizeFilterValue(filters.sessionId),
    run_id: normalizeFilterValue(filters.runId),
    step_id: normalizeFilterValue(filters.stepId),
    job_id: normalizeFilterValue(filters.jobId),
    workflow_id: normalizeFilterValue(filters.workflowId),
    trace_id: normalizeFilterValue(filters.traceId),
    limit: parsePositiveInteger(filters.limit),
  };
}

function buildTracesQuery(filters: OpsWorkspaceFilters): ObservabilityTracesQuery {
  return {
    request_id: normalizeFilterValue(filters.requestId),
    session_id: normalizeFilterValue(filters.sessionId),
    run_id: normalizeFilterValue(filters.runId),
    step_id: normalizeFilterValue(filters.stepId),
    job_id: normalizeFilterValue(filters.jobId),
    workflow_id: normalizeFilterValue(filters.workflowId),
    trace_id: normalizeFilterValue(filters.traceId),
    limit: parsePositiveInteger(filters.limit),
  };
}

function buildAuditQuery(filters: OpsWorkspaceFilters): AuditEventsQuery {
  return {
    event_type: normalizeAuditEventType(filters.eventType),
    session_id: normalizeFilterValue(filters.sessionId),
    run_id: normalizeFilterValue(filters.runId),
    step_id: normalizeFilterValue(filters.stepId),
    job_id: normalizeFilterValue(filters.jobId),
    workflow_id: normalizeFilterValue(filters.workflowId),
    tool_name: normalizeFilterValue(filters.toolName),
    connector_name: normalizeFilterValue(filters.connectorName),
    outcome: normalizeFilterValue(filters.outcome),
    limit: parsePositiveInteger(filters.limit),
  };
}

function getObservabilityErrorMessage(
  error: unknown,
  target: string,
  inspectionAccessState: AccessScopeState
): string {
  return getScopedAccessErrorMessage(
    "inspection",
    inspectionAccessState,
    error,
    `Could not load ${target} right now.`
  );
}

function summarizeMetricScope(record: ObservabilityMetricRecord): string[] {
  return [
    record.request_id ? `Request ${shortenIdentifier(record.request_id)}` : null,
    record.session_id ? `Session ${shortenIdentifier(record.session_id)}` : null,
    record.run_id ? `Run ${shortenIdentifier(record.run_id)}` : null,
    record.step_id ? `Step ${shortenIdentifier(record.step_id)}` : null,
    record.trace_id ? `Trace ${shortenIdentifier(record.trace_id)}` : null,
  ].filter((value): value is string => Boolean(value));
}

function summarizeTraceScope(record: ObservabilityTraceRecord): string[] {
  return [
    record.request_id ? `Request ${shortenIdentifier(record.request_id)}` : null,
    record.session_id ? `Session ${shortenIdentifier(record.session_id)}` : null,
    record.run_id ? `Run ${shortenIdentifier(record.run_id)}` : null,
    record.step_id ? `Step ${shortenIdentifier(record.step_id)}` : null,
    record.workflow_id ? `Workflow ${humanizeToken(record.workflow_id)}` : null,
  ].filter((value): value is string => Boolean(value));
}

function summarizeAuditScope(record: AuditEventRecord): string[] {
  return [
    record.session_id ? `Session ${shortenIdentifier(record.session_id)}` : null,
    record.run_id ? `Run ${shortenIdentifier(record.run_id)}` : null,
    record.step_id ? `Step ${shortenIdentifier(record.step_id)}` : null,
    record.job_id ? `Job ${shortenIdentifier(record.job_id, 6, 4)}` : null,
    record.workflow_id ? `Workflow ${formatTokenLabel(record.workflow_id)}` : null,
    record.tool_name ? `Tool ${record.tool_name}` : null,
    record.connector_name ? `Connector ${record.connector_name}` : null,
  ].filter((value): value is string => Boolean(value));
}

function formatAuditEventTypeLabel(eventType: AuditEventType): string {
  return formatTokenLabel(eventType) ?? eventType;
}

function formatAuditOutcomeLabel(outcome?: string | null): string {
  return formatTokenLabel(outcome) ?? "No outcome";
}

function auditOutcomeTone(outcome?: string | null): string {
  const normalized = outcome?.trim().toLowerCase();
  if (!normalized) {
    return "border-[rgba(148,163,184,0.24)] bg-[rgba(248,250,252,0.94)] text-slate-600";
  }
  if (
    normalized.includes("success") ||
    normalized === "completed" ||
    normalized === "received" ||
    normalized === "written" ||
    normalized === "submitted" ||
    normalized === "allow"
  ) {
    return "border-[rgba(15,118,110,0.18)] bg-[rgba(240,253,250,0.94)] text-teal-700";
  }
  if (
    normalized.includes("blocked") ||
    normalized.includes("warning") ||
    normalized.includes("approval")
  ) {
    return "border-[rgba(217,119,6,0.22)] bg-[rgba(255,247,237,0.95)] text-amber-700";
  }
  return "border-[rgba(220,38,38,0.18)] bg-[rgba(254,242,242,0.95)] text-rose-700";
}

function traceStatusTone(status: ObservabilityTraceStatus): string {
  if (status === "ok") {
    return "border-[rgba(15,118,110,0.18)] bg-[rgba(240,253,250,0.94)] text-teal-700";
  }
  if (status === "blocked") {
    return "border-[rgba(217,119,6,0.22)] bg-[rgba(255,247,237,0.95)] text-amber-700";
  }
  return "border-[rgba(220,38,38,0.18)] bg-[rgba(254,242,242,0.95)] text-rose-700";
}

function metricKindTone(kind: ObservabilityMetricRecord["metric_kind"]): string {
  if (kind === "duration") {
    return "border-[rgba(2,132,199,0.18)] bg-[rgba(240,249,255,0.95)] text-sky-700";
  }
  if (kind === "rate") {
    return "border-[rgba(124,58,237,0.18)] bg-[rgba(245,243,255,0.95)] text-violet-700";
  }
  if (kind === "gauge") {
    return "border-[rgba(217,119,6,0.18)] bg-[rgba(255,247,237,0.95)] text-amber-700";
  }
  return "border-[rgba(71,85,105,0.18)] bg-[rgba(248,250,252,0.95)] text-slate-700";
}

function connectorResultTone(result: ConnectorActionResult): string {
  if (result.status === "success") {
    return "border-[rgba(15,118,110,0.18)] bg-[rgba(240,253,250,0.94)] text-teal-700";
  }

  if (result.outcome === "blocked" || result.failure_mode === "blocked_action") {
    return "border-[rgba(217,119,6,0.22)] bg-[rgba(255,247,237,0.95)] text-amber-700";
  }

  return "border-[rgba(220,38,38,0.18)] bg-[rgba(254,242,242,0.95)] text-rose-700";
}

function connectorEnabledTone(enabled: boolean): string {
  return enabled
    ? "border-[rgba(15,118,110,0.18)] bg-[rgba(240,253,250,0.94)] text-teal-700"
    : "border-[rgba(148,163,184,0.24)] bg-[rgba(248,250,252,0.94)] text-slate-600";
}

function getConnectorHealthSummary(
  connector: ConnectorRegistryEntry
): { label: string; detail: string; tone: "default" | "warning" | "danger" } {
  const validationResult = connector.validation_result ?? null;
  const hasPersistedValidationFailure =
    validationResult !== null && validationResult.outcome !== "success";

  if (!connector.enabled) {
    return {
      label: "Disabled",
      detail: hasPersistedValidationFailure
        ? `Runtime actions remain blocked until the registry entry is enabled. Persisted validation still reports: ${validationResult?.summary ?? "the stored config is invalid."}`
        : "Runtime actions remain blocked until the registry entry is enabled.",
      tone: "warning",
    };
  }

  if (hasPersistedValidationFailure) {
    return {
      label: "Validation Failed",
      detail: validationResult?.summary ?? "Persisted validation failed.",
      tone:
        validationResult?.outcome === "invalid_input" ? "warning" : "danger",
    };
  }

  if (
    !connector.config_summary.configured ||
    connector.config_summary.missing_required_fields.length > 0
  ) {
    return {
      label: "Needs Config",
      detail:
        connector.config_summary.missing_required_fields.length > 0
          ? `Missing required fields: ${connector.config_summary.missing_required_fields.join(", ")}.`
          : "This connector still needs configuration before runtime actions will succeed.",
      tone: "warning",
    };
  }

  return {
    label: "Ready",
    detail: "Enabled and configured for controlled runtime actions.",
    tone: "default",
  };
}

function createConnectorRequestDraft(): JsonObject {
  return { dry_run: true };
}

function filterConnectorsByName(
  connectors: ConnectorRegistryEntry[],
  query: string
): ConnectorRegistryEntry[] {
  const trimmed = query.trim().toLowerCase();
  if (!trimmed) {
    return connectors;
  }

  return connectors.filter((connector) =>
    [
      connector.name,
      connector.display_name,
      connector.external_system,
      connector.system_kind,
    ].some((value) => value.toLowerCase().includes(trimmed))
  );
}

function formatConnectorFieldLabel(value: string): string {
  return formatTokenLabel(value) ?? value;
}

function retentionLabel(policy?: RetentionPolicy | null): string {
  if (!policy) {
    return "Retention unavailable";
  }

  const base = `${formatInteger(policy.retention_expectation_days)} day retention`;
  return policy.automatic_deletion ? `${base} with rotation` : base;
}

function OpsShell({ children }: { children: ReactNode }) {
  return (
    <section className="apex-panel flex h-full min-h-0 flex-col overflow-hidden rounded-[18px] shadow-[var(--panel-shadow-soft)]">
      <div className="flex min-h-0 flex-1 flex-col bg-[linear-gradient(180deg,rgba(245,248,252,0.98)_0%,rgba(238,243,249,0.95)_100%)]">
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6 sm:py-5 lg:px-8 lg:py-7">
          <div className="mx-auto flex w-full max-w-[76rem] flex-col gap-4 pb-2 sm:gap-5">
            {children}
          </div>
        </div>
      </div>
    </section>
  );
}

function OpsBadge({
  icon: Icon,
  children,
  tone = "default",
}: {
  icon: LucideIcon;
  children: ReactNode;
  tone?: "default" | "warning" | "neutral";
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em]",
        tone === "default" &&
          "border-[rgba(37,99,235,0.18)] bg-[rgba(239,246,255,0.92)] text-blue-700",
        tone === "warning" &&
          "border-[rgba(217,119,6,0.2)] bg-[rgba(255,247,237,0.96)] text-amber-700",
        tone === "neutral" &&
          "border-[rgba(148,163,184,0.24)] bg-[rgba(248,250,252,0.94)] text-slate-600"
      )}
    >
      <Icon size={12} />
      <span>{children}</span>
    </span>
  );
}

function OpsAction({
  children,
  onClick,
  tone = "default",
  disabled = false,
}: {
  children: ReactNode;
  onClick: () => void;
  tone?: "default" | "accent";
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-[11px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60",
        tone === "accent"
          ? "border-[rgba(37,99,235,0.22)] bg-[rgba(239,246,255,0.95)] text-blue-700 hover:bg-[rgba(219,234,254,0.95)]"
          : "border-[var(--shell-border)] bg-white/90 text-slate-600 hover:bg-[rgba(248,250,252,0.96)] hover:text-slate-800"
      )}
    >
      {children}
    </button>
  );
}

function OpsHero({
  badges,
  actions,
}: {
  badges?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="rounded-[24px] border border-[rgba(210,218,230,0.92)] bg-[linear-gradient(135deg,rgba(255,255,255,0.97),rgba(243,247,252,0.95))] p-4 shadow-[0_12px_32px_rgba(19,35,58,0.06)] sm:p-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="max-w-3xl">
          <div className="flex items-center gap-2">
            <div className="flex h-11 w-11 items-center justify-center rounded-[16px] bg-[rgba(219,234,254,0.96)] text-blue-700">
              <Activity size={20} />
            </div>
            <OpsBadge icon={ShieldCheck}>Inspection Workspace</OpsBadge>
          </div>
          <h2 className="mt-3 text-[1.3rem] font-semibold tracking-[-0.02em] text-slate-900">
            Ops
          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">
            Inspect BioAPEX runtime health, workflow delivery, traces, audit events,
            connector registry state, and dashboard definitions without leaving the
            production-operations surface.
          </p>
          {badges ? <div className="mt-3 flex flex-wrap gap-2">{badges}</div> : null}
        </div>

        {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
      </div>
    </div>
  );
}

function OpsSummaryCard({
  label,
  value,
  detail,
  tone = "default",
}: {
  label: string;
  value: string;
  detail: string;
  tone?: "default" | "warning" | "danger";
}) {
  return (
    <div
      className={cn(
        "rounded-[18px] border px-4 py-3 shadow-[0_8px_24px_rgba(19,35,58,0.04)]",
        tone === "default" &&
          "border-[rgba(210,218,230,0.92)] bg-white/94",
        tone === "warning" &&
          "border-[rgba(245,158,11,0.22)] bg-[rgba(255,251,235,0.96)]",
        tone === "danger" &&
          "border-[rgba(248,113,113,0.22)] bg-[rgba(254,242,242,0.96)]"
      )}
    >
      <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
        {label}
      </p>
      <p className="mt-2 text-lg font-semibold tracking-[-0.02em] text-slate-900">
        {value}
      </p>
      <p className="mt-1 text-[12px] leading-5 text-slate-500">{detail}</p>
    </div>
  );
}

function OpsStateCard({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "error" | "warning";
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "rounded-[18px] border px-4 py-6 text-sm leading-6",
        tone === "neutral" &&
          "border-[rgba(210,218,230,0.9)] bg-[rgba(248,250,252,0.95)] text-slate-500",
        tone === "error" &&
          "border-[rgba(248,113,113,0.28)] bg-[rgba(254,242,242,0.96)] text-rose-700",
        tone === "warning" &&
          "border-[rgba(245,158,11,0.22)] bg-[rgba(255,251,235,0.96)] text-amber-700"
      )}
    >
      {children}
    </div>
  );
}

function OpsSectionCard({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <div className="rounded-[22px] border border-[rgba(210,218,230,0.92)] bg-white/94 p-4 shadow-[0_8px_24px_rgba(19,35,58,0.04)] sm:p-5">
      <div className="border-b border-[rgba(210,218,230,0.72)] pb-3">
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
          {title}
        </p>
        <p className="mt-1 text-sm leading-6 text-slate-500">{description}</p>
      </div>
      <div className="mt-4">{children}</div>
    </div>
  );
}

function OpsFilterField({
  label,
  description,
  value,
  placeholder,
  onChange,
}: {
  label: string;
  description: string;
  value: string;
  placeholder: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
        {label}
      </span>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="w-full rounded-[12px] border border-[rgba(203,213,225,0.95)] bg-white px-3 py-2 text-sm text-slate-700 outline-none placeholder:text-slate-400 focus:border-blue-400"
      />
      <span className="text-[11px] leading-5 text-slate-400">{description}</span>
    </label>
  );
}

function OpsFilterSelect({
  label,
  description,
  value,
  options,
  onChange,
}: {
  label: string;
  description: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (value: string) => void;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
        {label}
      </span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-[12px] border border-[rgba(203,213,225,0.95)] bg-white px-3 py-2 text-sm text-slate-700 outline-none focus:border-blue-400"
      >
        {options.map((option) => (
          <option key={option.value || "all"} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <span className="text-[11px] leading-5 text-slate-400">{description}</span>
    </label>
  );
}

function FilterChipRow({
  chips,
  tone = "default",
}: {
  chips: FilterChip[];
  tone?: "default" | "warning";
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {chips.map((chip) => (
        <span
          key={`${chip.key}:${chip.value}`}
          className={cn(
            "inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px]",
            tone === "default" &&
              "border-[rgba(191,219,254,0.92)] bg-[rgba(239,246,255,0.94)] text-blue-700",
            tone === "warning" &&
              "border-[rgba(253,230,138,0.96)] bg-[rgba(255,251,235,0.96)] text-amber-700"
          )}
        >
          <span className="font-semibold">{chip.label}</span>
          <span>{chip.value}</span>
        </span>
      ))}
    </div>
  );
}

function OpsViewTabs({
  activeView,
  onSelect,
}: {
  activeView: OpsView;
  onSelect: (view: OpsView) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {(Object.keys(VIEW_CONFIG) as OpsView[]).map((view) => {
        const config = VIEW_CONFIG[view];
        const Icon = config.icon;
        const active = activeView === view;

        return (
          <button
            key={view}
            type="button"
            onClick={() => onSelect(view)}
            className={cn(
              "inline-flex items-center gap-2 rounded-full border px-3 py-2 text-sm transition-colors",
              active
                ? "border-[rgba(37,99,235,0.24)] bg-[rgba(239,246,255,0.96)] text-blue-700 shadow-[0_8px_18px_rgba(37,99,235,0.08)]"
                : "border-[rgba(203,213,225,0.95)] bg-white/92 text-slate-600 hover:bg-[rgba(248,250,252,0.98)] hover:text-slate-800"
            )}
          >
            <Icon size={15} />
            <span className="font-medium">{config.label}</span>
          </button>
        );
      })}
    </div>
  );
}

function SummaryDetailRow({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-[rgba(226,232,240,0.92)] py-2 text-sm last:border-b-0 last:pb-0 first:pt-0">
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-right font-medium text-slate-900">{value}</dd>
    </div>
  );
}

function IdentifierRow({
  label,
  value,
}: {
  label: string;
  value?: string | null;
}) {
  return (
    <div className="flex flex-col gap-1 rounded-[14px] border border-[rgba(226,232,240,0.95)] bg-[rgba(248,250,252,0.92)] px-3 py-2">
      <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
        {label}
      </span>
      <span className="break-all text-sm text-slate-700">{value ?? "Unavailable"}</span>
    </div>
  );
}

function JsonPreview({
  value,
}: {
  value: JsonValue | undefined;
}) {
  const renderedValue = formatJsonValue(value);
  return (
    <pre className="overflow-x-auto rounded-[16px] border border-[rgba(226,232,240,0.95)] bg-[rgba(248,250,252,0.96)] px-4 py-4 text-[12px] leading-6 text-slate-700">
      {renderedValue}
    </pre>
  );
}

function OverviewMetricsGrid({
  overview,
}: {
  overview: ObservabilityOverview;
}) {
  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <OpsSectionCard
        title="Chat Responsiveness"
        description="User-visible and backend timings derived from recent chat traffic."
      >
        <dl>
          <SummaryDetailRow
            label="User-visible p95"
            value={formatDurationSeconds(
              overview.chat_responsiveness.user_visible_latency_seconds.p95
            )}
          />
          <SummaryDetailRow
            label="User-visible average"
            value={formatDurationSeconds(
              overview.chat_responsiveness.user_visible_latency_seconds.average
            )}
          />
          <SummaryDetailRow
            label="Backend p95"
            value={formatDurationSeconds(
              overview.chat_responsiveness.backend_execution_latency_seconds.p95
            )}
          />
          <SummaryDetailRow
            label="Samples"
            value={formatInteger(
              overview.chat_responsiveness.user_visible_latency_seconds.count
            )}
          />
        </dl>
      </OpsSectionCard>

      <OpsSectionCard
        title="Workflow Delivery"
        description="Execution duration, failure rate, and blocking behavior across recent workflow activity."
      >
        <dl>
          <SummaryDetailRow
            label="Workflow p95"
            value={formatDurationSeconds(
              overview.workflow_delivery.workflow_duration_seconds.p95
            )}
          />
          <SummaryDetailRow
            label="Step p95"
            value={formatDurationSeconds(
              overview.workflow_delivery.step_duration_seconds.p95
            )}
          />
          <SummaryDetailRow
            label="Failure rate"
            value={formatRateSummaryValue(overview.workflow_delivery.failure_rate)}
          />
          <SummaryDetailRow
            label="Block rate"
            value={formatRateSummaryValue(overview.workflow_delivery.block_rate)}
          />
        </dl>
      </OpsSectionCard>

      <OpsSectionCard
        title="Workflow Quality"
        description="Quality gates and evidence coverage aggregated from recent workflow records."
      >
        <dl>
          <SummaryDetailRow
            label="QC pass rate"
            value={formatRateSummaryValue(overview.workflow_quality.qc_pass_rate)}
          />
          <SummaryDetailRow
            label="Evidence coverage"
            value={formatRateSummaryValue(overview.workflow_quality.evidence_coverage_rate)}
          />
          <SummaryDetailRow
            label="Metric records"
            value={formatInteger(overview.record_counts.metric_records)}
          />
          <SummaryDetailRow
            label="Trace records"
            value={formatInteger(overview.record_counts.trace_records)}
          />
        </dl>
      </OpsSectionCard>
    </div>
  );
}

function OverviewView({
  status,
  overview,
  error,
  ignoredFilters,
}: {
  status: OpsWorkspaceStatus;
  overview: ObservabilityOverview | null;
  error: string | null;
  ignoredFilters: FilterChip[];
}) {
  if (status === "loading" && !overview) {
    return <OpsStateCard>Loading observability overview…</OpsStateCard>;
  }

  if (status === "error") {
    return <OpsStateCard tone="error">{error ?? "Could not load the overview."}</OpsStateCard>;
  }

  if (!overview) {
    return <OpsStateCard>No overview records are available yet.</OpsStateCard>;
  }

  return (
    <div className="space-y-4">
      {ignoredFilters.length > 0 ? (
        <OpsStateCard tone="warning">
          Overview ignores some active filters because the backend summary route only
          applies request, session, workflow, and window constraints.
          <div className="mt-3">
            <FilterChipRow chips={ignoredFilters} tone="warning" />
          </div>
        </OpsStateCard>
      ) : null}

      <OverviewMetricsGrid overview={overview} />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
        <OpsSectionCard
          title="Scope"
          description="The summary window and applied backend filters used to generate this snapshot."
        >
          <dl>
            <SummaryDetailRow
              label="Generated"
              value={formatAbsoluteIsoTime(overview.generated_at)}
            />
            <SummaryDetailRow
              label="Window"
              value={`${overview.window_days} day${overview.window_days === 1 ? "" : "s"}`}
            />
            <SummaryDetailRow
              label="Request filter"
              value={overview.filters.request_id ?? "Any request"}
            />
            <SummaryDetailRow
              label="Session filter"
              value={overview.filters.session_id ?? "Any session"}
            />
            <SummaryDetailRow
              label="Workflow filter"
              value={overview.filters.workflow_id ?? "Any workflow"}
            />
          </dl>
        </OpsSectionCard>

        <OpsSectionCard
          title="Dashboard Coverage"
          description="Dashboard definitions bundled into the overview payload for operator reference."
        >
          {overview.dashboards.length === 0 ? (
            <OpsStateCard>No dashboard definitions are bundled into this overview.</OpsStateCard>
          ) : (
            <div className="space-y-3">
              {overview.dashboards.map((dashboard) => (
                <div
                  key={dashboard.id}
                  className="rounded-[18px] border border-[rgba(226,232,240,0.95)] bg-[rgba(248,250,252,0.92)] px-4 py-4"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-sm font-semibold text-slate-900">{dashboard.title}</p>
                    <OpsBadge icon={LayoutDashboard} tone="neutral">
                      {`${dashboard.panels.length} panel${dashboard.panels.length === 1 ? "" : "s"}`}
                    </OpsBadge>
                  </div>
                  <p className="mt-2 text-[12px] leading-5 text-slate-500">
                    {dashboard.description}
                  </p>
                </div>
              ))}
            </div>
          )}
        </OpsSectionCard>
      </div>
    </div>
  );
}

function MetricRecordNavigator({
  status,
  metrics,
  error,
  selectedRecordId,
  onSelect,
}: {
  status: OpsWorkspaceStatus;
  metrics: ObservabilityMetricRecord[];
  error: string | null;
  selectedRecordId: string | null;
  onSelect: (record: ObservabilityMetricRecord) => void;
}) {
  return (
    <OpsSectionCard
      title="Metric Records"
      description="Filter recent metrics by runtime identifiers, then inspect a record in detail."
    >
      <div className="space-y-2">
        {status === "loading" && metrics.length === 0 ? (
          <OpsStateCard>Loading metric records…</OpsStateCard>
        ) : status === "error" ? (
          <OpsStateCard tone="error">
            {error ?? "Could not load metric records right now."}
          </OpsStateCard>
        ) : metrics.length === 0 ? (
          <OpsStateCard>No metric records matched the current filters.</OpsStateCard>
        ) : (
          metrics.map((record) => {
            const active = record.record_id === selectedRecordId;
            const scope = summarizeMetricScope(record);
            return (
              <button
                key={record.record_id}
                type="button"
                onClick={() => onSelect(record)}
                className={cn(
                  "w-full rounded-[18px] border px-4 py-4 text-left transition-colors",
                  active
                    ? "border-[rgba(37,99,235,0.22)] bg-[rgba(239,246,255,0.95)] shadow-[0_10px_24px_rgba(37,99,235,0.08)]"
                    : "border-[rgba(210,218,230,0.88)] bg-[rgba(255,255,255,0.94)] hover:bg-[rgba(248,250,252,0.98)]"
                )}
              >
                <div className="flex items-start gap-3">
                  <div
                    className={cn(
                      "mt-0.5 flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-[12px]",
                      active
                        ? "bg-white text-blue-700"
                        : "bg-[rgba(248,250,252,0.92)] text-slate-500"
                    )}
                  >
                    <Activity size={18} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="truncate text-sm font-semibold text-slate-900">
                        {record.metric_name}
                      </p>
                      <span
                        className={cn(
                          "inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em]",
                          metricKindTone(record.metric_kind)
                        )}
                      >
                        {record.metric_kind}
                      </span>
                    </div>
                    <p className="mt-2 text-base font-semibold text-slate-900">
                      {formatMetricValue(record)}
                    </p>
                    <p className="mt-1 text-[12px] text-slate-500">
                      {formatRelativeIsoTime(record.recorded_at)}
                    </p>
                    {scope.length > 0 ? (
                      <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-slate-500">
                        {scope.map((item) => (
                          <span key={item}>{item}</span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                  <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full border border-[rgba(226,232,240,0.95)] bg-white/92 text-slate-400">
                    <ArrowRight size={14} />
                  </div>
                </div>
              </button>
            );
          })
        )}
      </div>
    </OpsSectionCard>
  );
}

function MetricDetailPane({
  status,
  record,
  error,
}: {
  status: OpsWorkspaceStatus;
  record: ObservabilityMetricRecord | null;
  error: string | null;
}) {
  return (
    <OpsSectionCard
      title="Metric Detail"
      description="Inspect the selected metric payload, identifiers, and raw attributes."
    >
      {status === "error" ? (
        <OpsStateCard tone="error">
          {error ?? "Could not load the selected metric detail."}
        </OpsStateCard>
      ) : !record ? (
        <OpsStateCard>Select a metric record to inspect its runtime context.</OpsStateCard>
      ) : (
        <div className="space-y-4">
          <div className="rounded-[20px] border border-[rgba(210,218,230,0.92)] bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(248,250,252,0.96))] px-4 py-4">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-lg font-semibold tracking-[-0.02em] text-slate-900">
                {record.metric_name}
              </h3>
              <span
                className={cn(
                  "inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em]",
                  metricKindTone(record.metric_kind)
                )}
              >
                {record.metric_kind}
              </span>
            </div>
            <p className="mt-3 text-2xl font-semibold tracking-[-0.03em] text-slate-900">
              {formatMetricValue(record)}
            </p>
            <p className="mt-1 text-sm text-slate-500">
              Recorded {formatAbsoluteIsoTime(record.recorded_at)}
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <IdentifierRow label="Record ID" value={record.record_id} />
            <IdentifierRow label="Request ID" value={record.request_id} />
            <IdentifierRow label="Session ID" value={record.session_id} />
            <IdentifierRow label="Run ID" value={record.run_id} />
            <IdentifierRow label="Step ID" value={record.step_id} />
            <IdentifierRow label="Trace ID" value={record.trace_id} />
            <IdentifierRow label="Span ID" value={record.span_id} />
            <IdentifierRow label="Workflow ID" value={record.workflow_id} />
          </div>

          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
              Attributes
            </p>
            <div className="mt-2">
              <JsonPreview value={record.attributes} />
            </div>
          </div>
        </div>
      )}
    </OpsSectionCard>
  );
}

function TraceRecordNavigator({
  status,
  traces,
  error,
  selectedTraceKey,
  onSelect,
}: {
  status: OpsWorkspaceStatus;
  traces: ObservabilityTraceRecord[];
  error: string | null;
  selectedTraceKey: string | null;
  onSelect: (record: ObservabilityTraceRecord) => void;
}) {
  return (
    <OpsSectionCard
      title="Trace Records"
      description="Track recent spans and status transitions across workflows and tool execution."
    >
      <div className="space-y-2">
        {status === "loading" && traces.length === 0 ? (
          <OpsStateCard>Loading trace records…</OpsStateCard>
        ) : status === "error" ? (
          <OpsStateCard tone="error">
            {error ?? "Could not load trace records right now."}
          </OpsStateCard>
        ) : traces.length === 0 ? (
          <OpsStateCard>No trace records matched the current filters.</OpsStateCard>
        ) : (
          traces.map((record) => {
            const traceKey = `${record.trace_id}:${record.span_id}`;
            const active = traceKey === selectedTraceKey;
            const scope = summarizeTraceScope(record);
            return (
              <button
                key={traceKey}
                type="button"
                onClick={() => onSelect(record)}
                className={cn(
                  "w-full rounded-[18px] border px-4 py-4 text-left transition-colors",
                  active
                    ? "border-[rgba(37,99,235,0.22)] bg-[rgba(239,246,255,0.95)] shadow-[0_10px_24px_rgba(37,99,235,0.08)]"
                    : "border-[rgba(210,218,230,0.88)] bg-[rgba(255,255,255,0.94)] hover:bg-[rgba(248,250,252,0.98)]"
                )}
              >
                <div className="flex items-start gap-3">
                  <div
                    className={cn(
                      "mt-0.5 flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-[12px]",
                      active
                        ? "bg-white text-blue-700"
                        : "bg-[rgba(248,250,252,0.92)] text-slate-500"
                    )}
                  >
                    <Route size={18} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="truncate text-sm font-semibold text-slate-900">
                        {record.span_name}
                      </p>
                      <span
                        className={cn(
                          "inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em]",
                          traceStatusTone(record.status)
                        )}
                      >
                        {record.status}
                      </span>
                    </div>
                    <p className="mt-2 text-base font-semibold text-slate-900">
                      {formatDurationSeconds(record.duration_seconds)}
                    </p>
                    <p className="mt-1 text-[12px] text-slate-500">
                      Started {formatRelativeIsoTime(record.started_at)}
                    </p>
                    {scope.length > 0 ? (
                      <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-slate-500">
                        {scope.map((item) => (
                          <span key={item}>{item}</span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                  <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full border border-[rgba(226,232,240,0.95)] bg-white/92 text-slate-400">
                    <ArrowRight size={14} />
                  </div>
                </div>
              </button>
            );
          })
        )}
      </div>
    </OpsSectionCard>
  );
}

function TraceDetailPane({
  status,
  record,
  error,
}: {
  status: OpsWorkspaceStatus;
  record: ObservabilityTraceRecord | null;
  error: string | null;
}) {
  return (
    <OpsSectionCard
      title="Trace Detail"
      description="Inspect identifiers, timings, parent-child relationships, and trace attributes."
    >
      {status === "error" ? (
        <OpsStateCard tone="error">
          {error ?? "Could not load the selected trace detail."}
        </OpsStateCard>
      ) : !record ? (
        <OpsStateCard>Select a trace record to inspect its span payload.</OpsStateCard>
      ) : (
        <div className="space-y-4">
          <div className="rounded-[20px] border border-[rgba(210,218,230,0.92)] bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(248,250,252,0.96))] px-4 py-4">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-lg font-semibold tracking-[-0.02em] text-slate-900">
                {record.span_name}
              </h3>
              <span
                className={cn(
                  "inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em]",
                  traceStatusTone(record.status)
                )}
              >
                {record.status}
              </span>
            </div>
            <p className="mt-3 text-2xl font-semibold tracking-[-0.03em] text-slate-900">
              {formatDurationSeconds(record.duration_seconds)}
            </p>
            <p className="mt-1 text-sm text-slate-500">
              {formatAbsoluteIsoTime(record.started_at)} to {formatAbsoluteIsoTime(record.ended_at)}
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <IdentifierRow label="Trace ID" value={record.trace_id} />
            <IdentifierRow label="Span ID" value={record.span_id} />
            <IdentifierRow label="Parent Span ID" value={record.parent_span_id} />
            <IdentifierRow label="Request ID" value={record.request_id} />
            <IdentifierRow label="Session ID" value={record.session_id} />
            <IdentifierRow label="Run ID" value={record.run_id} />
            <IdentifierRow label="Step ID" value={record.step_id} />
            <IdentifierRow label="Workflow ID" value={record.workflow_id} />
          </div>

          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
              Attributes
            </p>
            <div className="mt-2">
              <JsonPreview value={record.attributes} />
            </div>
          </div>
        </div>
      )}
    </OpsSectionCard>
  );
}

function AuditEventNavigator({
  status,
  events,
  error,
  retentionPolicy,
  selectedEventId,
  onSelect,
  onLoadMore,
  canLoadMore,
  currentLimit,
}: {
  status: OpsWorkspaceStatus;
  events: AuditEventRecord[];
  error: string | null;
  retentionPolicy: RetentionPolicy | null;
  selectedEventId: string | null;
  onSelect: (record: AuditEventRecord) => void;
  onLoadMore: () => void;
  canLoadMore: boolean;
  currentLimit: number;
}) {
  const nextLimit = Math.min(currentLimit + AUDIT_LIMIT_INCREMENT, MAX_OPS_LIST_LIMIT);

  return (
    <OpsSectionCard
      title="Audit Events"
      description="Review the latest matching audit events, then inspect the selected record in detail."
    >
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-[18px] border border-[rgba(226,232,240,0.95)] bg-[rgba(248,250,252,0.92)] px-4 py-4">
            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
              Retention
            </p>
            <p className="mt-2 text-sm font-semibold text-slate-900">
              {retentionLabel(retentionPolicy)}
            </p>
            <p className="mt-1 text-[12px] leading-5 text-slate-500">
              {retentionPolicy
                ? `${formatTokenLabel(retentionPolicy.rotation_strategy) ?? retentionPolicy.rotation_strategy}. ${
                    retentionPolicy.automatic_deletion
                      ? "Automatic deletion is enabled."
                      : "Automatic deletion is not enabled."
                  }`
                : "Retention metadata becomes available when audit events load."}
            </p>
          </div>
          <div className="rounded-[18px] border border-[rgba(226,232,240,0.95)] bg-[rgba(248,250,252,0.92)] px-4 py-4">
            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
              Query Window
            </p>
            <p className="mt-2 text-sm font-semibold text-slate-900">
              Showing {formatInteger(events.length)} loaded event
              {events.length === 1 ? "" : "s"}
            </p>
            <p className="mt-1 text-[12px] leading-5 text-slate-500">
              Current request cap: {formatInteger(currentLimit)}. Bounded loading keeps
              the audit surface responsive while still allowing deeper review.
            </p>
          </div>
        </div>

        <div className="space-y-2">
          {status === "loading" && events.length === 0 ? (
            <OpsStateCard>Loading audit events…</OpsStateCard>
          ) : status === "error" ? (
            <OpsStateCard tone="error">
              {error ?? "Could not load audit events right now."}
            </OpsStateCard>
          ) : events.length === 0 ? (
            <OpsStateCard>No audit events matched the current filters.</OpsStateCard>
          ) : (
            events.map((record) => {
              const active = record.event_id === selectedEventId;
              const scope = summarizeAuditScope(record);
              return (
                <button
                  key={record.event_id}
                  type="button"
                  onClick={() => onSelect(record)}
                  className={cn(
                    "w-full rounded-[18px] border px-4 py-4 text-left transition-colors",
                    active
                      ? "border-[rgba(37,99,235,0.22)] bg-[rgba(239,246,255,0.95)] shadow-[0_10px_24px_rgba(37,99,235,0.08)]"
                      : "border-[rgba(210,218,230,0.88)] bg-[rgba(255,255,255,0.94)] hover:bg-[rgba(248,250,252,0.98)]"
                  )}
                >
                  <div className="flex items-start gap-3">
                    <div
                      className={cn(
                        "mt-0.5 flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-[12px]",
                        active
                          ? "bg-white text-blue-700"
                          : "bg-[rgba(248,250,252,0.92)] text-slate-500"
                      )}
                    >
                      <ShieldCheck size={18} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="inline-flex items-center rounded-full border border-[rgba(191,219,254,0.92)] bg-[rgba(239,246,255,0.94)] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-blue-700">
                          {formatAuditEventTypeLabel(record.event_type)}
                        </span>
                        {record.outcome ? (
                          <span
                            className={cn(
                              "inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em]",
                              auditOutcomeTone(record.outcome)
                            )}
                          >
                            {formatAuditOutcomeLabel(record.outcome)}
                          </span>
                        ) : null}
                      </div>
                      <p className="mt-2 text-sm font-semibold text-slate-900">
                        {record.summary}
                      </p>
                      <p className="mt-1 text-[12px] text-slate-500">
                        {formatRelativeIsoTime(record.recorded_at)}
                      </p>
                      {scope.length > 0 ? (
                        <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-slate-500">
                          {scope.map((item) => (
                            <span key={item}>{item}</span>
                          ))}
                        </div>
                      ) : null}
                      {record.artifact_paths.length > 0 || record.external_systems.length > 0 ? (
                        <div className="mt-3 flex flex-wrap gap-2">
                          {record.artifact_paths.length > 0 ? (
                            <span className="rounded-full border border-[rgba(226,232,240,0.95)] bg-[rgba(248,250,252,0.96)] px-2.5 py-1 text-[11px] text-slate-500">
                              {`${record.artifact_paths.length} artifact path${record.artifact_paths.length === 1 ? "" : "s"}`}
                            </span>
                          ) : null}
                          {record.external_systems.map((system) => (
                            <span
                              key={`${record.event_id}:${system}`}
                              className="rounded-full border border-[rgba(226,232,240,0.95)] bg-[rgba(248,250,252,0.96)] px-2.5 py-1 text-[11px] text-slate-500"
                            >
                              {system}
                            </span>
                          ))}
                        </div>
                      ) : null}
                    </div>
                    <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full border border-[rgba(226,232,240,0.95)] bg-white/92 text-slate-400">
                      <ArrowRight size={14} />
                    </div>
                  </div>
                </button>
              );
            })
          )}
        </div>

        {status !== "error" ? (
          <div className="flex flex-col gap-3 rounded-[18px] border border-[rgba(226,232,240,0.95)] bg-[rgba(248,250,252,0.9)] px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-[12px] leading-5 text-slate-500">
              {canLoadMore
                ? `Showing the latest ${formatInteger(events.length)} matching events. Load more raises the backend limit to ${formatInteger(nextLimit)}.`
                : currentLimit >= MAX_OPS_LIST_LIMIT
                  ? `The audit query is at the maximum frontend limit of ${formatInteger(MAX_OPS_LIST_LIMIT)} events.`
                  : `Showing ${formatInteger(events.length)} matching event${events.length === 1 ? "" : "s"} within the current backend limit.`}
            </p>
            {canLoadMore ? (
              <OpsAction
                onClick={onLoadMore}
                tone="accent"
                disabled={status === "loading"}
              >
                <RefreshCw size={12} />
                Load More
              </OpsAction>
            ) : null}
          </div>
        ) : null}
      </div>
    </OpsSectionCard>
  );
}

function AuditEventDetailPane({
  status,
  record,
  error,
}: {
  status: OpsWorkspaceStatus;
  record: AuditEventRecord | null;
  error: string | null;
}) {
  return (
    <OpsSectionCard
      title="Audit Detail"
      description="Inspect the selected audit event, linked identifiers, artifact paths, and raw details."
    >
      {status === "error" ? (
        <OpsStateCard tone="error">
          {error ?? "Could not load the selected audit event detail."}
        </OpsStateCard>
      ) : !record ? (
        <OpsStateCard>Select an audit event to inspect its runtime context.</OpsStateCard>
      ) : (
        <div className="space-y-4">
          <div className="rounded-[20px] border border-[rgba(210,218,230,0.92)] bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(248,250,252,0.96))] px-4 py-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center rounded-full border border-[rgba(191,219,254,0.92)] bg-[rgba(239,246,255,0.94)] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-blue-700">
                {formatAuditEventTypeLabel(record.event_type)}
              </span>
              {record.outcome ? (
                <span
                  className={cn(
                    "inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em]",
                    auditOutcomeTone(record.outcome)
                  )}
                >
                  {formatAuditOutcomeLabel(record.outcome)}
                </span>
              ) : null}
              <OpsBadge icon={Clock3} tone="neutral">
                {formatRelativeIsoTime(record.recorded_at)}
              </OpsBadge>
            </div>
            <h3 className="mt-3 text-lg font-semibold tracking-[-0.02em] text-slate-900">
              {record.summary}
            </h3>
            <p className="mt-1 text-sm text-slate-500">
              Recorded {formatAbsoluteIsoTime(record.recorded_at)} by {record.actor}.
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <IdentifierRow label="Event ID" value={record.event_id} />
            <IdentifierRow label="Session ID" value={record.session_id} />
            <IdentifierRow label="Run ID" value={record.run_id} />
            <IdentifierRow label="Step ID" value={record.step_id} />
            <IdentifierRow label="Job ID" value={record.job_id} />
            <IdentifierRow label="Workflow ID" value={record.workflow_id} />
            <IdentifierRow label="Tool Name" value={record.tool_name} />
            <IdentifierRow label="Connector Name" value={record.connector_name} />
            <IdentifierRow label="Redaction Policy" value={record.redaction_policy} />
          </div>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,0.72fr)_minmax(0,1.28fr)]">
            <div className="space-y-4">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                  Artifact Paths
                </p>
                <div className="mt-2">
                  {record.artifact_paths.length === 0 ? (
                    <OpsStateCard>No artifact paths were recorded for this event.</OpsStateCard>
                  ) : (
                    <div className="space-y-2">
                      {record.artifact_paths.map((path) => (
                        <div
                          key={path}
                          className="rounded-[14px] border border-[rgba(226,232,240,0.95)] bg-[rgba(248,250,252,0.92)] px-3 py-2 font-mono text-[12px] leading-5 text-slate-700"
                        >
                          {path}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                  External Systems
                </p>
                <div className="mt-2">
                  {record.external_systems.length === 0 ? (
                    <OpsStateCard>No external systems were recorded for this event.</OpsStateCard>
                  ) : (
                    <div className="flex flex-wrap gap-2">
                      {record.external_systems.map((system) => (
                        <OpsBadge key={system} icon={ArrowRight} tone="neutral">
                          {system}
                        </OpsBadge>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                Raw Details
              </p>
              <div className="mt-2">
                <JsonPreview value={record.details} />
              </div>
            </div>
          </div>
        </div>
      )}
    </OpsSectionCard>
  );
}

function AuditView({
  status,
  events,
  error,
  retentionPolicy,
  ignoredFilters,
  selectedEventId,
  onSelect,
  onLoadMore,
  canLoadMore,
  currentLimit,
}: {
  status: OpsWorkspaceStatus;
  events: AuditEventRecord[];
  error: string | null;
  retentionPolicy: RetentionPolicy | null;
  ignoredFilters: FilterChip[];
  selectedEventId: string | null;
  onSelect: (record: AuditEventRecord) => void;
  onLoadMore: () => void;
  canLoadMore: boolean;
  currentLimit: number;
}) {
  const selectedEvent =
    events.find((record) => record.event_id === selectedEventId) ?? null;
  const blockedEvents = events.filter((record) =>
    record.outcome?.toLowerCase().includes("blocked")
  ).length;
  const toolLinkedEvents = events.filter(
    (record) => record.event_type === "tool_invoked" || Boolean(record.tool_name)
  ).length;
  const connectorLinkedEvents = events.filter(
    (record) =>
      record.event_type === "connector_action" || Boolean(record.connector_name)
  ).length;
  const workflowLinkedEvents = events.filter(
    (record) => Boolean(record.run_id || record.workflow_id)
  ).length;

  return (
    <div className="space-y-4">
      {ignoredFilters.length > 0 ? (
        <OpsStateCard tone="warning">
          Audit events ignore some active filters because the backend audit route only
          accepts event type, session, run, step, job, workflow, tool, connector,
          outcome, and list-limit constraints.
          <div className="mt-3">
            <FilterChipRow chips={ignoredFilters} tone="warning" />
          </div>
        </OpsStateCard>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <OpsSummaryCard
          label="Loaded Events"
          value={
            status === "loading" && events.length === 0
              ? "Loading"
              : formatInteger(events.length)
          }
          detail="Matching audit events currently loaded into the review surface."
        />
        <OpsSummaryCard
          label="Blocked Outcomes"
          value={formatInteger(blockedEvents)}
          detail="Events whose recorded outcome indicates a blocked action or state."
          tone={blockedEvents > 0 ? "warning" : "default"}
        />
        <OpsSummaryCard
          label="Tool-Linked"
          value={formatInteger(toolLinkedEvents)}
          detail="Events tied directly to tool execution or tool-specific audit context."
        />
        <OpsSummaryCard
          label="Workflow-Linked"
          value={formatInteger(workflowLinkedEvents)}
          detail={`Connector-linked events in view: ${formatInteger(connectorLinkedEvents)}.`}
        />
      </div>

      <div className="grid min-h-0 gap-4 xl:grid-cols-[minmax(0,0.88fr)_minmax(0,1.12fr)]">
        <AuditEventNavigator
          status={status}
          events={events}
          error={error}
          retentionPolicy={retentionPolicy}
          selectedEventId={selectedEventId}
          onSelect={onSelect}
          onLoadMore={onLoadMore}
          canLoadMore={canLoadMore}
          currentLimit={currentLimit}
        />
        <AuditEventDetailPane
          status={status}
          record={selectedEvent}
          error={error}
        />
      </div>
    </div>
  );
}

function ConnectorRegistryNavigator({
  status,
  connectors,
  error,
  selectedConnectorName,
  onSelect,
}: {
  status: OpsWorkspaceStatus;
  connectors: ConnectorRegistryEntry[];
  error: string | null;
  selectedConnectorName: string | null;
  onSelect: (connector: ConnectorRegistryEntry) => void;
}) {
  return (
    <OpsSectionCard
      title="Connector Registry"
      description="Inspect registered integration points, then open a connector to manage configuration and runtime actions."
    >
      <div className="space-y-2">
        {status === "loading" && connectors.length === 0 ? (
          <OpsStateCard>Loading connector registry entries…</OpsStateCard>
        ) : status === "error" ? (
          <OpsStateCard tone="error">
            {error ?? "Could not load the connector registry right now."}
          </OpsStateCard>
        ) : connectors.length === 0 ? (
          <OpsStateCard>No connectors matched the current filters.</OpsStateCard>
        ) : (
          connectors.map((connector) => {
            const active = connector.name === selectedConnectorName;
            const health = getConnectorHealthSummary(connector);
            return (
              <button
                key={connector.name}
                type="button"
                onClick={() => onSelect(connector)}
                className={cn(
                  "w-full rounded-[18px] border px-4 py-4 text-left transition-colors",
                  active
                    ? "border-[rgba(37,99,235,0.22)] bg-[rgba(239,246,255,0.95)] shadow-[0_10px_24px_rgba(37,99,235,0.08)]"
                    : "border-[rgba(210,218,230,0.88)] bg-[rgba(255,255,255,0.94)] hover:bg-[rgba(248,250,252,0.98)]"
                )}
              >
                <div className="flex items-start gap-3">
                  <div
                    className={cn(
                      "mt-0.5 flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-[12px]",
                      active
                        ? "bg-white text-blue-700"
                        : "bg-[rgba(248,250,252,0.92)] text-slate-500"
                    )}
                  >
                    <Plug size={18} />
                  </div>

                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="truncate text-sm font-semibold text-slate-900">
                        {connector.display_name}
                      </p>
                      <span
                        className={cn(
                          "inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em]",
                          connectorEnabledTone(connector.enabled)
                        )}
                      >
                        {connector.enabled ? "Enabled" : "Disabled"}
                      </span>
                      <span
                        className={cn(
                          "inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em]",
                          health.tone === "default" &&
                            "border-[rgba(15,118,110,0.18)] bg-[rgba(240,253,250,0.94)] text-teal-700",
                          health.tone === "warning" &&
                            "border-[rgba(217,119,6,0.22)] bg-[rgba(255,247,237,0.95)] text-amber-700",
                          health.tone === "danger" &&
                            "border-[rgba(220,38,38,0.18)] bg-[rgba(254,242,242,0.95)] text-rose-700"
                        )}
                      >
                        {health.label}
                      </span>
                    </div>

                    <p className="mt-1 text-[12px] text-slate-500">
                      {connector.name} · {formatConnectorFieldLabel(connector.system_kind)} ·{" "}
                      {connector.external_system}
                    </p>
                    <p className="mt-2 text-[12px] leading-5 text-slate-500">
                      {compactText(connector.description, 180)}
                    </p>
                    <p className="mt-2 text-[11px] leading-5 text-slate-500">
                      {health.detail}
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <span className="rounded-full border border-[rgba(226,232,240,0.95)] bg-[rgba(248,250,252,0.96)] px-2.5 py-1 text-[11px] text-slate-500">
                        {connector.capabilities.supported_actions.length} supported action
                        {connector.capabilities.supported_actions.length === 1 ? "" : "s"}
                      </span>
                      <span className="rounded-full border border-[rgba(226,232,240,0.95)] bg-[rgba(248,250,252,0.96)] px-2.5 py-1 text-[11px] text-slate-500">
                        {connector.config_summary.configured_fields.length} configured field
                        {connector.config_summary.configured_fields.length === 1 ? "" : "s"}
                      </span>
                    </div>
                  </div>

                  <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full border border-[rgba(226,232,240,0.95)] bg-white/92 text-slate-400">
                    <ArrowRight size={14} />
                  </div>
                </div>
              </button>
            );
          })
        )}
      </div>
    </OpsSectionCard>
  );
}

function ConnectorDetailPane({
  status,
  connector,
  error,
  adminConfigStatus,
  adminConfigError,
  adminAccessAllowed,
  adminAccessMessage,
  configLoaded,
  configDraft,
  requestDraft,
  pendingActionKey,
  currentValidationResult,
  latestResult,
  latestReceipt,
  onConfigDraftChange,
  onRequestDraftChange,
  onResetConfigDraft,
  onResetRequestDraft,
  onToggleEnabled,
  onSaveConfig,
  onValidateDraft,
  onRunAction,
}: {
  status: OpsWorkspaceStatus;
  connector: ConnectorRegistryEntry | null;
  error: string | null;
  adminConfigStatus: OpsWorkspaceStatus;
  adminConfigError: string | null;
  adminAccessAllowed: boolean;
  adminAccessMessage: string;
  configLoaded: boolean;
  configDraft: string;
  requestDraft: string;
  pendingActionKey: string | null;
  currentValidationResult: ConnectorActionResult | null;
  latestResult: ConnectorActionResult | null;
  latestReceipt: ConnectorActionReceipt | null;
  onConfigDraftChange: (value: string) => void;
  onRequestDraftChange: (value: string) => void;
  onResetConfigDraft: () => void;
  onResetRequestDraft: () => void;
  onToggleEnabled: () => void;
  onSaveConfig: () => void;
  onValidateDraft: () => void;
  onRunAction: (action: ConnectorExecutionAction) => void;
}) {
  if (status === "loading" && !connector) {
    return (
      <OpsSectionCard
        title="Connector Detail"
        description="Load a connector from the registry to inspect its admin surface."
      >
        <OpsStateCard>Loading connector detail…</OpsStateCard>
      </OpsSectionCard>
    );
  }

  if (status === "error") {
    return (
      <OpsSectionCard
        title="Connector Detail"
        description="Load a connector from the registry to inspect its admin surface."
      >
        <OpsStateCard tone="error">
          {error ?? "Could not load the selected connector detail."}
        </OpsStateCard>
      </OpsSectionCard>
    );
  }

  if (!connector) {
    return (
      <OpsSectionCard
        title="Connector Detail"
        description="Load a connector from the registry to inspect its admin surface."
      >
        <OpsStateCard>Select a connector to inspect its configuration summary and action controls.</OpsStateCard>
      </OpsSectionCard>
    );
  }

  const health = getConnectorHealthSummary(connector);
  const supportedRuntimeActions = CONNECTOR_EXECUTION_ACTIONS.filter((action) =>
    connector.capabilities.supported_actions.includes(action)
  );

  return (
    <OpsSectionCard
      title="Connector Detail"
      description="Inspect configuration readiness, admin-only controls, validation results, and runtime action receipts."
    >
      <div className="space-y-4">
        <div className="rounded-[20px] border border-[rgba(210,218,230,0.92)] bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(248,250,252,0.96))] px-4 py-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-lg font-semibold tracking-[-0.02em] text-slate-900">
                  {connector.display_name}
                </h3>
                <span
                  className={cn(
                    "inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em]",
                    connectorEnabledTone(connector.enabled)
                  )}
                >
                  {connector.enabled ? "Enabled" : "Disabled"}
                </span>
                <span
                  className={cn(
                    "inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em]",
                    health.tone === "default" &&
                      "border-[rgba(15,118,110,0.18)] bg-[rgba(240,253,250,0.94)] text-teal-700",
                    health.tone === "warning" &&
                      "border-[rgba(217,119,6,0.22)] bg-[rgba(255,247,237,0.95)] text-amber-700",
                    health.tone === "danger" &&
                      "border-[rgba(220,38,38,0.18)] bg-[rgba(254,242,242,0.95)] text-rose-700"
                  )}
                >
                  {health.label}
                </span>
                <OpsBadge icon={ShieldCheck} tone="warning">
                  Admin only
                </OpsBadge>
              </div>
              <p className="mt-1 text-sm text-slate-500">
                {connector.name} · {formatConnectorFieldLabel(connector.system_kind)} ·{" "}
                {connector.external_system}
              </p>
              <p className="mt-2 text-sm leading-6 text-slate-500">
                {connector.description}
              </p>
              <p className="mt-2 text-[12px] leading-5 text-slate-500">
                {health.detail}
              </p>
            </div>

            <OpsAction
              onClick={onToggleEnabled}
              tone="accent"
              disabled={pendingActionKey !== null || !adminAccessAllowed}
            >
              {pendingActionKey === `${connector.name}:toggle` ? (
                <Clock3 size={12} />
              ) : connector.enabled ? (
                <CircleOff size={12} />
              ) : (
                <Check size={12} />
              )}
              {pendingActionKey === `${connector.name}:toggle`
                ? "Updating…"
                : connector.enabled
                  ? "Disable Connector"
                  : "Enable Connector"}
            </OpsAction>
          </div>
        </div>

        {!adminAccessAllowed ? (
          <OpsStateCard tone="warning">{adminAccessMessage}</OpsStateCard>
        ) : null}

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <OpsSummaryCard
            label="Configured Fields"
            value={formatInteger(connector.config_summary.configured_fields.length)}
            detail="Fields currently represented in the stored connector config."
          />
          <OpsSummaryCard
            label="Missing Required"
            value={formatInteger(connector.config_summary.missing_required_fields.length)}
            detail="Required config keys still absent from the current registry state."
            tone={
              connector.config_summary.missing_required_fields.length > 0
                ? "warning"
                : "default"
            }
          />
          <OpsSummaryCard
            label="Runtime Actions"
            value={formatInteger(supportedRuntimeActions.length)}
            detail="Supported import, export, and status-sync actions."
          />
          <OpsSummaryCard
            label="Secret References"
            value={connector.config_summary.uses_secret_references ? "Yes" : "No"}
            detail="The registry summary indicates whether secret-backed config references are in use."
          />
        </div>

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <div className="space-y-4">
            <div className="rounded-[18px] border border-[rgba(226,232,240,0.95)] bg-[rgba(248,250,252,0.92)] px-4 py-4">
              <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                Config Summary
              </p>
              <div className="mt-3 space-y-3">
                <div>
                  <p className="text-[11px] font-semibold text-slate-700">
                    Configured fields
                  </p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {connector.config_summary.configured_fields.length === 0 ? (
                      <span className="text-[12px] text-slate-500">
                        No configured fields are exposed in the current summary.
                      </span>
                    ) : (
                      connector.config_summary.configured_fields.map((field) => (
                        <span
                          key={`${connector.name}:configured:${field}`}
                          className="rounded-full border border-[rgba(191,219,254,0.92)] bg-[rgba(239,246,255,0.94)] px-2.5 py-1 text-[11px] text-blue-700"
                        >
                          {field}
                        </span>
                      ))
                    )}
                  </div>
                </div>

                <div>
                  <p className="text-[11px] font-semibold text-slate-700">
                    Missing required fields
                  </p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {connector.config_summary.missing_required_fields.length === 0 ? (
                      <span className="text-[12px] text-slate-500">
                        No missing required fields are reported.
                      </span>
                    ) : (
                      connector.config_summary.missing_required_fields.map((field) => (
                        <span
                          key={`${connector.name}:missing:${field}`}
                          className="rounded-full border border-[rgba(253,230,138,0.96)] bg-[rgba(255,251,235,0.96)] px-2.5 py-1 text-[11px] text-amber-700"
                        >
                          {field}
                        </span>
                      ))
                    )}
                  </div>
                </div>

                {connector.notes.length > 0 ? (
                  <div>
                    <p className="text-[11px] font-semibold text-slate-700">Notes</p>
                    <div className="mt-2 space-y-2">
                      {connector.notes.map((note) => (
                        <div
                          key={`${connector.name}:note:${note}`}
                          className="rounded-[14px] border border-[rgba(226,232,240,0.95)] bg-white/92 px-3 py-2 text-[12px] leading-5 text-slate-600"
                        >
                          {note}
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            </div>

            <div className="rounded-[18px] border border-[rgba(226,232,240,0.95)] bg-white/94 px-4 py-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                    Config Draft Editor
                  </p>
                  <p className="mt-1 text-[12px] leading-5 text-slate-500">
                    Edit a JSON object for the next registry update. Stored secret values are
                    intentionally not returned by the detail API, so this editor is an explicit
                    operator draft rather than a live config mirror.
                  </p>
                </div>
                <OpsBadge icon={FileJson} tone="neutral">
                  JSON object
                </OpsBadge>
              </div>

              <div className="mt-3">
                <textarea
                  value={configDraft}
                  onChange={(event) => onConfigDraftChange(event.target.value)}
                  disabled={!configLoaded || !adminAccessAllowed}
                  spellCheck={false}
                  className="min-h-[15rem] w-full rounded-[16px] border border-[rgba(203,213,225,0.95)] bg-[rgba(248,250,252,0.96)] px-4 py-3 font-mono text-[12px] leading-6 text-slate-700 outline-none focus:border-blue-400 disabled:cursor-not-allowed disabled:opacity-60"
                />
              </div>

              {adminConfigStatus === "loading" && !configLoaded ? (
                <div className="mt-3">
                  <OpsStateCard>Loading the persisted connector config for safe editing…</OpsStateCard>
                </div>
              ) : adminConfigStatus === "error" && !configLoaded ? (
                <div className="mt-3">
                  <OpsStateCard tone="warning">
                    {adminConfigError ??
                      "Current connector config could not be loaded for editing."}
                  </OpsStateCard>
                </div>
              ) : null}

              <div className="mt-3 flex flex-wrap gap-2">
                <OpsAction
                  onClick={onSaveConfig}
                  tone="accent"
                  disabled={
                    pendingActionKey !== null || !configLoaded || !adminAccessAllowed
                  }
                >
                  {pendingActionKey === `${connector.name}:configure` ? (
                    <Clock3 size={12} />
                  ) : (
                    <Save size={12} />
                  )}
                  {pendingActionKey === `${connector.name}:configure`
                    ? "Saving…"
                    : "Save Config Draft"}
                </OpsAction>
                <OpsAction
                  onClick={onValidateDraft}
                  disabled={
                    pendingActionKey !== null || !configLoaded || !adminAccessAllowed
                  }
                >
                  {pendingActionKey === `${connector.name}:validate` ? (
                    <Clock3 size={12} />
                  ) : (
                    <ShieldCheck size={12} />
                  )}
                  {pendingActionKey === `${connector.name}:validate`
                    ? "Validating…"
                    : "Validate Draft"}
                </OpsAction>
                <OpsAction
                  onClick={onResetConfigDraft}
                  disabled={
                    pendingActionKey !== null || !configLoaded || !adminAccessAllowed
                  }
                >
                  <RefreshCw size={12} />
                  Reset Draft
                </OpsAction>
              </div>
            </div>

            <div className="rounded-[18px] border border-[rgba(226,232,240,0.95)] bg-white/94 px-4 py-4">
              <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                Config Fields
              </p>
              <div className="mt-3 space-y-2">
                {connector.config_fields.length === 0 ? (
                  <OpsStateCard>No typed config fields are declared for this connector.</OpsStateCard>
                ) : (
                  connector.config_fields.map((field) => (
                    <div
                      key={`${connector.name}:field:${field.key}`}
                      className="rounded-[16px] border border-[rgba(226,232,240,0.95)] bg-[rgba(248,250,252,0.92)] px-3 py-3"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-sm font-semibold text-slate-900">{field.key}</p>
                        <span className="rounded-full border border-[rgba(226,232,240,0.95)] bg-white/92 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                          {formatConnectorFieldLabel(field.kind)}
                        </span>
                        <span
                          className={cn(
                            "rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em]",
                            field.required
                              ? "border-[rgba(191,219,254,0.92)] bg-[rgba(239,246,255,0.94)] text-blue-700"
                              : "border-[rgba(226,232,240,0.95)] bg-white/92 text-slate-500"
                          )}
                        >
                          {field.required ? "Required" : "Optional"}
                        </span>
                        {field.secret_reference ? (
                          <span className="rounded-full border border-[rgba(253,230,138,0.96)] bg-[rgba(255,251,235,0.96)] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-amber-700">
                            Secret reference
                          </span>
                        ) : null}
                      </div>
                      <p className="mt-2 text-[12px] leading-5 text-slate-500">
                        {field.description}
                      </p>
                      {field.allowed_values.length > 0 ? (
                        <div className="mt-2 flex flex-wrap gap-2">
                          {field.allowed_values.map((value) => (
                            <span
                              key={`${connector.name}:field:${field.key}:${value}`}
                              className="rounded-full border border-[rgba(226,232,240,0.95)] bg-white/92 px-2.5 py-1 text-[11px] text-slate-500"
                            >
                              {value}
                            </span>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>

          <div className="space-y-4">
            <div className="rounded-[18px] border border-[rgba(226,232,240,0.95)] bg-[rgba(248,250,252,0.92)] px-4 py-4">
              <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                Validation State
              </p>
              {adminConfigStatus === "loading" && !currentValidationResult ? (
                <div className="mt-3">
                  <OpsStateCard>Loading the current persisted validation state…</OpsStateCard>
                </div>
              ) : adminConfigStatus === "error" && !currentValidationResult ? (
                <div className="mt-3">
                  <OpsStateCard tone="warning">
                    {adminConfigError ??
                      "Current validation state could not be loaded."}
                  </OpsStateCard>
                </div>
              ) : currentValidationResult ? (
                <div className="mt-3 space-y-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={cn(
                        "inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em]",
                        connectorResultTone(currentValidationResult)
                      )}
                    >
                      {formatTokenLabel(currentValidationResult.outcome) ??
                        currentValidationResult.outcome}
                    </span>
                    <OpsBadge icon={ShieldCheck} tone="neutral">
                      {formatTokenLabel(currentValidationResult.action) ??
                        currentValidationResult.action}
                    </OpsBadge>
                    {latestReceipt &&
                    latestReceipt.action === currentValidationResult.action ? (
                      <OpsBadge icon={Clock3} tone="neutral">
                        {formatRelativeIsoTime(latestReceipt.recordedAt)}
                      </OpsBadge>
                    ) : null}
                  </div>
                  <p className="text-sm font-semibold text-slate-900">
                    {currentValidationResult.summary}
                  </p>
                  {currentValidationResult.issues.length > 0 ? (
                    <div className="space-y-2">
                      {currentValidationResult.issues.map((issue, index) => (
                        <div
                          key={`${connector.name}:validation:${issue.code}:${index}`}
                          className="rounded-[14px] border border-[rgba(253,230,138,0.96)] bg-[rgba(255,251,235,0.96)] px-3 py-2 text-[12px] leading-5 text-amber-800"
                        >
                          <span className="font-semibold">
                            {issue.field ? `${issue.field}: ` : ""}
                          </span>
                          {issue.message}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-[12px] leading-5 text-slate-500">
                      No validation issues were reported for the current persisted connector config.
                    </p>
                  )}
                </div>
              ) : (
                <div className="mt-3">
                  <OpsStateCard>
                    No persisted validation state is available for this connector yet.
                  </OpsStateCard>
                </div>
              )}
            </div>

            <div className="rounded-[18px] border border-[rgba(245,158,11,0.22)] bg-[linear-gradient(180deg,rgba(255,251,235,0.96),rgba(255,247,237,0.96))] px-4 py-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-amber-700">
                    Runtime Actions
                  </p>
                  <p className="mt-1 text-[12px] leading-5 text-amber-900/80">
                    These actions call the backend connector runtime directly and are
                    intentionally admin-only. Each action records a visible local receipt and
                    surfaces backend blocks or permission failures clearly.
                  </p>
                </div>
                <OpsBadge icon={ShieldCheck} tone="warning">
                  Admin only
                </OpsBadge>
              </div>

              {!connector.enabled ? (
                <div className="mt-3">
                  <OpsStateCard tone="warning">
                    This registry entry is disabled. Runtime actions remain available for
                    inspection, but the backend will block them until the connector is enabled.
                  </OpsStateCard>
                </div>
              ) : null}

              <div className="mt-3">
                <textarea
                  value={requestDraft}
                  onChange={(event) => onRequestDraftChange(event.target.value)}
                  disabled={!adminAccessAllowed}
                  spellCheck={false}
                  className="min-h-[12rem] w-full rounded-[16px] border border-[rgba(251,191,36,0.32)] bg-white/92 px-4 py-3 font-mono text-[12px] leading-6 text-slate-700 outline-none focus:border-amber-400 disabled:cursor-not-allowed disabled:opacity-60"
                />
              </div>

              <div className="mt-3 flex flex-wrap gap-2">
                {supportedRuntimeActions.length === 0 ? (
                  <OpsStateCard>No runtime actions are registered for this connector.</OpsStateCard>
                ) : (
                  supportedRuntimeActions.map((action) => (
                    <OpsAction
                      key={`${connector.name}:run:${action}`}
                      onClick={() => onRunAction(action)}
                      tone={action === "sync_status" ? "default" : "accent"}
                      disabled={pendingActionKey !== null || !adminAccessAllowed}
                    >
                      {pendingActionKey === `${connector.name}:${action}` ? (
                        <Clock3 size={12} />
                      ) : (
                        <Play size={12} />
                      )}
                      {pendingActionKey === `${connector.name}:${action}`
                        ? `${formatTokenLabel(action) ?? action}…`
                        : formatTokenLabel(action) ?? action}
                    </OpsAction>
                  ))
                )}
                <OpsAction
                  onClick={onResetRequestDraft}
                  disabled={pendingActionKey !== null || !adminAccessAllowed}
                >
                  <RefreshCw size={12} />
                  Reset Request
                </OpsAction>
              </div>
            </div>

            <div className="rounded-[18px] border border-[rgba(226,232,240,0.95)] bg-white/94 px-4 py-4">
              <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                Latest Result
              </p>
              {latestResult ? (
                <div className="mt-3 space-y-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={cn(
                        "inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em]",
                        connectorResultTone(latestResult)
                      )}
                    >
                      {formatTokenLabel(latestResult.outcome) ?? latestResult.outcome}
                    </span>
                    <OpsBadge icon={ArrowRight} tone="neutral">
                      {formatTokenLabel(latestResult.action) ?? latestResult.action}
                    </OpsBadge>
                    {latestReceipt ? (
                      <OpsBadge
                        icon={latestReceipt.kind === "error" ? AlertTriangle : Clock3}
                        tone={latestReceipt.kind === "error" ? "warning" : "neutral"}
                      >
                        {formatRelativeIsoTime(latestReceipt.recordedAt)}
                      </OpsBadge>
                    ) : null}
                  </div>

                  <p className="text-sm font-semibold text-slate-900">
                    {latestResult.summary}
                  </p>

                  {latestResult.issues.length > 0 ? (
                    <div className="space-y-2">
                      {latestResult.issues.map((issue, index) => (
                        <div
                          key={`${connector.name}:result:${latestResult.action}:${issue.code}:${index}`}
                          className="rounded-[14px] border border-[rgba(226,232,240,0.95)] bg-[rgba(248,250,252,0.92)] px-3 py-2 text-[12px] leading-5 text-slate-600"
                        >
                          <span className="font-semibold">
                            {issue.field ? `${issue.field}: ` : ""}
                          </span>
                          {issue.message}
                        </div>
                      ))}
                    </div>
                  ) : null}

                  {(latestResult.artifact_paths.length > 0 ||
                    latestResult.external_paths.length > 0) ? (
                    <div className="grid gap-3 sm:grid-cols-2">
                      <div>
                        <p className="text-[11px] font-semibold text-slate-700">
                          Artifact paths
                        </p>
                        <div className="mt-2 space-y-2">
                          {latestResult.artifact_paths.length === 0 ? (
                            <p className="text-[12px] text-slate-500">
                              No artifact paths were returned.
                            </p>
                          ) : (
                            latestResult.artifact_paths.map((path) => (
                              <div
                                key={`${connector.name}:artifact:${path}`}
                                className="rounded-[14px] border border-[rgba(226,232,240,0.95)] bg-[rgba(248,250,252,0.92)] px-3 py-2 font-mono text-[12px] leading-5 text-slate-700"
                              >
                                {path}
                              </div>
                            ))
                          )}
                        </div>
                      </div>

                      <div>
                        <p className="text-[11px] font-semibold text-slate-700">
                          External paths
                        </p>
                        <div className="mt-2 space-y-2">
                          {latestResult.external_paths.length === 0 ? (
                            <p className="text-[12px] text-slate-500">
                              No external paths were returned.
                            </p>
                          ) : (
                            latestResult.external_paths.map((path) => (
                              <div
                                key={`${connector.name}:external:${path}`}
                                className="rounded-[14px] border border-[rgba(226,232,240,0.95)] bg-[rgba(248,250,252,0.92)] px-3 py-2 text-[12px] leading-5 text-slate-700"
                              >
                                {path}
                              </div>
                            ))
                          )}
                        </div>
                      </div>
                    </div>
                  ) : null}

                  <div>
                    <p className="text-[11px] font-semibold text-slate-700">Metadata</p>
                    <div className="mt-2">
                      <JsonPreview value={latestResult.metadata} />
                    </div>
                  </div>
                </div>
              ) : latestReceipt ? (
                <div className="mt-3">
                  <OpsStateCard tone={latestReceipt.kind === "error" ? "error" : "neutral"}>
                    {latestReceipt.message}
                  </OpsStateCard>
                </div>
              ) : (
                <div className="mt-3">
                  <OpsStateCard>
                    No connector mutation or runtime result has been recorded in this session yet.
                  </OpsStateCard>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </OpsSectionCard>
  );
}

function ConnectorsView({
  listStatus,
  connectors,
  listError,
  detailStatus,
  connector,
  detailError,
  adminConfigStatus,
  adminConfigError,
  adminAccessAllowed,
  adminAccessMessage,
  configLoaded,
  ignoredFilters,
  selectedConnectorName,
  configDraft,
  requestDraft,
  pendingActionKey,
  latestResult,
  currentValidationResult,
  latestReceipt,
  onSelect,
  onConfigDraftChange,
  onRequestDraftChange,
  onResetConfigDraft,
  onResetRequestDraft,
  onToggleEnabled,
  onSaveConfig,
  onValidateDraft,
  onRunAction,
}: {
  listStatus: OpsWorkspaceStatus;
  connectors: ConnectorRegistryEntry[];
  listError: string | null;
  detailStatus: OpsWorkspaceStatus;
  connector: ConnectorRegistryEntry | null;
  detailError: string | null;
  adminConfigStatus: OpsWorkspaceStatus;
  adminConfigError: string | null;
  adminAccessAllowed: boolean;
  adminAccessMessage: string;
  configLoaded: boolean;
  ignoredFilters: FilterChip[];
  selectedConnectorName: string | null;
  configDraft: string;
  requestDraft: string;
  pendingActionKey: string | null;
  latestResult: ConnectorActionResult | null;
  currentValidationResult: ConnectorActionResult | null;
  latestReceipt: ConnectorActionReceipt | null;
  onSelect: (connector: ConnectorRegistryEntry) => void;
  onConfigDraftChange: (value: string) => void;
  onRequestDraftChange: (value: string) => void;
  onResetConfigDraft: () => void;
  onResetRequestDraft: () => void;
  onToggleEnabled: () => void;
  onSaveConfig: () => void;
  onValidateDraft: () => void;
  onRunAction: (action: ConnectorExecutionAction) => void;
}) {
  const enabledCount = connectors.filter((connector) => connector.enabled).length;
  const validationReadyCount = connectors.filter((connector) =>
    connector.validation_result
      ? connector.validation_result.outcome === "success"
      : connector.config_summary.configured &&
        connector.config_summary.missing_required_fields.length === 0
  ).length;
  const attentionCount = connectors.filter((connector) => {
    const health = getConnectorHealthSummary(connector);
    return health.tone !== "default";
  }).length;

  return (
    <div className="space-y-4">
      {ignoredFilters.length > 0 ? (
        <OpsStateCard tone="warning">
          The connectors view only applies the shared connector-name filter. Other
          Ops filters are ignored because the registry routes expose administrative
          metadata rather than runtime records.
          <div className="mt-3">
            <FilterChipRow chips={ignoredFilters} tone="warning" />
          </div>
        </OpsStateCard>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <OpsSummaryCard
          label="Registry Entries"
          value={
            listStatus === "loading" && connectors.length === 0
              ? "Loading"
              : formatInteger(connectors.length)
          }
          detail="Connector definitions currently visible in the registry view."
        />
        <OpsSummaryCard
          label="Enabled"
          value={formatInteger(enabledCount)}
          detail="Entries currently enabled for runtime execution."
        />
        <OpsSummaryCard
          label="Config Ready"
          value={formatInteger(validationReadyCount)}
          detail="Entries whose persisted config currently validates successfully."
        />
        <OpsSummaryCard
          label="Needs Attention"
          value={formatInteger(attentionCount)}
          detail="Disabled or validation-impaired entries that need operator review."
          tone={attentionCount > 0 ? "warning" : "default"}
        />
      </div>

      <div className="grid min-h-0 gap-4 xl:grid-cols-[minmax(0,0.78fr)_minmax(0,1.22fr)]">
        <ConnectorRegistryNavigator
          status={listStatus}
          connectors={connectors}
          error={listError}
          selectedConnectorName={selectedConnectorName}
          onSelect={onSelect}
        />
        <ConnectorDetailPane
          status={detailStatus}
          connector={connector}
          error={detailError}
          adminConfigStatus={adminConfigStatus}
          adminConfigError={adminConfigError}
          adminAccessAllowed={adminAccessAllowed}
          adminAccessMessage={adminAccessMessage}
          configLoaded={configLoaded}
          configDraft={configDraft}
          requestDraft={requestDraft}
          pendingActionKey={pendingActionKey}
          currentValidationResult={currentValidationResult}
          latestResult={latestResult}
          latestReceipt={latestReceipt}
          onConfigDraftChange={onConfigDraftChange}
          onRequestDraftChange={onRequestDraftChange}
          onResetConfigDraft={onResetConfigDraft}
          onResetRequestDraft={onResetRequestDraft}
          onToggleEnabled={onToggleEnabled}
          onSaveConfig={onSaveConfig}
          onValidateDraft={onValidateDraft}
          onRunAction={onRunAction}
        />
      </div>
    </div>
  );
}

function DashboardDefinitionsView({
  status,
  dashboards,
  error,
  ignoredFilters,
}: {
  status: OpsWorkspaceStatus;
  dashboards: ObservabilityDashboardDefinition[];
  error: string | null;
  ignoredFilters: FilterChip[];
}) {
  if (status === "loading" && dashboards.length === 0) {
    return <OpsStateCard>Loading dashboard definitions…</OpsStateCard>;
  }

  if (status === "error") {
    return (
      <OpsStateCard tone="error">
        {error ?? "Could not load dashboard definitions."}
      </OpsStateCard>
    );
  }

  return (
    <div className="space-y-4">
      {ignoredFilters.length > 0 ? (
        <OpsStateCard tone="warning">
          Dashboard definitions do not accept runtime filters. The current filter
          set still applies to overview, metrics, and traces.
          <div className="mt-3">
            <FilterChipRow chips={ignoredFilters} tone="warning" />
          </div>
        </OpsStateCard>
      ) : null}

      {dashboards.length === 0 ? (
        <OpsStateCard>No dashboard definitions are available yet.</OpsStateCard>
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {dashboards.map((dashboard) => (
            <OpsSectionCard
              key={dashboard.id}
              title={dashboard.title}
              description={dashboard.description}
            >
              <div className="space-y-3">
                {dashboard.panels.map((panel, index) => (
                  <div
                    key={`${dashboard.id}:${panel.title}:${index}`}
                    className="rounded-[18px] border border-[rgba(226,232,240,0.95)] bg-[rgba(248,250,252,0.92)] px-4 py-4"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-semibold text-slate-900">{panel.title}</p>
                      <OpsBadge icon={Activity} tone="neutral">
                        {panel.aggregation}
                      </OpsBadge>
                    </div>
                    <p className="mt-2 text-[12px] leading-5 text-slate-500">
                      Metric: <span className="font-medium text-slate-700">{panel.metric_name}</span>
                    </p>
                    <div className="mt-3">
                      <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                        Static Filters
                      </p>
                      <div className="mt-2">
                        <JsonPreview value={panel.filters} />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </OpsSectionCard>
          ))}
        </div>
      )}
    </div>
  );
}

export default function OpsWorkspace() {
  const {
    accessByScope,
    hasAdminAccess,
    hasInspectionAccess,
    setWorkspaceMode,
  } = useApp();
  const [activeView, setActiveView] = useState<OpsView>("overview");
  const [draftFilters, setDraftFilters] = useState<OpsWorkspaceFilters>({
    ...DEFAULT_OPS_FILTERS,
  });
  const [appliedFilters, setAppliedFilters] = useState<OpsWorkspaceFilters>({
    ...DEFAULT_OPS_FILTERS,
  });
  const [refreshToken, setRefreshToken] = useState(0);

  const [overviewStatus, setOverviewStatus] =
    useState<OpsWorkspaceStatus>("loading");
  const [overview, setOverview] = useState<ObservabilityOverview | null>(null);
  const [overviewError, setOverviewError] = useState<string | null>(null);

  const [metricsStatus, setMetricsStatus] =
    useState<OpsWorkspaceStatus>("idle");
  const [metrics, setMetrics] = useState<ObservabilityMetricRecord[]>([]);
  const [metricsError, setMetricsError] = useState<string | null>(null);
  const [selectedMetricRecordId, setSelectedMetricRecordId] = useState<string | null>(
    null
  );

  const [tracesStatus, setTracesStatus] =
    useState<OpsWorkspaceStatus>("idle");
  const [traces, setTraces] = useState<ObservabilityTraceRecord[]>([]);
  const [tracesError, setTracesError] = useState<string | null>(null);
  const [selectedTraceKey, setSelectedTraceKey] = useState<string | null>(null);

  const [auditStatus, setAuditStatus] =
    useState<OpsWorkspaceStatus>("idle");
  const [auditEvents, setAuditEvents] = useState<AuditEventRecord[]>([]);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [auditRetentionPolicy, setAuditRetentionPolicy] =
    useState<RetentionPolicy | null>(null);
  const [selectedAuditEventId, setSelectedAuditEventId] = useState<string | null>(
    null
  );

  const [connectorsStatus, setConnectorsStatus] =
    useState<OpsWorkspaceStatus>("idle");
  const [connectors, setConnectors] = useState<ConnectorRegistryEntry[]>([]);
  const [connectorsError, setConnectorsError] = useState<string | null>(null);
  const [selectedConnectorName, setSelectedConnectorName] = useState<string | null>(
    null
  );
  const [connectorDetailStatus, setConnectorDetailStatus] =
    useState<OpsWorkspaceStatus>("idle");
  const [connectorDetail, setConnectorDetail] =
    useState<ConnectorRegistryEntry | null>(null);
  const [connectorDetailError, setConnectorDetailError] = useState<string | null>(
    null
  );
  const [connectorAdminDetailStatus, setConnectorAdminDetailStatus] =
    useState<OpsWorkspaceStatus>("idle");
  const [connectorAdminDetailError, setConnectorAdminDetailError] = useState<
    string | null
  >(null);
  const [connectorStoredConfigs, setConnectorStoredConfigs] = useState<
    Record<string, JsonObject>
  >({});
  const [connectorConfigDrafts, setConnectorConfigDrafts] = useState<
    Record<string, string>
  >({});
  const [connectorRequestDrafts, setConnectorRequestDrafts] = useState<
    Record<string, string>
  >({});
  const [connectorLatestResults, setConnectorLatestResults] = useState<
    Record<string, ConnectorActionResult>
  >({});
  const [connectorValidationResults, setConnectorValidationResults] = useState<
    Record<string, ConnectorActionResult>
  >({});
  const [connectorReceipts, setConnectorReceipts] = useState<
    Record<string, ConnectorActionReceipt>
  >({});
  const [connectorPendingActionKey, setConnectorPendingActionKey] = useState<
    string | null
  >(null);

  const [dashboardsStatus, setDashboardsStatus] =
    useState<OpsWorkspaceStatus>("idle");
  const [dashboards, setDashboards] = useState<ObservabilityDashboardDefinition[]>(
    []
  );
  const [dashboardsError, setDashboardsError] = useState<string | null>(null);
  const overviewQuery = useMemo(
    () => buildOverviewQuery(appliedFilters),
    [appliedFilters]
  );
  const metricsQuery = useMemo(
    () => buildMetricsQuery(appliedFilters),
    [appliedFilters]
  );
  const tracesQuery = useMemo(
    () => buildTracesQuery(appliedFilters),
    [appliedFilters]
  );
  const auditQuery = useMemo(
    () => buildAuditQuery(appliedFilters),
    [appliedFilters]
  );
  const filteredConnectors = useMemo(
    () => filterConnectorsByName(connectors, appliedFilters.connectorName),
    [appliedFilters.connectorName, connectors]
  );

  useEffect(() => {
    if (!hasInspectionAccess) {
      setOverview(null);
      setOverviewStatus("error");
      setOverviewError(accessByScope.inspection.detail);
      return;
    }

    let active = true;
    setOverviewStatus("loading");
    setOverviewError(null);
    setOverview(null);

    void getObservabilityOverview(overviewQuery)
      .then((response) => {
        if (!active) {
          return;
        }
        setOverview(response);
        setOverviewStatus("ready");
      })
      .catch((error) => {
        if (!active) {
          return;
        }
        setOverview(null);
        setOverviewStatus("error");
        setOverviewError(
          getObservabilityErrorMessage(
            error,
            "the ops overview",
            accessByScope.inspection
          )
        );
      });

    return () => {
      active = false;
    };
  }, [accessByScope.inspection, hasInspectionAccess, overviewQuery, refreshToken]);

  useEffect(() => {
    if (activeView !== "metrics") {
      return;
    }

    if (!hasInspectionAccess) {
      setMetrics([]);
      setMetricsStatus("error");
      setMetricsError(accessByScope.inspection.detail);
      return;
    }

    let active = true;
    setMetricsStatus("loading");
    setMetricsError(null);
    setMetrics([]);

    void listObservabilityMetrics(metricsQuery)
      .then((response) => {
        if (!active) {
          return;
        }
        setMetrics(response.metrics);
        setMetricsStatus("ready");
      })
      .catch((error) => {
        if (!active) {
          return;
        }
        setMetrics([]);
        setMetricsStatus("error");
        setMetricsError(
          getObservabilityErrorMessage(
            error,
            "metric records",
            accessByScope.inspection
          )
        );
      });

    return () => {
      active = false;
    };
  }, [accessByScope.inspection, activeView, hasInspectionAccess, metricsQuery, refreshToken]);

  useEffect(() => {
    if (metrics.length === 0) {
      if (selectedMetricRecordId !== null) {
        setSelectedMetricRecordId(null);
      }
      return;
    }

    if (selectedMetricRecordId && metrics.some((record) => record.record_id === selectedMetricRecordId)) {
      return;
    }

    setSelectedMetricRecordId(metrics[0].record_id);
  }, [metrics, selectedMetricRecordId]);

  useEffect(() => {
    if (activeView !== "traces") {
      return;
    }

    if (!hasInspectionAccess) {
      setTraces([]);
      setTracesStatus("error");
      setTracesError(accessByScope.inspection.detail);
      return;
    }

    let active = true;
    setTracesStatus("loading");
    setTracesError(null);
    setTraces([]);

    void listObservabilityTraces(tracesQuery)
      .then((response) => {
        if (!active) {
          return;
        }
        setTraces(response.traces);
        setTracesStatus("ready");
      })
      .catch((error) => {
        if (!active) {
          return;
        }
        setTraces([]);
        setTracesStatus("error");
        setTracesError(
          getObservabilityErrorMessage(
            error,
            "trace records",
            accessByScope.inspection
          )
        );
      });

    return () => {
      active = false;
    };
  }, [accessByScope.inspection, activeView, hasInspectionAccess, refreshToken, tracesQuery]);

  useEffect(() => {
    if (traces.length === 0) {
      if (selectedTraceKey !== null) {
        setSelectedTraceKey(null);
      }
      return;
    }

    if (selectedTraceKey && traces.some((record) => `${record.trace_id}:${record.span_id}` === selectedTraceKey)) {
      return;
    }

    setSelectedTraceKey(`${traces[0].trace_id}:${traces[0].span_id}`);
  }, [selectedTraceKey, traces]);

  useEffect(() => {
    if (activeView !== "dashboards") {
      return;
    }

    if (!hasInspectionAccess) {
      setDashboards([]);
      setDashboardsStatus("error");
      setDashboardsError(accessByScope.inspection.detail);
      return;
    }

    let active = true;
    setDashboardsStatus("loading");
    setDashboardsError(null);
    setDashboards([]);

    void getObservabilityDashboardDefinitions()
      .then((response) => {
        if (!active) {
          return;
        }
        setDashboards(response.dashboards);
        setDashboardsStatus("ready");
      })
      .catch((error) => {
        if (!active) {
          return;
        }
        setDashboards([]);
        setDashboardsStatus("error");
        setDashboardsError(
          getObservabilityErrorMessage(
            error,
            "dashboard definitions",
            accessByScope.inspection
          )
        );
      });

    return () => {
      active = false;
    };
  }, [accessByScope.inspection, activeView, hasInspectionAccess, refreshToken]);

  useEffect(() => {
    if (activeView !== "audit") {
      return;
    }

    if (!hasInspectionAccess) {
      setAuditEvents([]);
      setAuditRetentionPolicy(null);
      setAuditStatus("error");
      setAuditError(accessByScope.inspection.detail);
      return;
    }

    let active = true;
    setAuditStatus("loading");
    setAuditError(null);
    setAuditEvents([]);
    setAuditRetentionPolicy(null);

    void listAuditEvents(auditQuery)
      .then((response) => {
        if (!active) {
          return;
        }
        setAuditEvents(response.events);
        setAuditRetentionPolicy(response.retention_policy);
        setAuditStatus("ready");
      })
      .catch((error) => {
        if (!active) {
          return;
        }
        setAuditEvents([]);
        setAuditRetentionPolicy(null);
        setAuditStatus("error");
        setAuditError(
          getObservabilityErrorMessage(
            error,
            "audit events",
            accessByScope.inspection
          )
        );
      });

    return () => {
      active = false;
    };
  }, [accessByScope.inspection, activeView, auditQuery, hasInspectionAccess, refreshToken]);

  useEffect(() => {
    if (auditEvents.length === 0) {
      if (selectedAuditEventId !== null) {
        setSelectedAuditEventId(null);
      }
      return;
    }

    if (selectedAuditEventId && auditEvents.some((event) => event.event_id === selectedAuditEventId)) {
      return;
    }

    setSelectedAuditEventId(auditEvents[0].event_id);
  }, [auditEvents, selectedAuditEventId]);

  useEffect(() => {
    if (activeView !== "connectors") {
      return;
    }

    if (!hasInspectionAccess) {
      setConnectors([]);
      setConnectorsStatus("error");
      setConnectorsError(accessByScope.inspection.detail);
      return;
    }

    let active = true;
    setConnectorsStatus("loading");
    setConnectorsError(null);
    setConnectors([]);

    void listConnectorRegistry()
      .then((response) => {
        if (!active) {
          return;
        }
        setConnectors(response.connectors);
        setConnectorsStatus("ready");
      })
      .catch((error) => {
        if (!active) {
          return;
        }
        setConnectors([]);
        setConnectorsStatus("error");
        setConnectorsError(
          getObservabilityErrorMessage(
            error,
            "the connector registry",
            accessByScope.inspection
          )
        );
      });

    return () => {
      active = false;
    };
  }, [accessByScope.inspection, activeView, hasInspectionAccess, refreshToken]);

  useEffect(() => {
    if (activeView !== "connectors") {
      return;
    }

    if (filteredConnectors.length === 0) {
      if (selectedConnectorName !== null) {
        setSelectedConnectorName(null);
      }
      return;
    }

    if (
      selectedConnectorName &&
      filteredConnectors.some((connector) => connector.name === selectedConnectorName)
    ) {
      return;
    }

    setSelectedConnectorName(filteredConnectors[0].name);
  }, [activeView, filteredConnectors, selectedConnectorName]);

  useEffect(() => {
    if (activeView !== "connectors") {
      return;
    }

    if (!selectedConnectorName) {
      setConnectorDetail(null);
      setConnectorDetailError(null);
      setConnectorDetailStatus("idle");
      return;
    }

    if (!hasInspectionAccess) {
      setConnectorDetail(null);
      setConnectorDetailStatus("error");
      setConnectorDetailError(accessByScope.inspection.detail);
      return;
    }

    let active = true;
    setConnectorDetailStatus("loading");
    setConnectorDetailError(null);
    setConnectorDetail((current) =>
      current?.name === selectedConnectorName ? current : null
    );

    void getConnectorRegistryDetail(selectedConnectorName)
      .then((response) => {
        if (!active) {
          return;
        }
        setConnectorDetail(response);
        setConnectorDetailStatus("ready");
      })
      .catch((error) => {
        if (!active) {
          return;
        }
        setConnectorDetail(null);
        setConnectorDetailStatus("error");
        setConnectorDetailError(
          getObservabilityErrorMessage(
            error,
            "the selected connector detail",
            accessByScope.inspection
          )
        );
      });

    return () => {
      active = false;
    };
  }, [accessByScope.inspection, activeView, hasInspectionAccess, refreshToken, selectedConnectorName]);

  useEffect(() => {
    if (activeView !== "connectors") {
      return;
    }

    if (!selectedConnectorName) {
      setConnectorAdminDetailStatus("idle");
      setConnectorAdminDetailError(null);
      return;
    }

    if (!hasAdminAccess) {
      setConnectorAdminDetailStatus("error");
      setConnectorAdminDetailError(accessByScope.admin.detail);
      return;
    }

    let active = true;
    setConnectorAdminDetailStatus("loading");
    setConnectorAdminDetailError(null);

    void getConnectorRegistryAdminDetail(selectedConnectorName)
      .then((response) => {
        if (!active) {
          return;
        }
        setConnectorStoredConfigs((current) => ({
          ...current,
          [response.connector_name]: response.config,
        }));
        setConnectorValidationResults((current) => ({
          ...current,
          [response.connector_name]: response.validation_result,
        }));
        setConnectorConfigDrafts((current) =>
          response.connector_name in current
            ? current
            : {
                ...current,
                [response.connector_name]: formatJsonValue(response.config),
              }
        );
        setConnectorAdminDetailStatus("ready");
      })
      .catch((error) => {
        if (!active) {
          return;
        }
        setConnectorAdminDetailStatus("error");
        setConnectorAdminDetailError(
          getConnectorMutationErrorMessage(error, accessByScope.admin)
        );
      });

    return () => {
      active = false;
    };
  }, [accessByScope.admin, activeView, hasAdminAccess, selectedConnectorName]);

  const appliedFilterChips = useMemo(
    () => getAppliedFilterChips(appliedFilters),
    [appliedFilters]
  );
  const draftFilterChips = useMemo(
    () => getAppliedFilterChips(draftFilters),
    [draftFilters]
  );
  const ignoredFilterChips = useMemo(
    () => getIgnoredFilterChips(activeView, appliedFilters),
    [activeView, appliedFilters]
  );
  const canClearFilters =
    appliedFilterChips.length > 0 || draftFilterChips.length > 0;
  const selectedMetric =
    metrics.find((record) => record.record_id === selectedMetricRecordId) ?? null;
  const selectedTrace =
    traces.find((record) => `${record.trace_id}:${record.span_id}` === selectedTraceKey) ??
    null;
  const currentListLimit = resolveListLimit(appliedFilters.limit);
  const canLoadMoreAuditEvents =
    activeView === "audit" &&
    currentListLimit < MAX_OPS_LIST_LIMIT &&
    auditEvents.length >= currentListLimit;

  const currentRetentionPolicy =
    activeView === "audit"
      ? auditRetentionPolicy
      : overview?.retention_policy ?? null;
  const selectedConnector =
    connectorDetail && connectorDetail.name === selectedConnectorName
      ? connectorDetail
      : filteredConnectors.find((connector) => connector.name === selectedConnectorName) ??
        null;
  const selectedConnectorConfigLoaded = selectedConnectorName
    ? selectedConnectorName in connectorStoredConfigs
    : false;
  const selectedConnectorStoredConfig =
    selectedConnectorName && selectedConnectorConfigLoaded
      ? connectorStoredConfigs[selectedConnectorName]
      : null;
  const selectedConnectorConfigDraft = selectedConnectorName
    ? connectorConfigDrafts[selectedConnectorName] ??
      (selectedConnectorStoredConfig
        ? formatJsonValue(selectedConnectorStoredConfig)
        : "")
    : "{}";
  const selectedConnectorRequestDraft = selectedConnectorName
    ? connectorRequestDrafts[selectedConnectorName] ??
      formatJsonValue(createConnectorRequestDraft())
    : formatJsonValue(createConnectorRequestDraft());
  const selectedConnectorLatestResult = selectedConnectorName
    ? connectorLatestResults[selectedConnectorName] ?? null
    : null;
  const selectedConnectorValidationResult = selectedConnectorName
    ? selectedConnector?.validation_result ??
      connectorValidationResults[selectedConnectorName] ??
      null
    : null;
  const selectedConnectorReceipt = selectedConnectorName
    ? connectorReceipts[selectedConnectorName] ?? null
    : null;

  const syncConnectorEntry = (entry: ConnectorRegistryEntry) => {
    setConnectors((current) =>
      current.map((candidate) =>
        candidate.name === entry.name ? entry : candidate
      )
    );
    setConnectorDetail((current) =>
      current?.name === entry.name ? entry : current
    );
  };

  const recordConnectorReceipt = (
    connectorName: string,
    action: ConnectorAction,
    kind: "success" | "error",
    message: string
  ) => {
    setConnectorReceipts((current) => ({
      ...current,
      [connectorName]: {
        action,
        kind,
        message,
        recordedAt: new Date().toISOString(),
      },
    }));
  };

  const recordConnectorResult = (
    result: ConnectorActionResult,
    kind: "success" | "error" = result.status === "success" ? "success" : "error"
  ) => {
    setConnectorLatestResults((current) => ({
      ...current,
      [result.connector_name]: result,
    }));
    recordConnectorReceipt(result.connector_name, result.action, kind, result.summary);
  };

  const handleConnectorReceiptError = (
    connectorName: string,
    action: ConnectorAction,
    error: unknown
  ) => {
    const parsedResult = parseConnectorActionResultFromError(error);
    if (parsedResult) {
      recordConnectorResult(parsedResult, "error");
      return;
    }

    setConnectorLatestResults((current) => {
      if (!(connectorName in current)) {
        return current;
      }
      const next = { ...current };
      delete next[connectorName];
      return next;
    });
    recordConnectorReceipt(
      connectorName,
      action,
      "error",
      getConnectorMutationErrorMessage(error, accessByScope.admin)
    );
  };

  const handleToggleConnector = () => {
    if (!selectedConnector || !hasAdminAccess) {
      if (selectedConnector) {
        recordConnectorReceipt(
          selectedConnector.name,
          "configure",
          "error",
          accessByScope.admin.detail
        );
      }
      return;
    }

    const actionKey = `${selectedConnector.name}:toggle`;
    setConnectorPendingActionKey(actionKey);

    void updateConnectorRegistryEntry(selectedConnector.name, {
      enabled: !selectedConnector.enabled,
    })
      .then((response) => {
        syncConnectorEntry(response.connector);
        const persistedValidationResult = response.connector.validation_result;
        if (persistedValidationResult) {
          setConnectorValidationResults((current) => ({
            ...current,
            [response.connector.name]: persistedValidationResult,
          }));
        }
        recordConnectorResult(response.result);
      })
      .catch((error) => {
        const parsedResult = parseConnectorActionResultFromError(error);
        if (parsedResult) {
          recordConnectorResult(parsedResult, "error");
          return;
        }
        handleConnectorReceiptError(selectedConnector.name, "configure", error);
      })
      .finally(() => {
        setConnectorPendingActionKey((current) =>
          current === actionKey ? null : current
        );
      });
  };

  const handleSaveConnectorConfig = () => {
    if (!selectedConnector || !hasAdminAccess) {
      if (selectedConnector) {
        recordConnectorReceipt(
          selectedConnector.name,
          "configure",
          "error",
          accessByScope.admin.detail
        );
      }
      return;
    }

    if (!selectedConnectorConfigLoaded) {
      recordConnectorReceipt(
        selectedConnector.name,
        "configure",
        "error",
        "Load the persisted connector config before editing it."
      );
      return;
    }

    const parsed = parseJsonObjectEditor(
      selectedConnectorConfigDraft,
      "Connector config draft"
    );
    if (parsed.error || parsed.value === null) {
      recordConnectorReceipt(
        selectedConnector.name,
        "configure",
        "error",
        parsed.error ?? "Connector config draft must be a JSON object."
      );
      return;
    }
    const nextConfig = parsed.value;

    const actionKey = `${selectedConnector.name}:configure`;
    setConnectorPendingActionKey(actionKey);

    void updateConnectorRegistryEntry(selectedConnector.name, {
      enabled: selectedConnector.enabled,
      config: nextConfig,
    })
      .then((response) => {
        setConnectorStoredConfigs((current) => ({
          ...current,
          [response.connector.name]: nextConfig,
        }));
        const persistedValidationResult = response.connector.validation_result;
        if (persistedValidationResult) {
          setConnectorValidationResults((current) => ({
            ...current,
            [response.connector.name]: persistedValidationResult,
          }));
        }
        syncConnectorEntry(response.connector);
        recordConnectorResult(response.result);
      })
      .catch((error) => {
        handleConnectorReceiptError(selectedConnector.name, "configure", error);
      })
      .finally(() => {
        setConnectorPendingActionKey((current) =>
          current === actionKey ? null : current
        );
      });
  };

  const handleValidateConnectorDraft = () => {
    if (!selectedConnector || !hasAdminAccess) {
      if (selectedConnector) {
        recordConnectorReceipt(
          selectedConnector.name,
          "validate",
          "error",
          accessByScope.admin.detail
        );
      }
      return;
    }

    if (!selectedConnectorConfigLoaded) {
      recordConnectorReceipt(
        selectedConnector.name,
        "validate",
        "error",
        "Load the persisted connector config before validating edits."
      );
      return;
    }

    const parsed = parseJsonObjectEditor(
      selectedConnectorConfigDraft,
      "Connector config draft"
    );
    if (parsed.error || parsed.value === null) {
      recordConnectorReceipt(
        selectedConnector.name,
        "validate",
        "error",
        parsed.error ?? "Connector config draft must be a JSON object."
      );
      return;
    }

    const actionKey = `${selectedConnector.name}:validate`;
    setConnectorPendingActionKey(actionKey);

    void validateConnectorRegistryEntry(
      selectedConnector.name,
      { config: parsed.value }
    )
      .then((result) => {
        recordConnectorResult(result);
      })
      .catch((error) => {
        handleConnectorReceiptError(selectedConnector.name, "validate", error);
      })
      .finally(() => {
        setConnectorPendingActionKey((current) =>
          current === actionKey ? null : current
        );
      });
  };

  const handleRunConnectorAction = (action: ConnectorExecutionAction) => {
    if (!selectedConnector || !hasAdminAccess) {
      if (selectedConnector) {
        recordConnectorReceipt(
          selectedConnector.name,
          action,
          "error",
          accessByScope.admin.detail
        );
      }
      return;
    }

    const parsed = parseJsonObjectEditor(
      selectedConnectorRequestDraft,
      "Connector runtime request"
    );
    if (parsed.error) {
      recordConnectorReceipt(selectedConnector.name, action, "error", parsed.error);
      return;
    }

    const actionKey = `${selectedConnector.name}:${action}`;
    setConnectorPendingActionKey(actionKey);

    void runConnectorRegistryAction(
      selectedConnector.name,
      action,
      parsed.value !== null ? parsed.value : undefined
    )
      .then((result) => {
        recordConnectorResult(result);
      })
      .catch((error) => {
        handleConnectorReceiptError(selectedConnector.name, action, error);
      })
      .finally(() => {
        setConnectorPendingActionKey((current) =>
          current === actionKey ? null : current
        );
      });
  };

  const activeViewDescription = VIEW_CONFIG[activeView].description;
  const activeScopeBadgeLabel =
    activeView === "overview"
      ? `${overviewQuery.days ?? 7} day window`
      : activeView === "connectors"
        ? "Registry + detail"
      : activeView === "dashboards"
        ? "Static definitions"
        : `${formatInteger(currentListLimit)} row limit`;
  const viewSupportSummary =
    activeView === "overview"
      ? "Overview uses the time window plus request, session, and workflow filters."
      : activeView === "audit"
        ? "Audit applies event type, session, run, step, job, workflow, tool, connector, outcome, and list-limit filters."
      : activeView === "connectors"
        ? "Connectors uses the shared connector-name filter and otherwise shows registry metadata plus admin-only action controls."
      : activeView === "dashboards"
        ? "Dashboard definitions are static backend metadata and ignore runtime filters."
        : "Metrics and traces apply request, session, run, step, job, workflow, trace, and list-limit filters.";

  return (
    <OpsShell>
      <OpsHero
        badges={
          <>
            <OpsBadge icon={VIEW_CONFIG[activeView].icon}>
              {VIEW_CONFIG[activeView].label}
            </OpsBadge>
            <OpsBadge icon={Clock3} tone="neutral">
              {activeScopeBadgeLabel}
            </OpsBadge>
            <OpsBadge icon={Filter} tone={appliedFilterChips.length > 0 ? "warning" : "neutral"}>
              {appliedFilterChips.length === 0
                ? "No extra filters"
                : `${appliedFilterChips.length} active filter${appliedFilterChips.length === 1 ? "" : "s"}`}
            </OpsBadge>
            <OpsBadge icon={ShieldCheck} tone="neutral">
              {retentionLabel(currentRetentionPolicy)}
            </OpsBadge>
          </>
        }
        actions={
          <>
            <OpsAction onClick={() => setRefreshToken((current) => current + 1)} tone="accent">
              <RefreshCw size={12} />
              Refresh
            </OpsAction>
            <OpsAction onClick={() => setWorkspaceMode("sessions")}>
              <MessageSquare size={12} />
              Return To Session
            </OpsAction>
          </>
        }
      />

      {activeView !== "audit" && activeView !== "connectors" ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <OpsSummaryCard
            label="Observed Records"
            value={
              overview
                ? formatInteger(
                    overview.record_counts.metric_records + overview.record_counts.trace_records
                  )
                : overviewStatus === "loading"
                  ? "Loading"
                  : "Unavailable"
            }
            detail="Total overview-visible metric and trace records in the current time window."
          />
          <OpsSummaryCard
            label="Chat Latency P95"
            value={
              overview
                ? formatDurationSeconds(
                    overview.chat_responsiveness.user_visible_latency_seconds.p95
                  )
                : overviewStatus === "loading"
                  ? "Loading"
                  : "Unavailable"
            }
            detail="Recent user-visible response time at the 95th percentile."
          />
          <OpsSummaryCard
            label="Workflow Failure Rate"
            value={
              overview
                ? formatRateSummaryValue(overview.workflow_delivery.failure_rate)
                : overviewStatus === "loading"
                  ? "Loading"
                  : "Unavailable"
            }
            detail="Recent failure frequency across workflow delivery records."
            tone={
              overview &&
              overview.workflow_delivery.failure_rate.average !== null &&
              overview.workflow_delivery.failure_rate.average > 0
                ? "warning"
                : "default"
            }
          />
          <OpsSummaryCard
            label="Evidence Coverage"
            value={
              overview
                ? formatRateSummaryValue(overview.workflow_quality.evidence_coverage_rate)
                : overviewStatus === "loading"
                  ? "Loading"
                  : "Unavailable"
            }
            detail="Recent evidence-link coverage for workflow quality tracking."
            tone={
              overview &&
              overview.workflow_quality.evidence_coverage_rate.average !== null &&
              overview.workflow_quality.evidence_coverage_rate.average < 0.5
                ? "danger"
                : "default"
            }
          />
        </div>
      ) : null}

      <OpsSectionCard
        title="Filters"
        description="Set shared runtime, audit, and connector filters, then apply them to the relevant Ops views."
      >
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          <OpsFilterField
            label="Days"
            description="Overview only"
            value={draftFilters.days}
            placeholder="7"
            onChange={(value) =>
              setDraftFilters((current) => ({ ...current, days: value }))
            }
          />
          <OpsFilterField
            label="List Limit"
            description="Metrics, traces, audit"
            value={draftFilters.limit}
            placeholder="100"
            onChange={(value) =>
              setDraftFilters((current) => ({ ...current, limit: value }))
            }
          />
          <OpsFilterSelect
            label="Event Type"
            description="Audit only"
            value={draftFilters.eventType}
            options={[
              { value: "", label: "Any event type" },
              ...AUDIT_EVENT_TYPE_OPTIONS.map((eventType) => ({
                value: eventType,
                label: formatAuditEventTypeLabel(eventType),
              })),
            ]}
            onChange={(value) =>
              setDraftFilters((current) => ({ ...current, eventType: value }))
            }
          />
          <OpsFilterField
            label="Request ID"
            description="Overview, metrics, traces"
            value={draftFilters.requestId}
            placeholder="req_..."
            onChange={(value) =>
              setDraftFilters((current) => ({ ...current, requestId: value }))
            }
          />
          <OpsFilterField
            label="Session ID"
            description="Overview, metrics, traces, audit"
            value={draftFilters.sessionId}
            placeholder="session_..."
            onChange={(value) =>
              setDraftFilters((current) => ({ ...current, sessionId: value }))
            }
          />
          <OpsFilterField
            label="Run ID"
            description="Metrics, traces, audit"
            value={draftFilters.runId}
            placeholder="run_..."
            onChange={(value) =>
              setDraftFilters((current) => ({ ...current, runId: value }))
            }
          />
          <OpsFilterField
            label="Step ID"
            description="Metrics, traces, audit"
            value={draftFilters.stepId}
            placeholder="step_..."
            onChange={(value) =>
              setDraftFilters((current) => ({ ...current, stepId: value }))
            }
          />
          <OpsFilterField
            label="Job ID"
            description="Metrics, traces, audit"
            value={draftFilters.jobId}
            placeholder="job_..."
            onChange={(value) =>
              setDraftFilters((current) => ({ ...current, jobId: value }))
            }
          />
          <OpsFilterField
            label="Workflow ID"
            description="Overview, metrics, traces, audit"
            value={draftFilters.workflowId}
            placeholder="workflow_..."
            onChange={(value) =>
              setDraftFilters((current) => ({ ...current, workflowId: value }))
            }
          />
          <OpsFilterField
            label="Trace ID"
            description="Metrics and traces"
            value={draftFilters.traceId}
            placeholder="trace_..."
            onChange={(value) =>
              setDraftFilters((current) => ({ ...current, traceId: value }))
            }
          />
          <OpsFilterField
            label="Tool Name"
            description="Audit only"
            value={draftFilters.toolName}
            placeholder="read_file"
            onChange={(value) =>
              setDraftFilters((current) => ({ ...current, toolName: value }))
            }
          />
          <OpsFilterField
            label="Connector Name"
            description="Audit, connectors"
            value={draftFilters.connectorName}
            placeholder="benchling"
            onChange={(value) =>
              setDraftFilters((current) => ({ ...current, connectorName: value }))
            }
          />
          <OpsFilterField
            label="Outcome"
            description="Audit only"
            value={draftFilters.outcome}
            placeholder="blocked"
            onChange={(value) =>
              setDraftFilters((current) => ({ ...current, outcome: value }))
            }
          />
        </div>

        <div className="mt-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p className="text-sm text-slate-600">{activeViewDescription}</p>
            <p className="mt-1 text-[12px] text-slate-400">{viewSupportSummary}</p>
          </div>

          <div className="flex flex-wrap gap-2">
            <OpsAction
              onClick={() => {
                const normalizedFilters = normalizeOpsFilters(draftFilters);
                setDraftFilters(normalizedFilters);
                setAppliedFilters(normalizedFilters);
              }}
              tone="accent"
            >
              <Filter size={12} />
              Apply Filters
            </OpsAction>
            <OpsAction
              onClick={() => {
                setDraftFilters({ ...DEFAULT_OPS_FILTERS });
                setAppliedFilters({ ...DEFAULT_OPS_FILTERS });
              }}
              disabled={!canClearFilters}
            >
              <X size={12} />
              Clear Filters
            </OpsAction>
          </div>
        </div>

        {appliedFilterChips.length > 0 ? (
          <div className="mt-4">
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
              Applied Filters
            </p>
            <div className="mt-2">
              <FilterChipRow chips={appliedFilterChips} />
            </div>
          </div>
        ) : null}
      </OpsSectionCard>

      <div className="rounded-[22px] border border-[rgba(210,218,230,0.92)] bg-white/94 p-4 shadow-[0_8px_24px_rgba(19,35,58,0.04)]">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
              Inspection Views
            </p>
            <p className="mt-1 text-sm leading-6 text-slate-500">
              Move between summary, metrics, traces, audit events, connector registry controls, and dashboard definitions without leaving the Ops workspace.
            </p>
          </div>
          <OpsViewTabs activeView={activeView} onSelect={setActiveView} />
        </div>
      </div>

      {activeView === "overview" ? (
        <OverviewView
          status={overviewStatus}
          overview={overview}
          error={overviewError}
          ignoredFilters={ignoredFilterChips}
        />
      ) : null}

      {activeView === "metrics" ? (
        <div className="grid min-h-0 gap-4 xl:grid-cols-[minmax(0,0.88fr)_minmax(0,1.12fr)]">
          <MetricRecordNavigator
            status={metricsStatus}
            metrics={metrics}
            error={metricsError}
            selectedRecordId={selectedMetricRecordId}
            onSelect={(record) => setSelectedMetricRecordId(record.record_id)}
          />
          <MetricDetailPane
            status={metricsStatus}
            record={selectedMetric}
            error={metricsError}
          />
        </div>
      ) : null}

      {activeView === "traces" ? (
        <div className="grid min-h-0 gap-4 xl:grid-cols-[minmax(0,0.88fr)_minmax(0,1.12fr)]">
          <TraceRecordNavigator
            status={tracesStatus}
            traces={traces}
            error={tracesError}
            selectedTraceKey={selectedTraceKey}
            onSelect={(record) => setSelectedTraceKey(`${record.trace_id}:${record.span_id}`)}
          />
          <TraceDetailPane
            status={tracesStatus}
            record={selectedTrace}
            error={tracesError}
          />
        </div>
      ) : null}

      {activeView === "audit" ? (
        <AuditView
          status={auditStatus}
          events={auditEvents}
          error={auditError}
          retentionPolicy={auditRetentionPolicy}
          ignoredFilters={ignoredFilterChips}
          selectedEventId={selectedAuditEventId}
          onSelect={(record) => setSelectedAuditEventId(record.event_id)}
          onLoadMore={() => {
            const nextLimit = String(
              Math.min(currentListLimit + AUDIT_LIMIT_INCREMENT, MAX_OPS_LIST_LIMIT)
            );
            setDraftFilters((current) => ({ ...current, limit: nextLimit }));
            setAppliedFilters((current) => ({ ...current, limit: nextLimit }));
          }}
          canLoadMore={canLoadMoreAuditEvents}
          currentLimit={currentListLimit}
        />
      ) : null}

      {activeView === "connectors" ? (
        <ConnectorsView
          listStatus={connectorsStatus}
          connectors={filteredConnectors}
          listError={connectorsError}
          detailStatus={connectorDetailStatus}
          connector={selectedConnector}
          detailError={connectorDetailError}
          adminConfigStatus={connectorAdminDetailStatus}
          adminConfigError={connectorAdminDetailError}
          adminAccessAllowed={hasAdminAccess}
          adminAccessMessage={accessByScope.admin.detail}
          configLoaded={selectedConnectorConfigLoaded}
          ignoredFilters={ignoredFilterChips}
          selectedConnectorName={selectedConnectorName}
          configDraft={selectedConnectorConfigDraft}
          requestDraft={selectedConnectorRequestDraft}
          pendingActionKey={connectorPendingActionKey}
          latestResult={selectedConnectorLatestResult}
          currentValidationResult={selectedConnectorValidationResult}
          latestReceipt={selectedConnectorReceipt}
          onSelect={(connector) => setSelectedConnectorName(connector.name)}
          onConfigDraftChange={(value) => {
            if (!selectedConnectorName) {
              return;
            }
            setConnectorConfigDrafts((current) => ({
              ...current,
              [selectedConnectorName]: value,
            }));
          }}
          onRequestDraftChange={(value) => {
            if (!selectedConnectorName) {
              return;
            }
            setConnectorRequestDrafts((current) => ({
              ...current,
              [selectedConnectorName]: value,
            }));
          }}
          onResetConfigDraft={() => {
            if (!selectedConnectorName || !selectedConnectorStoredConfig) {
              return;
            }
            setConnectorConfigDrafts((current) => ({
              ...current,
              [selectedConnectorName]: formatJsonValue(selectedConnectorStoredConfig),
            }));
          }}
          onResetRequestDraft={() => {
            if (!selectedConnectorName) {
              return;
            }
            setConnectorRequestDrafts((current) => ({
              ...current,
              [selectedConnectorName]: formatJsonValue(createConnectorRequestDraft()),
            }));
          }}
          onToggleEnabled={handleToggleConnector}
          onSaveConfig={handleSaveConnectorConfig}
          onValidateDraft={handleValidateConnectorDraft}
          onRunAction={handleRunConnectorAction}
        />
      ) : null}

      {activeView === "dashboards" ? (
        <DashboardDefinitionsView
          status={dashboardsStatus}
          dashboards={dashboards}
          error={dashboardsError}
          ignoredFilters={ignoredFilterChips}
        />
      ) : null}

      {overviewStatus === "error" &&
      activeView !== "overview" &&
      activeView !== "audit" &&
      activeView !== "connectors" &&
      overviewError ? (
        <OpsStateCard tone="warning">
          The summary header is currently operating without overview data.
          <div className="mt-2">{overviewError}</div>
        </OpsStateCard>
      ) : null}

      {overview &&
      activeView !== "audit" &&
      activeView !== "connectors" &&
      overview.workflow_delivery.failure_rate.average !== null &&
      overview.workflow_delivery.failure_rate.average > 0 ? (
        <OpsStateCard tone="warning">
          Recent workflow delivery includes failures. Use the Metrics or Traces views with
          request, run, step, or trace filters to drill into the affected execution path.
        </OpsStateCard>
      ) : null}

      {overview &&
      activeView !== "audit" &&
      activeView !== "connectors" &&
      overview.workflow_quality.evidence_coverage_rate.average !== null &&
      overview.workflow_quality.evidence_coverage_rate.average < 0.5 ? (
        <OpsStateCard tone="warning">
          Evidence coverage is currently below 50% in the selected overview window.
          Review the associated workflow and trace records before treating the output as complete.
        </OpsStateCard>
      ) : null}

    </OpsShell>
  );
}
