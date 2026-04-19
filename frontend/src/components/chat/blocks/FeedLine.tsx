"use client";

import { cn } from "@/lib/utils";
import { lineToneClass } from "./tone";
import type { FeedLineDescriptor } from "./types";

export default function FeedLine({
  text,
  tone = "default",
  fullOutput,
}: Omit<FeedLineDescriptor, "kind">) {
  return (
    <p
      className={cn(
        "whitespace-pre-wrap break-words font-mono text-[11px] italic leading-5",
        lineToneClass(tone)
      )}
    >
      {text}
      {fullOutput ? (
        <>
          {" "}
          <a
            href={fullOutput.href}
            target="_blank"
            rel="noreferrer"
            className="not-italic font-medium text-[var(--apex-accent-strong)] underline decoration-dotted underline-offset-2 hover:decoration-solid"
          >
            {fullOutput.label ?? "full output →"}
          </a>
        </>
      ) : null}
    </p>
  );
}
