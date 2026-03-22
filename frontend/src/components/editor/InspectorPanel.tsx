"use client";

import dynamic from "next/dynamic";
import Image from "next/image";
import {
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  BookOpen,
  Brain,
  FileText,
  Hash,
  RefreshCw,
  Save,
  Search,
  Sparkles,
} from "lucide-react";
import {
  getRawFileUrl,
  getSessionTokens,
  listSkills,
  readFile,
  saveFile,
} from "@/lib/api";
import { getWorkflowSummary } from "@/lib/session-status";
import { useApp } from "@/lib/store";
import { cn } from "@/lib/utils";
import type {
  Message,
  Skill,
  TokenStats,
  WorkflowArtifactScope,
  WorkflowStreamEvent,
} from "@/lib/types";

const MonacoEditor = dynamic(() => import("@monaco-editor/react"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full items-center justify-center text-sm text-slate-400">
      Loading editor…
    </div>
  ),
});

const MEMORY_PATH = "memory/MEMORY.md";
const INSPECTOR_TABS = [
  { id: "files", label: "Files", icon: FileText },
  { id: "sources", label: "Sources", icon: Search },
  { id: "memory", label: "Memory", icon: Brain },
  { id: "skills", label: "Skills", icon: Sparkles },
  { id: "usage", label: "Usage", icon: Hash },
] as const;

type GeneratedArtifactItem = {
  path: string;
  label: string;
  artifactType: string | null;
  scope: WorkflowArtifactScope | null;
  outputName: string | null;
  stepLabel: string | null;
  lastSeenOrder: number;
};

type GeneratedArtifactKind =
  | "table"
  | "plot"
  | "structured"
  | "report"
  | "archive"
  | "file";

type InspectorPreviewMode = "text" | "image" | "pdf" | "unsupported";

function humanizeToken(value?: string | null): string | null {
  if (!value) return null;
  return value.replaceAll("_", " ").replaceAll("-", " ");
}

function getFileExtension(path: string): string | null {
  const fileName = path.split("/").pop() ?? path;
  const index = fileName.lastIndexOf(".");
  if (index <= 0 || index === fileName.length - 1) {
    return null;
  }
  return fileName.slice(index).toLowerCase();
}

function getInspectorPreviewMode(path: string): InspectorPreviewMode {
  const extension = getFileExtension(path);

  if (
    extension === ".png" ||
    extension === ".jpg" ||
    extension === ".jpeg" ||
    extension === ".svg"
  ) {
    return "image";
  }

  if (extension === ".pdf") {
    return "pdf";
  }

  if (
    extension === ".zip" ||
    extension === ".gz" ||
    extension === ".tgz" ||
    extension === ".tar" ||
    extension === ".tif" ||
    extension === ".tiff" ||
    extension === ".xlsx" ||
    extension === ".xls" ||
    extension === ".parquet" ||
    extension === ".mtx"
  ) {
    return "unsupported";
  }

  return "text";
}

function getUnsupportedPreviewMessage(path: string): string {
  const extension = getFileExtension(path);

  if (
    extension === ".zip" ||
    extension === ".gz" ||
    extension === ".tgz" ||
    extension === ".tar"
  ) {
    return "Archive previews are not available in the inspector yet. Use Open raw to inspect or download the artifact.";
  }

  if (extension === ".tif" || extension === ".tiff") {
    return "This image format is not previewed inline in the inspector yet. Use Open raw to inspect the artifact.";
  }

  if (
    extension === ".xlsx" ||
    extension === ".xls" ||
    extension === ".parquet" ||
    extension === ".mtx"
  ) {
    return "This generated table format is not previewed inline yet. Use Open raw to inspect the artifact.";
  }

  return "This file is not previewed inline in the inspector yet. Use Open raw to inspect the artifact.";
}

function shouldShowGeneratedArtifact(item: {
  path: string;
  artifactType: string | null;
  scope: WorkflowArtifactScope | null;
}): boolean {
  if (!item.path) {
    return false;
  }

  if (item.scope === "run_record") {
    return false;
  }

  if (item.artifactType === "workflow_run") {
    return false;
  }

  return true;
}

function collectArtifacts(events: WorkflowStreamEvent[]) {
  const items = new Map<string, GeneratedArtifactItem>();
  let order = 0;

  const upsertArtifact = ({
    path,
    artifactType,
    scope,
    outputName,
    stepLabel,
  }: {
    path: string;
    artifactType?: string | null;
    scope?: WorkflowArtifactScope | null;
    outputName?: string | null;
    stepLabel?: string | null;
  }) => {
    const existing = items.get(path);
    const nextItem: GeneratedArtifactItem = {
      path,
      label: path.split("/").pop() ?? path,
      artifactType: artifactType ?? existing?.artifactType ?? null,
      scope: scope ?? existing?.scope ?? null,
      outputName: outputName ?? existing?.outputName ?? null,
      stepLabel: stepLabel ?? existing?.stepLabel ?? null,
      lastSeenOrder: order,
    };
    order += 1;

    if (!shouldShowGeneratedArtifact(nextItem)) {
      return;
    }

    items.set(path, nextItem);
  };

  events.forEach((event) => {
    if (event.type === "workflow_artifact") {
      upsertArtifact({
        path: event.artifact.path,
        artifactType: event.artifact.artifact_type,
        scope: event.scope,
        outputName: event.output_name,
        stepLabel: event.step_label,
      });
    }

    if (event.type === "workflow_step_end") {
      event.artifact_refs.forEach((artifact) => {
        upsertArtifact({
          path: artifact.path,
          artifactType: artifact.artifact_type,
          outputName: null,
          stepLabel: event.step_label,
        });
      });
    }
  });

  return Array.from(items.values())
    .sort((left, right) => right.lastSeenOrder - left.lastSeenOrder)
    .slice(0, 12);
}

