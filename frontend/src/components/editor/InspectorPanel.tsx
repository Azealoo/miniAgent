"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import { BookOpen, Brain, RefreshCw, Save } from "lucide-react";
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

type Tab = "files" | "sources" | "memory" | "skills" | "usage";
const MEMORY_PATH = "memory/MEMORY.md";

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

  return Array.from(items.values()).reverse().slice(0, 8);
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

function TabButton({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "rounded-full px-3 py-1.5 text-[11px] font-medium transition-colors",
        active
          ? "bg-[var(--apex-accent-soft)] text-[var(--apex-accent-strong)]"
          : "text-slate-500 hover:bg-[var(--panel-soft)] hover:text-slate-700"
      )}
    >
      {label}
    </button>
  );
}

function InspectorCard({
  title,
  meta,
  children,
}: {
  title: string;
  meta?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-[14px] border border-[var(--shell-border)] bg-white px-3 py-3">
      <div className="mb-3 flex items-start justify-between gap-3">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
          {title}
        </h3>
        {meta && <span className="text-[11px] text-slate-400">{meta}</span>}
      </div>
      {children}
    </section>
  );
}

function PreviewPane({ content }: { content: string }) {
  return (
    <pre className="max-h-64 overflow-y-auto whitespace-pre-wrap break-words rounded-[12px] bg-[var(--panel-soft)] px-3 py-3 text-xs leading-6 text-slate-600">
      {content}
    </pre>
  );
}

