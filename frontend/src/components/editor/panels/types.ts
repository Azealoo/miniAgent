import type { SourcesInspectorCitationTone } from "@/lib/types";

export type GeneratedArtifactItem = {
  path: string;
  label: string;
  artifactType: string | null;
  sourceTool: string | null;
  lastSeenOrder: number;
};

export type GeneratedArtifactKind =
  | "table"
  | "plot"
  | "structured"
  | "report"
  | "archive"
  | "file";

export type SourceInspectorItemKind = "review" | "evidence" | "retrieval";

export type SourceInspectorTone = SourcesInspectorCitationTone;

export type SourceInspectorItem = {
  id: string;
  kind: SourceInspectorItemKind;
  artifactType: string | null;
  title: string;
  sourceType: string;
  identifier: string | null;
  stateLabel: string | null;
  detail: string | null;
  metadata: string[];
  tone: SourceInspectorTone;
  path: string | null;
  lastSeenOrder: number;
};

export type RetrievedSourceSummary = {
  source: string;
  identifier: string | null;
  score: number;
  count: number;
  lastSeenOrder: number;
};

export type MemoryInspectorItemKind = "bullet" | "numbered" | "block";

export type MemoryInspectorItem = {
  id: string;
  namespace: string;
  key: string;
  value: string;
  kind: MemoryInspectorItemKind;
  rawLines: string[];
};

export type ParsedMemoryDocument = {
  title: string;
  items: MemoryInspectorItem[];
};

export type MemoryItemDraft = {
  mode: "create" | "edit";
  targetId: string | null;
  namespace: string;
  key: string;
  value: string;
};