function inferGeneratedArtifactKind(item: GeneratedArtifactItem): GeneratedArtifactKind {
  const extension = getFileExtension(item.path);
  const artifactType = item.artifactType?.toLowerCase() ?? "";
  const outputName = item.outputName?.toLowerCase() ?? "";
  const label = item.label.toLowerCase();

  if (
    extension === ".csv" ||
    extension === ".tsv" ||
    extension === ".xlsx" ||
    extension === ".xls" ||
    extension === ".parquet" ||
    extension === ".mtx" ||
    artifactType.includes("matrix") ||
    artifactType.includes("results") ||
    outputName.includes("table") ||
    label.includes("matrix")
  ) {
    return "table";
  }

  if (
    extension === ".png" ||
    extension === ".jpg" ||
    extension === ".jpeg" ||
    extension === ".svg" ||
    extension === ".tif" ||
    extension === ".tiff" ||
    artifactType === "figure" ||
    outputName.includes("plot") ||
    outputName.includes("figure")
  ) {
    return "plot";
  }

  if (
    extension === ".html" ||
    extension === ".pdf" ||
    extension === ".md" ||
    artifactType.includes("report")
  ) {
    return "report";
  }

  if (
    extension === ".json" ||
    extension === ".yaml" ||
    extension === ".yml" ||
    artifactType.includes("manifest") ||
    artifactType.includes("summary") ||
    artifactType.includes("metrics")
  ) {
    return "structured";
  }

  if (
    extension === ".zip" ||
    extension === ".gz" ||
    extension === ".tgz" ||
    extension === ".tar"
  ) {
    return "archive";
  }

  return "file";
}

function getGeneratedArtifactCue(item: GeneratedArtifactItem) {
  const extension = getFileExtension(item.path);
  const kind = inferGeneratedArtifactKind(item);

  if (extension === ".json") {
    return { kind, label: "JSON" };
  }

  if (extension === ".yaml" || extension === ".yml") {
    return { kind, label: "YAML" };
  }

  if (extension === ".csv") {
    return { kind, label: "CSV" };
  }

  if (extension === ".tsv") {
    return { kind, label: "TSV" };
  }

  if (extension === ".html") {
    return { kind, label: "HTML" };
  }

  if (extension === ".pdf") {
    return { kind, label: "PDF" };
  }

  if (extension === ".md") {
    return { kind, label: "MD" };
  }

  if (kind === "table") {
    return { kind, label: "Table" };
  }

  if (kind === "plot") {
    return { kind, label: "Plot" };
  }

  if (kind === "report") {
    return { kind, label: "Report" };
  }

  if (kind === "structured") {
    return { kind, label: "Data" };
  }

  if (kind === "archive") {
    return { kind, label: "Archive" };
  }

  return { kind, label: "File" };
}

function getGeneratedArtifactTone(kind: GeneratedArtifactKind) {
  if (kind === "table") {
    return {
      badge: "border-amber-200 bg-amber-50 text-amber-700",
      icon: "bg-amber-50 text-amber-700",
      active:
        "border-amber-200 bg-[linear-gradient(180deg,rgba(255,251,235,0.95),rgba(254,243,199,0.72))]",
      idle: "border-[rgba(245,158,11,0.14)] bg-[rgba(255,251,235,0.68)]",
    };
  }

  if (kind === "plot") {
    return {
      badge: "border-rose-200 bg-rose-50 text-rose-700",
      icon: "bg-rose-50 text-rose-700",
      active:
        "border-rose-200 bg-[linear-gradient(180deg,rgba(255,241,242,0.96),rgba(255,228,230,0.74))]",
      idle: "border-[rgba(244,63,94,0.12)] bg-[rgba(255,244,246,0.7)]",
    };
  }

  if (kind === "report") {
    return {
      badge: "border-emerald-200 bg-emerald-50 text-emerald-700",
      icon: "bg-emerald-50 text-emerald-700",
      active:
        "border-emerald-200 bg-[linear-gradient(180deg,rgba(236,253,245,0.96),rgba(209,250,229,0.72))]",
      idle: "border-[rgba(16,185,129,0.12)] bg-[rgba(240,253,244,0.72)]",
    };
  }

  if (kind === "structured") {
    return {
      badge: "border-sky-200 bg-sky-50 text-sky-700",
      icon: "bg-sky-50 text-sky-700",
      active:
        "border-sky-200 bg-[linear-gradient(180deg,rgba(240,249,255,0.96),rgba(224,242,254,0.74))]",
      idle: "border-[rgba(14,165,233,0.12)] bg-[rgba(240,249,255,0.7)]",
    };
  }

  if (kind === "archive") {
    return {
      badge: "border-slate-200 bg-slate-100 text-slate-600",
      icon: "bg-slate-100 text-slate-600",
      active:
        "border-slate-300 bg-[linear-gradient(180deg,rgba(248,250,252,0.96),rgba(241,245,249,0.82))]",
      idle: "border-[rgba(148,163,184,0.14)] bg-[rgba(248,250,252,0.78)]",
    };
  }

  return {
    badge: "border-stone-200 bg-stone-50 text-stone-700",
    icon: "bg-stone-50 text-stone-700",
    active:
      "border-stone-200 bg-[linear-gradient(180deg,rgba(250,250,249,0.96),rgba(245,245,244,0.82))]",
    idle: "border-[rgba(168,162,158,0.14)] bg-[rgba(250,250,249,0.76)]",
  };
}

