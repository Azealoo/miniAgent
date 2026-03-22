"use client";

import { useEffect, useState, type ReactNode } from "react";
import {
  ArrowRight,
  BookOpen,
  ExternalLink,
  FileText,
  Files,
  FlaskConical,
  FolderOpen,
  MessageSquare,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import ChatPanel from "@/components/chat/ChatPanel";
import WorkflowProgressCard from "@/components/chat/WorkflowProgressCard";
import {
  getWorkflowSummary,
  getReadinessSummary,
  isWorkflowSelectionPending,
} from "@/lib/session-status";
import { useApp } from "@/lib/store";
import { readFile } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  describeWorkflow,
  formatWorkflowLabel,
  getWorkflowSurfaceItems,
  quickStartItems,
  recentFiles,
  summarizeWorkflowMeta,
  workspaceDocs,
  type SurfaceItem,
} from "./workspace-data";

type PreviewStatus = "idle" | "loading" | "ready" | "error";

function usePreviewContent(path: string | null) {
  const [status, setStatus] = useState<PreviewStatus>("idle");
  const [content, setContent] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    if (!path) {
      setStatus("idle");
      setContent("");
      setError(null);
      return () => {
        active = false;
      };
    }

    setStatus("loading");
    setContent("");
    setError(null);

    void readFile(path)
      .then((response) => {
        if (!active) return;
        setContent(response.content);
        setStatus("ready");
      })
      .catch((previewError) => {
        if (!active) return;
        setStatus("error");
        setError(
          previewError instanceof Error
            ? previewError.message
            : "Unable to load that file preview right now."
        );
      });

    return () => {
      active = false;
    };
  }, [path]);

  return { status, content, error };
}

function previewText(content: string): string {
  const lines = content.split("\n");
  const clipped = lines.slice(0, 80).join("\n");
  return lines.length > 80 ? `${clipped}\n…` : clipped;
}

function WorkspaceBadge({
  icon: Icon,
  children,
}: {
  icon: LucideIcon;
  children: ReactNode;
}) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-[rgba(35,130,83,0.16)] bg-[rgba(35,130,83,0.08)] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--apex-accent-strong)]">
      <Icon size={12} />
      <span>{children}</span>
    </span>
  );
}

function WorkspaceAction({
  children,
  onClick,
  tone = "default",
}: {
  children: ReactNode;
  onClick: () => void;
  tone?: "default" | "accent";
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-[11px] font-medium transition-colors",
        tone === "accent"
          ? "border-[rgba(35,130,83,0.18)] bg-[var(--apex-accent-soft)] text-[var(--apex-accent-strong)] hover:bg-[rgba(35,130,83,0.16)]"
          : "border-[var(--shell-border)] bg-white/90 text-slate-600 hover:bg-[var(--panel-soft)] hover:text-slate-800"
      )}
    >
      {children}
    </button>
  );
}

function WorkspaceShell({
  children,
  mode,
}: {
  children: ReactNode;
  mode: "flows" | "docs" | "files";
}) {
  const backgroundClass =
    mode === "flows"
      ? "bg-[linear-gradient(180deg,rgba(247,250,246,0.98)_0%,rgba(242,247,242,0.92)_100%)]"
      : mode === "docs"
        ? "bg-[linear-gradient(180deg,rgba(250,251,248,0.98)_0%,rgba(246,248,243,0.94)_100%)]"
        : "bg-[linear-gradient(180deg,rgba(248,250,247,0.98)_0%,rgba(243,246,242,0.94)_100%)]";

  return (
    <section className="apex-panel flex h-full min-h-0 flex-col overflow-hidden rounded-[18px] shadow-[var(--panel-shadow-soft)]">
      <div className={cn("flex min-h-0 flex-1 flex-col", backgroundClass)}>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6 sm:py-5 lg:px-8 lg:py-7">
          <div className="mx-auto flex w-full max-w-[70rem] flex-col gap-4 pb-2 sm:gap-5">
            {children}
          </div>
        </div>
      </div>
    </section>
  );
}

