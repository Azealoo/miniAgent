"use client";

import dynamic from "next/dynamic";
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
import { getSessionTokens, listSkills, readFile, saveFile } from "@/lib/api";
import { getWorkflowSummary } from "@/lib/session-status";
import { useApp } from "@/lib/store";
import { cn } from "@/lib/utils";
import type { Message, Skill, TokenStats, WorkflowStreamEvent } from "@/lib/types";

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

type InspectorTabId = (typeof INSPECTOR_TABS)[number]["id"];

function collectArtifacts(events: WorkflowStreamEvent[]) {
  const items = new Map<
    string,
    { path: string; label: string; meta: string }
  >();

  events.forEach((event) => {
    if (event.type === "workflow_artifact") {
      items.set(event.artifact.path, {
        path: event.artifact.path,
        label: event.artifact.path.split("/").pop() ?? event.artifact.path,
        meta: event.output_name ?? event.scope.replaceAll("_", " "),
      });
    }

    if (event.type === "workflow_step_end") {
      event.artifact_refs.forEach((artifact) => {
        items.set(artifact.path, {
          path: artifact.path,
          label: artifact.path.split("/").pop() ?? artifact.path,
          meta: artifact.artifact_type ?? event.step_label,
        });
      });
    }
  });

  return Array.from(items.values()).reverse().slice(0, 12);
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

function formatFileMeta(path: string, meta: string) {
  return [meta, shortenPath(path, 3)].filter(Boolean).join(" · ");
}

function getProgressLabel(summary: ReturnType<typeof getWorkflowSummary>) {
  if (summary.totalSteps !== null) {
    return `${summary.completedSteps}/${summary.totalSteps} steps`;
  }

  if (summary.observedSteps > 0) {
    return `${summary.completedSteps} completed`;
  }

  if (summary.status === "blocked") {
    return "Blocked";
  }

  if (summary.status === "completed") {
    return "Completed";
  }

  return "No run";
}

function getRunDetail(summary: ReturnType<typeof getWorkflowSummary>) {
  if (summary.currentStep) {
    return `Current: ${summary.currentStep}`;
  }

  if (summary.blockedReason) {
    return summary.blockedReason;
  }

  if (summary.status === "completed") {
    return "Run finished.";
  }

  if (summary.status === "running") {
    return "Waiting for the next step update.";
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

function FileRow({
  active,
  label,
  meta,
  onClick,
}: {
  active: boolean;
  label: string;
  meta: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full items-start gap-2 rounded-[10px] border px-2.5 py-2 text-left transition-colors",
        active
          ? "border-[rgba(35,130,83,0.16)] bg-[rgba(35,130,83,0.08)]"
          : "border-transparent bg-[rgba(251,252,248,0.95)] hover:border-[rgba(211,219,210,0.86)] hover:bg-white"
      )}
    >
      <span
        className={cn(
          "mt-0.5 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-[8px]",
          active
            ? "bg-[rgba(35,130,83,0.12)] text-[var(--apex-accent-strong)]"
            : "bg-white text-slate-500"
        )}
      >
        <FileText size={12} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[12px] font-medium text-slate-700">
          {label}
        </span>
        <span className="mt-0.5 block text-[10px] leading-4 text-slate-400">
          {meta}
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
  const [previewLoading, setPreviewLoading] = useState(false);
  const memoryRequestIdRef = useRef(0);
  const skillsRequestIdRef = useRef(0);
  const previewRequestIdRef = useRef(0);

  const isMemoryDirty = memoryContent !== savedMemoryContent;
  const isSkillDirty = skillContent !== savedSkillContent;
  const activeSession =
    sessions.find((session) => session.id === currentSessionId) ?? null;
  const workflowSummary = getWorkflowSummary(messages);
  const artifactItems = collectArtifacts(workflowSummary.events);
  const sourceItems = collectSources(messages);
  const progressLabel = getProgressLabel(workflowSummary);
  const runDetail = getRunDetail(workflowSummary);

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
    setPreviewLoading(true);

    try {
      const res = await readFile(path);
      if (previewRequestIdRef.current !== requestId) return;

      setPreviewContent(res.content);
    } catch {
      if (previewRequestIdRef.current !== requestId) return;

      setPreviewContent("# Could not load file preview");
    } finally {
      if (previewRequestIdRef.current === requestId) {
        setPreviewLoading(false);
      }
    }
  };

  useEffect(() => {
    if (!inspectorPreviewPath) {
      setPreviewContent("");
      setPreviewLoading(false);
      return;
    }

    void loadPreview(inspectorPreviewPath);
  }, [inspectorPreviewPath]);

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
        meta={workflowSummary.workflowId ?? (workflowSummary.workflowName ? "Current workflow" : undefined)}
      >
        {workflowSummary.workflowName ? (
          <div className="space-y-2">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="truncate text-[12px] font-semibold text-slate-800">
                  {workflowSummary.workflowName}
                </p>
                <p className="mt-0.5 text-[10px] uppercase tracking-[0.16em] text-slate-400">
                  Progress
                </p>
              </div>
              <p className="shrink-0 text-[12px] font-semibold text-slate-700">
                {progressLabel}
              </p>
            </div>
            <p className="text-[11px] leading-5 text-slate-500">{runDetail}</p>
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
              <FileRow
                key={artifact.path}
                active={inspectorPreviewPath === artifact.path}
                label={artifact.label}
                meta={formatFileMeta(artifact.path, artifact.meta)}
                onClick={() => openInspectorPath(artifact.path)}
              />
            ))}
          </div>
        ) : (
          <EmptyState>No generated files yet for this session.</EmptyState>
        )}
      </InspectorCard>

      {inspectorPreviewPath ? (
        <InspectorCard
          title="Preview"
          meta={shortenPath(inspectorPreviewPath, 3)}
          controls={
            <>
              <ActionButton onClick={() => void loadPreview(inspectorPreviewPath)}>
                <RefreshCw size={11} />
                Refresh
              </ActionButton>
              <ActionButton onClick={clearInspectorPath}>Clear</ActionButton>
            </>
          }
        >
          {previewLoading ? (
            <LoadingState label="Loading preview..." />
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
