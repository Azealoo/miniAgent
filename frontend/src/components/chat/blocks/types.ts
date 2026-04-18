import type { SessionApprovalGateBlock } from "@/lib/types";

export type FeedTone = "default" | "active" | "success" | "warning" | "error";
export type FeedSectionKey = "thinking" | "planning" | "verification";

export interface FeedBlockDescriptor {
  kind: "block";
  title: string;
  detail: string;
  badge?: string | null;
  tone?: FeedTone;
}

export interface FeedPlanningDescriptor {
  kind: "planning";
  steps: string[];
  tone?: FeedTone;
}

export interface FeedLineDescriptor {
  kind: "line";
  text: string;
  tone?: FeedTone;
}

export interface FeedGateDescriptor {
  kind: "gate";
  block: SessionApprovalGateBlock;
}

export type FeedEntryDescriptor =
  | FeedBlockDescriptor
  | FeedPlanningDescriptor
  | FeedLineDescriptor
  | FeedGateDescriptor;

export interface FeedSectionDescriptor {
  key: FeedSectionKey;
  title: string;
  entries: FeedEntryDescriptor[];
}
