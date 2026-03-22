"use client";

import { useEffect, useState } from "react";
import {
  CircleCheck,
  CircleDashed,
  CircleX,
  Clock3,
  LoaderCircle,
  ShieldAlert,
  Workflow,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  buildWorkflowProgressRuns,
  elapsedWorkflowDuration,
  formatWorkflowDuration,
  type WorkflowDisplayStepStatus,
  type WorkflowProgressRun,
  type WorkflowProgressStep,
} from "@/lib/workflow-progress";
import type { WorkflowStreamEvent } from "@/lib/types";

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

export default function WorkflowProgressCard({ events }: WorkflowProgressCardProps) {
  const runs = buildWorkflowProgressRuns(events);
  const run = selectDisplayRun(runs);
  const isLive = Boolean(
    run &&
      (run.lifecycleStatus === "running" ||
        run.lifecycleStatus === "waiting" ||
        run.lifecycleStatus === "created" ||
        run.lifecycleStatus === "preflight_checked" ||
        run.steps.some((step) => step.status === "running"))
  );
  const [nowMs, setNowMs] = useState(() => Date.now());

  useEffect(() => {
    if (!isLive) return undefined;

    const intervalId = window.setInterval(() => {
      setNowMs(Date.now());
    }, 1000);

    return () => window.clearInterval(intervalId);
  }, [isLive]);

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

      <div className="px-3 py-3 sm:px-4">
        <div className="space-y-2">
          {run.steps.map((step) => {
            const isCurrent = step.stepId === run.currentStepId;
            const durationLabel = liveStepDuration(step, nowMs);

            return (
              <div
                key={step.stepId}
                className={cn(
                  "flex items-start gap-3 rounded-[16px] border px-3 py-2.5 transition-colors",
                  stepStatusClass(step.status, isCurrent)
                )}
              >
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
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
