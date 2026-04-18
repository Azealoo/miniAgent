"use client";

import { cn } from "@/lib/utils";
import type { Message } from "@/lib/types";
import FeedSection from "./blocks/FeedSection";
import { buildFeedSections } from "./turn-activity-feed.helpers";

interface TurnActivityFeedProps {
  message: Message;
}

export default function TurnActivityFeed({ message }: TurnActivityFeedProps) {
  const live = message.isStreaming === true;
  const sections = buildFeedSections(message, live);

  if (!live && sections.length === 0) {
    return null;
  }

  return (
    <section
      role="status"
      aria-live={live ? "polite" : undefined}
      className={cn(
        "apex-process-rail space-y-1.5",
        live ? "apex-transcript-enter" : "mt-3"
      )}
    >
      {sections.map((section) => (
        <FeedSection
          key={section.key}
          live={live}
          title={section.title}
          entries={section.entries}
        />
      ))}
    </section>
  );
}
