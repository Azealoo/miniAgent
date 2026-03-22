import type {
  WorkflowArtifactEvent,
  WorkflowArtifactRef,
  WorkflowIssueDetail,
  WorkflowLifecycleStatus,
  WorkflowStepDescriptor,
  WorkflowStreamEvent,
} from "./types";

export type WorkflowDisplayStepStatus =
  | "pending"
  | "running"
  | "completed"
  | "blocked"
  | "failed";

export interface WorkflowArtifactTrace {
  artifact: WorkflowArtifactRef;
  scope: WorkflowArtifactEvent["scope"];
  stepId?: string | null;
  outputName?: string | null;
}

export interface WorkflowProgressStep {
  stepId: string;
  stepLabel: string;
  stepNumber: number | null;
  status: WorkflowDisplayStepStatus;
  rawStatus: string;
  executorType?: string;
  engineName?: string | null;
  prerequisiteStepIds: string[];
  artifacts: WorkflowArtifactRef[];
  warnings: string[];
  warningDetails: WorkflowIssueDetail[];
  errors: string[];
  errorDetails: WorkflowIssueDetail[];
  startedAt: string | null;
  endedAt: string | null;
  durationSeconds: number | null;
}

export interface WorkflowProgressRun {
  runId: string;
  workflowId: string;
  workflowName: string;
  lifecycleStatus: WorkflowLifecycleStatus;
  resumed: boolean;
  runRecordPath?: string;
  blockedReason?: string;
  blockedIssueDetails: WorkflowIssueDetail[];
  blockedStage?: string;
  blockingSource?: string;
  completedSteps: number;
  totalSteps: number | null;
  warningCount?: number;
  currentStepId: string | null;
  currentStepLabel: string | null;
  currentStepPosition: number | null;
  startedAt: string | null;
  endedAt: string | null;
  durationSeconds: number | null;
  steps: WorkflowProgressStep[];
  artifacts: WorkflowArtifactTrace[];
}

interface MutableWorkflowProgressRun extends Omit<WorkflowProgressRun, "steps"> {
  steps: WorkflowProgressStep[];
}

function parseTimestamp(value?: string | null): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

function secondsBetween(start?: string | null, end?: string | null): number | null {
  const startedMs = parseTimestamp(start);
  const endedMs = parseTimestamp(end);
  if (startedMs === null || endedMs === null) return null;
  return Math.max(0, (endedMs - startedMs) / 1000);
}

