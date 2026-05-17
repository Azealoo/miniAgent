import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import FeedPlanning from "./FeedPlanning";

describe("FeedPlanning", () => {
  it("renders each plan step as its own line", () => {
    render(
      <FeedPlanning
        steps={[
          "Prepared a 2-step plan.",
          "1. Inspect memory.",
          "2. Draft the answer.",
        ]}
      />
    );

    expect(screen.getByText("Prepared a 2-step plan.")).toBeTruthy();
    expect(screen.getByText("1. Inspect memory.")).toBeTruthy();
    expect(screen.getByText("2. Draft the answer.")).toBeTruthy();
  });

  it("defaults to the active accent tone", () => {
    render(
      <FeedPlanning steps={["Planning next steps."]} />
    );

    expect(screen.getByText("Planning next steps.").className).toContain(
      "text-[var(--apex-accent-strong)]"
    );
  });

  it("propagates the configured tone to every rendered line", () => {
    render(
      <FeedPlanning
        steps={["Needs revision.", "Re-check citations."]}
        tone="warning"
      />
    );

    expect(screen.getByText("Needs revision.").className).toContain(
      "text-amber-700"
    );
    expect(screen.getByText("Re-check citations.").className).toContain(
      "text-amber-700"
    );
  });

  it("renders nothing when no steps are provided", () => {
    const { container } = render(<FeedPlanning steps={[]} />);

    expect(container.querySelectorAll("p")).toHaveLength(0);
  });
});
