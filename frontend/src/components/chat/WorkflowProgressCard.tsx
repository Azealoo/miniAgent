"use client";

import { useEffect, useState, type ReactNode } from "react";
import {
  ChevronDown,
  ChevronRight,
  CircleCheck,
  CircleDashed,
  CircleX,
  Clock3,
  LoaderCircle,
  Package,
  ShieldAlert,
  Workflow,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  buildWorkflowProgressRuns,
  elapsedWorkflowDuration,
  formatWorkflowDuration,
  type WorkflowArtifactTrace,
  type WorkflowDisplayStepStatus,
  type WorkflowProgressRun,
  type WorkflowProgressStep,
} from "@/lib/workflow-progress";
import type {
  WorkflowArtifactRef,
  WorkflowIssueDetail,
  WorkflowStreamEvent,
} from "@/lib/types";

interface WorkflowProgressCardProps {
  events: WorkflowStreamEvent[];
}

function humanizeValue(value?: string | null): string {
  if (!value) return "unknown";
  return value.replaceAll("_", " ");
}

function stepStatusLabel(status: WorkflowDisplayStepStatus): string {
  return status === "pending" ? "Pending" : humanizeValue(status);
}

function runStatusLabel(run: WorkflowProgressRun): string {
  if (run.lifecycleStatus === "waiting") return "Running";
  if (run.lifecycleStatus === "preflight_checked") return "Running";
  if (run.lifecycleStatus === "created") return "Preparing";
  return humanizeValue(run.lifecycleStatus);
}

function runStatusClass(status: WorkflowProgressRun["lifecycleStatus"]): string {
  if (status === "completed") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  if (status === "blocked" || status === "failed") {
    return "border-rose-200 bg-rose-50 text-rose-700";
  }
  return "border-[rgba(35,130,83,0.16)] bg-[rgba(35,130,83,0.1)] text-[var(--apex-accent-strong)]";
}

function stepStatusClass(status: WorkflowDisplayStepStatus, isCurrent: boolean): string {
  if (status === "completed") {
    return isCurrent
      ? "border-emerald-200 bg-emerald-50/90 text-emerald-800"
      : "border-emerald-100 bg-emerald-50/55 text-emerald-800";
  }
  if (status === "blocked" || status === "failed") {
    return isCurrent
      ? "border-rose-200 bg-rose-50/95 text-rose-800"
      : "border-rose-100 bg-rose-50/70 text-rose-800";
  }
  if (status === "running") {
    return "border-[rgba(35,130,83,0.22)] bg-[linear-gradient(180deg,rgba(242,250,245,0.98),rgba(233,246,238,0.98))] text-slate-800 shadow-[0_8px_20px_rgba(35,130,83,0.08)]";
  }
  return isCurrent
    ? "border-slate-200 bg-slate-50/85 text-slate-700"
    : "border-[rgba(32,43,35,0.06)] bg-white/84 text-slate-500";
}

function StepIcon({ status }: { status: WorkflowDisplayStepStatus }) {
  if (status === "completed") {
    return <CircleCheck size={16} className="text-emerald-600" />;
  }
  if (status === "blocked") {
    return <ShieldAlert size={16} className="text-rose-600" />;
  }
  if (status === "failed") {
    return <CircleX size={16} className="text-rose-600" />;
  }
  if (status === "running") {
    return <LoaderCircle size={16} className="animate-spin text-[var(--apex-accent-strong)]" />;
  }
  return <CircleDashed size={16} className="text-slate-400" />;
}

function selectDisplayRun(runs: WorkflowProgressRun[]): WorkflowProgressRun | null {
  if (runs.length === 0) return null;

  const active = [...runs]
    .reverse()
    .find(
      (run) =>
        run.lifecycleStatus === "running" ||
        run.lifecycleStatus === "waiting" ||
        run.lifecycleStatus === "blocked" ||
        run.lifecycleStatus === "created" ||
        run.lifecycleStatus === "preflight_checked"
    );

  return active ?? runs[runs.length - 1] ?? null;
}

