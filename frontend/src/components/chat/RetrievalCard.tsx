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
    <div className="mb-3 overflow-hidden rounded-[18px] border border-[rgba(47,122,95,0.16)] bg-[rgba(236,245,239,0.76)]">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2.5 text-left transition-colors hover:bg-[rgba(232,242,235,0.92)]"
      >
        <Brain size={13} className="flex-shrink-0 text-[var(--apex-accent)]" />
        <span className="text-xs font-medium text-[var(--apex-accent-strong)]">
          Retrieved memory ({results.length} fragment{results.length !== 1 ? "s" : ""})
        </span>
        <span className="ml-auto">
          {open ? (
            <ChevronDown size={12} className="text-[var(--apex-accent)]" />
          ) : (
            <ChevronRight size={12} className="text-[var(--apex-accent)]" />
          )}
        </span>
      </button>

      {open && (
        <div className="px-3 pb-3 space-y-2">
          {results.map((r, i) => (
            <div key={i} className="rounded-[14px] border border-white/80 bg-white/92 p-2.5">
              <p className="text-xs leading-relaxed text-slate-600">{r.text}</p>
              <p className="mt-1 text-[10px] text-[var(--apex-accent)]">
                {r.source} · score {r.score.toFixed(3)}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
