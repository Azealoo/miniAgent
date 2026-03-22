"use client";

import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";
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
  Plus,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import ChatPanel from "@/components/chat/ChatPanel";
import {
  getWorkflowSummary,
} from "@/lib/session-status";
import { useApp } from "@/lib/store";
import {
  getFlowsWorkspaceSummary,
  readFile,
} from "@/lib/api";
import type {
  FlowsWorkspaceStatus,
  FlowsWorkspaceSummaryItem,
} from "@/lib/types";
import { cn, formatRelativeTime } from "@/lib/utils";
import {
  describeWorkflow,
  flowsWorkspaceDefinitions,
  flowsWorkspaceSummaryMap,
  getQuickStartItem,
  parseWorkspaceDocument,
  type ParsedWorkspaceDocument,
  recentFiles,
  summarizeFlowsWorkspaceStatus,
  workspaceDocs,
  type SurfaceItem,
  type WorkspaceDocument,
} from "./workspace-data";

type PreviewStatus = "idle" | "loading" | "ready" | "error";
type DocsWorkspaceStatus = "loading" | "ready" | "error";

interface LoadedWorkspaceDocument extends WorkspaceDocument {
  parsed: ParsedWorkspaceDocument;
}

interface WorkspaceDocumentFailure extends WorkspaceDocument {
  error: string;
}

type DocsNavigatorEntry =
  | { kind: "loaded"; document: LoadedWorkspaceDocument }
  | { kind: "failed"; document: WorkspaceDocumentFailure };

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

function DocumentTypeBadge({
  label,
}: {
  label: WorkspaceDocument["typeLabel"];
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em]",
        label === "Spec" &&
          "border-[rgba(35,130,83,0.18)] bg-[rgba(35,130,83,0.09)] text-[var(--apex-accent-strong)]",
        label === "Reference" &&
          "border-[rgba(148,163,184,0.22)] bg-[rgba(241,245,249,0.9)] text-slate-600",
        label === "SOP" &&
          "border-[rgba(217,119,6,0.18)] bg-[rgba(255,247,237,0.95)] text-amber-700"
      )}
    >
      {label}
    </span>
  );
}

function formatSectionCount(value: number): string {
  return `${value} section${value === 1 ? "" : "s"}`;
}

function WorkspaceStateCard({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "error";
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "rounded-[18px] border px-4 py-6 text-sm leading-6",
        tone === "neutral" &&
          "border-[rgba(211,219,210,0.88)] bg-[rgba(251,252,248,0.95)] text-slate-500",
        tone === "error" &&
          "border-[rgba(240,195,195,0.92)] bg-[rgba(253,244,244,0.94)] text-rose-700"
      )}
    >
      {children}
    </div>
  );
}