function getGeneratedArtifactDetail(item: GeneratedArtifactItem): string {
  const values = [
    humanizeToken(item.outputName),
    humanizeToken(item.artifactType),
    humanizeToken(item.stepLabel),
  ].filter((value): value is string => Boolean(value));

  const uniqueValues = values.filter(
    (value, index) => values.indexOf(value) === index
  );

  return uniqueValues[0] ?? "Generated artifact";
}

function getGeneratedArtifactScopeLabel(item: GeneratedArtifactItem): string | null {
  return humanizeToken(item.scope);
}

function collectSources(messages: Message[]) {
  const sources = new Map<
    string,
    { source: string; score: number; count: number }
  >();

  messages.forEach((message) => {
    (message.retrievals ?? []).forEach((result) => {
      const existing = sources.get(result.source);
      if (existing) {
        existing.score = Math.max(existing.score, result.score);
        existing.count += 1;
      } else {
        sources.set(result.source, {
          source: result.source,
          score: result.score,
          count: 1,
        });
      }
    });
  });

  return Array.from(sources.values()).sort((a, b) => b.score - a.score);
}

function shortenPath(path: string, maxSegments = 2) {
  const normalized = path.replaceAll("\\", "/");
  const segments = normalized.split("/").filter(Boolean);

  if (segments.length <= maxSegments) {
    return normalized;
  }

  return `.../${segments.slice(-maxSegments).join("/")}`;
}

function getRunStatusLabel(summary: ReturnType<typeof getWorkflowSummary>) {
  if (summary.status === "not_started") {
    return "Not started";
  }

  if (summary.status === "running") {
    return "In progress";
  }

  if (summary.status === "blocked") {
    return "Blocked";
  }

  if (summary.status === "failed") {
    return "Failed";
  }

  if (summary.status === "completed") {
    return "Completed";
  }

  return "Idle";
}

function getRunStatusClass(summary: ReturnType<typeof getWorkflowSummary>) {
  if (summary.status === "completed") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }

  if (summary.status === "blocked" || summary.status === "failed") {
    return "border-rose-200 bg-rose-50 text-rose-700";
  }

  if (summary.status === "not_started") {
    return "border-slate-200 bg-slate-50 text-slate-600";
  }

  return "border-[rgba(35,130,83,0.18)] bg-[rgba(35,130,83,0.1)] text-[var(--apex-accent-strong)]";
}

function getRunSurfaceClass(summary: ReturnType<typeof getWorkflowSummary>) {
  if (summary.status === "completed") {
    return "border-emerald-100 bg-[linear-gradient(180deg,rgba(244,251,247,0.98),rgba(237,249,241,0.98))]";
  }

  if (summary.status === "blocked" || summary.status === "failed") {
    return "border-rose-100 bg-[linear-gradient(180deg,rgba(255,247,247,0.98),rgba(254,241,241,0.98))]";
  }

  if (summary.status === "not_started") {
    return "border-slate-200 bg-[linear-gradient(180deg,rgba(249,250,251,0.98),rgba(245,247,249,0.98))]";
  }

  return "border-[rgba(35,130,83,0.14)] bg-[linear-gradient(180deg,rgba(242,250,245,0.98),rgba(234,247,239,0.98))]";
}

function getStepCountLabel(summary: ReturnType<typeof getWorkflowSummary>) {
  if (summary.totalSteps !== null) {
    return `${summary.completedSteps}/${summary.totalSteps}`;
  }

  if (summary.observedSteps > 0) {
    return `${summary.completedSteps}/${summary.observedSteps}`;
  }

  return "0";
}

function getProgressLabel(summary: ReturnType<typeof getWorkflowSummary>) {
  if (summary.currentStep) {
    return summary.currentStep;
  }

  if (summary.status === "not_started") {
    return summary.lifecycleStatus === "preflight_checked"
      ? "Preflight checked"
      : "Waiting for first step";
  }

  if (summary.status === "running") {
    return summary.observedSteps > 0 ? "Awaiting next step" : "Starting workflow";
  }

  if (summary.status === "blocked") {
    return "Action required";
  }

  if (summary.status === "failed") {
    return "Run halted";
  }

  if (summary.status === "completed") {
    return "All steps finished";
  }

  return null;
}

function getRunDetail(summary: ReturnType<typeof getWorkflowSummary>) {
  if (summary.currentStep) {
    return `Current: ${summary.currentStep}`;
  }

  if (summary.blockedReason) {
    return summary.blockedReason;
  }

  if (summary.failureReason) {
    return summary.failureReason;
  }

  if (summary.status === "not_started") {
    return summary.totalSteps !== null
      ? `Run is staged with ${summary.totalSteps} step${summary.totalSteps === 1 ? "" : "s"} and waiting to begin.`
      : "Run is staged and waiting for the first workflow step.";
  }

  if (summary.status === "completed") {
    return "Run finished.";
  }

  if (summary.status === "running") {
    return "Waiting for the next step update.";
  }

  if (summary.status === "failed") {
    return "The latest workflow run failed.";
  }

  return "No active workflow step yet.";
}

