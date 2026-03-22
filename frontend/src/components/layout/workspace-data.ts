"use client";

import {
  BookOpen,
  Files,
  FlaskConical,
  MessageSquare,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";
import {
  getWorkflowSummary,
  type WorkflowSummary,
} from "@/lib/session-status";
import type { Message, WorkspaceMode } from "@/lib/types";

export interface WorkspaceNavItem {
  id: WorkspaceMode;
  label: string;
  icon: LucideIcon;
}

export interface QuickStartItem {
  id: string;
  label: string;
  description: string;
  kind: string;
  icon: LucideIcon;
  workflowId?: string | null;
  draftMessage: string;
}

export interface SurfaceItem {
  id: string;
  label: string;
  description: string;
  meta?: string;
  icon: LucideIcon;
  path?: string;
}

export const primaryNavItems: WorkspaceNavItem[] = [
  { id: "sessions", label: "Sessions", icon: MessageSquare },
  { id: "flows", label: "Flows", icon: FlaskConical },
  { id: "docs", label: "Docs", icon: BookOpen },
  { id: "files", label: "Files", icon: Files },
];

export const quickStartItems: QuickStartItem[] = [
  {
    id: "rnaseq-de",
    label: "RNA-seq DE",
    description: "Prime the RNA-seq differential expression workflow.",
    kind: "Workflow",
    icon: FlaskConical,
    workflowId: "rnaseq_qc_de",
    draftMessage:
      "Run the RNA-seq differential expression workflow on the attached dataset manifest with condition_field=condition baseline_condition=control comparison_condition=treated. Use the standard QC and report outputs unless I provide different parameters.",
  },
  {
    id: "evidence-review",
    label: "Evidence Review",
    description: "Draft a source-grounded evidence review request.",
    kind: "Review",
    icon: BookOpen,
    draftMessage:
      "Review the evidence for this biology question, separate source facts from conclusions, and cite the strongest supporting artifacts.",
  },
  {
    id: "compliance",
    label: "Compliance",
    description: "Prepare a compliance and readiness check request.",
    kind: "Safety",
    icon: ShieldCheck,
    draftMessage:
      "Run a compliance and readiness check on this request, summarize any warnings or approvals required, and note what information is missing.",
  },
];

export const workspaceDocs: SurfaceItem[] = [
  {
    id: "current-feature",
    label: "Current Feature",
    description: "Active implementation contract for this pass.",
    meta: "context/current-feature.md",
    icon: BookOpen,
    path: "context/current-feature.md",
  },
  {
    id: "project-overview",
    label: "Project Overview",
    description: "Mission, architecture, and product direction.",
    meta: "context/project-overview.md",
    icon: BookOpen,
    path: "context/project-overview.md",
  },
  {
    id: "coding-standards",
    label: "Coding Standards",
    description: "Frontend and backend implementation guardrails.",
    meta: "context/coding-standards.md",
    icon: BookOpen,
    path: "context/coding-standards.md",
  },
  {
    id: "ai-interaction",
    label: "AI Interaction",
    description: "Feature workflow and review expectations.",
    meta: "context/ai-interaction.md",
    icon: BookOpen,
    path: "context/ai-interaction.md",
  },
];

export function formatWorkflowLabel(value: string): string {
  return value.replaceAll("_", " ").replaceAll("-", " ");
}

function humanizeToken(value?: string | null): string | null {
  if (!value) return null;
  return value.replaceAll("_", " ").replaceAll("-", " ");
}

function shortenPath(path: string): string {
  const segments = path.split("/").filter(Boolean);
  if (segments.length <= 2) return path;
  return segments.slice(-2).join("/");
}

export function matchesQuery(
  query: string,
  ...parts: Array<string | null | undefined>
): boolean {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) return true;
  return parts.some((part) => part?.toLowerCase().includes(normalizedQuery));
}