function progressPosition(run: WorkflowProgressRun, totalSteps: number | null): number | null {
  if (!totalSteps || totalSteps <= 0) return null;
  if (run.currentStepPosition) return run.currentStepPosition;
  if (run.lifecycleStatus === "completed") return totalSteps;
  if (run.lifecycleStatus === "blocked") return null;
  if (run.completedSteps > 0) return Math.min(run.completedSteps + 1, totalSteps);
  return 1;
}

function progressFill(run: WorkflowProgressRun, totalSteps: number | null): number {
  if (!totalSteps || totalSteps <= 0) return 0;

  if (run.lifecycleStatus === "completed") {
    return 100;
  }

  const activeBonus =
    run.lifecycleStatus === "running" ||
    run.lifecycleStatus === "waiting" ||
    run.lifecycleStatus === "created" ||
    run.lifecycleStatus === "preflight_checked"
      ? 0.45
      : run.lifecycleStatus === "blocked" && run.currentStepPosition
        ? 0.18
        : 0;

  return Math.min(100, ((run.completedSteps + activeBonus) / totalSteps) * 100);
}

function liveStepDuration(step: WorkflowProgressStep, nowMs: number): string | null {
  const seconds =
    step.status === "running"
      ? elapsedWorkflowDuration(step.startedAt, step.endedAt, nowMs)
      : step.durationSeconds;
  return formatWorkflowDuration(seconds);
}

function formatWorkflowIssueDetail(detail: WorkflowIssueDetail): string {
  const location = detail.field_path ?? "manifest";
  const pathSuffix = detail.path ? ` (${detail.path})` : "";
  return `${location}${pathSuffix}: ${detail.message}`;
}

function formatWorkflowArtifact(artifact: WorkflowArtifactRef): string {
  return `${artifact.artifact_type} - ${artifact.path}`;
}

function formatRunArtifactTrace(trace: WorkflowArtifactTrace): string {
  const outputName = trace.outputName ? ` (${trace.outputName})` : "";
  return `${humanizeValue(trace.scope)}${outputName}: ${formatWorkflowArtifact(trace.artifact)}`;
}

function hasStepDetails(step: WorkflowProgressStep): boolean {
  return (
    step.prerequisiteStepIds.length > 0 ||
    step.artifacts.length > 0 ||
    step.warnings.length > 0 ||
    step.warningDetails.length > 0 ||
    step.errors.length > 0 ||
    step.errorDetails.length > 0
  );
}

function hasRunDetails(run: WorkflowProgressRun, runArtifacts: WorkflowArtifactTrace[]): boolean {
  return (
    Boolean(run.runId) ||
    Boolean(run.runRecordPath) ||
    Boolean(run.blockedStage) ||
    Boolean(run.blockingSource && run.blockingSource !== "unknown") ||
    run.blockedIssueDetails.length > 0 ||
    runArtifacts.length > 0
  );
}