function WorkspaceHero({
  icon: Icon,
  title,
  description,
  badges,
  actions,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  badges?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="rounded-[24px] border border-[rgba(211,219,210,0.9)] bg-[linear-gradient(135deg,rgba(255,255,255,0.96),rgba(247,249,245,0.94))] p-4 shadow-[0_12px_32px_rgba(29,42,33,0.05)] sm:p-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="max-w-3xl">
          <div className="flex items-center gap-2">
            <div className="flex h-11 w-11 items-center justify-center rounded-[16px] bg-[var(--apex-accent-soft)] text-[var(--apex-accent-strong)]">
              <Icon size={20} />
            </div>
            <WorkspaceBadge icon={Sparkles}>Workspace Mode</WorkspaceBadge>
          </div>
          <h2 className="mt-3 text-[1.3rem] font-semibold tracking-[-0.02em] text-slate-900">
            {title}
          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">
            {description}
          </p>
          {badges ? <div className="mt-3 flex flex-wrap gap-2">{badges}</div> : null}
        </div>

        {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
      </div>
    </div>
  );
}

function SummaryCard({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="rounded-[18px] border border-[rgba(211,219,210,0.9)] bg-white/92 px-4 py-3 shadow-[0_8px_24px_rgba(29,42,33,0.04)]">
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

function SurfaceListCard({
  title,
  subtitle,
  items,
  selectedPath,
  onSelect,
  emptyMessage,
}: {
  title: string;
  subtitle: string;
  items: SurfaceItem[];
  selectedPath?: string | null;
  onSelect: (item: SurfaceItem) => void;
  emptyMessage: string;
}) {
  return (
    <div className="rounded-[22px] border border-[rgba(211,219,210,0.9)] bg-white/90 p-3 shadow-[0_8px_24px_rgba(29,42,33,0.04)]">
      <div className="border-b border-[rgba(211,219,210,0.72)] px-1 pb-3">
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
          {title}
        </p>
        <p className="mt-1 text-sm leading-6 text-slate-500">{subtitle}</p>
      </div>

      <div className="mt-3 space-y-2">
        {items.length === 0 ? (
          <div className="rounded-[16px] border border-dashed border-[rgba(211,219,210,0.9)] bg-[rgba(251,252,248,0.95)] px-3 py-4 text-sm leading-6 text-slate-500">
            {emptyMessage}
          </div>
        ) : (
          items.map((item) => {
            const Icon = item.icon;
            const active = Boolean(item.path) && item.path === selectedPath;

            return (
              <button
                key={item.id}
                type="button"
                onClick={() => onSelect(item)}
                className={cn(
                  "flex w-full items-start gap-3 rounded-[16px] border px-3 py-3 text-left transition-colors",
                  active
                    ? "border-[rgba(35,130,83,0.18)] bg-[rgba(35,130,83,0.08)]"
                    : "border-[rgba(211,219,210,0.85)] bg-[rgba(255,255,255,0.86)] hover:border-[rgba(35,130,83,0.16)] hover:bg-[rgba(248,251,247,0.95)]"
                )}
              >
                <div
                  className={cn(
                    "mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-[12px]",
                    active
                      ? "bg-white text-[var(--apex-accent-strong)]"
                      : "bg-[rgba(247,249,245,0.9)] text-slate-500"
                  )}
                >
                  <Icon size={16} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <p className="truncate text-sm font-semibold text-slate-800">
                      {item.label}
                    </p>
                    {item.meta ? (
                      <span className="truncate text-[10px] text-slate-400">
                        {item.meta}
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-1 text-[12px] leading-5 text-slate-500">
                    {item.description}
                  </p>
                </div>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}

function PreviewCard({
  eyebrow,
  title,
  path,
  status,
  content,
  error,
  emptyMessage,
  onOpen,
}: {
  eyebrow: string;
  title: string;
  path: string | null;
  status: PreviewStatus;
  content: string;
  error: string | null;
  emptyMessage: string;
  onOpen?: () => void;
}) {
  return (
    <div className="flex min-h-[24rem] flex-col rounded-[22px] border border-[rgba(211,219,210,0.9)] bg-white/92 shadow-[0_8px_24px_rgba(29,42,33,0.04)]">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[rgba(211,219,210,0.72)] px-4 py-4">
        <div className="min-w-0">
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
            {eyebrow}
          </p>
          <h3 className="mt-1 text-base font-semibold tracking-[-0.02em] text-slate-900">
            {title}
          </h3>
          <p className="mt-1 truncate text-[11px] text-slate-500">
            {path ?? "Choose an item to inspect its inline preview."}
          </p>
        </div>

        {path && onOpen ? (
          <WorkspaceAction onClick={onOpen}>
            <ExternalLink size={12} />
            Open In Inspector
          </WorkspaceAction>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        {!path ? (
          <div className="rounded-[18px] border border-dashed border-[rgba(211,219,210,0.88)] bg-[rgba(251,252,248,0.95)] px-4 py-8 text-sm leading-6 text-slate-500">
            {emptyMessage}
          </div>
        ) : status === "loading" ? (
          <div className="rounded-[18px] border border-[rgba(211,219,210,0.88)] bg-[rgba(251,252,248,0.95)] px-4 py-8 text-sm leading-6 text-slate-500">
            Loading preview…
          </div>
        ) : status === "error" ? (
          <div className="rounded-[18px] border border-[rgba(240,195,195,0.92)] bg-[rgba(253,244,244,0.94)] px-4 py-8 text-sm leading-6 text-rose-700">
            {error ?? "Unable to load that preview."}
          </div>
        ) : status === "ready" ? (
          <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded-[18px] border border-[rgba(211,219,210,0.88)] bg-[rgba(248,250,246,0.95)] px-4 py-4 font-mono text-[12px] leading-6 text-slate-700">
            {previewText(content)}
          </pre>
        ) : (
          <div className="rounded-[18px] border border-dashed border-[rgba(211,219,210,0.88)] bg-[rgba(251,252,248,0.95)] px-4 py-8 text-sm leading-6 text-slate-500">
            {emptyMessage}
          </div>
        )}
      </div>
    </div>
  );
}

function EmptyWorkspaceState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-[22px] border border-dashed border-[rgba(211,219,210,0.88)] bg-[rgba(251,252,248,0.95)] px-5 py-8 text-center">
      <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--apex-accent-strong)]">
        Workspace Ready
      </p>
      <h3 className="mt-2 text-lg font-semibold tracking-[-0.02em] text-slate-900">
        {title}
      </h3>
      <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-slate-500">
        {description}
      </p>
      {action ? <div className="mt-4 flex justify-center">{action}</div> : null}
    </div>
  );
}

function FlowsWorkspace() {
  const {
    messages,
    sessions,
    currentSessionId,
    isStreaming,
    selectedWorkflow,
    setWorkspaceMode,
    selectWorkflow,
    primeDraftMessage,
    clearDraftMessage,
    openInspectorPath,
  } = useApp();

  const workflowSummary = getWorkflowSummary(messages);
  const readiness = getReadinessSummary(messages, {
    workflowSummary,
    isStreaming,
  });
  const pendingSelection = isWorkflowSelectionPending(messages, selectedWorkflow);
  const workflowItems = getWorkflowSurfaceItems(
    messages,
    selectedWorkflow,
    pendingSelection
  );
  const artifactItems = recentFiles(messages);
  const workflowQuickStarts = quickStartItems.filter((item) => item.workflowId);
  const currentSession =
    sessions.find((session) => session.id === currentSessionId) ?? null;
  const activeWorkflowLabel = selectedWorkflow
    ? formatWorkflowLabel(selectedWorkflow)
    : workflowSummary.workflowName ?? "No workflow selected";

  return (
    <WorkspaceShell mode="flows">
      <WorkspaceHero
        icon={FlaskConical}
        title="Flows Workspace"
        description="Review the active workflow focus, inspect the latest run status, and move back into the session when you are ready to send the next request."
        badges={
          <>
            <WorkspaceBadge icon={FlaskConical}>{activeWorkflowLabel}</WorkspaceBadge>
            <WorkspaceBadge icon={Sparkles}>{readiness.label}</WorkspaceBadge>
            <WorkspaceBadge icon={MessageSquare}>
              {currentSession?.title ?? "Active session"}
            </WorkspaceBadge>
          </>
        }
        actions={
          <>
            <WorkspaceAction onClick={() => setWorkspaceMode("sessions")} tone="accent">
              <MessageSquare size={12} />
              Continue In Session
            </WorkspaceAction>
            {selectedWorkflow ? (
              <WorkspaceAction
                onClick={() => {
                  selectWorkflow(null);
                  clearDraftMessage();
                }}
              >
                Clear Workflow
              </WorkspaceAction>
            ) : null}
          </>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <SummaryCard
          label="Workflow"
          value={activeWorkflowLabel}
          detail={
            pendingSelection
              ? "Selected and waiting for the next request."
              : describeWorkflow(workflowSummary)
          }
        />
        <SummaryCard
          label="Readiness"
          value={readiness.label}
          detail={readiness.detail ?? "No active warnings in this workflow workspace."}
        />
        <SummaryCard
          label="Progress"
          value={summarizeWorkflowMeta(workflowSummary)}
          detail={
            workflowSummary.currentStep
              ? `${workflowSummary.currentStep} is active right now.`
              : "Progress stays aligned with the latest workflow events."
          }
        />
        <SummaryCard
          label="Artifacts"
          value={`${artifactItems.length}`}
          detail="Recent workflow and tool outputs stay available in the files workspace and inspector."
        />
      </div>

      <div className="grid min-h-0 gap-4 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
        <div className="space-y-4">
          <SurfaceListCard
            title="Flow Focus"
            subtitle="Selected workflows and the latest observed run stay visible here even when the session surface is hidden."
            items={workflowItems}
            selectedPath={null}
            onSelect={() => {
              setWorkspaceMode("sessions");
            }}
            emptyMessage="No workflow is selected yet. Choose a workflow quick start or ask for one in the session workspace."
          />

          <div className="rounded-[22px] border border-[rgba(211,219,210,0.9)] bg-white/90 p-3 shadow-[0_8px_24px_rgba(29,42,33,0.04)]">
            <div className="border-b border-[rgba(211,219,210,0.72)] px-1 pb-3">
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                Workflow Quick Starts
              </p>
              <p className="mt-1 text-sm leading-6 text-slate-500">
                Prime a workflow-focused request, then return to the session workspace to run it.
              </p>
            </div>

            <div className="mt-3 space-y-2">
              {workflowQuickStarts.map((item) => {
                const Icon = item.icon;
                const active = selectedWorkflow === item.workflowId;

                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => {
                      selectWorkflow(item.workflowId ?? null);
                      primeDraftMessage(item.draftMessage);
                      setWorkspaceMode("sessions");
                    }}
                    className={cn(
                      "flex w-full items-start gap-3 rounded-[16px] border px-3 py-3 text-left transition-colors",
                      active
                        ? "border-[rgba(35,130,83,0.18)] bg-[rgba(35,130,83,0.08)]"
                        : "border-[rgba(211,219,210,0.85)] bg-[rgba(255,255,255,0.86)] hover:border-[rgba(35,130,83,0.16)] hover:bg-[rgba(248,251,247,0.95)]"
                    )}
                  >
                    <div className="mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-[12px] bg-[rgba(247,249,245,0.9)] text-slate-500">
                      <Icon size={16} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <p className="truncate text-sm font-semibold text-slate-800">
                          {item.label}
                        </p>
                        <span className="text-[10px] uppercase tracking-[0.16em] text-slate-400">
                          {item.kind}
                        </span>
                      </div>
                      <p className="mt-1 text-[12px] leading-5 text-slate-500">
                        {item.description}
                      </p>
                    </div>
                    <ArrowRight size={14} className="mt-1 text-slate-400" />
                  </button>
                );
              })}
            </div>
          </div>

          <SurfaceListCard
            title="Recent Artifacts"
            subtitle="The latest outputs from workflow and tool execution remain one click away from the inspector."
            items={artifactItems}
            selectedPath={null}
            onSelect={(item) => {
              if (item.path) {
                openInspectorPath(item.path);
              }
            }}
            emptyMessage="Artifacts will appear here after a workflow or tool produces durable outputs."
          />
        </div>

        {workflowSummary.events.length > 0 ? (
          <WorkflowProgressCard events={workflowSummary.events} />
        ) : (
          <EmptyWorkspaceState
            title="No workflow run is active yet"
            description="Once a workflow starts, this workspace will show the live step-by-step run trace without forcing you back into the chat surface."
            action={
              <WorkspaceAction onClick={() => setWorkspaceMode("sessions")} tone="accent">
                <MessageSquare size={12} />
                Open Session Workspace
              </WorkspaceAction>
            }
          />
        )}
      </div>
    </WorkspaceShell>
  );
}

function DocsWorkspace() {
  const { workspaceMode, inspectorPreviewPath, openInspectorPath, setWorkspaceMode } =
    useApp();
  const [selectedDocPath, setSelectedDocPath] = useState<string | null>(
    workspaceDocs[0]?.path ?? null
  );

  useEffect(() => {
    if (
      workspaceMode === "docs" &&
      inspectorPreviewPath &&
      workspaceDocs.some((item) => item.path === inspectorPreviewPath)
    ) {
      setSelectedDocPath(inspectorPreviewPath);
    }
  }, [inspectorPreviewPath, workspaceMode]);

  const selectedDoc =
    workspaceDocs.find((item) => item.path === selectedDocPath) ?? workspaceDocs[0] ?? null;
  const preview = usePreviewContent(selectedDoc?.path ?? null);

  return (
    <WorkspaceShell mode="docs">
      <WorkspaceHero
        icon={BookOpen}
        title="Docs Workspace"
        description="Keep the BioAPEX working contract, project guidance, and implementation guardrails close by without disrupting the surrounding shell."
        badges={
          <>
            <WorkspaceBadge icon={BookOpen}>{`${workspaceDocs.length} core docs`}</WorkspaceBadge>
            {selectedDoc ? (
              <WorkspaceBadge icon={FileText}>{selectedDoc.label}</WorkspaceBadge>
            ) : null}
          </>
        }
        actions={
          <>
            {selectedDoc?.path ? (
              <WorkspaceAction
                onClick={() => openInspectorPath(selectedDoc.path!)}
                tone="accent"
              >
                <FolderOpen size={12} />
                Inspect Selected Doc
              </WorkspaceAction>
            ) : null}
            <WorkspaceAction onClick={() => setWorkspaceMode("sessions")}>
              <MessageSquare size={12} />
              Return To Session
            </WorkspaceAction>
          </>
        }
      />

      <div className="grid gap-3 sm:grid-cols-3">
        <SummaryCard
          label="Working Set"
          value={`${workspaceDocs.length} docs`}
          detail="Project context stays one mode switch away instead of hiding behind sidebar metadata."
        />
        <SummaryCard
          label="Focused Doc"
          value={selectedDoc?.label ?? "None"}
          detail={selectedDoc?.description ?? "Choose a document to preview it inline."}
        />
        <SummaryCard
          label="Inspector Sync"
          value={selectedDoc?.path === inspectorPreviewPath ? "Aligned" : "Independent"}
          detail="Inline preview and inspector preview can follow the same file without forcing a reset."
        />
      </div>

      <div className="grid min-h-0 gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <SurfaceListCard
          title="Working Docs"
          subtitle="These are the contract and guidance files most often used while implementing BioAPEX features."
          items={workspaceDocs}
          selectedPath={selectedDoc?.path ?? null}
          onSelect={(item) => {
            if (item.path) {
              setSelectedDocPath(item.path);
            }
          }}
          emptyMessage="No working docs are configured for this workspace."
        />

        <PreviewCard
          eyebrow="Inline Preview"
          title={selectedDoc?.label ?? "Select a document"}
          path={selectedDoc?.path ?? null}
          status={preview.status}
          content={preview.content}
          error={preview.error}
          emptyMessage="Pick a working document to preview it here and open it in the inspector when you need the full file view."
          onOpen={
            selectedDoc?.path ? () => openInspectorPath(selectedDoc.path!) : undefined
          }
        />
      </div>
    </WorkspaceShell>
  );
}

function FilesWorkspace() {
  const { workspaceMode, inspectorPreviewPath, openInspectorPath, setWorkspaceMode, messages } =
    useApp();
  const fileItems = recentFiles(messages);
  const [selectedFilePath, setSelectedFilePath] = useState<string | null>(null);

  useEffect(() => {
    if (workspaceMode !== "files") return;

    if (
      inspectorPreviewPath &&
      fileItems.some((item) => item.path === inspectorPreviewPath)
    ) {
      setSelectedFilePath(inspectorPreviewPath);
      return;
    }

    if (!selectedFilePath && fileItems[0]?.path) {
      setSelectedFilePath(fileItems[0].path ?? null);
    }
  }, [fileItems, inspectorPreviewPath, selectedFilePath, workspaceMode]);

  const selectedFile =
    fileItems.find((item) => item.path === selectedFilePath) ?? fileItems[0] ?? null;
  const preview = usePreviewContent(selectedFile?.path ?? null);

  return (
    <WorkspaceShell mode="files">
      <WorkspaceHero
        icon={Files}
        title="Files Workspace"
        description="Browse recent durable outputs from the active session without moving the top bar, sidebar, or inspector out of place."
        badges={
          <>
            <WorkspaceBadge icon={Files}>{`${fileItems.length} recent files`}</WorkspaceBadge>
            {selectedFile ? (
              <WorkspaceBadge icon={FileText}>{selectedFile.label}</WorkspaceBadge>
            ) : null}
          </>
        }
        actions={
          <>
            {selectedFile?.path ? (
              <WorkspaceAction
                onClick={() => openInspectorPath(selectedFile.path!)}
                tone="accent"
              >
                <FolderOpen size={12} />
                Inspect Selected File
              </WorkspaceAction>
            ) : null}
            <WorkspaceAction onClick={() => setWorkspaceMode("flows")}>
              <FlaskConical size={12} />
              Open Flows Workspace
            </WorkspaceAction>
          </>
        }
      />

      <div className="grid gap-3 sm:grid-cols-3">
        <SummaryCard
          label="Recent Outputs"
          value={`${fileItems.length}`}
          detail="Latest workflow artifacts and tool-produced files are surfaced from the active session history."
        />
        <SummaryCard
          label="Focused File"
          value={selectedFile?.label ?? "None"}
          detail={selectedFile?.description ?? "Choose a file to inspect its inline preview."}
        />
        <SummaryCard
          label="Preview State"
          value={
            preview.status === "ready"
              ? "Loaded"
              : preview.status === "loading"
                ? "Loading"
                : preview.status === "error"
                  ? "Issue"
                  : "Waiting"
          }
          detail="The files workspace keeps the center column focused on durable artifacts rather than the chat stream."
        />
      </div>

      {fileItems.length === 0 ? (
        <EmptyWorkspaceState
          title="No recent files yet"
          description="Run a workflow, inspect generated artifacts, or attach a reference in the session workspace and the latest durable files will appear here."
          action={
            <WorkspaceAction onClick={() => setWorkspaceMode("sessions")} tone="accent">
              <MessageSquare size={12} />
              Open Session Workspace
            </WorkspaceAction>
          }
        />
      ) : (
        <div className="grid min-h-0 gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
          <SurfaceListCard
            title="Recent Files"
            subtitle="Files stay scoped to recent workflow and tool activity so this workspace feels like a product surface, not just a sidebar badge."
            items={fileItems}
            selectedPath={selectedFile?.path ?? null}
            onSelect={(item) => {
              if (item.path) {
                setSelectedFilePath(item.path);
              }
            }}
            emptyMessage="No files are available in this workspace yet."
          />

          <PreviewCard
            eyebrow="Inline Preview"
            title={selectedFile?.label ?? "Select a file"}
            path={selectedFile?.path ?? null}
            status={preview.status}
            content={preview.content}
            error={preview.error}
            emptyMessage="Choose a recent file to preview it here and open it in the inspector for the full file experience."
            onOpen={
              selectedFile?.path ? () => openInspectorPath(selectedFile.path!) : undefined
            }
          />
        </div>
      )}
    </WorkspaceShell>
  );
}

export default function WorkspacePanel() {
  const { workspaceMode } = useApp();

  return (
    <div className="relative h-full">
      <div
        className={cn("h-full", workspaceMode !== "sessions" && "hidden")}
        aria-hidden={workspaceMode !== "sessions"}
      >
        <ChatPanel />
      </div>

      {workspaceMode === "flows" ? <FlowsWorkspace /> : null}
      {workspaceMode === "docs" ? <DocsWorkspace /> : null}
      {workspaceMode === "files" ? <FilesWorkspace /> : null}
    </div>
  );
}
