import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import FeedSection from "./FeedSection";
import type { FeedEntryDescriptor } from "./types";

describe("FeedSection", () => {
  it("renders the title and heading", () => {
    render(<FeedSection live={false} title="Thinking" entries={[]} />);

    expect(screen.getByText("Thinking")).toBeTruthy();
  });

  it("animates the header label while live in a known section", () => {
    render(<FeedSection live={true} title="Planning" entries={[]} />);

    expect(screen.getByText("Planning").className).toContain(
      "apex-thinking-label"
    );
  });

  it("does not animate the header once the turn has finished", () => {
    render(<FeedSection live={false} title="Planning" entries={[]} />);

    expect(screen.getByText("Planning").className).not.toContain(
      "apex-thinking-label"
    );
  });

  it("renders line, block, and planning entries side by side", () => {
    const entries: FeedEntryDescriptor[] = [
      { kind: "line", text: "Looked at memory.", tone: "active" },
      {
        kind: "block",
        title: "Evidence Review",
        detail: "All claims supported.",
        badge: "supported",
        tone: "success",
      },
      {
        kind: "planning",
        steps: ["Prepared a 1-step plan.", "1. Inspect memory."],
        tone: "active",
      },
    ];

    render(<FeedSection live={false} title="Thinking" entries={entries} />);

    expect(screen.getByText("Looked at memory.")).toBeTruthy();
    expect(screen.getByText("Evidence Review")).toBeTruthy();
    expect(screen.getByText("All claims supported.")).toBeTruthy();
    expect(screen.getByText("supported")).toBeTruthy();
    expect(screen.getByText("Prepared a 1-step plan.")).toBeTruthy();
    expect(screen.getByText("1. Inspect memory.")).toBeTruthy();
  });

  it("renders each planning step inside a planning entry", () => {
    const entries: FeedEntryDescriptor[] = [
      {
        kind: "planning",
        steps: [
          "Prepared a 2-step plan.",
          "1. Review metadata.",
          "2. Draft the answer.",
        ],
        tone: "active",
      },
    ];

    render(<FeedSection live={true} title="Planning" entries={entries} />);

    expect(screen.getByText("Prepared a 2-step plan.")).toBeTruthy();
    expect(screen.getByText("1. Review metadata.")).toBeTruthy();
    expect(screen.getByText("2. Draft the answer.")).toBeTruthy();
  });
});