function DetailPanel({
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
        : "border-[rgba(32,43,35,0.08)] bg-white/90 text-slate-700";

  return (
    <div className={cn("rounded-[14px] border px-3 py-2.5", toneClass)}>
      <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
        {label}
      </p>
      {children}
    </div>
  );
}

function WorkflowStepCard({
  step,
  isCurrent,
  nowMs,
}: {
  step: WorkflowProgressStep;
  isCurrent: boolean;
  nowMs: number;
}) {
  const durationLabel = liveStepDuration(step, nowMs);
  const detailCount = Number(hasStepDetails(step));
  const [detailsOpen, setDetailsOpen] = useState(
    () => (step.status === "blocked" || step.status === "failed") && detailCount > 0
  );
  const showDetailsToggle = hasStepDetails(step);

  useEffect(() => {
    if (step.status === "blocked" || step.status === "failed") {
      setDetailsOpen(true);
    }
  }, [step.status]);

  return (
    <div
      className={cn(
        "rounded-[16px] border px-3 py-2.5 transition-colors",
        stepStatusClass(step.status, isCurrent)
      )}
    >
      <div className="flex items-start gap-3">
        <div className="flex w-7 flex-shrink-0 justify-center pt-0.5">
          <span className="text-[11px] font-semibold text-slate-400">
            {step.stepNumber ?? "•"}
          </span>
        </div>

        <div className="pt-0.5">
          <StepIcon status={step.status} />
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={cn(
                "text-sm font-medium",
                isCurrent ? "text-[var(--apex-accent-strong)]" : "text-inherit"
              )}
            >
              {step.stepLabel}
            </span>
            <span className="rounded-full border border-current/10 bg-white/70 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-current">
              {stepStatusLabel(step.status)}
            </span>
            {step.engineName ? (
              <span className="rounded-full border border-[rgba(32,43,35,0.08)] bg-white/70 px-2 py-0.5 text-[10px] uppercase tracking-[0.14em] text-slate-500">
                {step.engineName}
              </span>
            ) : step.executorType ? (
              <span className="rounded-full border border-[rgba(32,43,35,0.08)] bg-white/70 px-2 py-0.5 text-[10px] uppercase tracking-[0.14em] text-slate-500">
                {step.executorType}
              </span>
            ) : null}
          </div>

          {(step.warnings.length > 0 || step.errors.length > 0) && (
            <p className="mt-1 text-[11px] leading-5 text-slate-500">
              {step.errors[0] ?? step.warnings[0]}
            </p>
          )}
        </div>

        <div className="flex flex-col items-end gap-1 pl-2 text-right">
          {durationLabel && (
            <span className="text-[11px] font-medium text-slate-500">
              {durationLabel}
            </span>
          )}
          {isCurrent && (
            <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--apex-accent-strong)]">
              Current
            </span>
          )}
          {showDetailsToggle && (
            <button
              type="button"
              onClick={() => setDetailsOpen((value) => !value)}
              className="inline-flex items-center gap-1 rounded-full border border-[rgba(32,43,35,0.08)] bg-white/82 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500 transition-colors hover:bg-white"
            >
              {detailsOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
              Details
            </button>
          )}
        </div>
      </div>

      {showDetailsToggle && detailsOpen && (
        <div className="mt-3 space-y-2.5 pl-10 sm:pl-[4rem]">
          {step.prerequisiteStepIds.length > 0 && (
            <DetailPanel label="Prerequisites">
              <div className="text-xs text-slate-600">
                after: {step.prerequisiteStepIds.join(", ")}
              </div>
            </DetailPanel>
          )}

          {step.artifacts.length > 0 && (
            <DetailPanel label="Artifacts">
              <div className="space-y-1.5">
                {step.artifacts.map((artifact, index) => (
                  <div key={`${artifact.path}-${index}`} className="flex items-start gap-2">
                    <Package size={12} className="mt-0.5 flex-shrink-0 text-slate-500" />
                    <span className="text-[11px] text-slate-600 break-all">
                      {formatWorkflowArtifact(artifact)}
                    </span>
                  </div>
                ))}
              </div>
            </DetailPanel>
          )}

          {step.warnings.length > 0 && (
            <DetailPanel label="Warnings" tone="warning">
              <pre className="whitespace-pre-wrap break-all text-xs font-mono">
                {step.warnings.join("\n")}
              </pre>
            </DetailPanel>
          )}

          {step.warningDetails.length > 0 && (
            <DetailPanel label="Warning Details" tone="warning">
              <pre className="whitespace-pre-wrap break-all text-xs font-mono">
                {step.warningDetails.map(formatWorkflowIssueDetail).join("\n")}
              </pre>
            </DetailPanel>
          )}

          {step.errors.length > 0 && (
            <DetailPanel label="Errors" tone="error">
              <pre className="whitespace-pre-wrap break-all text-xs font-mono">
                {step.errors.join("\n")}
              </pre>
            </DetailPanel>
          )}

          {step.errorDetails.length > 0 && (
            <DetailPanel label="Error Details" tone="error">
              <pre className="whitespace-pre-wrap break-all text-xs font-mono">
                {step.errorDetails.map(formatWorkflowIssueDetail).join("\n")}
              </pre>
            </DetailPanel>
          )}
        </div>
      )}
    </div>
  );
}

