"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import {
  BookOpen,
  Copy,
  Pencil,
  Plus,
  RefreshCw,
  Save,
  Trash2,
} from "lucide-react";
import { openRawFileInNewTab, readFile, saveFile } from "@/lib/api";
import { useApp } from "@/lib/store";
import {
  ActionButton,
  EmptyState,
  LoadingState,
  MemoryCardActionButton,
  MetaBadge,
  PreviewPane,
  PrimaryActionButton,
  WideActionButton,
} from "./primitives";
import {
  MEMORY_PATH,
  duplicateMemoryDocumentItem,
  parseMemoryDocument,
  removeMemoryDocumentItem,
  serializeMemoryDocument,
  upsertMemoryDocumentItem,
} from "./memory-document";
import { pluralize, uniqueStrings } from "./shared-utils";
import type { MemoryInspectorItem, MemoryItemDraft } from "./types";

const MonacoEditor = dynamic(() => import("@monaco-editor/react"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full items-center justify-center text-sm text-slate-400">
      Loading editor…
    </div>
  ),
});

export default function MemoryPanel() {
  const {
    accessByScope,
    hasInspectionAccess,
    inspectorTab,
    openInspectorPath,
    setInspectorTab,
  } = useApp();

  const [memoryContent, setMemoryContent] = useState("");
  const [savedMemoryContent, setSavedMemoryContent] = useState("");
  const [memoryLoadError, setMemoryLoadError] = useState("");
  const [memoryLoading, setMemoryLoading] = useState(false);
  const [memorySaving, setMemorySaving] = useState(false);
  const [memorySaveMsg, setMemorySaveMsg] = useState("");
  const [memoryActionMsg, setMemoryActionMsg] = useState("");
  const [memoryItemDraft, setMemoryItemDraft] = useState<MemoryItemDraft | null>(null);
  const [memoryFileOpen, setMemoryFileOpen] = useState(false);
  const [memoryEditorOpen, setMemoryEditorOpen] = useState(false);

  const memoryRequestIdRef = useRef(0);
  const hasLoadedMemoryRef = useRef(false);
  const inspectionAccessStatus = accessByScope.inspection.status;

  const isMemoryDirty = memoryContent !== savedMemoryContent;
  const parsedMemoryDocument = parseMemoryDocument(memoryContent);
  const memoryItems = parsedMemoryDocument.items;
  const showMemorySaveAction = !memoryLoadError && (isMemoryDirty || memorySaving);
  const memoryNamespaces = uniqueStrings([
    ...memoryItems.map((item) => item.namespace),
    memoryItemDraft?.namespace ?? null,
  ]);

  const confirmDiscardChanges = (targetLabel: string) => {
    if (typeof window === "undefined") {
      return false;
    }
    return window.confirm(
      `Discard unsaved memory edits and load ${targetLabel} from disk?`
    );
  };

  const canReloadMemory = () =>
    !isMemoryDirty || confirmDiscardChanges(MEMORY_PATH);

  const loadMemory = async () => {
    const requestId = memoryRequestIdRef.current + 1;
    memoryRequestIdRef.current = requestId;
    setMemoryLoading(true);
    setMemoryLoadError("");

    if (!hasInspectionAccess) {
      setMemoryContent("");
      setSavedMemoryContent("");
      setMemoryItemDraft(null);
      setMemoryFileOpen(false);
      setMemoryEditorOpen(false);
      setMemorySaveMsg("");
      setMemoryActionMsg("");
      setMemoryLoadError(accessByScope.inspection.detail);
      hasLoadedMemoryRef.current = false;
      setMemoryLoading(false);
      return;
    }

    try {
      const res = await readFile(MEMORY_PATH);
      if (memoryRequestIdRef.current !== requestId) return;

      setMemoryContent(res.content);
      setSavedMemoryContent(res.content);
      setMemoryLoadError("");
      hasLoadedMemoryRef.current = true;
    } catch {
      if (memoryRequestIdRef.current !== requestId) return;

      setMemoryContent("");
      setSavedMemoryContent("");
      setMemoryItemDraft(null);
      setMemoryFileOpen(false);
      setMemoryEditorOpen(false);
      setMemorySaveMsg("");
      setMemoryActionMsg("");
      setMemoryLoadError(`Could not load \`${MEMORY_PATH}\`.`);
      hasLoadedMemoryRef.current = true;
    } finally {
      if (memoryRequestIdRef.current === requestId) {
        setMemoryLoading(false);
      }
    }
  };

  useEffect(() => {
    if (
      inspectionAccessStatus === "granted" ||
      inspectionAccessStatus === "checking" ||
      inspectionAccessStatus === "unavailable"
    ) {
      return;
    }

    hasLoadedMemoryRef.current = false;
  }, [inspectionAccessStatus]);

  useEffect(() => {
    setMemoryFileOpen(false);
    setMemoryEditorOpen(false);

    if (inspectorTab === "memory") {
      setMemorySaveMsg("");
      setMemoryActionMsg("");
      if (
        inspectionAccessStatus !== "granted" &&
        inspectionAccessStatus !== "checking" &&
        inspectionAccessStatus !== "unavailable" &&
        !hasLoadedMemoryRef.current
      ) {
        void loadMemory();
      }
    }
  }, [inspectorTab]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!hasInspectionAccess) {
      return;
    }

    if (inspectorTab === "memory" && !hasLoadedMemoryRef.current) {
      void loadMemory();
    }
  }, [hasInspectionAccess, inspectorTab]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (
      inspectionAccessStatus === "granted" ||
      inspectionAccessStatus === "checking" ||
      inspectionAccessStatus === "unavailable"
    ) {
      return;
    }

    setMemoryContent("");
    setSavedMemoryContent("");
    setMemoryItemDraft(null);
    setMemoryFileOpen(false);
    setMemoryEditorOpen(false);
    setMemorySaveMsg("");
    setMemoryActionMsg("");
    setMemoryLoadError(accessByScope.inspection.detail);
  }, [accessByScope.inspection.detail, inspectionAccessStatus]);

  const openRawFile = (path: string) => {
    if (typeof window === "undefined") {
      return;
    }

    void openRawFileInNewTab(path).catch(() => {
      setMemoryActionMsg("Raw file unavailable");
      window.setTimeout(() => setMemoryActionMsg(""), 2000);
    });
  };

  const inspectPathInFiles = (path: string) => {
    openInspectorPath(path);
    setInspectorTab("files");
  };

  const flashMemoryAction = (message: string) => {
    setMemoryActionMsg(message);
    window.setTimeout(() => setMemoryActionMsg(""), 2000);
  };

  const handleMemoryRefresh = async () => {
    if (!canReloadMemory()) {
      return;
    }

    setMemoryItemDraft(null);
    await loadMemory();
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

  const startMemoryItemDraft = (item?: MemoryInspectorItem) => {
    setMemoryFileOpen(false);
    setMemoryEditorOpen(false);
    setMemoryItemDraft(
      item
        ? {
            mode: "edit",
            targetId: item.id,
            namespace: item.namespace,
            key: item.key,
            value: item.value,
          }
        : {
            mode: "create",
            targetId: null,
            namespace: memoryItems[0]?.namespace ?? "General",
            key: "",
            value: "",
          }
    );
  };

  const handleMemoryDraftSave = () => {
    if (!memoryItemDraft) {
      return;
    }

    if (!memoryItemDraft.key.trim() && !memoryItemDraft.value.trim()) {
      flashMemoryAction("Add a key or value first");
      return;
    }

    const nextDocument = upsertMemoryDocumentItem(parsedMemoryDocument, memoryItemDraft);
    setMemoryContent(serializeMemoryDocument(nextDocument));
    setMemoryItemDraft(null);
    flashMemoryAction(
      memoryItemDraft.mode === "create" ? "Memory item added" : "Memory item updated"
    );
  };

  const handleMemoryItemDelete = (itemId: string) => {
    const nextDocument = removeMemoryDocumentItem(parsedMemoryDocument, itemId);
    setMemoryContent(serializeMemoryDocument(nextDocument));
    if (memoryItemDraft?.targetId === itemId) {
      setMemoryItemDraft(null);
    }
    flashMemoryAction("Memory item removed");
  };

  const handleMemoryItemDuplicate = (itemId: string) => {
    const nextDocument = duplicateMemoryDocumentItem(parsedMemoryDocument, itemId);
    setMemoryContent(serializeMemoryDocument(nextDocument));
    flashMemoryAction("Memory item duplicated");
  };

  return (
    <div className="space-y-3">
      <div className="flex items-start justify-between gap-2 px-0.5">
        <div className="min-w-0">
          <h3 className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
            Context Memory
          </h3>
          <p className="mt-1 truncate text-[10px] leading-4 text-slate-500">
            Synced to `{MEMORY_PATH}`
          </p>
        </div>

        <div className="flex shrink-0 flex-wrap items-center justify-end gap-1">
          <ActionButton onClick={() => void handleMemoryRefresh()}>
            <RefreshCw size={11} />
            Refresh
          </ActionButton>
          <ActionButton
            onClick={() => {
              if (memoryLoadError) {
                openRawFile(MEMORY_PATH);
                return;
              }

              setMemoryFileOpen((value) => !value);
              setMemoryEditorOpen(false);
            }}
          >
            <BookOpen size={11} />
            {memoryLoadError ? "Open raw" : memoryFileOpen ? "Hide file" : "Raw file"}
          </ActionButton>
          {showMemorySaveAction ? (
            <PrimaryActionButton
              onClick={() => void handleMemorySave()}
              disabled={!isMemoryDirty || memorySaving}
            >
              <Save size={11} />
              {memorySaving ? "Saving…" : "Save"}
            </PrimaryActionButton>
          ) : null}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-1.5 px-0.5">
        {memoryLoadError ? (
          <MetaBadge tone="warning">Load issue</MetaBadge>
        ) : (
          <>
            <MetaBadge tone={isMemoryDirty ? "warning" : "success"}>
              {isMemoryDirty ? "Unsaved edits" : "File synced"}
            </MetaBadge>
            <MetaBadge>{pluralize(memoryItems.length, "item")}</MetaBadge>
            {memoryItemDraft ? <MetaBadge tone="accent">Draft open</MetaBadge> : null}
          </>
        )}
        {memorySaveMsg ? (
          <MetaBadge tone={memorySaveMsg === "Saved" ? "success" : "warning"}>
            {memorySaveMsg}
          </MetaBadge>
        ) : null}
        {memoryActionMsg ? <MetaBadge tone="accent">{memoryActionMsg}</MetaBadge> : null}
      </div>

      {memoryLoading ? (
        <LoadingState label="Loading memory..." />
      ) : memoryLoadError ? (
        <div className="space-y-2">
          <EmptyState>
            {memoryLoadError} Structured memory editing is paused until the file can
            be read again.
          </EmptyState>

          <div className="rounded-[16px] border border-[rgba(211,219,210,0.86)] bg-[rgba(251,252,248,0.92)] px-3 py-3">
            <p className="text-[10px] leading-4 text-slate-500">
              Use the raw file or Files inspector if you need to inspect the path
              directly, then refresh this tab once `memory/MEMORY.md` is reachable
              again.
            </p>

            <div className="mt-2 flex flex-wrap gap-1.5">
              <ActionButton onClick={() => openRawFile(MEMORY_PATH)}>
                Open raw
              </ActionButton>
              <ActionButton onClick={() => inspectPathInFiles(MEMORY_PATH)}>
                Inspect
              </ActionButton>
            </div>
          </div>
        </div>
      ) : (
        <>
          {memoryItemDraft ? (
            <div className="rounded-[16px] border border-[rgba(35,130,83,0.16)] bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(248,251,248,0.98))] px-3 py-3 shadow-[0_1px_2px_rgba(32,43,35,0.03)]">
              <div className="flex items-center justify-between gap-2">
                <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--apex-accent-strong)]">
                  {memoryItemDraft.mode === "create" ? "Add Memory Item" : "Edit Memory Item"}
                </p>
                <MetaBadge tone="warning">Draft</MetaBadge>
              </div>

              <div className="mt-3 space-y-2">
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                    Namespace
                  </label>
                  <input
                    list="memory-namespaces"
                    value={memoryItemDraft.namespace}
                    onChange={(event) =>
                      setMemoryItemDraft((current) =>
                        current
                          ? { ...current, namespace: event.target.value }
                          : current
                      )
                    }
                    className="w-full rounded-[12px] border border-[rgba(211,219,210,0.9)] bg-white px-3 py-2 text-[12px] text-slate-700 outline-none focus:border-[var(--apex-accent)]"
                  />
                  {memoryNamespaces.length > 0 ? (
                    <datalist id="memory-namespaces">
                      {memoryNamespaces.map((namespace) => (
                        <option key={namespace} value={namespace} />
                      ))}
                    </datalist>
                  ) : null}
                </div>

                <div className="space-y-1">
                  <label className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                    Key
                  </label>
                  <input
                    value={memoryItemDraft.key}
                    onChange={(event) =>
                      setMemoryItemDraft((current) =>
                        current
                          ? { ...current, key: event.target.value }
                          : current
                      )
                    }
                    className="w-full rounded-[12px] border border-[rgba(211,219,210,0.9)] bg-white px-3 py-2 text-[12px] text-slate-700 outline-none focus:border-[var(--apex-accent)]"
                    placeholder="dataset"
                  />
                </div>

                <div className="space-y-1">
                  <label className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                    Value
                  </label>
                  <textarea
                    rows={4}
                    value={memoryItemDraft.value}
                    onChange={(event) =>
                      setMemoryItemDraft((current) =>
                        current
                          ? { ...current, value: event.target.value }
                          : current
                      )
                    }
                    className="w-full rounded-[12px] border border-[rgba(211,219,210,0.9)] bg-white px-3 py-2 text-[12px] leading-5 text-slate-700 outline-none focus:border-[var(--apex-accent)]"
                    placeholder="BRCA1_cohort_v2"
                  />
                </div>
              </div>

              <div className="mt-3 flex items-center justify-end gap-1.5">
                <ActionButton onClick={() => setMemoryItemDraft(null)}>
                  Cancel
                </ActionButton>
                <PrimaryActionButton onClick={handleMemoryDraftSave}>
                  <Save size={11} />
                  Apply
                </PrimaryActionButton>
              </div>
            </div>
          ) : null}

          {memoryItems.length > 0 ? (
            <div className="space-y-2.5">
              {memoryItems.map((item) => (
                <div
                  key={item.id}
                  className="rounded-[18px] border border-[rgba(219,226,216,0.94)] bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(251,252,248,0.98))] px-3.5 py-3.5 shadow-[0_1px_3px_rgba(32,43,35,0.04)]"
                >
                  <div className="flex items-start justify-between gap-3">
                    <p className="min-w-0 truncate font-mono text-[11px] font-semibold text-[var(--apex-accent-strong)]">
                      {item.namespace}/{item.key}
                    </p>
                    <MetaBadge tone="success">ACTIVE</MetaBadge>
                  </div>

                  <p className="mt-3 break-words font-mono text-[15px] leading-6 text-slate-700">
                    {item.value || item.key}
                  </p>

                  <div className="mt-3 flex items-center gap-1">
                    <MemoryCardActionButton
                      onClick={() => startMemoryItemDraft(item)}
                      title="Edit memory item"
                    >
                      <Pencil size={16} />
                    </MemoryCardActionButton>
                    <MemoryCardActionButton
                      onClick={() => handleMemoryItemDuplicate(item.id)}
                      title="Duplicate memory item"
                    >
                      <Copy size={16} />
                    </MemoryCardActionButton>
                    <div className="ml-auto">
                      <MemoryCardActionButton
                        onClick={() => handleMemoryItemDelete(item.id)}
                        title="Delete memory item"
                        tone="danger"
                      >
                        <Trash2 size={16} />
                      </MemoryCardActionButton>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState>
              No structured memory items are available yet. Add an item here or
              open the raw file when you want to shape `MEMORY.md` directly.
            </EmptyState>
          )}

          <WideActionButton onClick={() => startMemoryItemDraft()}>
            <Plus size={13} />
            Add Item
          </WideActionButton>

          {memoryFileOpen ? (
            <div className="rounded-[16px] border border-[rgba(211,219,210,0.86)] bg-[rgba(251,252,248,0.92)] px-3 py-3">
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                    Underlying File
                  </p>
                  <p className="mt-1 truncate text-[10px] leading-4 text-slate-500">
                    {MEMORY_PATH}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <ActionButton onClick={() => setMemoryEditorOpen((value) => !value)}>
                    <BookOpen size={11} />
                    {memoryEditorOpen ? "Preview" : "Edit"}
                  </ActionButton>
                </div>
              </div>

              <p className="mt-2 text-[10px] leading-4 text-slate-500">
                Structured card edits write back to this markdown file so memory
                retrieval and file inspection stay aligned.
              </p>

              <div className="mt-2 flex flex-wrap gap-1.5">
                <ActionButton onClick={() => openRawFile(MEMORY_PATH)}>
                  Open raw
                </ActionButton>
                <ActionButton onClick={() => inspectPathInFiles(MEMORY_PATH)}>
                  Inspect
                </ActionButton>
              </div>

              <div className="mt-2">
                {memoryEditorOpen ? (
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
                  <PreviewPane content={memoryContent} className="max-h-[220px]" />
                )}
              </div>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
