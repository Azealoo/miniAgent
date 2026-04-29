import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import FeedBlock from "./FeedBlock";

describe("FeedBlock", () => {
  it("renders the title and detail text", () => {
    render(
      <FeedBlock
        title="Evidence Review"
        detail="Reviewed two supporting papers."
      />
    );

    expect(screen.getByText("Evidence Review")).toBeTruthy();
    expect(screen.getByText("Reviewed two supporting papers.")).toBeTruthy();
  });

  it("omits the badge element when no badge is provided", () => {
    render(
      <FeedBlock title="Readiness Check" detail="All good." />
    );

    expect(screen.queryByText("supported")).toBeNull();
  });

  it("renders the badge with matching tone classes when provided", () => {
    render(
      <FeedBlock
        title="Evidence Review"
        detail="Claims look supported."
        badge="supported"
        tone="success"
      />
    );

    const badge = screen.getByText("supported");
    expect(badge).toBeTruthy();
    expect(badge.className).toContain("border-emerald-200");
    expect(badge.className).toContain("text-emerald-700");
  });

  it("applies the warning tone to the outer container for warning states", () => {
    render(
      <FeedBlock
        title="Readiness"
        detail="Some checks still pending."
        tone="warning"
      />
    );

    const title = screen.getByText("Readiness");
    const container = title.closest("div")?.parentElement;
    expect(container).toBeTruthy();
    expect(container?.className).toContain("border-amber-200");
  });
});
