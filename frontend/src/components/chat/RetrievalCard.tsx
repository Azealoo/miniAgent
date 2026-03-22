"use client";

import { useState } from "react";
import { Brain, ChevronDown, ChevronRight } from "lucide-react";
import type { RetrievalResult } from "@/lib/types";

interface RetrievalCardProps {
  results: RetrievalResult[];
}

export default function RetrievalCard({ results }: RetrievalCardProps) {
  const [open, setOpen] = useState(false);

  if (!results || results.length === 0) return null;

  return (
    <div className="overflow-hidden rounded-[16px] border border-[rgba(47,122,95,0.14)] bg-[linear-gradient(180deg,rgba(248,250,247,0.98),rgba(238,246,240,0.96))] shadow-[0_8px_18px_rgba(32,43,35,0.03)]">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3.5 py-2.5 text-left transition-colors hover:bg-[rgba(234,243,237,0.96)]"
      >
        <Brain size={13} className="flex-shrink-0 text-[var(--apex-accent)]" />
        <div className="min-w-0">
          <span className="block text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--apex-accent-strong)]">
            Retrieved Memory
          </span>
          <span className="block text-[11px] text-[rgba(23,97,61,0.72)]">
            {results.length} fragment{results.length !== 1 ? "s" : ""}
          </span>
        </div>
        <span className="ml-auto">
          {open ? (
            <ChevronDown size={12} className="text-[var(--apex-accent)]" />
          ) : (
            <ChevronRight size={12} className="text-[var(--apex-accent)]" />
          )}
        </span>
      </button>

      {open && (
        <div className="space-y-2 px-3.5 pb-3">
          {results.map((r, i) => (
            <div key={i} className="rounded-[14px] border border-white/80 bg-white/92 p-3">
              <p className="text-xs leading-relaxed text-slate-600">{r.text}</p>
              <p className="mt-1.5 text-[10px] uppercase tracking-[0.14em] text-[var(--apex-accent)]">
                {r.source} · score {r.score.toFixed(3)}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
