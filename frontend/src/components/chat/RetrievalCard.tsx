"use client";

import type { ReactNode } from "react";
import { BookOpen, Brain, Database, FileText } from "lucide-react";
import type { RetrievalResult } from "@/lib/types";

interface RetrievalCardProps {
  results: RetrievalResult[];
}

type RetrievalSourceKind = "dataset" | "protocol" | "note" | "knowledge";

interface RetrievalSourceSummary {
  source: string;
  displaySource: string;
  snippet: string;
  score: number;
  excerptCount: number;
  kind: RetrievalSourceKind;
}

const MAX_VISIBLE_SOURCES = 3;

function stripCommonExtension(value: string): string {
  return value.replace(/\.(md|markdown|txt|json|yaml|yml)$/i, "");
}

function displaySourceLabel(source: string): string {
  const trimmed = source.trim();
  if (!trimmed) return "Retrieved context";
  const normalized = trimmed.replace(/\\/g, "/");
  const basename = normalized.split("/").pop() ?? normalized;
  return stripCommonExtension(basename) || trimmed;
}

function normalizeSnippet(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

function trimSnippet(text: string, limit = 120): string {
  if (text.length <= limit) return text;
  return `${text.slice(0, limit).trimEnd()}...`;
}

function inferSourceKind(source: string): RetrievalSourceKind {
  const normalized = source.toLowerCase();
  if (
    normalized.includes("protocol") ||
    normalized.includes("sop") ||
    normalized.includes("procedure")
  ) {
    return "protocol";
  }
  if (
    normalized.includes("dataset") ||
    normalized.includes("counts") ||
    normalized.includes("expression") ||
    normalized.includes("sample_sheet") ||
    normalized.includes(".csv") ||
    normalized.includes(".tsv") ||
    normalized.includes(".h5ad") ||
    normalized.includes(".loom") ||
    normalized.includes(".mtx") ||
    normalized.includes(".fastq") ||
    normalized.includes(".fq") ||
    normalized.includes(".bam") ||
    normalized.includes(".vcf") ||
    /\bgse\d+\b/.test(normalized)
  ) {
    return "dataset";
  }
  if (
    normalized.includes("memory") ||
    normalized.includes("note") ||
    normalized.includes("notes")
  ) {
    return "note";
  }
  return "knowledge";
}

function kindLabel(kind: RetrievalSourceKind): string {
  switch (kind) {
    case "dataset":
      return "Dataset";
    case "protocol":
      return "Protocol";
    case "note":
      return "Note";
    default:
      return "Knowledge File";
  }
}

function kindIcon(kind: RetrievalSourceKind): ReactNode {
  switch (kind) {
    case "dataset":
      return <Database size={14} />;
    case "protocol":
      return <BookOpen size={14} />;
    default:
      return <FileText size={14} />;
  }
}

function summarizeResults(results: RetrievalResult[]): RetrievalSourceSummary[] {
  const summaries = new Map<string, RetrievalSourceSummary>();

  results.forEach((result) => {
    const source = result.source?.trim() || "Retrieved context";
    const snippet = trimSnippet(normalizeSnippet(result.text));
    const existing = summaries.get(source);

    if (existing) {
      existing.excerptCount += 1;
      if (result.score > existing.score) {
        existing.score = result.score;
        if (snippet) {
          existing.snippet = snippet;
        }
      }
      return;
    }

    summaries.set(source, {
      source,
      displaySource: displaySourceLabel(source),
      snippet,
      score: result.score,
      excerptCount: 1,
      kind: inferSourceKind(source),
    });
  });

  return Array.from(summaries.values()).sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.excerptCount !== a.excerptCount) return b.excerptCount - a.excerptCount;
    return a.displaySource.localeCompare(b.displaySource);
  });
}

export default function RetrievalCard({ results }: RetrievalCardProps) {
  if (!results || results.length === 0) return null;

  const sources = summarizeResults(results);
  const visibleSources = sources.slice(0, MAX_VISIBLE_SOURCES);
  const hiddenSourceCount = Math.max(0, sources.length - visibleSources.length);

  return (
    <section className="rounded-[20px] border border-[rgba(47,122,95,0.14)] bg-[linear-gradient(180deg,rgba(247,251,248,0.98),rgba(240,247,242,0.96))] px-4 py-3.5 shadow-[0_10px_22px_rgba(32,43,35,0.035)]">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-[12px] border border-[rgba(47,122,95,0.12)] bg-white/80 text-[var(--apex-accent-strong)]">
          <Brain size={14} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-semibold text-[var(--apex-accent-strong)]">
              Knowledge Retrieved
            </p>
            <span className="rounded-full border border-[rgba(47,122,95,0.12)] bg-white/78 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-[rgba(23,97,61,0.72)]">
              {sources.length} source{sources.length !== 1 ? "s" : ""}
            </span>
          </div>
          <p className="mt-1 text-[12px] leading-5 text-[rgba(23,97,61,0.72)]">
            Supporting context loaded for this response from retrieved notes, protocols, files, or datasets.
          </p>
        </div>
      </div>

      <div className="mt-3 space-y-2">
        {visibleSources.map((source) => (
          <div
            key={source.source}
            className="flex items-start gap-3 rounded-[15px] border border-white/75 bg-white/82 px-3 py-2.5"
          >
            <div className="mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-[10px] bg-[rgba(35,130,83,0.08)] text-[var(--apex-accent-strong)]">
              {kindIcon(source.kind)}
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                  {kindLabel(source.kind)}
                </span>
                <span className="text-sm font-medium text-slate-700">
                  {source.displaySource}
                </span>
                {source.excerptCount > 1 && (
                  <span className="rounded-full bg-[rgba(35,130,83,0.08)] px-2 py-0.5 text-[10px] font-medium text-[rgba(23,97,61,0.72)]">
                    {source.excerptCount} excerpts
                  </span>
                )}
              </div>
              {source.snippet && (
                <p className="mt-1 text-[12px] leading-5 text-slate-500">
                  {source.snippet}
                </p>
              )}
            </div>
          </div>
        ))}

        {hiddenSourceCount > 0 && (
          <p className="px-1 text-[11px] text-slate-500">
            +{hiddenSourceCount} more source{hiddenSourceCount !== 1 ? "s" : ""} retrieved for this response.
          </p>
        )}
      </div>
    </section>
  );
}
