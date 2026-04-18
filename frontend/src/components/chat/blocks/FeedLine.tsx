"use client";

import { cn } from "@/lib/utils";
import { lineToneClass } from "./tone";
import type { FeedLineDescriptor } from "./types";

export default function FeedLine({
  text,
  tone = "default",
}: Omit<FeedLineDescriptor, "kind">) {
  return (
    <p
      className={cn(
        "whitespace-pre-wrap break-words font-mono text-[11px] italic leading-5",
        lineToneClass(tone)
      )}
    >
      {text}
    </p>
  );
}
