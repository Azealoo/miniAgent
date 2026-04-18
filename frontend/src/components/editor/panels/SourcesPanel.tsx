"use client";

import { useEffect, useRef, useState } from "react";
import {
  parseEvidenceArtifactMetadata,
  type EvidenceArtifactMetadata,
} from "@/lib/evidence";
import { readFile } from "@/lib/api";
import { useApp } from "@/lib/store";
import { cn } from "@/lib/utils";
import { EmptyState } from "./primitives";
import { pluralize } from "./shared-utils";
import {
  ChecklistRow,
  SourceCitationRow,
  buildSourcesInspectorSummary,
  collectSourceInspectorData,
  getChecklistBadgeClass,
  getChecklistCardClass,
  mergeSourceItemWithMetadata,
} from "./sources-data";

export default function SourcesPanel() {
  const { messages, openInspectorPath } = useApp();
  const [sourceArtifactMetadata, setSourceArtifactMetadata] = useState<
    Record<string, EvidenceArtifactMetadata | null>
  >({});
  const sourceMetadataRequestIdRef = useRef(0);

  const sourceInspectorData = collectSourceInspectorData(messages);
  const reviewedSourceItems = sourceInspectorData.reviewedItems.map((item) =>
    item.path
      ? mergeSourceItemWithMetadata(item, sourceArtifactMetadata[item.path])
      : item
  );
  const sourcesSummary = buildSourcesInspectorSummary({
    scopedMessages: sourceInspectorData.scopedMessages,
    reviewedItems: reviewedSourceItems,
    retrievedItems: sourceInspectorData.retrievedItems,
  });

  useEffect(() => {
    const pendingPaths = reviewedSourceItems
      .filter(
        (item) =>
          item.kind === "evidence" &&
          item.artifactType === "evidence_card" &&
          item.path &&
          !Object.prototype.hasOwnProperty.call(sourceArtifactMetadata, item.path)
      )
      .map((item) => item.path as string);

    if (pendingPaths.length === 0) {
      return;
    }

    const requestId = sourceMetadataRequestIdRef.current + 1;
    sourceMetadataRequestIdRef.current = requestId;

    void Promise.all(
      pendingPaths.map(async (path) => {
        try {
          const res = await readFile(path);
          return {
            path,
            metadata: parseEvidenceArtifactMetadata(path, res.content),
          };
        } catch {
          return { path, metadata: null };
        }
      })
    ).then((entries) => {
      if (sourceMetadataRequestIdRef.current !== requestId) {
        return;
      }

      setSourceArtifactMetadata((current) => {
        const next = { ...current };
        entries.forEach(({ path, metadata }) => {
          next[path] = metadata;
        });
        return next;
      });
    });
  }, [reviewedSourceItems, sourceArtifactMetadata]);

  return (
    <div className="space-y-3">
      <section className="space-y-2">
        <div className="flex items-baseline justify-between gap-2 px-0.5">
          <h3 className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
            Citations
          </h3>
          {sourcesSummary.scoped_message_count > 0 ? (
            <span className="text-[10px] text-slate-400">
              {pluralize(sourcesSummary.scoped_message_count, "message")}
            </span>
          ) : null}
        </div>

        {sourcesSummary.citations.length > 0 ? (
          <div className="space-y-1">
            {sourcesSummary.citations.map((citation) => (
              <SourceCitationRow
                key={citation.id}
                citation={citation}
                onInspect={openInspectorPath}
              />
            ))}
          </div>
        ) : (
          <EmptyState>
            No reviewed evidence or retrieval-backed citations are linked to the current turn yet. Evidence retrieval and evidence review outputs will populate this view.
          </EmptyState>
        )}
      </section>

      <section
        className={cn(
          "rounded-[16px] border px-3 py-3 shadow-[0_1px_2px_rgba(32,43,35,0.03)]",
          getChecklistCardClass(sourcesSummary.checklist.state)
        )}
      >
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <h3 className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--apex-accent-strong)]">
              Source checklist
            </h3>
            {sourcesSummary.checklist.detail &&
            sourcesSummary.checklist.state !== "complete" ? (
              <p className="mt-1 text-[10px] leading-4 text-slate-500">
                {sourcesSummary.checklist.detail}
              </p>
            ) : null}
          </div>
          {sourcesSummary.checklist.summary_label ? (
            <span
              className={cn(
                "inline-flex shrink-0 items-center rounded-full border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.08em]",
                getChecklistBadgeClass(sourcesSummary.checklist.state)
              )}
            >
              {sourcesSummary.checklist.summary_label}
            </span>
          ) : null}
        </div>

        <div className="mt-3 space-y-2">
          {sourcesSummary.checklist.items.map((item) => (
            <ChecklistRow key={item.id} item={item} />
          ))}
        </div>
      </section>
    </div>
  );
}
