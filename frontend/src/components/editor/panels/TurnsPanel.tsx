"use client";

import TurnDetailsPanel from "@/components/editor/TurnDetailsPanel";
import { useApp } from "@/lib/store";
import { EmptyState, InspectorCard, MetaBadge } from "./primitives";
import { pluralize } from "./shared-utils";

export default function TurnsPanel() {
  const { messages } = useApp();

  return (
    <div className="space-y-2">
      <InspectorCard
        title="Turn Details"
        controls={
          <MetaBadge tone={messages.length > 0 ? "accent" : "neutral"}>
            {pluralize(messages.length, "message")}
          </MetaBadge>
        }
      >
        {messages.length === 0 ? (
          <EmptyState>Start a conversation to inspect turn details.</EmptyState>
        ) : (
          <div className="space-y-3">
            <p className="rounded-[10px] bg-[rgba(251,252,248,0.86)] px-2 py-1.5 text-[10px] leading-4 text-slate-500">
              Main chat stays concise after each turn. This view keeps the
              detailed retrieval, tool, and response trace available
              for inspection.
            </p>
            <TurnDetailsPanel messages={messages} />
          </div>
        )}
      </InspectorCard>
    </div>
  );
}
