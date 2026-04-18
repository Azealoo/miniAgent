"use client";

import FeedLine from "./FeedLine";
import type { FeedPlanningDescriptor } from "./types";

export default function FeedPlanning({
  steps,
  tone = "active",
}: FeedPlanningDescriptor) {
  return (
    <div className="space-y-1">
      {steps.map((step) => (
        <FeedLine key={step} text={step} tone={tone} />
      ))}
    </div>
  );
}