export function summarizeWorkflowMeta(summary: WorkflowSummary): string {
  if (summary.status === "running" || summary.status === "not_started") {
    if (summary.totalSteps !== null) {
      return `${summary.completedSteps}/${summary.totalSteps} steps`;
    }
    if (summary.observedSteps > 0) {
      return `${summary.completedSteps}/${summary.observedSteps} observed`;
    }
    return summary.status === "not_started" ? "Not started" : "Running";
  }

  if (summary.status === "blocked") return "Blocked";
  if (summary.status === "failed") return "Failed";
  if (summary.status === "completed") {
    if (summary.totalSteps !== null) {
      return `${summary.completedSteps}/${summary.totalSteps} steps`;
    }
    return "Completed";
  }

  return "Idle";
}

export function describeWorkflow(summary: WorkflowSummary): string {
  if (summary.status === "blocked") {
    return summary.blockedReason ?? "Workflow execution is blocked.";
  }

  if (summary.status === "failed") {
    return summary.failureReason ?? "Latest workflow run failed.";
  }

  if (summary.status === "not_started") {
    return summary.totalSteps !== null
      ? `Workflow run is ready to begin with ${summary.totalSteps} step${summary.totalSteps === 1 ? "" : "s"}.`
      : "Workflow run is ready to begin.";
  }

  if (summary.status === "running") {
    if (summary.currentStep) {
      return `${summary.currentStep} is running now.`;
    }
    return "Workflow execution is in progress.";
  }

  if (summary.status === "completed") {
    return "Latest workflow run completed successfully.";
  }

  return "No workflow run has started yet.";
}

export function getWorkflowSurfaceItems(
  messages: Message[],
  selectedWorkflow: string | null,
  selectionPending: boolean
): SurfaceItem[] {
  const summary = getWorkflowSummary(messages);
  const items: SurfaceItem[] = [];

  if (selectedWorkflow) {
    items.push({
      id: `selected-${selectedWorkflow}`,
      label:
        !selectionPending &&
        summary.workflowId === selectedWorkflow &&
        summary.workflowName
          ? summary.workflowName
          : formatWorkflowLabel(selectedWorkflow),
      description:
        !selectionPending &&
        summary.workflowId === selectedWorkflow &&
        summary.status !== "idle"
          ? describeWorkflow(summary)
          : "Selected and ready for the next request.",
      meta:
        !selectionPending && summary.workflowId === selectedWorkflow
          ? summarizeWorkflowMeta(summary)
          : "Selected",
      icon: FlaskConical,
    });
  }

  if (summary.workflowId && summary.workflowId !== selectedWorkflow) {
    items.push({
      id: `recent-${summary.workflowId}`,
      label: summary.workflowName ?? formatWorkflowLabel(summary.workflowId),
      description: describeWorkflow(summary),
      meta: summarizeWorkflowMeta(summary),
      icon: FlaskConical,
    });
  }

  return items;
}

export function recentFiles(messages: Message[]): SurfaceItem[] {
  const items: SurfaceItem[] = [];
  const seenPaths = new Set<string>();

  const pushItem = (
    path: string | null | undefined,
    description: string,
    meta?: string | null
  ) => {
    if (!path || seenPaths.has(path) || items.length >= 6) return;
    seenPaths.add(path);
    items.push({
      id: path,
      label: path.split("/").pop() ?? path,
      description,
      meta: meta ?? shortenPath(path),
      icon: Files,
      path,
    });
  };

  for (let messageIndex = messages.length - 1; messageIndex >= 0; messageIndex -= 1) {
    const message = messages[messageIndex];

    const workflowEvents = message.workflow_events ?? [];
    for (let eventIndex = workflowEvents.length - 1; eventIndex >= 0; eventIndex -= 1) {
      const event = workflowEvents[eventIndex];
      if (event.type !== "workflow_artifact") continue;
      pushItem(
        event.artifact.path,
        humanizeToken(event.artifact.artifact_type) ?? "Workflow artifact"
      );
    }

    const toolCalls = message.tool_calls ?? [];
    for (let callIndex = toolCalls.length - 1; callIndex >= 0; callIndex -= 1) {
      const artifactRefs = toolCalls[callIndex]?.result?.artifact_refs ?? [];
      for (let refIndex = artifactRefs.length - 1; refIndex >= 0; refIndex -= 1) {
        const ref = artifactRefs[refIndex];
        pushItem(
          ref.path,
          humanizeToken(ref.artifact_type) ?? ref.label ?? "Tool artifact"
        );
      }
    }
  }

  return items;
}
