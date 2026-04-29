"use client";

import { cn } from "@/lib/utils";
import { badgeToneClass, blockToneClass } from "./tone";
import type { FeedBlockDescriptor } from "./types";

export default function FeedBlock({
  title,
  detail,
  badge,
  tone = "default",
}: Omit<FeedBlockDescriptor, "kind" | "id">) {
  return (
    <div
      className={cn(
        "rounded-[12px] border px-3 py-2 shadow-[0_1px_2px_rgba(32,43,35,0.03)]",
        blockToneClass(tone)
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-[11px] font-semibold text-slate-800">{title}</p>
        {badge ? (
          <span
            className={cn(
              "rounded-full border px-2 py-0.5 text-[9px] font-medium tracking-[0.02em]",
              badgeToneClass(tone)
            )}
          >
            {badge}
          </span>
        ) : null}
      </div>
      <p className="mt-1 whitespace-pre-wrap text-[11px] leading-5 text-slate-600">
        {detail}
      </p>
    </div>
  );
}
