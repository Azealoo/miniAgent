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
    <div className="mb-2 border border-purple-200 rounded-xl overflow-hidden bg-purple-50/50">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-purple-50 transition-colors"
      >
        <Brain size={13} className="text-purple-500 flex-shrink-0" />
        <span className="text-xs font-medium text-purple-700">
          Retrieved memory ({results.length} fragment{results.length !== 1 ? "s" : ""})
        </span>
        <span className="ml-auto">
          {open ? (
            <ChevronDown size={12} className="text-purple-400" />
          ) : (
            <ChevronRight size={12} className="text-purple-400" />
          )}
        </span>
      </button>

      {open && (
        <div className="px-3 pb-3 space-y-2">
          {results.map((r, i) => (
            <div key={i} className="bg-white border border-purple-100 rounded-lg p-2.5">
              <p className="text-xs text-gray-600 leading-relaxed">{r.text}</p>
              <p className="text-[10px] text-purple-400 mt-1">
                {r.source} · score {r.score.toFixed(3)}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
