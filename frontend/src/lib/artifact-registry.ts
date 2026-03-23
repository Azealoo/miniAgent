"use client";

import { getFilePreviewDescriptor } from "./file-preview";
import type { ArtifactRegistryQuery, ArtifactRegistryRecord } from "./types";

export interface ArtifactRegistryFilterState {
  run_id: string;
  artifact_type: string;
  workflow: string;
  date: string;
  dataset_id: string;
  include_invalid: boolean;
}

export const DEFAULT_ARTIFACT_REGISTRY_FILTERS: ArtifactRegistryFilterState = {
  run_id: "",
  artifact_type: "",
  workflow: "",
  date: "",
  dataset_id: "",
  include_invalid: false,
};

export type ArtifactRegistryPreviewMode =
  | "text"
  | "markdown"
  | "json"
  | "html"
  | "image"
  | "pdf"
  | "unsupported";

function uniqueStrings(values: Array<string | null | undefined>): string[] {
  return values.filter((value, index, array): value is string => {
    if (!value) return false;
    return array.indexOf(value) === index;
  });
}

export function humanizeArtifactToken(value?: string | null): string | null {
  if (!value) return null;
  return value.replaceAll("_", " ").replaceAll("-", " ");
}

export function normalizeArtifactRegistryQuery(
  filters: ArtifactRegistryFilterState
): ArtifactRegistryQuery {
  const normalizeValue = (value: string): string | undefined => {
    const trimmed = value.trim();
    return trimmed || undefined;
  };

  return {
    run_id: normalizeValue(filters.run_id),
    artifact_type: normalizeValue(filters.artifact_type),
    workflow: normalizeValue(filters.workflow),
    date: normalizeValue(filters.date),
    dataset_id: normalizeValue(filters.dataset_id),
    include_invalid: filters.include_invalid,
  };
}

export function artifactRegistryHasActiveFilters(
  filters: ArtifactRegistryFilterState
): boolean {
  return Boolean(
    filters.run_id.trim() ||
      filters.artifact_type.trim() ||
      filters.workflow.trim() ||
      filters.date.trim() ||
      filters.dataset_id.trim() ||
      filters.include_invalid
  );
}

export function getArtifactRegistryDisplayName(
  record: ArtifactRegistryRecord
): string {
  return record.path.split("/").pop() ?? record.artifact_id;
}

export function getArtifactRegistryDescription(
  record: ArtifactRegistryRecord
): string {
  if (record.status === "invalid") {
    return record.error ?? "Registry entry is marked invalid.";
  }

  const details = uniqueStrings([
    humanizeArtifactToken(record.source_tool),
    humanizeArtifactToken(record.source_workflow),
    humanizeArtifactToken(record.dataset_id),
    humanizeArtifactToken(record.artifact_type),
  ]);

  return details[0] ?? "Durable registry artifact";
}

export function getArtifactRegistryMetadataSummary(
  record: ArtifactRegistryRecord
): string[] {
  return uniqueStrings([
    humanizeArtifactToken(record.workflow),
    record.run_id,
    record.dataset_id,
  ]);
}

export function shortenArtifactPath(path: string, depth = 4): string {
  const segments = path.split("/").filter(Boolean);
  if (segments.length <= depth) {
    return path;
  }
  return segments.slice(-depth).join("/");
}

export function getArtifactRegistryTimestamp(
  record: ArtifactRegistryRecord
): number | null {
  const candidate = record.created_at ?? record.indexed_at ?? null;
  if (!candidate) return null;
  const timestamp = Date.parse(candidate);
  return Number.isNaN(timestamp) ? null : timestamp;
}

export function sortArtifactRegistryRecords(
  records: ArtifactRegistryRecord[]
): ArtifactRegistryRecord[] {
  return [...records].sort((left, right) => {
    const leftTimestamp = getArtifactRegistryTimestamp(left) ?? 0;
    const rightTimestamp = getArtifactRegistryTimestamp(right) ?? 0;

    if (rightTimestamp !== leftTimestamp) {
      return rightTimestamp - leftTimestamp;
    }

    if (left.status !== right.status) {
      return left.status === "invalid" ? 1 : -1;
    }

    return left.path.localeCompare(right.path);
  });
}

export function getArtifactRegistryRunRecordPath(
  record: ArtifactRegistryRecord
): string {
  return `artifacts/${record.workflow}/${record.date}/${record.run_id}/run.json`;
}

export function getArtifactRegistryPreviewMode(
  record: ArtifactRegistryRecord
): ArtifactRegistryPreviewMode {
  return getFilePreviewDescriptor({
    path: record.path,
    artifactType: record.artifact_type,
    label: getArtifactRegistryDisplayName(record),
  }).mode;
}

export function isArtifactRegistryTextPreviewable(
  record: ArtifactRegistryRecord
): boolean {
  const mode = getArtifactRegistryPreviewMode(record);
  return (
    mode === "text" ||
    mode === "markdown" ||
    mode === "json" ||
    mode === "html"
  );
}

export function matchesArtifactRegistryText(
  record: ArtifactRegistryRecord,
  query: string
): boolean {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) return true;

  const searchFields = [
    record.artifact_id,
    record.declared_id,
    record.artifact_type,
    record.path,
    record.run_id,
    record.workflow,
    record.date,
    record.source_workflow,
    record.source_tool,
    record.dataset_id,
    record.status,
    record.error,
  ];

  return searchFields.some((field) =>
    field?.toLowerCase().includes(normalizedQuery)
  );
}
