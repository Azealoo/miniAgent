"use client";

import { cn } from "@/lib/utils";
import type { TurnExit } from "@/lib/types";

interface TurnExitPillProps {
  exit: TurnExit;
}

type ExitPresentation = {
  label: string;
  tone: string;
  hint: string;
  testId: string;
};

const EXIT_PRESENTATIONS: Record<TurnExit["reason"], ExitPresentation> = {
  success: {
    label: "Completed",
    tone:
      "border-[rgba(67,150,104,0.32)] bg-[rgba(229,244,235,0.85)] text-[#276946]",
    hint: "The turn finished cleanly.",
    testId: "turn-exit-pill-success",
  },
  tool_error: {
    label: "Tool error",
    tone:
      "border-[rgba(219,96,96,0.45)] bg-[rgba(255,233,233,0.95)] text-[#a12929]",
    hint: "A tool call failed before the turn could complete.",
    testId: "turn-exit-pill-tool-error",
  },
  user_abort: {
    label: "Cancelled",
    tone:
      "border-[rgba(119,119,119,0.4)] bg-[rgba(241,241,241,0.95)] text-[#555]",
    hint: "The turn was cancelled before it finished.",
    testId: "turn-exit-pill-user-abort",
  },
  context_limit: {
    label: "Context full",
    tone:
      "border-[rgba(175,124,33,0.45)] bg-[rgba(253,239,204,0.95)] text-[#8a5b11]",
    hint: "The session hit its context window limit.",
    testId: "turn-exit-pill-context-limit",
  },
  token_budget: {
    label: "Token budget exceeded",
    tone:
      "border-[rgba(175,124,33,0.45)] bg-[rgba(253,239,204,0.95)] text-[#8a5b11]",
    hint: "The per-turn token budget was reached.",
    testId: "turn-exit-pill-token-budget",
  },
  approval_denied: {
    label: "Approval denied",
    tone:
      "border-[rgba(200,85,120,0.45)] bg-[rgba(252,224,232,0.95)] text-[#8c2a4a]",
    hint: "A reviewer denied a required tool call.",
    testId: "turn-exit-pill-approval-denied",
  },
  awaiting_approval: {
    label: "Awaiting approval",
    tone:
      "border-[rgba(78,131,180,0.45)] bg-[rgba(222,237,252,0.95)] text-[#254d7a]",
    hint: "The turn is paused until a reviewer approves the gated tool call.",
    testId: "turn-exit-pill-awaiting-approval",
  },
};

export default function TurnExitPill({ exit }: TurnExitPillProps) {
  const presentation = EXIT_PRESENTATIONS[exit.reason];
  const summary = exit.summary?.trim();

  return (
    <div
      role="status"
      data-testid={presentation.testId}
      data-exit-reason={exit.reason}
      data-exit-code={exit.exit_code}
      className={cn(
        "mt-2 inline-flex max-w-full items-center gap-2 rounded-full border px-3 py-1 text-[0.74rem] font-medium shadow-[0_1px_2px_rgba(0,0,0,0.04)]",
        presentation.tone
      )}
    >
      <span className="truncate">{presentation.label}</span>
      {summary ? (
        <span className="truncate text-[0.7rem] font-normal opacity-80">
          — {summary}
        </span>
      ) : (
        <span className="sr-only">{presentation.hint}</span>
      )}
    </div>
  );
}