function TabButton({
  active,
  icon: Icon,
  label,
  onClick,
}: {
  active: boolean;
  icon: typeof FileText;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex min-h-[42px] flex-col items-center justify-center gap-0.5 rounded-[10px] border px-1 py-1 text-center transition-colors",
        active
          ? "border-[rgba(35,130,83,0.18)] bg-[rgba(35,130,83,0.1)] text-[var(--apex-accent-strong)]"
          : "border-transparent text-slate-500 hover:border-[var(--shell-border)] hover:bg-white/80 hover:text-slate-700"
      )}
    >
      <Icon size={12} strokeWidth={1.75} />
      <span className="text-[9px] font-medium leading-tight">{label}</span>
    </button>
  );
}

function InspectorCard({
  title,
  meta,
  controls,
  children,
}: {
  title: string;
  meta?: string;
  controls?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rounded-[14px] border border-[rgba(211,219,210,0.86)] bg-[rgba(255,255,255,0.88)] px-2.5 py-2.5 shadow-[0_1px_2px_rgba(32,43,35,0.03)] backdrop-blur-sm">
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-[9px] font-semibold uppercase tracking-[0.18em] text-slate-400">
            {title}
          </h3>
          {meta ? (
            <p className="mt-0.5 truncate text-[10px] leading-4 text-slate-500">
              {meta}
            </p>
          ) : null}
        </div>
        {controls ? (
          <div className="flex shrink-0 items-center gap-1">{controls}</div>
        ) : null}
      </div>
      {children}
    </section>
  );
}

function ActionButton({
  onClick,
  disabled,
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium transition-colors",
        disabled
          ? "cursor-not-allowed border-[var(--shell-border)] bg-[rgba(247,249,245,0.92)] text-slate-400"
          : "border-[var(--shell-border)] bg-white/85 text-slate-500 hover:bg-[var(--panel-soft)] hover:text-slate-700"
      )}
    >
      {children}
    </button>
  );
}

function MiniStat({
  label,
  value,
  accent = false,
}: {
  label: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-[10px] border px-2.5 py-2",
        accent
          ? "border-[rgba(35,130,83,0.14)] bg-[rgba(35,130,83,0.08)]"
          : "border-[rgba(211,219,210,0.72)] bg-[rgba(251,252,248,0.9)]"
      )}
    >
      <p
        className={cn(
          "text-[9px] font-semibold uppercase tracking-[0.16em]",
          accent ? "text-[var(--apex-accent-strong)]" : "text-slate-400"
        )}
      >
        {label}
      </p>
      <p
        className={cn(
          "mt-0.5 text-xs font-semibold",
          accent ? "text-[var(--apex-accent-strong)]" : "text-slate-700"
        )}
      >
        {value}
      </p>
    </div>
  );
}

function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-[12px] border border-dashed border-[rgba(211,219,210,0.92)] bg-[rgba(251,252,248,0.78)] px-2.5 py-3 text-[11px] leading-5 text-slate-500">
      {children}
    </div>
  );
}

function GeneratedFileRow({
  item,
  active,
  onClick,
}: {
  item: GeneratedArtifactItem;
  active: boolean;
  onClick: () => void;
}) {
  const cue = getGeneratedArtifactCue(item);
  const tone = getGeneratedArtifactTone(cue.kind);
  const detail = getGeneratedArtifactDetail(item);
  const scopeLabel = getGeneratedArtifactScopeLabel(item);

  return (
    <button
      type="button"
      onClick={onClick}
      title={item.path}
      className={cn(
        "flex w-full items-start gap-2 rounded-[12px] border px-2.5 py-2 text-left transition-colors",
        active
          ? tone.active
          : `${tone.idle} hover:border-[rgba(211,219,210,0.9)] hover:bg-white`
      )}
    >
      <span
        className={cn(
          "mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-[9px]",
          tone.icon
        )}
      >
        <FileText size={12} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-start justify-between gap-2">
          <span className="min-w-0 truncate text-[12px] font-semibold text-slate-700">
            {item.label}
          </span>
          <span
            className={cn(
              "inline-flex shrink-0 items-center rounded-full border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.08em]",
              tone.badge
            )}
          >
            {cue.label}
          </span>
        </span>
        <span className="mt-1 flex min-w-0 items-center gap-1.5">
          <span className="truncate text-[10px] font-medium text-slate-500">
            {detail}
          </span>
          {scopeLabel ? (
            <span className="shrink-0 rounded-full bg-white/80 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-[0.08em] text-slate-400">
              {scopeLabel}
            </span>
          ) : null}
        </span>
        <span className="mt-1 block truncate font-mono text-[9px] text-slate-400">
          {shortenPath(item.path, 4)}
        </span>
      </span>
    </button>
  );
}

function PreviewPane({
  content,
  className,
}: {
  content: string;
  className?: string;
}) {
  return (
    <pre
      className={cn(
        "max-h-[360px] overflow-y-auto whitespace-pre-wrap break-words rounded-[12px] border border-[rgba(211,219,210,0.8)] bg-[rgba(248,250,246,0.96)] px-2.5 py-2.5 text-[11px] leading-5 text-slate-600",
        className
      )}
    >
      {content}
    </pre>
  );
}