function DocsNavigatorCard({
  status,
  documents,
  failedDocuments,
  selectedPath,
  onSelect,
  error,
}: {
  status: DocsWorkspaceStatus;
  documents: LoadedWorkspaceDocument[];
  failedDocuments: WorkspaceDocumentFailure[];
  selectedPath: string | null;
  onSelect: (document: LoadedWorkspaceDocument) => void;
  error: string | null;
}) {
  const loadedByPath = new Map(documents.map((document) => [document.path, document]));
  const failedByPath = new Map(
    failedDocuments.map((document) => [document.path, document])
  );
  const orderedEntries: DocsNavigatorEntry[] = [];

  workspaceDocs.forEach((document) => {
    const loadedDocument = loadedByPath.get(document.path);
    if (loadedDocument) {
      orderedEntries.push({ kind: "loaded", document: loadedDocument });
      return;
    }

    const failedDocument = failedByPath.get(document.path);
    if (failedDocument) {
      orderedEntries.push({ kind: "failed", document: failedDocument });
    }
  });

  return (
    <div className="rounded-[22px] border border-[rgba(211,219,210,0.9)] bg-white/92 p-3 shadow-[0_8px_24px_rgba(29,42,33,0.04)]">
      <div className="border-b border-[rgba(211,219,210,0.72)] px-1 pb-3">
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
          Document Navigator
        </p>
        <p className="mt-1 text-sm leading-6 text-slate-500">
          Protocols, specs, and reference files stay collected here so the docs
          workspace feels like a reading surface instead of a generic file list.
        </p>
      </div>

      <div className="mt-3 space-y-2">
        {status === "loading" ? (
          <WorkspaceStateCard>Loading documentation index…</WorkspaceStateCard>
        ) : status === "error" ? (
          <WorkspaceStateCard tone="error">
            {error ?? "Unable to load the documentation index right now."}
          </WorkspaceStateCard>
        ) : orderedEntries.length === 0 ? (
          <WorkspaceStateCard>
            No documents are configured for this workspace yet.
          </WorkspaceStateCard>
        ) : (
          orderedEntries.map((entry) => {
            if (entry.kind === "failed") {
              const document = entry.document;
              const Icon = document.icon;

              return (
                <div
                  key={document.id}
                  className="rounded-[18px] border border-[rgba(240,195,195,0.92)] bg-[rgba(253,244,244,0.9)] px-4 py-4"
                >
                  <div className="flex items-start gap-3">
                    <div className="mt-0.5 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-[12px] bg-white text-rose-500">
                      <Icon size={17} />
                    </div>

                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="truncate text-sm font-semibold text-rose-900">
                          {document.label}
                        </p>
                        <DocumentTypeBadge label={document.typeLabel} />
                      </div>
                      <p className="mt-2 text-[12px] leading-5 text-rose-700">
                        {document.error}
                      </p>
                      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-rose-600">
                        <span>{document.audience}</span>
                        <span className="truncate">{document.meta ?? document.path}</span>
                        <span>Unavailable</span>
                      </div>
                    </div>
                  </div>
                </div>
              );
            }

            const document = entry.document;
            const active = document.path === selectedPath;
            const Icon = document.icon;

            return (
              <button
                key={document.id}
                type="button"
                onClick={() => onSelect(document)}
                className={cn(
                  "w-full rounded-[18px] border px-4 py-4 text-left transition-colors",
                  active
                    ? "border-[rgba(35,130,83,0.18)] bg-[rgba(35,130,83,0.08)] shadow-[0_10px_24px_rgba(35,130,83,0.08)]"
                    : "border-[rgba(211,219,210,0.85)] bg-[rgba(255,255,255,0.92)] hover:border-[rgba(35,130,83,0.16)] hover:bg-[rgba(248,251,247,0.95)]"
                )}
              >
                <div className="flex items-start gap-3">
                  <div
                    className={cn(
                      "mt-0.5 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-[12px]",
                      active
                        ? "bg-white text-[var(--apex-accent-strong)]"
                        : "bg-[rgba(247,249,245,0.9)] text-slate-500"
                    )}
                  >
                    <Icon size={17} />
                  </div>

                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="truncate text-sm font-semibold text-slate-900">
                        {document.label}
                      </p>
                      <DocumentTypeBadge label={document.typeLabel} />
                    </div>
                    <p className="mt-2 text-[12px] leading-5 text-slate-500">
                      {document.description}
                    </p>
                    <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-500">
                      <span>{document.audience}</span>
                      <span>{formatSectionCount(document.parsed.sections.length)}</span>
                      <span className="truncate">{document.meta ?? document.path}</span>
                    </div>
                  </div>
                </div>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}

function DocumentSectionMarkdown({
  content,
}: {
  content: string;
}) {
  return (
    <div className="apex-chat-prose prose prose-sm max-w-none prose-pre:bg-[#1e1e1e] prose-pre:text-gray-100 prose-p:text-slate-600 prose-li:text-slate-600 prose-strong:text-slate-900">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          h1({ children }) {
            return (
              <h4 className="mt-0 text-base font-semibold tracking-[-0.02em] text-slate-900">
                {children}
              </h4>
            );
          },
          h2({ children }) {
            return (
              <h4 className="mt-0 text-base font-semibold tracking-[-0.02em] text-slate-900">
                {children}
              </h4>
            );
          },
          h3({ children }) {
            return (
              <h5 className="mt-4 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 first:mt-0">
                {children}
              </h5>
            );
          },
          code({ className, children, ...props }) {
            const match = /language-(\w+)/.exec(className ?? "");
            if (!match) {
              return (
                <code
                  className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[0.8em] text-[#c7254e]"
                  {...props}
                >
                  {children}
                </code>
              );
            }

            return (
              <code className={className} {...props}>
                {children}
              </code>
            );
          },
          table({ children }) {
            return (
              <div className="my-4 overflow-x-auto">
                <table className="min-w-full overflow-hidden rounded-lg border border-slate-200 text-xs">
                  {children}
                </table>
              </div>
            );
          },
          th({ children }) {
            return (
              <th className="border-b border-slate-200 bg-slate-50 px-3 py-2 text-left font-semibold text-slate-700">
                {children}
              </th>
            );
          },
          td({ children }) {
            return (
              <td className="border-b border-slate-100 px-3 py-2 text-slate-600">
                {children}
              </td>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function DocsReaderPane({
  status,
  document,
  error,
  warning,
  onOpen,
}: {
  status: DocsWorkspaceStatus;
  document: LoadedWorkspaceDocument | null;
  error: string | null;
  warning?: string | null;
  onOpen?: () => void;
}) {
  return (
    <div className="flex min-h-[32rem] flex-col rounded-[22px] border border-[rgba(211,219,210,0.9)] bg-white/94 shadow-[0_8px_24px_rgba(29,42,33,0.04)]">
      <div className="border-b border-[rgba(211,219,210,0.72)] px-5 py-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="max-w-3xl">
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
              Reading Pane
            </p>
            <h3 className="mt-2 text-[1.4rem] font-semibold tracking-[-0.03em] text-slate-900">
              {document?.parsed.title ?? "Select a document"}
            </h3>
            <p className="mt-2 text-sm leading-6 text-slate-500">
              {document?.description ??
                "Choose a protocol, spec, or reference from the navigator to read it as structured sections."}
            </p>
            {document?.meta ? (
              <p className="mt-2 text-[11px] text-slate-400">{document.meta}</p>
            ) : null}
          </div>

          {document?.path && onOpen ? (
            <WorkspaceAction onClick={onOpen} tone="accent">
              <FolderOpen size={12} />
              Open In Inspector
            </WorkspaceAction>
          ) : null}
        </div>

        {document ? (
          <div className="mt-4 flex flex-wrap gap-2">
            <DocumentTypeBadge label={document.typeLabel} />
            <WorkspaceBadge icon={BookOpen}>
              {formatSectionCount(document.parsed.sections.length)}
            </WorkspaceBadge>
            <WorkspaceBadge icon={FileText}>{document.audience}</WorkspaceBadge>
          </div>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
        {warning ? (
          <div className="mb-4">
            <WorkspaceStateCard>{warning}</WorkspaceStateCard>
          </div>
        ) : null}

        {status === "loading" ? (
          <WorkspaceStateCard>Loading selected document…</WorkspaceStateCard>
        ) : status === "error" ? (
          <WorkspaceStateCard tone="error">
            {error ?? "Unable to load the selected document right now."}
          </WorkspaceStateCard>
        ) : !document ? (
          <WorkspaceStateCard>
            Select a document from the navigator to load its reading view.
          </WorkspaceStateCard>
        ) : document.parsed.sections.length === 0 ? (
          <WorkspaceStateCard>
            This document does not have any structured sections to render yet.
          </WorkspaceStateCard>
        ) : (
          <div className="space-y-4">
            {document.parsed.sections.map((section, index) => (
              <section
                key={section.id}
                className="rounded-[20px] border border-[rgba(211,219,210,0.88)] bg-[linear-gradient(180deg,rgba(250,251,248,0.97),rgba(255,255,255,0.98))] p-4 shadow-[0_8px_20px_rgba(29,42,33,0.03)]"
              >
                <div className="flex flex-wrap items-center gap-3">
                  <span className="inline-flex items-center rounded-full bg-[rgba(35,130,83,0.08)] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--apex-accent-strong)]">
                    Section {index + 1}
                  </span>
                  <h4 className="text-lg font-semibold tracking-[-0.02em] text-slate-900">
                    {section.title}
                  </h4>
                </div>

                <div className="mt-4 rounded-[16px] border border-[rgba(214,221,212,0.86)] bg-white/92 px-4 py-4">
                  <DocumentSectionMarkdown content={section.markdown} />
                </div>
              </section>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function FlowsPrimaryAction({
  children,
  onClick,
}: {
  children: ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-2 rounded-[14px] bg-[var(--apex-accent)] px-4 py-2.5 text-sm font-semibold text-white shadow-[0_10px_24px_rgba(35,130,83,0.18)] transition-colors hover:bg-[var(--apex-accent-strong)]"
    >
      {children}
    </button>
  );
}

function FlowsStatusBadge({
  status,
}: {
  status: FlowsWorkspaceStatus;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-semibold",
        status === "active" &&
          "bg-[rgba(35,130,83,0.12)] text-[var(--apex-accent-strong)]",
        status === "idle" && "bg-[rgba(148,163,184,0.12)] text-slate-500",
        status === "blocked" && "bg-[rgba(217,119,6,0.12)] text-amber-700",
        status === "failed" && "bg-[rgba(220,38,38,0.1)] text-red-700"
      )}
    >
      {summarizeFlowsWorkspaceStatus(status)}
    </span>
  );
}

function FlowsWorkspaceCard({
  label,
  status,
  runCount,
  lastActivityAt,
  selected = false,
  onClick,
}: {
  label: string;
  status: FlowsWorkspaceStatus;
  runCount: number;
  lastActivityAt: number | null;
  selected?: boolean;
  onClick: () => void;
}) {
  const timestampLabel = lastActivityAt
    ? formatRelativeTime(lastActivityAt)
    : "No recent activity";
  const runCountLabel =
    runCount === 0 ? "No runs yet" : `${runCount} run${runCount === 1 ? "" : "s"}`;

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-4 rounded-[20px] border px-5 py-5 text-left shadow-[0_10px_28px_rgba(18,24,20,0.04)] transition-colors",
        selected && "shadow-[0_14px_34px_rgba(18,24,20,0.08)]",
        status === "active" &&
          (selected
            ? "border-[rgba(101,174,135,0.96)] bg-[linear-gradient(180deg,rgba(244,251,247,0.99),rgba(238,248,242,0.99))]"
            : "border-[rgba(131,191,157,0.92)] bg-[linear-gradient(180deg,rgba(247,252,249,0.98),rgba(241,249,244,0.98))] hover:border-[rgba(101,174,135,0.96)]"),
        status === "idle" &&
          (selected
            ? "border-[rgba(194,204,194,0.98)] bg-[rgba(250,251,249,0.99)]"
            : "border-[rgba(228,232,226,0.96)] bg-white/96 hover:border-[rgba(204,214,203,0.96)] hover:bg-[rgba(251,252,250,0.98)]"),
        status === "blocked" &&
          (selected
            ? "border-[rgba(217,119,6,0.36)] bg-[linear-gradient(180deg,rgba(255,249,230,0.99),rgba(255,244,231,0.99))]"
            : "border-[rgba(245,158,11,0.3)] bg-[linear-gradient(180deg,rgba(255,251,235,0.98),rgba(255,247,237,0.98))] hover:border-[rgba(217,119,6,0.34)]"),
        status === "failed" &&
          (selected
            ? "border-[rgba(220,38,38,0.34)] bg-[linear-gradient(180deg,rgba(254,240,240,0.99),rgba(254,245,245,0.99))]"
            : "border-[rgba(248,113,113,0.28)] bg-[linear-gradient(180deg,rgba(254,242,242,0.98),rgba(254,247,247,0.98))] hover:border-[rgba(220,38,38,0.32)]")
      )}
    >
      <div className="min-w-0 flex-1">
        <p className="truncate text-[1.05rem] font-semibold tracking-[-0.02em] text-slate-900">
          {label}
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 text-sm text-slate-500">
          <FlowsStatusBadge status={status} />
          <span>{runCountLabel}</span>
          <span>{timestampLabel}</span>
        </div>
      </div>

      <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full border border-[rgba(226,232,240,0.95)] bg-white/92 text-slate-500">
        <ArrowRight size={16} />
      </div>
    </button>
  );
}

function summarizeFlowsDetail(status: FlowsWorkspaceStatus): string {
  if (status === "active") {
    return "Recent activity is live or staged for the next workflow request.";
  }
  if (status === "blocked") {
    return "The latest activity hit a block and needs review before it can move forward.";
  }
  if (status === "failed") {
    return "The latest observed run failed and should be inspected before retrying.";
  }
  return "Recent activity is settled, and this workflow is ready for the next run.";
}

function FlowsWorkspace() {
  const {
    messages,
    sessions,
    selectedWorkflow,
    draftMessage,
    setWorkspaceMode,
    selectWorkflow,
    primeDraftMessage,
  } = useApp();

  const workflowSummary = getWorkflowSummary(messages);
  const [workspaceItems, setWorkspaceItems] = useState<FlowsWorkspaceSummaryItem[]>([]);
  const [workspaceStatus, setWorkspaceStatus] = useState<"loading" | "ready" | "error">(
    "loading"
  );
  const [selectedFlowId, setSelectedFlowId] = useState<string | null>(null);
  const sessionRefreshToken = sessions
    .map((session) => `${session.id}:${session.updated_at}:${session.message_count}`)
    .join("|");

  useEffect(() => {
    let active = true;
    setWorkspaceStatus("loading");

    void getFlowsWorkspaceSummary()
      .then((response) => {
        if (!active) return;
        setWorkspaceItems(response.items);
        setWorkspaceStatus("ready");
      })
      .catch(() => {
        if (!active) return;
        setWorkspaceItems([]);
        setWorkspaceStatus("error");
      });

    return () => {
      active = false;
    };
  }, [sessionRefreshToken]);

  const workspaceSummary = flowsWorkspaceSummaryMap(workspaceItems);
  const flowCards = flowsWorkspaceDefinitions.map((definition) => {
    const summary = workspaceSummary.get(definition.id);
    const quickStart = getQuickStartItem(definition.quickStartId);
    const quickStartActive = quickStart
      ? quickStart.workflowId
        ? selectedWorkflow === quickStart.workflowId
        : !selectedWorkflow && draftMessage === quickStart.draftMessage
      : false;
    const currentWorkflowState =
      definition.workflowId && workflowSummary.workflowId === definition.workflowId
        ? workflowSummary.status
        : null;

    let status: FlowsWorkspaceStatus = summary?.status ?? "idle";
    if (currentWorkflowState === "blocked") {
      status = "blocked";
    } else if (currentWorkflowState === "failed") {
      status = "failed";
    } else if (
      currentWorkflowState === "running" ||
      currentWorkflowState === "not_started" ||
      quickStartActive
    ) {
      status = "active";
    }

    return {
      ...definition,
      status,
      runCount: summary?.run_count ?? 0,
      lastActivityAt: summary?.last_activity_at ?? null,
      quickStart,
    };
  });
  const hasRecordedActivity = flowCards.some((item) => item.runCount > 0);
  const selectedCard =
    flowCards.find((item) => item.id === selectedFlowId) ?? flowCards[0] ?? null;

  useEffect(() => {
    if (flowCards.length === 0) {
      if (selectedFlowId !== null) {
        setSelectedFlowId(null);
      }
      return;
    }

    if (selectedFlowId && flowCards.some((item) => item.id === selectedFlowId)) {
      return;
    }

    setSelectedFlowId(flowCards[0].id);
  }, [flowCards, selectedFlowId]);

  const selectedCardSessionDetail =
    selectedCard?.workflowId &&
    workflowSummary.workflowId === selectedCard.workflowId &&
    workflowSummary.status !== "idle"
      ? describeWorkflow(workflowSummary)
      : null;

  return (
    <WorkspaceShell mode="flows">
      <div className="mx-auto flex w-full max-w-[52rem] flex-col gap-5">
        <div className="flex flex-col gap-4 rounded-[24px] border border-[rgba(223,229,221,0.96)] bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(248,250,246,0.96))] px-5 py-5 shadow-[0_12px_30px_rgba(24,35,27,0.04)] sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h2 className="text-[1.65rem] font-semibold tracking-[-0.03em] text-slate-900">
              Workflows
            </h2>
            <p className="mt-1 text-sm leading-6 text-slate-500">
              Manage and track your analysis workflows.
            </p>
          </div>

          <FlowsPrimaryAction onClick={() => setWorkspaceMode("sessions")}>
            <Plus size={15} />
            New Workflow
          </FlowsPrimaryAction>
        </div>

        {workspaceStatus === "error" ? (
          <EmptyWorkspaceState
            title="Workflow activity could not load"
            description="The Flows workspace could not read recent workflow activity right now. Open the session workspace to continue working, then try again."
            action={
              <WorkspaceAction onClick={() => setWorkspaceMode("sessions")} tone="accent">
                <MessageSquare size={12} />
                Open Session Workspace
              </WorkspaceAction>
            }
          />
        ) : !hasRecordedActivity && workspaceStatus === "ready" ? (
          <EmptyWorkspaceState
            title="No workflow activity yet"
            description="Start a workflow, run an evidence review, or trigger a compliance check and the latest activity will appear here for quick tracking."
            action={
              <FlowsPrimaryAction onClick={() => setWorkspaceMode("sessions")}>
                <Plus size={15} />
                New Workflow
              </FlowsPrimaryAction>
            }
          />
        ) : (
          <div className="space-y-4">
            {flowCards.map((item) => (
              <FlowsWorkspaceCard
                key={item.id}
                label={item.label}
                status={item.status}
                runCount={item.runCount}
                lastActivityAt={item.lastActivityAt}
                selected={selectedCard?.id === item.id}
                onClick={() => setSelectedFlowId(item.id)}
              />
            ))}

            {selectedCard ? (
              <div className="rounded-[22px] border border-[rgba(223,229,221,0.96)] bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(248,250,246,0.96))] p-5 shadow-[0_10px_28px_rgba(18,24,20,0.05)]">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                  <div className="max-w-2xl">
                    <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                      Workflow Detail
                    </p>
                    <h3 className="mt-2 text-xl font-semibold tracking-[-0.02em] text-slate-900">
                      {selectedCard.label}
                    </h3>
                    <p className="mt-2 text-sm leading-6 text-slate-500">
                      {selectedCardSessionDetail ??
                        selectedCard.description ??
                        summarizeFlowsDetail(selectedCard.status)}
                    </p>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    <WorkspaceAction onClick={() => setWorkspaceMode("sessions")}>
                      <MessageSquare size={12} />
                      Open Session
                    </WorkspaceAction>
                    {selectedCard.quickStart ? (
                      <WorkspaceAction
                        onClick={() => {
                          const quickStart = selectedCard.quickStart;
                          if (!quickStart) return;
                          selectWorkflow(quickStart.workflowId ?? null);
                          primeDraftMessage(quickStart.draftMessage);
                          setWorkspaceMode("sessions");
                        }}
                        tone="accent"
                      >
                        <Sparkles size={12} />
                        Prepare In Session
                      </WorkspaceAction>
                    ) : null}
                  </div>
                </div>

                <div className="mt-4 flex flex-wrap gap-2">
                  <WorkspaceBadge icon={FlaskConical}>
                    {summarizeFlowsWorkspaceStatus(selectedCard.status)}
                  </WorkspaceBadge>
                  <WorkspaceBadge icon={Sparkles}>
                    {selectedCard.runCount === 0
                      ? "No runs yet"
                      : `${selectedCard.runCount} run${selectedCard.runCount === 1 ? "" : "s"}`}
                  </WorkspaceBadge>
                  <WorkspaceBadge icon={MessageSquare}>
                    {selectedCard.lastActivityAt
                      ? formatRelativeTime(selectedCard.lastActivityAt)
                      : "No recent activity"}
                  </WorkspaceBadge>
                  {selectedCard.workflowId ? (
                    <WorkspaceBadge icon={FlaskConical}>
                      {selectedCard.workflowId}
                    </WorkspaceBadge>
                  ) : null}
                </div>
              </div>
            ) : null}

            {workspaceStatus === "loading" ? (
              <p className="px-1 text-sm text-slate-500">
                Syncing recent workflow activity…
              </p>
            ) : null}
          </div>
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
  const [documents, setDocuments] = useState<LoadedWorkspaceDocument[]>([]);
  const [failedDocuments, setFailedDocuments] = useState<WorkspaceDocumentFailure[]>(
    []
  );
  const [workspaceStatus, setWorkspaceStatus] =
    useState<DocsWorkspaceStatus>("loading");
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [workspaceWarning, setWorkspaceWarning] = useState<string | null>(null);

  useEffect(() => {
    if (
      workspaceMode === "docs" &&
      inspectorPreviewPath &&
      workspaceDocs.some((item) => item.path === inspectorPreviewPath)
    ) {
      setSelectedDocPath(inspectorPreviewPath);
    }
  }, [inspectorPreviewPath, workspaceMode]);

  useEffect(() => {
    if (workspaceMode !== "docs") return;

    let active = true;
    setWorkspaceStatus("loading");
    setWorkspaceError(null);
    setWorkspaceWarning(null);
    setFailedDocuments([]);

    void Promise.allSettled(
      workspaceDocs.map(async (document) => {
        const response = await readFile(document.path);
        const loadedDocument: LoadedWorkspaceDocument = {
          ...document,
          parsed: parseWorkspaceDocument(response.content, document.label),
        };
        return loadedDocument;
      })
    )
      .then((results) => {
        if (!active) return;

        const loadedDocuments: LoadedWorkspaceDocument[] = [];
        const unreadableDocuments: WorkspaceDocumentFailure[] = [];

        results.forEach((result, index) => {
          const configuredDocument = workspaceDocs[index];
          if (!configuredDocument) return;

          if (result.status === "fulfilled") {
            loadedDocuments.push(result.value);
            return;
          }

          unreadableDocuments.push({
            ...configuredDocument,
            error:
              result.reason instanceof Error
                ? result.reason.message
                : "Unable to read this document right now.",
          });
        });

        setDocuments(loadedDocuments);
        setFailedDocuments(unreadableDocuments);

        if (loadedDocuments.length === 0) {
          setWorkspaceStatus("error");
          setWorkspaceError(
            unreadableDocuments.length === 1
              ? `The Docs workspace could not load ${unreadableDocuments[0]?.label ?? "the configured document"}.`
              : "The Docs workspace could not load any configured documents right now."
          );
          return;
        }

        setWorkspaceStatus("ready");
        if (unreadableDocuments.length > 0) {
          setWorkspaceWarning(
            unreadableDocuments.length === 1
              ? `${unreadableDocuments[0]?.label ?? "One document"} is temporarily unavailable. The remaining docs are still ready to read.`
              : `${unreadableDocuments.length} configured docs are temporarily unavailable. The remaining docs are still ready to read.`
          );
        }
      })
      .catch((error) => {
        if (!active) return;
        setDocuments([]);
        setFailedDocuments([]);
        setWorkspaceStatus("error");
        setWorkspaceError(
          error instanceof Error
            ? error.message
            : "Unable to load documentation right now."
        );
      });

    return () => {
      active = false;
    };
  }, [workspaceMode]);

  useEffect(() => {
    if (documents.length === 0) return;
    if (selectedDocPath && documents.some((document) => document.path === selectedDocPath)) {
      return;
    }

    setSelectedDocPath(documents[0].path);
  }, [documents, selectedDocPath]);

  const selectedDoc =
    documents.find((item) => item.path === selectedDocPath) ?? documents[0] ?? null;

  return (
    <WorkspaceShell mode="docs">
      <WorkspaceHero
        icon={BookOpen}
        title="Documentation"
        description="Read BioAPEX specs, SOPs, and reference material in a workspace built for implementation work instead of a plain file preview."
        badges={
          <>
            <WorkspaceBadge icon={BookOpen}>{`${workspaceDocs.length} docs`}</WorkspaceBadge>
            {selectedDoc ? (
              <WorkspaceBadge icon={FileText}>{selectedDoc.parsed.title}</WorkspaceBadge>
            ) : null}
            {selectedDoc ? <DocumentTypeBadge label={selectedDoc.typeLabel} /> : null}
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
          detail="Protocols, specs, and reference material stay together in one center-workspace surface."
        />
        <SummaryCard
          label="Focused Doc"
          value={selectedDoc?.label ?? "None"}
          detail={
            selectedDoc?.description ??
            "Choose a document to load its structured reading view."
          }
        />
        <SummaryCard
          label="Reading State"
          value={
            workspaceStatus === "ready"
              ? selectedDoc
                ? formatSectionCount(selectedDoc.parsed.sections.length)
                : "Waiting"
              : workspaceStatus === "loading"
                ? "Loading"
                : "Issue"
          }
          detail="The selected document is rendered as section cards so longer specs and protocols remain readable."
        />
      </div>

      <div className="grid min-h-0 gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <DocsNavigatorCard
          status={workspaceStatus}
          documents={documents}
          failedDocuments={failedDocuments}
          selectedPath={selectedDoc?.path ?? null}
          onSelect={(document) => setSelectedDocPath(document.path)}
          error={workspaceError}
        />

        <DocsReaderPane
          status={workspaceStatus}
          document={selectedDoc}
          error={workspaceError}
          warning={workspaceWarning}
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
