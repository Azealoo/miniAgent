"use client";

import { ShieldAlert } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  humanizeComplianceValue,
  summarizeComplianceReport,
  type ComplianceSurfaceState,
} from "@/lib/compliance";
import type { ComplianceReportArtifact } from "@/lib/types";

interface ComplianceSummaryCardProps {
  report: ComplianceReportArtifact | null;
  auditLogPath?: string | null;
  title?: string;
  emptyMessage?: string | null;
  compact?: boolean;
  className?: string;
  showPlaceholderAction?: boolean;
  maxRules?: number;
}

function surfaceClass(state: ComplianceSurfaceState): string {
  if (state === "blocked") {
    return "border-rose-200 bg-[linear-gradient(180deg,rgba(255,247,247,0.98),rgba(254,241,241,0.98))] text-rose-950";
  }

  if (state === "approval_required" || state === "warning") {
    return "border-amber-200 bg-[linear-gradient(180deg,rgba(255,251,235,0.98),rgba(254,243,199,0.68))] text-amber-950";
  }

  if (state === "approved") {
    return "border-sky-200 bg-[linear-gradient(180deg,rgba(245,250,255,0.98),rgba(235,245,255,0.98))] text-sky-950";
  }

  if (state === "ready") {
    return "border-[rgba(35,130,83,0.16)] bg-[linear-gradient(180deg,rgba(248,251,248,0.98),rgba(242,247,243,0.98))] text-emerald-950";
  }

  return "border-[rgba(211,219,210,0.86)] bg-[linear-gradient(180deg,rgba(252,252,251,0.98),rgba(247,249,246,0.98))] text-slate-900";
}

function badgeClass(state: ComplianceSurfaceState): string {
  if (state === "blocked") {
    return "border-rose-200 bg-rose-50 text-rose-700";
  }

  if (state === "approval_required" || state === "warning") {
    return "border-amber-200 bg-amber-50 text-amber-700";
  }

  if (state === "approved") {
    return "border-sky-200 bg-sky-50 text-sky-700";
  }

  if (state === "ready") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }

  return "border-[rgba(211,219,210,0.86)] bg-white/80 text-slate-500";
}

function DetailCell({
  label,
  value,
  monospace = false,
}: {
  label: string;
  value: string | null;
  monospace?: boolean;
}) {
  return (
    <div className="rounded-[12px] border border-white/70 bg-white/70 px-2.5 py-2">
      <p className="text-[9px] font-semibold uppercase tracking-[0.14em] text-slate-400">
        {label}
      </p>
      <p
        className={cn(
          "mt-1 text-[11px] leading-5 text-slate-700",
          monospace && "font-mono break-all"
        )}
      >
        {value ?? "Not recorded"}
      </p>
    </div>
  );
}

export default function ComplianceSummaryCard({
  report,
  auditLogPath,
  title = "Compliance",
  emptyMessage = null,
  compact = false,
  className,
  showPlaceholderAction = true,
  maxRules,
}: ComplianceSummaryCardProps) {
  if (!report) {
    if (!emptyMessage) {
      return null;
    }

    return (
      <section
        className={cn(
          "rounded-[16px] border border-[rgba(211,219,210,0.86)] bg-[linear-gradient(180deg,rgba(252,252,251,0.98),rgba(247,249,246,0.98))] px-3 py-3",
          className
        )}
      >
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
          {title}
        </p>
        <p className="mt-1 text-[11px] leading-5 text-slate-500">{emptyMessage}</p>
      </section>
    );
  }

  const summary = summarizeComplianceReport(report);
  const visibleRules = report.triggered_rules.slice(
    0,
    maxRules ?? (compact ? 2 : 4)
  );
  const remainingRuleCount = report.triggered_rules.length - visibleRules.length;

  return (
    <section
      className={cn(
        "rounded-[16px] border px-3 py-3 shadow-[0_1px_2px_rgba(32,43,35,0.03)]",
        surfaceClass(summary.state),
        className
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="inline-flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">
            <ShieldAlert size={12} />
            {title}
          </p>
          <h3
            className={cn(
              "mt-2 font-semibold tracking-[-0.01em] text-slate-800",
              compact ? "text-[0.96rem]" : "text-[1rem]"
            )}
          >
            {summary.label}
          </h3>
          <p className="mt-1 text-[11px] leading-5 text-slate-600">{summary.detail}</p>
        </div>

        <span
          className={cn(
            "inline-flex shrink-0 items-center rounded-full border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.14em]",
            badgeClass(summary.state)
          )}
        >
          {summary.finalDispositionLabel ?? summary.label}
        </span>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2">
        <DetailCell label="Risk" value={summary.riskLabel} />
        <DetailCell label="Approval" value={summary.approvalLabel} />
        <DetailCell label="Runtime" value={summary.runtimeLabel} />
        <DetailCell label="Preflight" value={summary.preflightLabel} />
      </div>

      {visibleRules.length > 0 ? (
        <div className="mt-3">
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
            Triggered Rules
          </p>
          <div className="mt-2 space-y-2">
            {visibleRules.map((rule) => (
              <div
                key={`${rule.rule_id}-${rule.trigger_text}`}
                className="rounded-[12px] border border-white/70 bg-white/72 px-2.5 py-2"
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="text-[11px] font-semibold text-slate-700">{rule.rule_id}</p>
                  <span className="rounded-full border border-[rgba(32,43,35,0.08)] bg-white/85 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.12em] text-slate-500">
                    {humanizeComplianceValue(rule.recommended_action) ?? "recorded"}
                  </span>
                </div>
                <p className="mt-1 text-[10px] leading-4 text-slate-500">
                  {(humanizeComplianceValue(rule.category) ?? "unknown category")
                    .replace(/^./, (value) => value.toUpperCase())}
                  {" - "}
                  {(humanizeComplianceValue(rule.severity) ?? "unknown severity")
                    .replace(/^./, (value) => value.toUpperCase())}
                </p>
                <p className="mt-1 text-[11px] leading-5 text-slate-700">
                  Matched &quot;{rule.trigger_text}&quot;
                </p>
              </div>
            ))}

            {remainingRuleCount > 0 ? (
              <p className="text-[10px] leading-4 text-slate-500">
                + {remainingRuleCount} more triggered {remainingRuleCount === 1 ? "rule" : "rules"} recorded in the full report.
              </p>
            ) : null}
          </div>
        </div>
      ) : null}

      {showPlaceholderAction && summary.actionLabel && summary.actionDetail ? (
        <div className="mt-3 rounded-[12px] border border-dashed border-current/15 bg-white/58 px-2.5 py-2.5">
          <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
            {summary.actionLabel}
          </p>
          <p className="mt-1 text-[11px] leading-5 text-slate-600">
            {summary.actionDetail}
          </p>
        </div>
      ) : null}

      {(report.approval?.rationale || auditLogPath) && !compact ? (
        <div className="mt-3 space-y-2">
          {report.approval?.rationale ? (
            <DetailCell label="Approval rationale" value={report.approval.rationale} />
          ) : null}
          {auditLogPath ? (
            <DetailCell label="Audit log" value={auditLogPath} monospace />
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