function ImagePreview({
  src,
  alt,
}: {
  src: string;
  alt: string;
}) {
  return (
    <div className="overflow-hidden rounded-[12px] border border-[rgba(211,219,210,0.8)] bg-[rgba(248,250,246,0.96)] p-2">
      <Image
        src={src}
        alt={alt}
        width={1600}
        height={900}
        unoptimized
        className="max-h-[360px] h-auto w-full rounded-[10px] object-contain"
      />
    </div>
  );
}

function FramePreview({
  src,
  title,
}: {
  src: string;
  title: string;
}) {
  return (
    <div className="overflow-hidden rounded-[12px] border border-[rgba(211,219,210,0.8)] bg-[rgba(248,250,246,0.96)]">
      <iframe
        src={src}
        title={title}
        className="h-[360px] w-full bg-white"
      />
    </div>
  );
}

function LoadingState({ label }: { label: string }) {
  return (
    <div className="rounded-[12px] border border-dashed border-[rgba(211,219,210,0.92)] bg-[rgba(251,252,248,0.78)] px-2.5 py-5 text-center text-[11px] text-slate-400">
      {label}
    </div>
  );
}

export default function InspectorPanel() {
  const {
    currentSessionId,
    sessions,
    messages,
    ragMode,
    inspectorTab,
    inspectorPreviewPath,
    setInspectorTab,
    openInspectorPath,
    clearInspectorPath,
  } = useApp();

  const [skills, setSkills] = useState<Skill[]>([]);
  const [tokens, setTokens] = useState<TokenStats | null>(null);
  const [memoryContent, setMemoryContent] = useState("");
  const [savedMemoryContent, setSavedMemoryContent] = useState("");
  const [memoryLoading, setMemoryLoading] = useState(false);
  const [memorySaving, setMemorySaving] = useState(false);
  const [memorySaveMsg, setMemorySaveMsg] = useState("");
  const [memoryEditorOpen, setMemoryEditorOpen] = useState(false);
  const [skillContent, setSkillContent] = useState("");
  const [savedSkillContent, setSavedSkillContent] = useState("");
  const [selectedSkillPath, setSelectedSkillPath] = useState<string | null>(null);
  const [skillsLoading, setSkillsLoading] = useState(false);
  const [skillSaving, setSkillSaving] = useState(false);
  const [skillSaveMsg, setSkillSaveMsg] = useState("");
  const [skillEditorOpen, setSkillEditorOpen] = useState(false);
  const [previewContent, setPreviewContent] = useState("");
  const [previewError, setPreviewError] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const memoryRequestIdRef = useRef(0);
  const skillsRequestIdRef = useRef(0);
  const previewRequestIdRef = useRef(0);

  const isMemoryDirty = memoryContent !== savedMemoryContent;
  const isSkillDirty = skillContent !== savedSkillContent;
  const activeSession =
    sessions.find((session) => session.id === currentSessionId) ?? null;
  const workflowSummary = getWorkflowSummary(messages);
  const hasActiveRun = workflowSummary.events.length > 0;
  const artifactItems = collectArtifacts(workflowSummary.events);
  const sourceItems = collectSources(messages);
  const runStatusLabel = getRunStatusLabel(workflowSummary);
  const stepCountLabel = getStepCountLabel(workflowSummary);
  const progressLabel = getProgressLabel(workflowSummary);
  const runDetail = getRunDetail(workflowSummary);
  const previewMode = inspectorPreviewPath
    ? getInspectorPreviewMode(inspectorPreviewPath)
    : null;
  const previewRawUrl = inspectorPreviewPath
    ? getRawFileUrl(inspectorPreviewPath)
    : null;

  useEffect(() => {
    if (!currentSessionId) {
      setTokens(null);
      return;
    }

    getSessionTokens(currentSessionId)
      .then(setTokens)
      .catch(() => setTokens(null));
  }, [currentSessionId]);

  useEffect(() => {
    setMemoryEditorOpen(false);
    setSkillEditorOpen(false);

    if (inspectorTab === "memory") {
      setMemorySaveMsg("");
      void loadMemory();
    }

    if (inspectorTab === "skills") {
      setSkillSaveMsg("");
      void refreshSkills();
    }
  }, [inspectorTab]); // eslint-disable-line react-hooks/exhaustive-deps

  const loadMemory = async () => {
    const requestId = memoryRequestIdRef.current + 1;
    memoryRequestIdRef.current = requestId;
    setMemoryLoading(true);

    try {
      const res = await readFile(MEMORY_PATH);
      if (memoryRequestIdRef.current !== requestId) return;

      setMemoryContent(res.content);
      setSavedMemoryContent(res.content);
    } catch {
      if (memoryRequestIdRef.current !== requestId) return;

      setMemoryContent("# Could not load MEMORY.md");
      setSavedMemoryContent("# Could not load MEMORY.md");
    } finally {
      if (memoryRequestIdRef.current === requestId) {
        setMemoryLoading(false);
      }
    }
  };

  const refreshSkills = async (preferredPath?: string) => {
    const requestId = skillsRequestIdRef.current + 1;
    skillsRequestIdRef.current = requestId;
    setSkillsLoading(true);

    let nextPath: string | null = preferredPath ?? selectedSkillPath;

    try {
      const nextSkills = await listSkills();
      if (skillsRequestIdRef.current !== requestId) return;

      setSkills(nextSkills);

      if (nextSkills.length === 0) {
        setSelectedSkillPath(null);
        setSkillContent("# No skills found");
        setSavedSkillContent("# No skills found");
        return;
      }

      nextPath =
        preferredPath ??
        (selectedSkillPath &&
        nextSkills.some((skill) => skill.path === selectedSkillPath)
          ? selectedSkillPath
          : nextSkills[0].path);

      setSelectedSkillPath(nextPath);

      const res = await readFile(nextPath);
      if (skillsRequestIdRef.current !== requestId) return;

      setSkillContent(res.content);
      setSavedSkillContent(res.content);
    } catch {
      if (skillsRequestIdRef.current !== requestId) return;

      setSelectedSkillPath(nextPath);
      setSkillContent("# Could not load skill file");
      setSavedSkillContent("# Could not load skill file");
    } finally {
      if (skillsRequestIdRef.current === requestId) {
        setSkillsLoading(false);
      }
    }
  };

  const loadPreview = async (path: string) => {
    const requestId = previewRequestIdRef.current + 1;
    previewRequestIdRef.current = requestId;
    setPreviewContent("");
    setPreviewError("");

    if (getInspectorPreviewMode(path) !== "text") {
      setPreviewLoading(false);
      return;
    }

    setPreviewLoading(true);

    try {
      const res = await readFile(path);
      if (previewRequestIdRef.current !== requestId) return;

      setPreviewContent(res.content);
    } catch {
      if (previewRequestIdRef.current !== requestId) return;

      setPreviewError(
        "Could not load file preview. Use Open raw to inspect the artifact."
      );
    } finally {
      if (previewRequestIdRef.current === requestId) {
        setPreviewLoading(false);
      }
    }
  };

  useEffect(() => {
    if (!inspectorPreviewPath) {
      setPreviewContent("");
      setPreviewError("");
      setPreviewLoading(false);
      return;
    }

    void loadPreview(inspectorPreviewPath);
  }, [inspectorPreviewPath]);

  const openPreviewRawFile = () => {
    if (!previewRawUrl || typeof window === "undefined") {
      return;
    }

    window.open(previewRawUrl, "_blank", "noopener,noreferrer");
  };

  const handleMemorySave = async () => {
    if (!isMemoryDirty) return;

    setMemorySaving(true);
    setMemorySaveMsg("");

    try {
      await saveFile(MEMORY_PATH, memoryContent);
      setSavedMemoryContent(memoryContent);
      setMemorySaveMsg("Saved");
      setTimeout(() => setMemorySaveMsg(""), 2000);
    } catch {
      setMemorySaveMsg("Save failed");
    } finally {
      setMemorySaving(false);
    }
  };

  const handleSkillSave = async () => {
    if (!selectedSkillPath || !isSkillDirty) return;

    setSkillSaving(true);
    setSkillSaveMsg("");

    try {
      await saveFile(selectedSkillPath, skillContent);
      setSavedSkillContent(skillContent);
      setSkillSaveMsg("Saved");
      setTimeout(() => setSkillSaveMsg(""), 2000);
    } catch {
      setSkillSaveMsg("Save failed");
    } finally {
      setSkillSaving(false);
    }
  };

  const renderFilesTab = () => (
    <div className="space-y-2">
      <InspectorCard
        title="Active Run"
        meta={workflowSummary.workflowId ?? (hasActiveRun ? "Current workflow run" : undefined)}
      >
        {hasActiveRun ? (
          <div
            className={cn(
              "space-y-2 rounded-[12px] border px-2.5 py-2.5",
              getRunSurfaceClass(workflowSummary)
            )}
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="truncate text-[12px] font-semibold text-slate-800">
                  {workflowSummary.workflowName ?? workflowSummary.workflowId ?? "Workflow run"}
                </p>
                {progressLabel ? (
                  <p className="mt-0.5 truncate text-[10px] leading-4 text-slate-500">
                    {progressLabel}
                  </p>
                ) : null}
              </div>
              <span
                className={cn(
                  "inline-flex shrink-0 items-center rounded-full border px-2 py-1 text-[10px] font-semibold",
                  getRunStatusClass(workflowSummary)
                )}
              >
                {runStatusLabel}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-1.5">
              <MiniStat
                label="Steps"
                value={stepCountLabel}
                accent={workflowSummary.status === "running"}
              />
              <MiniStat
                label="State"
                value={runStatusLabel}
                accent={
                  workflowSummary.status === "running" ||
                  workflowSummary.status === "completed"
                }
              />
            </div>

            <p className="text-[11px] leading-5 text-slate-600">{runDetail}</p>
          </div>
        ) : (
          <EmptyState>
            Send a workflow-oriented request to populate run progress and generated files here.
          </EmptyState>
        )}
      </InspectorCard>

      <InspectorCard
        title="Generated"
        meta={`${artifactItems.length} item${artifactItems.length === 1 ? "" : "s"}`}
      >
        {artifactItems.length > 0 ? (
          <div className="space-y-1">
            {artifactItems.map((artifact) => (
              <GeneratedFileRow
                key={artifact.path}
                item={artifact}
                active={inspectorPreviewPath === artifact.path}
                onClick={() => openInspectorPath(artifact.path)}
              />
            ))}
          </div>
        ) : (
          <EmptyState>
            Generated workflow outputs will appear here once a step materializes inspectable artifacts.
          </EmptyState>
        )}
      </InspectorCard>

      {inspectorPreviewPath ? (
        <InspectorCard
          title="Preview"
          meta={shortenPath(inspectorPreviewPath, 3)}
          controls={
            <>
              {previewMode === "text" ? (
                <ActionButton onClick={() => void loadPreview(inspectorPreviewPath)}>
                  <RefreshCw size={11} />
                  Refresh
                </ActionButton>
              ) : null}
              <ActionButton onClick={openPreviewRawFile}>Open raw</ActionButton>
              <ActionButton onClick={clearInspectorPath}>Clear</ActionButton>
            </>
          }
        >
          {previewLoading ? (
            <LoadingState label="Loading preview..." />
          ) : previewMode === "image" && previewRawUrl ? (
            <ImagePreview
              src={previewRawUrl}
              alt={inspectorPreviewPath.split("/").pop() ?? "Generated artifact"}
            />
          ) : previewMode === "pdf" && previewRawUrl ? (
            <FramePreview
              src={previewRawUrl}
              title={inspectorPreviewPath.split("/").pop() ?? "Generated artifact"}
            />
          ) : previewMode === "unsupported" ? (
            <EmptyState>{getUnsupportedPreviewMessage(inspectorPreviewPath)}</EmptyState>
          ) : previewError ? (
            <EmptyState>{previewError}</EmptyState>
          ) : (
            <PreviewPane content={previewContent} />
          )}
        </InspectorCard>
      ) : null}
    </div>
  );

  const renderSourcesTab = () => (
    <div className="space-y-2">
      <InspectorCard
        title="Retrieved Sources"
        meta={`${sourceItems.length} source${sourceItems.length === 1 ? "" : "s"}`}
      >
        {sourceItems.length > 0 ? (
          <div className="space-y-1">
            {sourceItems.slice(0, 10).map((source) => (
              <div
                key={source.source}
                className="rounded-[10px] border border-[rgba(211,219,210,0.72)] bg-[rgba(251,252,248,0.92)] px-2.5 py-2"
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="min-w-0 truncate text-[12px] font-medium text-slate-700">
                    {source.source}
                  </p>
                  <span className="shrink-0 text-[10px] font-medium text-slate-400">
                    {source.score.toFixed(3)}
                  </span>
                </div>
                <p className="mt-0.5 text-[10px] leading-4 text-slate-400">
                  {source.count} hit{source.count === 1 ? "" : "s"} in this session
                </p>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState>
            No retrieved sources yet. Retrieved evidence will appear here after a RAG-backed response.
          </EmptyState>
        )}
      </InspectorCard>

      <InspectorCard title="Retrieval Context" meta={ragMode ? "RAG on" : "RAG off"}>
        <div className="space-y-1 text-[11px] text-slate-600">
          <p>{messages.length} message(s) loaded in the current workspace.</p>
          <p>
            {ragMode
              ? "Retrieved evidence is enabled for the active shell."
              : "Retrieved evidence is currently disabled for this shell."}
          </p>
        </div>
      </InspectorCard>
    </div>
  );

  const renderMemoryTab = () => (
    <InspectorCard
      title="Memory"
      meta={MEMORY_PATH}
      controls={
        <>
          <ActionButton onClick={() => void loadMemory()}>
            <RefreshCw size={11} />
            Refresh
          </ActionButton>
          <ActionButton onClick={() => setMemoryEditorOpen((value) => !value)}>
            <Brain size={11} />
            {memoryEditorOpen ? "Preview" : "Edit"}
          </ActionButton>
        </>
      }
    >
      <div className="mb-2 flex items-center justify-end gap-2">
        {memorySaveMsg ? (
          <span
            className={cn(
              "text-[10px]",
              memorySaveMsg === "Saved" ? "text-emerald-600" : "text-red-500"
            )}
          >
            {memorySaveMsg}
          </span>
        ) : null}
        <button
          type="button"
          onClick={() => void handleMemorySave()}
          disabled={!isMemoryDirty || memorySaving}
          className={cn(
            "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium transition-colors",
            isMemoryDirty && !memorySaving
              ? "bg-[var(--apex-accent)] text-white hover:bg-[var(--apex-accent-strong)]"
              : "cursor-not-allowed bg-slate-200 text-slate-400"
          )}
        >
          <Save size={11} />
          {memorySaving ? "Saving…" : "Save"}
        </button>
      </div>

      {memoryLoading ? (
        <LoadingState label="Loading memory..." />
      ) : memoryEditorOpen ? (
        <div className="h-[220px] overflow-hidden rounded-[12px] border border-[rgba(211,219,210,0.86)] bg-white">
          <MonacoEditor
            height="100%"
            language="markdown"
            value={memoryContent}
            theme="vs"
            onChange={(value) => setMemoryContent(value ?? "")}
            options={{
              minimap: { enabled: false },
              wordWrap: "on",
              fontSize: 11,
              lineNumbers: "on",
              scrollBeyondLastLine: false,
              overviewRulerLanes: 0,
              padding: { top: 10, bottom: 10 },
              fontFamily: '"SF Mono", "Fira Code", Consolas, monospace',
            }}
          />
        </div>
      ) : (
        <PreviewPane content={memoryContent} />
      )}
    </InspectorCard>
  );

  const renderSkillsTab = () => (
    <div className="space-y-2">
      <InspectorCard
        title="Skills"
        meta={`${skills.length} available`}
        controls={
          <ActionButton onClick={() => void refreshSkills(selectedSkillPath ?? undefined)}>
            <RefreshCw size={11} />
            Refresh
          </ActionButton>
        }
      >
        {skillsLoading && skills.length === 0 ? (
          <LoadingState label="Loading skills..." />
        ) : skills.length > 0 ? (
          <div className="space-y-1">
            {skills.map((skill) => (
              <button
                key={skill.path}
                type="button"
                onClick={() => void refreshSkills(skill.path)}
                className={cn(
                  "flex w-full items-center gap-2 rounded-[10px] border px-2.5 py-2 text-left transition-colors",
                  skill.path === selectedSkillPath
                    ? "border-[rgba(35,130,83,0.16)] bg-[rgba(35,130,83,0.08)] text-[var(--apex-accent-strong)]"
                    : "border-transparent bg-[rgba(251,252,248,0.95)] text-slate-600 hover:border-[rgba(211,219,210,0.86)] hover:bg-white"
                )}
              >
                <span
                  className={cn(
                    "mt-0.5 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-[8px]",
                    skill.path === selectedSkillPath
                      ? "bg-[rgba(35,130,83,0.12)]"
                      : "bg-white"
                  )}
                >
                  <Sparkles size={12} />
                </span>
                <span className="min-w-0 flex-1 truncate text-[12px] font-medium">
                  {skill.name}
                </span>
              </button>
            ))}
          </div>
        ) : (
          <EmptyState>No skills are currently available to preview.</EmptyState>
        )}
      </InspectorCard>

      {selectedSkillPath ? (
        <InspectorCard
          title="Skill Preview"
          meta={shortenPath(selectedSkillPath, 3)}
          controls={
            <>
              <ActionButton onClick={() => void refreshSkills(selectedSkillPath)}>
                <RefreshCw size={11} />
                Refresh
              </ActionButton>
              <ActionButton onClick={() => setSkillEditorOpen((value) => !value)}>
                <BookOpen size={11} />
                {skillEditorOpen ? "Preview" : "Edit"}
              </ActionButton>
            </>
          }
        >
          <div className="mb-2 flex items-center justify-end gap-2">
            {skillSaveMsg ? (
              <span
                className={cn(
                  "text-[10px]",
                  skillSaveMsg === "Saved" ? "text-emerald-600" : "text-red-500"
                )}
              >
                {skillSaveMsg}
              </span>
            ) : null}
            <button
              type="button"
              onClick={() => void handleSkillSave()}
              disabled={!isSkillDirty || skillSaving}
              className={cn(
                "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium transition-colors",
                isSkillDirty && !skillSaving
                  ? "bg-[var(--apex-accent)] text-white hover:bg-[var(--apex-accent-strong)]"
                  : "cursor-not-allowed bg-slate-200 text-slate-400"
              )}
            >
              <Save size={11} />
              {skillSaving ? "Saving…" : "Save"}
            </button>
          </div>

          {skillsLoading ? (
            <LoadingState label="Loading skill..." />
          ) : skillEditorOpen ? (
            <div className="h-[220px] overflow-hidden rounded-[12px] border border-[rgba(211,219,210,0.86)] bg-white">
              <MonacoEditor
                height="100%"
                language="markdown"
                value={skillContent}
                theme="vs"
                onChange={(value) => setSkillContent(value ?? "")}
                options={{
                  minimap: { enabled: false },
                  wordWrap: "on",
                  fontSize: 11,
                  lineNumbers: "on",
                  scrollBeyondLastLine: false,
                  overviewRulerLanes: 0,
                  padding: { top: 10, bottom: 10 },
                  fontFamily: '"SF Mono", "Fira Code", Consolas, monospace',
                }}
              />
            </div>
          ) : (
            <PreviewPane content={skillContent} />
          )}
        </InspectorCard>
      ) : null}
    </div>
  );

  const renderUsageTab = () => (
    <div className="space-y-2">
      <InspectorCard title="Usage" meta={currentSessionId ?? "No session"}>
        {tokens ? (
          <div className="grid grid-cols-2 gap-2">
            <MiniStat label="System" value={tokens.system_tokens.toLocaleString()} />
            <MiniStat label="Messages" value={tokens.message_tokens.toLocaleString()} />
            <div className="col-span-2">
              <MiniStat
                label="Total"
                value={tokens.total_tokens.toLocaleString()}
                accent
              />
            </div>
          </div>
        ) : (
          <EmptyState>Token usage will appear once a session is selected.</EmptyState>
        )}
      </InspectorCard>

      <InspectorCard title="Context" meta={ragMode ? "RAG on" : "RAG off"}>
        <div className="space-y-1 text-[11px] text-slate-600">
          <p>{sessions.length} session(s) available.</p>
          <p>{messages.length} message(s) loaded in the current workspace.</p>
          <p>{activeSession ? activeSession.title : "No active session selected."}</p>
        </div>
      </InspectorCard>
    </div>
  );

  return (
    <aside className="apex-panel apex-panel-muted flex h-full flex-col overflow-hidden rounded-[18px]">
      <div className="border-b border-[var(--shell-border)] bg-white/70 px-2 py-1.5">
        <div className="grid grid-cols-5 gap-0.5">
          {INSPECTOR_TABS.map((tab) => (
            <TabButton
              key={tab.id}
              active={inspectorTab === tab.id}
              icon={tab.icon}
              label={tab.label}
              onClick={() => setInspectorTab(tab.id)}
            />
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
        {inspectorTab === "files" && renderFilesTab()}
        {inspectorTab === "sources" && renderSourcesTab()}
        {inspectorTab === "memory" && renderMemoryTab()}
        {inspectorTab === "skills" && renderSkillsTab()}
        {inspectorTab === "usage" && renderUsageTab()}
      </div>
    </aside>
  );
}
