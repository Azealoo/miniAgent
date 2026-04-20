"use client";

import { cn } from "@/lib/utils";
import ApprovalGate from "../ApprovalGate";
import FeedBlock from "./FeedBlock";
import FeedLine from "./FeedLine";
import FeedPlanning from "./FeedPlanning";
import type { FeedEntryDescriptor } from "./types";

interface FeedSectionProps {
  live: boolean;
  title: string;
  entries: FeedEntryDescriptor[];
  sessionId?: string | null;
}

export default function FeedSection({
  live,
  title,
  entries,
  sessionId = null,
}: FeedSectionProps) {
  const animated =
    live &&
    (title === "Thinking" || title === "Planning" || title === "Verification");

  return (
    <div className="space-y-1.5">
      <div className="-mx-2 rounded-[12px] px-2 py-1">
        <p className="font-mono text-[11px] font-medium italic text-slate-500">
          <span className={cn(animated && "apex-thinking-label")}>{title}</span>
        </p>
      </div>

      <div className="space-y-1.5">
        {entries.map((entry) => {
          if (entry.kind === "block") {
            return <FeedBlock key={entry.id} {...entry} />;
          }
          if (entry.kind === "planning") {
            return <FeedPlanning key={entry.id} {...entry} />;
          }
          if (entry.kind === "gate") {
            return (
              <ApprovalGate
                key={entry.id}
                block={entry.block}
                sessionId={sessionId}
              />
            );
          }
          return <FeedLine key={entry.id} {...entry} />;
        })}
      </div>
    </div>
  );
}
