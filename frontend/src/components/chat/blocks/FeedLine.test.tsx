import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import FeedLine from "./FeedLine";

describe("FeedLine", () => {
  it("renders the provided text with the default slate tone", () => {
    render(<FeedLine text="Preparing next step." />);

    const paragraph = screen.getByText("Preparing next step.");
    expect(paragraph).toBeTruthy();
    expect(paragraph.className).toContain("text-slate-500");
  });

  it("uses the accent tone for active and success states", () => {
    const { rerender } = render(
      <FeedLine text="Looked at memory." tone="active" />
    );
    expect(screen.getByText("Looked at memory.").className).toContain(
      "text-[var(--apex-accent-strong)]"
    );

    rerender(<FeedLine text="Passed verification." tone="success" />);
    expect(screen.getByText("Passed verification.").className).toContain(
      "text-[var(--apex-accent-strong)]"
    );
  });

  it("uses amber for warnings and rose for errors", () => {
    const { rerender } = render(
      <FeedLine text="Needs revision before delivery." tone="warning" />
    );
    expect(
      screen.getByText("Needs revision before delivery.").className
    ).toContain("text-amber-700");

    rerender(<FeedLine text="Verification failed." tone="error" />);
    expect(screen.getByText("Verification failed.").className).toContain(
      "text-rose-700"
    );
  });
});