function normalizeStepStatus(status?: string | null): WorkflowDisplayStepStatus {
  if (status === "running" || status === "waiting") return "running";
  if (status === "completed") return "completed";
  if (status === "blocked") return "blocked";
  if (status === "failed") return "failed";
  return "pending";
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

function ensureRun(
  runs: Map<string, MutableWorkflowProgressRun>,
  stepMaps: Map<string, Map<string, WorkflowProgressStep>>,
  stepOrders: Map<string, string[]>,
  order: string[],
  event: WorkflowStreamEvent
): MutableWorkflowProgressRun {
  const existing = runs.get(event.run_id);
  if (existing) return existing;

  const created: MutableWorkflowProgressRun = {
    runId: event.run_id,
    workflowId: event.workflow_id,
    workflowName: event.workflow_id,
    lifecycleStatus: "created",
    resumed: false,
    blockedIssueDetails: [],
    completedSteps: 0,
    totalSteps: null,
    currentStepId: null,
    currentStepLabel: null,
    currentStepPosition: null,
    startedAt: null,
    endedAt: null,
    durationSeconds: null,
    steps: [],
    artifacts: [],
  };
  runs.set(event.run_id, created);
  stepMaps.set(event.run_id, new Map());
  stepOrders.set(event.run_id, []);
  order.push(event.run_id);
  return created;
}

function ensureStep(
  run: MutableWorkflowProgressRun,
  stepMaps: Map<string, Map<string, WorkflowProgressStep>>,
  stepOrders: Map<string, string[]>,
  stepId: string,
  stepLabel: string
): WorkflowProgressStep {
  const runSteps = stepMaps.get(run.runId) ?? new Map<string, WorkflowProgressStep>();
  stepMaps.set(run.runId, runSteps);

  const existing = runSteps.get(stepId);
  if (existing) {
    existing.stepLabel = stepLabel;
    return existing;
  }

  const created: WorkflowProgressStep = {
    stepId,
    stepLabel,
    stepNumber: null,
    status: "pending",
    rawStatus: "created",
    prerequisiteStepIds: [],
    artifacts: [],
    warnings: [],
    warningDetails: [],
    errors: [],
    errorDetails: [],
    startedAt: null,
    endedAt: null,
    durationSeconds: null,
  };
  runSteps.set(stepId, created);

  const order = stepOrders.get(run.runId) ?? [];
  if (!order.includes(stepId)) {
    order.push(stepId);
  }
  stepOrders.set(run.runId, order);

  return created;
}

function seedOrderedSteps(
  run: MutableWorkflowProgressRun,
  stepMaps: Map<string, Map<string, WorkflowProgressStep>>,
  stepOrders: Map<string, string[]>,
  steps: WorkflowStepDescriptor[]
): void {
  if (steps.length === 0) return;

  const orderedIds: string[] = [];
  for (const [index, descriptor] of steps.entries()) {
    const step = ensureStep(run, stepMaps, stepOrders, descriptor.step_id, descriptor.step_label);
    step.stepNumber = index + 1;
    step.executorType = descriptor.executor_type;
    step.engineName = descriptor.engine_name ?? null;
    step.prerequisiteStepIds = descriptor.prerequisite_step_ids ?? [];
    if (descriptor.status) {
      step.rawStatus = descriptor.status;
      step.status = normalizeStepStatus(descriptor.status);
    }
    step.startedAt = descriptor.started_at ?? step.startedAt;
    step.endedAt = descriptor.ended_at ?? step.endedAt;
    step.durationSeconds =
      descriptor.duration_seconds ??
      step.durationSeconds ??
      secondsBetween(step.startedAt, step.endedAt);
    step.warnings = Array.from(new Set([...step.warnings, ...(descriptor.warnings ?? [])]));
    step.warningDetails = pushUniqueIssueDetails(
      step.warningDetails,
      descriptor.warning_details ?? []
    );
    step.errors = Array.from(new Set([...step.errors, ...(descriptor.errors ?? [])]));
    step.errorDetails = pushUniqueIssueDetails(step.errorDetails, descriptor.error_details ?? []);
    for (const artifact of descriptor.artifact_refs ?? []) {
      step.artifacts = pushUniqueArtifact(step.artifacts, artifact);
    }
    orderedIds.push(descriptor.step_id);
  }

  const existingOrder = stepOrders.get(run.runId) ?? [];
  for (const stepId of existingOrder) {
    if (!orderedIds.includes(stepId)) {
      orderedIds.push(stepId);
    }
  }
  stepOrders.set(run.runId, orderedIds);
}

export function buildWorkflowProgressRuns(
  events: WorkflowStreamEvent[]
): WorkflowProgressRun[] {
  const runs = new Map<string, MutableWorkflowProgressRun>();
  const stepMaps = new Map<string, Map<string, WorkflowProgressStep>>();
  const stepOrders = new Map<string, string[]>();
  const order: string[] = [];

  for (const event of events) {
    const run = ensureRun(runs, stepMaps, stepOrders, order, event);

    switch (event.type) {
      case "workflow_start":
        run.workflowName = event.workflow_name;
        run.lifecycleStatus = event.lifecycle_status;
        run.resumed = event.resumed;
        run.runRecordPath = event.run_record_path;
        run.totalSteps =
          typeof event.total_steps === "number" ? event.total_steps : run.totalSteps;
        run.startedAt = event.started_at ?? run.startedAt;
        seedOrderedSteps(run, stepMaps, stepOrders, event.steps ?? []);
        break;

      case "workflow_step_start": {
        const step = ensureStep(run, stepMaps, stepOrders, event.step_id, event.step_label);
        step.status = "running";
        step.rawStatus = event.status;
        step.executorType = event.executor_type;
        step.engineName = event.engine_name ?? null;
        step.prerequisiteStepIds = event.prerequisite_step_ids;
        step.startedAt = event.started_at ?? step.startedAt;
        run.startedAt = run.startedAt ?? step.startedAt;
        run.lifecycleStatus = "running";
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
          const step = ensureStep(run, stepMaps, stepOrders, event.step_id, event.step_label);
          step.artifacts = pushUniqueArtifact(step.artifacts, event.artifact);
        }
        break;
      }

      case "workflow_step_end": {
        const step = ensureStep(run, stepMaps, stepOrders, event.step_id, event.step_label);
        step.rawStatus = event.status;
        step.status = normalizeStepStatus(event.status);
        step.startedAt = event.started_at ?? step.startedAt;
        step.endedAt = event.ended_at ?? step.endedAt;
        step.durationSeconds =
          event.duration_seconds ?? secondsBetween(step.startedAt, step.endedAt);
        run.startedAt = run.startedAt ?? step.startedAt;
        step.warnings = Array.from(new Set([...step.warnings, ...event.warnings]));
        step.warningDetails = pushUniqueIssueDetails(step.warningDetails, event.warning_details);
        step.errors = Array.from(new Set([...step.errors, ...event.errors]));
        step.errorDetails = pushUniqueIssueDetails(step.errorDetails, event.error_details);
        for (const artifact of event.artifact_refs) {
          step.artifacts = pushUniqueArtifact(step.artifacts, artifact);
        }
        if (event.status === "waiting") {
          run.lifecycleStatus = "waiting";
        } else if (event.status === "failed") {
          run.lifecycleStatus = "failed";
        } else if (event.status === "blocked") {
          run.lifecycleStatus = "blocked";
        }
        break;
      }

      case "workflow_blocked":
        run.lifecycleStatus = "blocked";
        run.blockedReason = event.reason;
        run.blockedIssueDetails = pushUniqueIssueDetails(
          run.blockedIssueDetails,
          event.issue_details
        );
        run.blockedStage = event.stage;
        run.blockingSource = event.blocking_source;
        if (event.step_id && event.step_label) {
          const step = ensureStep(run, stepMaps, stepOrders, event.step_id, event.step_label);
          step.status = "blocked";
          step.rawStatus = "blocked";
          step.errorDetails = pushUniqueIssueDetails(step.errorDetails, event.issue_details);
          if (!step.errors.includes(event.reason)) {
            step.errors = [...step.errors, event.reason];
          }
        }
        break;

      case "workflow_done":
        run.lifecycleStatus = event.lifecycle_status;
        run.runRecordPath = event.run_record_path;
        run.completedSteps = event.completed_steps;
        run.totalSteps = event.total_steps;
        run.warningCount = event.warning_count;
        run.startedAt = event.started_at ?? run.startedAt;
        run.endedAt = event.ended_at ?? run.endedAt;
        run.durationSeconds =
          event.duration_seconds ?? secondsBetween(run.startedAt, run.endedAt);
        if (event.blocked_reason) {
          run.blockedReason = event.blocked_reason;
        }
        run.blockedIssueDetails = pushUniqueIssueDetails(
          run.blockedIssueDetails,
          event.blocked_issue_details ?? []
        );
        break;
    }
  }

  return order
    .map((runId) => {
      const run = runs.get(runId);
      if (!run) return null;

      const runStepMap = stepMaps.get(runId) ?? new Map<string, WorkflowProgressStep>();
      const orderedStepIds = stepOrders.get(runId) ?? [];
      const orderedSteps = orderedStepIds
        .map((stepId) => runStepMap.get(stepId))
        .filter(Boolean) as WorkflowProgressStep[];

      orderedSteps.forEach((step, index) => {
        if (step.stepNumber === null) {
          step.stepNumber = index + 1;
        }
        if (step.durationSeconds === null) {
          step.durationSeconds = secondsBetween(step.startedAt, step.endedAt);
        }
      });

      const observedCompletedSteps = orderedSteps.filter(
        (step) => step.status === "completed"
      ).length;
      if (run.completedSteps === 0 && observedCompletedSteps > 0) {
        run.completedSteps = observedCompletedSteps;
      }
      if (run.totalSteps === null && orderedSteps.length > 0) {
        run.totalSteps = orderedSteps.length;
      }
      if (run.durationSeconds === null) {
        run.durationSeconds = secondsBetween(run.startedAt, run.endedAt);
      }

      const runningStep = [...orderedSteps].reverse().find((step) => step.status === "running");
      const blockedStep = [...orderedSteps].reverse().find((step) => step.status === "blocked");
      const pendingStep = orderedSteps.find((step) => step.status === "pending");

      const currentStep =
        runningStep ??
        (run.lifecycleStatus === "blocked" ? blockedStep ?? null : null) ??
        (run.lifecycleStatus === "completed" ||
        run.lifecycleStatus === "failed" ||
        run.lifecycleStatus === "blocked"
          ? null
          : pendingStep ?? null);

      run.currentStepId = currentStep?.stepId ?? null;
      run.currentStepLabel = currentStep?.stepLabel ?? null;
      run.currentStepPosition = currentStep?.stepNumber ?? null;
      run.steps = orderedSteps;

      return run;
    })
    .filter(Boolean) as WorkflowProgressRun[];
}

export function formatWorkflowDuration(seconds?: number | null): string | null {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) {
    return null;
  }

  if (seconds < 10) {
    return `${seconds.toFixed(1)}s`;
  }
  if (seconds < 60) {
    return `${Math.round(seconds)}s`;
  }

  const roundedSeconds = Math.round(seconds);
  const hours = Math.floor(roundedSeconds / 3600);
  const minutes = Math.floor((roundedSeconds % 3600) / 60);
  const remainingSeconds = roundedSeconds % 60;

  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }
  if (minutes > 0) {
    return `${minutes}m ${remainingSeconds}s`;
  }
  return `${remainingSeconds}s`;
}

export function elapsedWorkflowDuration(
  startedAt?: string | null,
  endedAt?: string | null,
  nowMs: number = Date.now()
): number | null {
  const startedMs = parseTimestamp(startedAt);
  if (startedMs === null) return null;
  const endedMs = parseTimestamp(endedAt);
  const effectiveEnd = endedMs ?? nowMs;
  return Math.max(0, (effectiveEnd - startedMs) / 1000);
}
