import type { SessionApprovalGateBlock } from "@/lib/types";

export type FeedTone = "default" | "active" | "success" | "warning" | "error";
export type FeedSectionKey =
  | "thinking"
  | "planning"
  | "verification"
  | "workflow";

// Every descriptor carries a stable `id` derived from upstream identifiers
// (run_id / block index / step_id). FeedSection uses it as the React key so
// reorders and filters don't remount children and discard internal state
// such as ApprovalGate's pending/confirming flags.

export interface FeedBlockDescriptor {
  kind: "block";
  id: string;
  title: string;
  detail: string;
  badge?: string | null;
  tone?: FeedTone;
}

export interface FeedPlanningDescriptor {
  kind: "planning";
  id: string;
  steps: string[];
  tone?: FeedTone;
}

export interface FeedLineFullOutputLink {
  href: string;
  label?: string;
}

export interface FeedLineDescriptor {
  kind: "line";
  id: string;
  text: string;
  tone?: FeedTone;
  fullOutput?: FeedLineFullOutputLink;
}

export interface FeedGateDescriptor {
  kind: "gate";
  id: string;
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
