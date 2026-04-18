"use client";

import { cn } from "@/lib/utils";
import FeedBlock from "./FeedBlock";
import FeedLine from "./FeedLine";
import FeedPlanning from "./FeedPlanning";
import type { FeedEntryDescriptor } from "./types";

interface FeedSectionProps {
  live: boolean;
  title: string;
  entries: FeedEntryDescriptor[];
}

export default function FeedSection({
  live,
  title,
  entries,
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
        {entries.map((entry, index) =>
          entry.kind === "block" ? (
            <FeedBlock
              key={`${title}-${entry.title}-${entry.badge ?? "none"}-${index}`}
              {...entry}
            />
          ) : entry.kind === "planning" ? (
            <FeedPlanning key={`${title}-planning-${index}`} {...entry} />
          ) : (
            <FeedLine key={`${title}-${entry.text}-${index}`} {...entry} />
          )
        )}
      </div>
    </div>
  );
}
