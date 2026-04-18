"use client";

import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import {
  FilePreviewSurface,
  useFilePreview,
  type FilePreviewTarget,
} from "@/components/preview/FilePreviewSurface";
import { openRawFileInNewTab } from "@/lib/api";
import { getLatestRequestMessages } from "@/lib/session-status";
import { useApp } from "@/lib/store";
import {
  ActionButton,
  EmptyState,
  InspectorCard,
  MiniStat,
} from "./primitives";
import { collectArtifacts, GeneratedFileRow } from "./artifacts-data";
import { shortenPath } from "./shared-utils";

export default function FilesPanel() {
  const {
    messages,
    isStreaming,
    inspectorPreviewPath,
    openInspectorPath,
    clearInspectorPath,
  } = useApp();

  const [previewActionError, setPreviewActionError] = useState("");

  const latestRequestMessages = getLatestRequestMessages(messages);
  const scopedMessages =
    latestRequestMessages.length > 0 ? latestRequestMessages : messages;
  const artifactItems = collectArtifacts(scopedMessages);
  const selectedArtifactItem =
    artifactItems.find((item) => item.path === inspectorPreviewPath) ?? null;
  const inspectorPreviewTarget: FilePreviewTarget | null = inspectorPreviewPath
    ? {
        path: inspectorPreviewPath,
        displayName:
          selectedArtifactItem?.label ??
          inspectorPreviewPath.split("/").pop() ??
          inspectorPreviewPath,
        artifactType: selectedArtifactItem?.artifactType ?? null,
        outputName: null,
        runId: null,
      }
    : null;
  const preview = useFilePreview(inspectorPreviewTarget);

  useEffect(() => {
    setPreviewActionError("");
  }, [inspectorPreviewPath]);

  const openPreviewRawFile = () => {
    if (!inspectorPreviewPath || typeof window === "undefined") {
      return;
    }

    void openRawFileInNewTab(inspectorPreviewPath).catch(() => {
      setPreviewActionError("Could not open the raw file right now.");
    });
  };

  return (
    <div className="space-y-2">
      <InspectorCard
        title="Current Turn"
        meta={scopedMessages.at(-1)?.request_id ?? undefined}
      >
        {scopedMessages.length > 0 ? (
          <div className="space-y-2 rounded-[12px] border border-[rgba(35,130,83,0.14)] bg-[linear-gradient(180deg,rgba(242,250,245,0.98),rgba(234,247,239,0.98))] px-2.5 py-2.5">
            <div className="grid grid-cols-2 gap-1.5">
              <MiniStat
                label="Messages"
                value={String(scopedMessages.length)}
                accent={isStreaming}
              />
              <MiniStat
                label="Artifacts"
                value={String(artifactItems.length)}
                accent={artifactItems.length > 0}
              />
            </div>

            <p className="text-[11px] leading-5 text-slate-600">
              Generated files and source evidence below are scoped to the latest chat request.
            </p>
          </div>
        ) : (
          <EmptyState>
            Send a message to populate generated files and source detail here.
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
            Generated files will appear here once tool calls materialize inspectable artifacts.
          </EmptyState>
        )}
      </InspectorCard>

      {inspectorPreviewPath ? (
        <InspectorCard
          title="Preview"
          meta={shortenPath(inspectorPreviewPath, 3)}
          controls={
            <>
              <ActionButton onClick={preview.refresh}>
                <RefreshCw size={11} />
                Refresh
              </ActionButton>
              <ActionButton onClick={openPreviewRawFile}>Open raw</ActionButton>
              <ActionButton onClick={clearInspectorPath}>Clear</ActionButton>
            </>
          }
        >
          {previewActionError ? <EmptyState>{previewActionError}</EmptyState> : null}
          <FilePreviewSurface
            target={inspectorPreviewTarget}
            preview={preview}
            emptyMessage="Select a generated file to preview it here."
            compact
            className={previewActionError ? "mt-2" : undefined}
          />
        </InspectorCard>
      ) : null}
    </div>
  );
}