export default function WorkflowProgressCard({ events }: WorkflowProgressCardProps) {
  const runs = buildWorkflowProgressRuns(events);
  const run = selectDisplayRun(runs);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [runDetailsOpen, setRunDetailsOpen] = useState(false);

  const isLive = Boolean(
    run &&
      (run.lifecycleStatus === "running" ||
        run.lifecycleStatus === "waiting" ||
        run.lifecycleStatus === "created" ||
        run.lifecycleStatus === "preflight_checked" ||
        run.steps.some((step) => step.status === "running"))
  );

  useEffect(() => {
    if (!isLive) return undefined;

    const intervalId = window.setInterval(() => {
      setNowMs(Date.now());
    }, 1000);

    return () => window.clearInterval(intervalId);
  }, [isLive]);

  useEffect(() => {
    if (run?.blockedIssueDetails.length) {
      setRunDetailsOpen(true);
    }
  }, [run?.blockedIssueDetails.length]);

  if (!run) return null;

  const totalSteps = run.totalSteps ?? (run.steps.length > 0 ? run.steps.length : null);
  const currentPosition = progressPosition(run, totalSteps);
  const elapsedLabel = formatWorkflowDuration(
    elapsedWorkflowDuration(run.startedAt, run.endedAt, nowMs) ?? run.durationSeconds
  );
  const statusLabel = runStatusLabel(run);
  const detailLabel = run.blockedReason
    ? run.blockedReason
    : run.currentStepLabel
      ? `Current step: ${run.currentStepLabel}`
      : run.lifecycleStatus === "completed"
        ? "Run completed successfully."
        : run.lifecycleStatus === "failed"
          ? "Run stopped before all planned steps completed."
          : "Preparing workflow execution.";
  const runArtifacts = run.artifacts.filter((artifact) => !artifact.stepId);
  const showRunDetails = hasRunDetails(run, runArtifacts);

  return (
    <section className="overflow-hidden rounded-[20px] border border-[rgba(32,43,35,0.08)] bg-[linear-gradient(180deg,rgba(253,254,252,0.98),rgba(245,249,244,0.98))] shadow-[0_12px_28px_rgba(32,43,35,0.05)]">
      <div className="border-b border-[rgba(32,43,35,0.06)] px-4 py-4 sm:px-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.2em] text-[var(--apex-accent-strong)]">
                <Workflow size={14} />
                Workflow Progress
              </span>
              <span
                className={cn(
                  "rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em]",
                  runStatusClass(run.lifecycleStatus)
                )}
              >
                {statusLabel}
              </span>
              {run.resumed && (
                <span className="rounded-full border border-slate-200 bg-white/85 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                  Resumed
                </span>
              )}
            </div>

            <h3 className="mt-3 text-[1rem] font-semibold tracking-[-0.01em] text-slate-800">
              {run.workflowName}
            </h3>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
              {detailLabel}
            </p>

            <div className="mt-3 flex flex-wrap items-center gap-2.5 text-[11px] text-slate-500">
              {currentPosition && totalSteps ? (
                <span className="rounded-full border border-[rgba(32,43,35,0.08)] bg-white/82 px-2.5 py-1">
                  Step {currentPosition} of {totalSteps}
                </span>
              ) : totalSteps ? (
                <span className="rounded-full border border-[rgba(32,43,35,0.08)] bg-white/82 px-2.5 py-1">
                  {totalSteps} planned steps
                </span>
              ) : null}
              <span className="rounded-full border border-[rgba(32,43,35,0.08)] bg-white/82 px-2.5 py-1">
                {run.completedSteps} completed
              </span>
              {elapsedLabel && (
                <span className="inline-flex items-center gap-1.5 rounded-full border border-[rgba(32,43,35,0.08)] bg-white/82 px-2.5 py-1">
                  <Clock3 size={12} className="text-slate-400" />
                  Elapsed {elapsedLabel}
                </span>
              )}
            </div>
          </div>

          <div className="flex min-w-[8rem] flex-shrink-0 flex-col items-end rounded-[18px] border border-[rgba(35,130,83,0.12)] bg-[linear-gradient(180deg,rgba(255,255,255,0.92),rgba(242,248,243,0.98))] px-3.5 py-3 shadow-[0_10px_24px_rgba(32,43,35,0.04)]">
            <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
              Active Run
            </span>
            <span className="mt-1 text-[1.65rem] font-semibold tracking-[-0.03em] text-slate-800">
              {totalSteps ? `${run.completedSteps}/${totalSteps}` : run.completedSteps}
            </span>
            <span className="text-[11px] text-slate-500">
              {totalSteps ? "steps complete" : "completed"}
            </span>
          </div>
        </div>

        {totalSteps && totalSteps > 0 && (
          <div className="mt-4">
            <div className="h-2 rounded-full bg-[rgba(32,43,35,0.08)]">
              <div
                className="h-full rounded-full bg-[linear-gradient(90deg,var(--apex-accent),rgba(35,130,83,0.55))] transition-[width] duration-300"
                style={{ width: `${progressFill(run, totalSteps)}%` }}
              />
            </div>
          </div>
        )}
      </div>

      <div className="space-y-3 px-3 py-3 sm:px-4">
        <div className="space-y-2">
          {run.steps.map((step) => (
            <WorkflowStepCard
              key={step.stepId}
              step={step}
              isCurrent={step.stepId === run.currentStepId}
              nowMs={nowMs}
            />
          ))}
        </div>

        {showRunDetails && (
          <div className="overflow-hidden rounded-[16px] border border-[rgba(32,43,35,0.08)] bg-white/82">
            <button
              type="button"
              onClick={() => setRunDetailsOpen((value) => !value)}
              className="flex w-full items-center gap-2 border-b border-[rgba(32,43,35,0.06)] bg-[rgba(248,250,247,0.92)] px-3 py-2.5 text-left transition-colors hover:bg-[rgba(244,247,243,0.96)]"
            >
              {runDetailsOpen ? (
                <ChevronDown size={14} className="text-slate-400" />
              ) : (
                <ChevronRight size={14} className="text-slate-400" />
              )}
              <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-600">
                Workflow Details
              </span>
            </button>

            {runDetailsOpen && (
              <div className="space-y-2.5 px-3 pb-3 pt-2.5">
                <DetailPanel label="Run">
                  <div className="space-y-1 text-xs">
                    <div>
                      <span className="text-slate-400">Run ID:</span>{" "}
                      <span className="font-mono break-all text-slate-700">{run.runId}</span>
                    </div>
                    {run.runRecordPath && (
                      <div>
                        <span className="text-slate-400">Run record:</span>{" "}
                        <span className="font-mono break-all text-slate-700">
                          {run.runRecordPath}
                        </span>
                      </div>
                    )}
                    {run.blockedStage && (
                      <div>
                        <span className="text-slate-400">Blocked stage:</span>{" "}
                        {humanizeValue(run.blockedStage)}
                      </div>
                    )}
                    {run.blockingSource && run.blockingSource !== "unknown" && (
                      <div>
                        <span className="text-slate-400">Blocking source:</span>{" "}
                        {humanizeValue(run.blockingSource)}
                      </div>
                    )}
                  </div>
                </DetailPanel>

                {run.blockedIssueDetails.length > 0 && (
                  <DetailPanel label="Blocked Issue Details" tone="error">
                    <pre className="whitespace-pre-wrap break-all text-xs font-mono">
                      {run.blockedIssueDetails.map(formatWorkflowIssueDetail).join("\n")}
                    </pre>
                  </DetailPanel>
                )}

                {runArtifacts.length > 0 && (
                  <DetailPanel label="Run Artifacts">
                    <div className="space-y-1.5">
                      {runArtifacts.map((artifactTrace, index) => (
                        <div
                          key={`${artifactTrace.artifact.path}-${artifactTrace.scope}-${index}`}
                          className="flex items-start gap-2"
                        >
                          <Package size={12} className="mt-0.5 flex-shrink-0 text-slate-500" />
                          <span className="text-[11px] text-slate-600 break-all">
                            {formatRunArtifactTrace(artifactTrace)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </DetailPanel>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