export default function InspectorPanel() {
  const { currentSessionId, sessions, messages, ragMode } = useApp();

  const [tab, setTab] = useState<Tab>("files");
  const [skills, setSkills] = useState<Skill[]>([]);
  const [tokens, setTokens] = useState<TokenStats | null>(null);
  const [memoryContent, setMemoryContent] = useState("");
  const [savedMemoryContent, setSavedMemoryContent] = useState("");
  const [memoryLoading, setMemoryLoading] = useState(false);
  const [memorySaving, setMemorySaving] = useState(false);
  const [memorySaveMsg, setMemorySaveMsg] = useState("");
  const [skillContent, setSkillContent] = useState("");
  const [savedSkillContent, setSavedSkillContent] = useState("");
  const [selectedSkillPath, setSelectedSkillPath] = useState<string | null>(null);
  const [skillsLoading, setSkillsLoading] = useState(false);
  const [skillSaving, setSkillSaving] = useState(false);
  const [skillSaveMsg, setSkillSaveMsg] = useState("");
  const [editorOpen, setEditorOpen] = useState(false);
  const memoryRequestIdRef = useRef(0);
  const skillsRequestIdRef = useRef(0);

  const isMemoryDirty = memoryContent !== savedMemoryContent;
  const isSkillDirty = skillContent !== savedSkillContent;
  const activeSession =
    sessions.find((session) => session.id === currentSessionId) ?? null;
  const workflowSummary = getWorkflowSummary(messages);
  const artifactItems = collectArtifacts(workflowSummary.events);
  const sourceItems = collectSources(messages);
  const workflowMeta = !workflowSummary.workflowName
    ? "No workflow"
    : workflowSummary.totalSteps !== null
      ? `${workflowSummary.completedSteps}/${workflowSummary.totalSteps} steps`
      : workflowSummary.observedSteps > 0
        ? `${workflowSummary.completedSteps} completed · ${workflowSummary.observedSteps} observed`
        : workflowSummary.status === "blocked"
          ? "Blocked before step execution"
          : "Waiting for step events";

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
    setEditorOpen(false);

    if (tab === "memory") {
      setMemorySaveMsg("");
      void loadMemory();
    }

    if (tab === "skills") {
      setSkillSaveMsg("");
      void refreshSkills();
    }
  }, [tab]); // eslint-disable-line react-hooks/exhaustive-deps

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
    <div className="space-y-3">
      <InspectorCard
        title="Active Run"
        meta={workflowMeta}
      >
        {workflowSummary.workflowName ? (
          <div className="space-y-2 text-sm text-slate-600">
            <p className="font-medium text-slate-800">
              {workflowSummary.workflowName}
            </p>
            <p>
              Status:{" "}
              <span
                className={cn(
                  "font-medium",
                  workflowSummary.status === "blocked"
                    ? "text-[rgb(142,98,29)]"
                    : workflowSummary.status === "running"
                      ? "text-[var(--apex-accent-strong)]"
                      : "text-slate-700"
                )}
              >
                {workflowSummary.status}
              </span>
            </p>
            <p>
              {workflowSummary.currentStep
                ? `Current step: ${workflowSummary.currentStep}`
                : "No step is actively running."}
            </p>
          </div>
        ) : (
          <p className="text-sm leading-6 text-slate-500">
            Send a workflow-oriented request to populate run progress and output artifacts here.
          </p>
        )}
      </InspectorCard>

      <InspectorCard title="Generated" meta={`${artifactItems.length} items`}>
        {artifactItems.length > 0 ? (
          <div className="space-y-2">
            {artifactItems.map((artifact) => (
              <div
                key={artifact.path}
                className="rounded-[12px] bg-[var(--panel-soft)] px-3 py-2"
              >
                <p className="truncate text-sm font-medium text-slate-700">
                  {artifact.label}
                </p>
                <p className="mt-1 text-[11px] text-slate-400">{artifact.meta}</p>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm leading-6 text-slate-500">
            No generated files yet for this session.
          </p>
        )}
      </InspectorCard>

      <InspectorCard title="Session" meta={activeSession?.id ?? "No session"}>
        <div className="space-y-2 text-sm text-slate-600">
          <p>
            {activeSession
              ? activeSession.title
              : "Create or select a session to keep supporting metadata attached to the shell."}
          </p>
          {activeSession && (
            <p>{activeSession.message_count} message(s) recorded.</p>
          )}
        </div>
      </InspectorCard>
    </div>
  );

  const renderSourcesTab = () => (
    <InspectorCard title="Retrieved Sources" meta={`${sourceItems.length} sources`}>
      {sourceItems.length > 0 ? (
        <div className="space-y-2">
          {sourceItems.slice(0, 8).map((source) => (
            <div
              key={source.source}
              className="rounded-[12px] bg-[var(--panel-soft)] px-3 py-2"
            >
              <p className="truncate text-sm font-medium text-slate-700">
                {source.source}
              </p>
              <p className="mt-1 text-[11px] text-slate-400">
                score {source.score.toFixed(3)} · {source.count} hit
                {source.count === 1 ? "" : "s"}
              </p>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm leading-6 text-slate-500">
          No retrieved sources yet. Retrieved evidence will appear here after a RAG-backed response.
        </p>
      )}
    </InspectorCard>
  );

  const renderMemoryTab = () => (
    <InspectorCard title="Memory" meta={MEMORY_PATH}>
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <button
            onClick={loadMemory}
            className="inline-flex items-center gap-1 rounded-full border border-[var(--shell-border)] px-2.5 py-1 text-[11px] font-medium text-slate-500 transition-colors hover:bg-[var(--panel-soft)]"
          >
            <RefreshCw size={12} />
            Refresh
          </button>
          <button
            onClick={() => setEditorOpen((value) => !value)}
            className="inline-flex items-center gap-1 rounded-full border border-[var(--shell-border)] px-2.5 py-1 text-[11px] font-medium text-slate-500 transition-colors hover:bg-[var(--panel-soft)]"
          >
            <Brain size={12} />
            {editorOpen ? "Preview" : "Edit"}
          </button>
        </div>

        <div className="flex items-center gap-2">
          {memorySaveMsg && (
            <span
              className={cn(
                "text-[10px]",
                memorySaveMsg === "Saved" ? "text-emerald-600" : "text-red-500"
              )}
            >
              {memorySaveMsg}
            </span>
          )}

          <button
            onClick={handleMemorySave}
            disabled={!isMemoryDirty || memorySaving}
            className={cn(
              "inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors",
              isMemoryDirty && !memorySaving
                ? "bg-[var(--apex-accent)] text-white hover:bg-[var(--apex-accent-strong)]"
                : "bg-slate-200 text-slate-400 cursor-not-allowed"
            )}
          >
            <Save size={12} />
            {memorySaving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      {memoryLoading ? (
        <div className="rounded-[12px] bg-[var(--panel-soft)] px-3 py-8 text-center text-sm text-slate-400">
          Loading memory…
        </div>
      ) : editorOpen ? (
        <div className="h-[280px] overflow-hidden rounded-[12px] border border-[var(--shell-border)]">
          <MonacoEditor
            height="100%"
            language="markdown"
            value={memoryContent}
            theme="vs"
            onChange={(value) => setMemoryContent(value ?? "")}
            options={{
              minimap: { enabled: false },
              wordWrap: "on",
              fontSize: 12,
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
    <div className="space-y-3">
      <InspectorCard title="Skills" meta={`${skills.length} available`}>
        {skillsLoading && skills.length === 0 ? (
          <p className="text-sm text-slate-400">Loading skills…</p>
        ) : skills.length > 0 ? (
          <div className="space-y-1">
            {skills.map((skill) => (
              <button
                key={skill.path}
                onClick={() => void refreshSkills(skill.path)}
                className={cn(
                  "flex w-full items-center justify-between rounded-[12px] px-3 py-2 text-left text-sm transition-colors",
                  skill.path === selectedSkillPath
                    ? "bg-[var(--apex-accent-soft)] text-[var(--apex-accent-strong)]"
                    : "bg-[var(--panel-soft)] text-slate-600 hover:bg-white"
                )}
              >
                <span className="truncate">{skill.name}</span>
                <span className="text-[11px] text-slate-400">
                  <BookOpen size={12} />
                </span>
              </button>
            ))}
          </div>
        ) : (
          <p className="text-sm leading-6 text-slate-500">
            No skills are currently available to preview.
          </p>
        )}
      </InspectorCard>

      {selectedSkillPath && (
        <InspectorCard title="Skill Preview" meta={selectedSkillPath}>
          <div className="mb-3 flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <button
                onClick={() => void refreshSkills(selectedSkillPath)}
                className="inline-flex items-center gap-1 rounded-full border border-[var(--shell-border)] px-2.5 py-1 text-[11px] font-medium text-slate-500 transition-colors hover:bg-[var(--panel-soft)]"
              >
                <RefreshCw size={12} />
                Refresh
              </button>
              <button
                onClick={() => setEditorOpen((value) => !value)}
                className="inline-flex items-center gap-1 rounded-full border border-[var(--shell-border)] px-2.5 py-1 text-[11px] font-medium text-slate-500 transition-colors hover:bg-[var(--panel-soft)]"
              >
                <BookOpen size={12} />
                {editorOpen ? "Preview" : "Edit"}
              </button>
            </div>

            <div className="flex items-center gap-2">
              {skillSaveMsg && (
                <span
                  className={cn(
                    "text-[10px]",
                    skillSaveMsg === "Saved" ? "text-emerald-600" : "text-red-500"
                  )}
                >
                  {skillSaveMsg}
                </span>
              )}

              <button
                onClick={handleSkillSave}
                disabled={!isSkillDirty || skillSaving}
                className={cn(
                  "inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors",
                  isSkillDirty && !skillSaving
                    ? "bg-[var(--apex-accent)] text-white hover:bg-[var(--apex-accent-strong)]"
                    : "bg-slate-200 text-slate-400 cursor-not-allowed"
                )}
              >
                <Save size={12} />
                {skillSaving ? "Saving…" : "Save"}
              </button>
            </div>
          </div>

          {skillsLoading ? (
            <div className="rounded-[12px] bg-[var(--panel-soft)] px-3 py-8 text-center text-sm text-slate-400">
              Loading skill…
            </div>
          ) : editorOpen ? (
            <div className="h-[280px] overflow-hidden rounded-[12px] border border-[var(--shell-border)]">
              <MonacoEditor
                height="100%"
                language="markdown"
                value={skillContent}
                theme="vs"
                onChange={(value) => setSkillContent(value ?? "")}
                options={{
                  minimap: { enabled: false },
                  wordWrap: "on",
                  fontSize: 12,
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
      )}
    </div>
  );

  const renderUsageTab = () => (
    <div className="space-y-3">
      <InspectorCard title="Usage" meta={currentSessionId ?? "No session"}>
        {tokens ? (
          <div className="grid grid-cols-3 gap-2">
            <div className="rounded-[12px] bg-[var(--panel-soft)] px-3 py-2">
              <p className="text-[10px] uppercase tracking-[0.18em] text-slate-400">
                System
              </p>
              <p className="mt-1 text-sm font-semibold text-slate-700">
                {tokens.system_tokens.toLocaleString()}
              </p>
            </div>
            <div className="rounded-[12px] bg-[var(--panel-soft)] px-3 py-2">
              <p className="text-[10px] uppercase tracking-[0.18em] text-slate-400">
                Messages
              </p>
              <p className="mt-1 text-sm font-semibold text-slate-700">
                {tokens.message_tokens.toLocaleString()}
              </p>
            </div>
            <div className="rounded-[12px] bg-[var(--apex-accent-soft)] px-3 py-2">
              <p className="text-[10px] uppercase tracking-[0.18em] text-[var(--apex-accent-strong)]">
                Total
              </p>
              <p className="mt-1 text-sm font-semibold text-[var(--apex-accent-strong)]">
                {tokens.total_tokens.toLocaleString()}
              </p>
            </div>
          </div>
        ) : (
          <p className="text-sm leading-6 text-slate-500">
            Token usage will appear once a session is selected.
          </p>
        )}
      </InspectorCard>

      <InspectorCard title="Context" meta={ragMode ? "RAG on" : "RAG off"}>
        <div className="space-y-2 text-sm text-slate-600">
          <p>{sessions.length} session(s) available.</p>
          <p>{messages.length} message(s) loaded in the current workspace.</p>
          <p>{ragMode ? "Retrieval is enabled for this shell." : "Retrieval is currently disabled."}</p>
        </div>
      </InspectorCard>
    </div>
  );

  return (
    <aside className="apex-panel flex h-full flex-col overflow-hidden rounded-[18px]">
      <div className="border-b border-[var(--shell-border)] px-3 py-3">
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
          Inspector
        </p>
        <p className="mt-1 text-sm font-semibold text-slate-800">
          {workflowSummary.workflowName ?? activeSession?.title ?? "Supporting context"}
        </p>
      </div>

      <div className="overflow-x-auto border-b border-[var(--shell-border)] px-2 py-2">
        <div className="flex min-w-max gap-1">
          <TabButton active={tab === "files"} label="Files" onClick={() => setTab("files")} />
          <TabButton active={tab === "sources"} label="Sources" onClick={() => setTab("sources")} />
          <TabButton active={tab === "memory"} label="Memory" onClick={() => setTab("memory")} />
          <TabButton active={tab === "skills"} label="Skills" onClick={() => setTab("skills")} />
          <TabButton active={tab === "usage"} label="Usage" onClick={() => setTab("usage")} />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
        {tab === "files" && renderFilesTab()}
        {tab === "sources" && renderSourcesTab()}
        {tab === "memory" && renderMemoryTab()}
        {tab === "skills" && renderSkillsTab()}
        {tab === "usage" && renderUsageTab()}
      </div>
    </aside>
  );
}
