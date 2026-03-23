"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Activity,
  ArrowRight,
  Clock3,
  Filter,
  Gauge,
  LayoutDashboard,
  MessageSquare,
  RefreshCw,
  Route,
  ShieldCheck,
  X,
  type LucideIcon,
} from "lucide-react";
import {
  listAuditEvents,
  getObservabilityDashboardDefinitions,
  getObservabilityOverview,
  listObservabilityMetrics,
  listObservabilityTraces,
} from "@/lib/api";
import { useApp } from "@/lib/store";
import type {
  AuditEventRecord,
  AuditEventsQuery,
  AuditEventType,
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

type OpsView = "overview" | "metrics" | "traces" | "audit" | "dashboards";
type OpsWorkspaceStatus = "idle" | "loading" | "ready" | "error";

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

function getObservabilityErrorMessage(error: unknown, target: string): string {
  const rawMessage =
    error instanceof Error
      ? error.message.trim()
      : `Could not load ${target} right now.`;
  const message = rawMessage.toLowerCase();

  if (message.includes("environment variable") || message.includes("http 503")) {
    return "Inspection routes are configured, but the inspection bearer token is unavailable on the server.";
  }

  if (
    message.includes("bearer token required") ||
    message.includes("configured bearer token") ||
    message.includes("local access or a configured bearer token") ||
    message.includes("http 401") ||
    message.includes("http 403")
  ) {
    return "Inspection access is required to view Ops data. Use a loopback client or configure an inspection bearer token.";
  }

  const compactMessage = compactText(rawMessage, 160);
  return compactMessage || `Could not load ${target} right now.`;
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
            and dashboard definitions without leaving the production-operations surface.
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
  const { setWorkspaceMode } = useApp();
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

  useEffect(() => {
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
        setOverviewError(getObservabilityErrorMessage(error, "the ops overview"));
      });

    return () => {
      active = false;
    };
  }, [overviewQuery, refreshToken]);

  useEffect(() => {
    if (activeView !== "metrics") {
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
        setMetricsError(getObservabilityErrorMessage(error, "metric records"));
      });

    return () => {
      active = false;
    };
  }, [activeView, metricsQuery, refreshToken]);

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
        setTracesError(getObservabilityErrorMessage(error, "trace records"));
      });

    return () => {
      active = false;
    };
  }, [activeView, refreshToken, tracesQuery]);

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
          getObservabilityErrorMessage(error, "dashboard definitions")
        );
      });

    return () => {
      active = false;
    };
  }, [activeView, refreshToken]);

  useEffect(() => {
    if (activeView !== "audit") {
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
        setAuditError(getObservabilityErrorMessage(error, "audit events"));
      });

    return () => {
      active = false;
    };
  }, [activeView, auditQuery, refreshToken]);

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

  const activeViewDescription = VIEW_CONFIG[activeView].description;
  const activeScopeBadgeLabel =
    activeView === "overview"
      ? `${overviewQuery.days ?? 7} day window`
      : activeView === "dashboards"
        ? "Static definitions"
        : `${formatInteger(currentListLimit)} row limit`;
  const viewSupportSummary =
    activeView === "overview"
      ? "Overview uses the time window plus request, session, and workflow filters."
      : activeView === "audit"
        ? "Audit applies event type, session, run, step, job, workflow, tool, connector, outcome, and list-limit filters."
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

      {activeView !== "audit" ? (
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
        description="Set shared runtime and audit filters, then apply them to the relevant Ops views."
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
            description="Audit only"
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
              Move between summary, metrics, traces, audit events, and dashboard definitions without leaving the Ops workspace.
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
      overviewError ? (
        <OpsStateCard tone="warning">
          The summary header is currently operating without overview data.
          <div className="mt-2">{overviewError}</div>
        </OpsStateCard>
      ) : null}

      {overview &&
      activeView !== "audit" &&
      overview.workflow_delivery.failure_rate.average !== null &&
      overview.workflow_delivery.failure_rate.average > 0 ? (
        <OpsStateCard tone="warning">
          Recent workflow delivery includes failures. Use the Metrics or Traces views with
          request, run, step, or trace filters to drill into the affected execution path.
        </OpsStateCard>
      ) : null}

      {overview &&
      activeView !== "audit" &&
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
