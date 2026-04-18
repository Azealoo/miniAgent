"use client";

import {
  Dna,
  FileText,
  Files,
  Search,
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
    id: "find-papers",
    label: "Find Papers",
    description: "Draft a literature search request on a biology topic.",
    kind: "Search",
    icon: Search,
    draftMessage:
      "Find peer-reviewed papers on <TOPIC>. Summarize the main approaches, highlight the strongest sources with citations, and flag where the literature is thin or contested.",
  },
  {
    id: "summarize-pdf",
    label: "Summarize PDF",
    description: "Draft a request to summarize an attached paper or PDF.",
    kind: "Summarize",
    icon: FileText,
    draftMessage:
      "Summarize the attached PDF. Extract the research question, methods, key findings, and limitations, and quote the passages that back up each point.",
  },
  {
    id: "design-primers",
    label: "Design Primers",
    description: "Draft a primer design request for a biology target.",
    kind: "Design",
    icon: Dna,
    draftMessage:
      "Design PCR primers for <TARGET>. State the design constraints you are assuming (length, Tm, GC content, amplicon size), propose forward/reverse candidates, and call out any specificity or secondary-structure concerns.",
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
