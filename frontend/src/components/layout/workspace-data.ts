"use client";

import {
  BookOpen,
  Files,
  FlaskConical,
  MessageSquare,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";
import { humanizeToken } from "@/lib/format";
import {
  getMessageRetrievals,
  getMessageToolCalls,
} from "@/lib/message-blocks";
import type { Message } from "@/lib/types";

export interface QuickStartItem {
  id: string;
  label: string;
  description: string;
  kind: string;
  icon: LucideIcon;
  draftMessage: string;
}

export interface SurfaceItem {
  id: string;
  label: string;
  description: string;
  meta?: string;
  icon: LucideIcon;
  path?: string;
}

export const quickStartItems: QuickStartItem[] = [
  {
    id: "biology-question",
    label: "Biology Question",
    description: "Draft an open-ended biology question for BioAPEX to answer.",
    kind: "Ask",
    icon: MessageSquare,
    draftMessage:
      "Help me answer this biology question using the attached context and any relevant tools. Separate what is known from what is uncertain, and cite or inspect sources when they matter.",
  },
  {
    id: "rnaseq-de",
    label: "RNA-seq Analysis",
    description: "Draft a chat request for RNA-seq QC and differential expression guidance.",
    kind: "Analyze",
    icon: FlaskConical,
    draftMessage:
      "Review the attached RNA-seq dataset context, outline the QC and differential expression steps you recommend, call out missing inputs or assumptions, and explain what analysis I should run next.",
  },
  {
    id: "evidence-review",
    label: "Evidence Review",
    description: "Draft a source-grounded biology evidence review request.",
    kind: "Review",
    icon: BookOpen,
    draftMessage:
      "Review the evidence for this biology question, separate source facts from conclusions, and cite the strongest supporting artifacts.",
  },
  {
    id: "request-review",
    label: "Request Review",
    description: "Draft a pre-execution request review with risks, warnings, and missing context.",
    kind: "Check",
    icon: ShieldCheck,
    draftMessage:
      "Review this request before execution, call out risks or warnings, and note what information is missing before we proceed.",
  },
];

function shortenPath(path: string): string {
  const segments = path.split("/").filter(Boolean);
  if (segments.length <= 2) return path;
  return segments.slice(-2).join("/");
}

export function matchesQuery(
  query: string,
  ...parts: Array<string | null | undefined>
): boolean {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) return true;
  return parts.some((part) => part?.toLowerCase().includes(normalizedQuery));
}

export function recentFiles(messages: Message[]): SurfaceItem[] {
  const items: SurfaceItem[] = [];
  const seenPaths = new Set<string>();

  const pushItem = (
    path: string | null | undefined,
    description: string,
    meta?: string | null
  ) => {
    if (!path || seenPaths.has(path) || items.length >= 6) return;
    seenPaths.add(path);
    items.push({
      id: path,
      label: path.split("/").pop() ?? path,
      description,
      meta: meta ?? shortenPath(path),
      icon: Files,
      path,
    });
  };

  for (let messageIndex = messages.length - 1; messageIndex >= 0; messageIndex -= 1) {
    const message = messages[messageIndex];

    const toolCalls = getMessageToolCalls(message);
    for (let callIndex = toolCalls.length - 1; callIndex >= 0; callIndex -= 1) {
      const artifactRefs = toolCalls[callIndex]?.result?.artifact_refs ?? [];
      for (let refIndex = artifactRefs.length - 1; refIndex >= 0; refIndex -= 1) {
        const ref = artifactRefs[refIndex];
        pushItem(
          ref.path,
          humanizeToken(ref.artifact_type) ?? ref.label ?? "Tool artifact"
        );
      }
    }

    const retrievals = getMessageRetrievals(message);
    for (let retrievalIndex = retrievals.length - 1; retrievalIndex >= 0; retrievalIndex -= 1) {
      const retrieval = retrievals[retrievalIndex];
      pushItem(retrieval.source, "Retrieved source", retrieval.source);
    }
  }

  return items;
}
