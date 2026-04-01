"use client";

import {
  Activity,
  BookOpen,
  FileText,
  Files,
  FlaskConical,
  Gauge,
  LayoutDashboard,
  MessageSquare,
  Microscope,
  Package,
  Route,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";
import {
  getWorkflowSummary,
  type WorkflowSummary,
} from "@/lib/session-status";
import type {
  FlowsWorkspaceStatus,
  FlowsWorkspaceSummaryItem,
  Message,
  WorkspaceMode,
} from "@/lib/types";

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

export interface FlowsWorkspaceDefinition {
  id: string;
  label: string;
  description: string;
  quickStartId: QuickStartItem["id"];
  workflowId?: string | null;
}

export type WorkspaceDocumentType = "Spec" | "Reference" | "SOP";

export interface WorkspaceDocument extends SurfaceItem {
  path: string;
  typeLabel: WorkspaceDocumentType;
  audience: string;
}

export interface WorkspaceDocumentSection {
  id: string;
  title: string;
  markdown: string;
}

export interface ParsedWorkspaceDocument {
  title: string;
  sections: WorkspaceDocumentSection[];
}

export const primaryNavItems: WorkspaceNavItem[] = [
  { id: "sessions", label: "Sessions", icon: MessageSquare },
  { id: "flows", label: "Flows", icon: FlaskConical },
  { id: "docs", label: "Docs", icon: BookOpen },
  { id: "files", label: "Files", icon: Files },
  { id: "studies", label: "Studies", icon: Microscope },
  { id: "ops", label: "Ops", icon: Activity },
  { id: "artifacts", label: "Artifacts", icon: Package },
];

export const studiesWorkspaceSections: SurfaceItem[] = [
  {
    id: "studies-summaries",
    label: "Study Summaries",
    description:
      "Browse derived study status, assay type, organism, privacy class, and artifact rollups.",
    meta: "Derived list",
    icon: Microscope,
  },
  {
    id: "studies-preview",
    label: "Selected Study",
    description:
      "Inspect the selected study summary shell and follow drill-through touchpoints from registry records.",
    meta: "Preview shell",
    icon: FileText,
  },
];

export const opsWorkspaceSections: SurfaceItem[] = [
  {
    id: "ops-overview",
    label: "Overview",
    description: "Read the latest health, latency, workflow delivery, and quality summaries.",
    meta: "System snapshot",
    icon: Gauge,
  },
  {
    id: "ops-metrics",
    label: "Metrics",
    description: "Inspect recent metric records with request, session, run, and trace filters.",
    meta: "Record browser",
    icon: Activity,
  },
  {
    id: "ops-traces",
    label: "Traces",
    description: "Follow trace and span activity to debug workflow execution and tool behavior.",
    meta: "Execution timeline",
    icon: Route,
  },
  {
    id: "ops-dashboards",
    label: "Dashboards",
    description: "Review backend dashboard definitions without leaving the inspection workspace.",
    meta: "Definitions",
    icon: LayoutDashboard,
  },
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

export const flowsWorkspaceDefinitions: FlowsWorkspaceDefinition[] = [
  {
    id: "rnaseq_qc_de",
    label: "RNA-seq DE Analysis",
    description: "Track RNA-seq differential expression workflow activity.",
    quickStartId: "rnaseq-de",
    workflowId: "rnaseq_qc_de",
  },
  {
    id: "evidence_review",
    label: "Evidence Review",
    description: "Review grounded evidence activity and recent synthesis runs.",
    quickStartId: "evidence-review",
  },
  {
    id: "compliance_preflight",
    label: "Compliance Check",
    description: "Monitor deterministic compliance and readiness preflights.",
    quickStartId: "compliance",
  },
];

export const workspaceDocs: WorkspaceDocument[] = [
  {
    id: "current-feature",
    label: "Current Feature",
    description: "Active implementation contract for this pass.",
    meta: "context/current-feature.md",
    icon: FileText,
    path: "context/current-feature.md",
    typeLabel: "Spec",
    audience: "Implementation contract",
  },
  {
    id: "project-overview",
    label: "Project Overview",
    description: "Mission, architecture, and product direction.",
    meta: "context/project-overview.md",
    icon: BookOpen,
    path: "context/project-overview.md",
    typeLabel: "Reference",
    audience: "Product context",
  },
  {
    id: "coding-standards",
    label: "Coding Standards",
    description: "Frontend and backend implementation guardrails.",
    meta: "context/coding-standards.md",
    icon: BookOpen,
    path: "context/coding-standards.md",
    typeLabel: "SOP",
    audience: "Engineering guardrails",
  },
  {
    id: "ai-interaction",
    label: "AI Interaction",
    description: "Feature workflow and review expectations.",
    meta: "context/ai-interaction.md",
    icon: BookOpen,
    path: "context/ai-interaction.md",
    typeLabel: "SOP",
    audience: "Execution workflow",
  },
];

export function formatWorkflowLabel(value: string): string {
  return value.replaceAll("_", " ").replaceAll("-", " ");
}

export function getQuickStartItem(id: QuickStartItem["id"]): QuickStartItem | null {
  return quickStartItems.find((item) => item.id === id) ?? null;
}

export function summarizeFlowsWorkspaceStatus(
  workflowStatus?: FlowsWorkspaceStatus | null
): string {
  if (workflowStatus === "active") return "Active";
  if (workflowStatus === "blocked") return "Blocked";
  if (workflowStatus === "failed") return "Failed";
  return "Idle";
}

export function flowsWorkspaceSummaryMap(
  items: FlowsWorkspaceSummaryItem[]
): Map<string, FlowsWorkspaceSummaryItem> {
  return new Map(items.map((item) => [item.id, item]));
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

function slugifyHeading(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function finalizeDocumentSection(
  sections: WorkspaceDocumentSection[],
  title: string,
  lines: string[],
  index: number
): void {
  const markdown = lines.join("\n").trim();
  if (!markdown) return;

  sections.push({
    id: `${slugifyHeading(title) || "section"}-${index + 1}`,
    title,
    markdown,
  });
}

export function parseWorkspaceDocument(
  content: string,
  fallbackTitle: string
): ParsedWorkspaceDocument {
  const normalized = content.replaceAll("\r\n", "\n");
  const lines = normalized.split("\n");
  let title = fallbackTitle;
  let startIndex = 0;
  const titleMatch = lines[0]?.match(/^#\s+(.+)$/);

  if (titleMatch) {
    title = titleMatch[1].trim();
    startIndex = 1;
  }

  const sections: WorkspaceDocumentSection[] = [];
  let currentSectionTitle: string | null = null;
  let currentSectionLines: string[] = [];
  let leadLines: string[] = [];

  for (let index = startIndex; index < lines.length; index += 1) {
    const line = lines[index];
    const sectionMatch = line.match(/^##\s+(.+)$/);

    if (sectionMatch) {
      if (currentSectionTitle) {
        finalizeDocumentSection(
          sections,
          currentSectionTitle,
          currentSectionLines,
          sections.length
        );
      } else {
        finalizeDocumentSection(sections, "Overview", leadLines, sections.length);
      }

      currentSectionTitle = sectionMatch[1].trim();
      currentSectionLines = [];
      leadLines = [];
      continue;
    }

    if (currentSectionTitle) {
      currentSectionLines.push(line);
    } else {
      leadLines.push(line);
    }
  }

  if (currentSectionTitle) {
    finalizeDocumentSection(
      sections,
      currentSectionTitle,
      currentSectionLines,
      sections.length
    );
  } else {
    finalizeDocumentSection(sections, "Overview", leadLines, sections.length);
  }

  if (sections.length === 0 && normalized.trim()) {
    sections.push({
      id: "document-body-1",
      title: "Document Body",
      markdown: normalized.trim(),
    });
  }

  return { title, sections };
}
