import React, { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ErrorBoundary from "@/components/ErrorBoundary";

const SIBLING_TEXT = "sidebar-still-here";
const FALLBACK_TEXT = "This panel hit an unexpected error";

// React logs caught errors to console.error during render. Silence it so the
// test output stays readable — we assert on the fallback, which is the real
// signal that the boundary caught the throw.
let consoleErrorSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  consoleErrorSpy.mockRestore();
});

function Exploder({ message }: { message: string }): React.ReactElement {
  throw new Error(message);
}

function ExploderOnClick({
  message,
}: {
  message: string;
}): React.ReactElement {
  const [exploded, setExploded] = useState(false);
  if (exploded) {
    throw new Error(message);
  }
  return (
    <button type="button" onClick={() => setExploded(true)}>
      detonate
    </button>
  );
}

describe("ErrorBoundary", () => {
  it("renders the fallback when a descendant throws synchronously", () => {
    render(
      <div>
        <div>{SIBLING_TEXT}</div>
        <ErrorBoundary>
          <Exploder message="kaboom-sync" />
        </ErrorBoundary>
      </div>
    );

    expect(screen.getByText(SIBLING_TEXT)).toBeTruthy();
    expect(screen.getByText(FALLBACK_TEXT)).toBeTruthy();
    expect(screen.getByText("kaboom-sync")).toBeTruthy();
    expect(screen.getByRole("alert")).toBeTruthy();
  });

  it("catches errors thrown after mount without unmounting sibling panels", async () => {
    const user = userEvent.setup();

    render(
      <div>
        <div data-testid="sibling">{SIBLING_TEXT}</div>
        <ErrorBoundary>
          <ExploderOnClick message="kaboom-later" />
        </ErrorBoundary>
      </div>
    );

    expect(screen.getByTestId("sibling").textContent).toBe(SIBLING_TEXT);

    await user.click(screen.getByRole("button", { name: "detonate" }));

    expect(screen.getByText(FALLBACK_TEXT)).toBeTruthy();
    expect(screen.getByText("kaboom-later")).toBeTruthy();

    // Sibling rendered outside the boundary must still be present, proving the
    // boundary isolates the failure to its own subtree.
    expect(screen.getByTestId("sibling").textContent).toBe(SIBLING_TEXT);
  });

  it("invokes the optional onError handler with the caught error", () => {
    const onError = vi.fn();

    render(
      <ErrorBoundary onError={onError}>
        <Exploder message="observed" />
      </ErrorBoundary>
    );

    expect(onError).toHaveBeenCalledTimes(1);
    const [firstArg] = onError.mock.calls[0];
    expect(firstArg).toBeInstanceOf(Error);
    expect((firstArg as Error).message).toBe("observed");
  });

  it("isolates one panel's crash from its siblings in a three-panel layout", async () => {
    const user = userEvent.setup();

    // Mirrors AppShell's Sidebar / Workspace / Inspector structure: each panel
    // is wrapped in its own boundary so a throw in one does not unmount the
    // others.
    render(
      <div>
        <ErrorBoundary label="Sidebar">
          <div data-testid="sidebar-panel">sidebar-content</div>
        </ErrorBoundary>
        <ErrorBoundary label="Workspace">
          <ExploderOnClick message="workspace-crash" />
        </ErrorBoundary>
        <ErrorBoundary label="Inspector">
          <div data-testid="inspector-panel">inspector-content</div>
        </ErrorBoundary>
      </div>
    );

    expect(screen.getByTestId("sidebar-panel").textContent).toBe("sidebar-content");
    expect(screen.getByTestId("inspector-panel").textContent).toBe("inspector-content");

    await user.click(screen.getByRole("button", { name: "detonate" }));

    expect(screen.getByText("Workspace")).toBeTruthy();
    expect(screen.getByText("workspace-crash")).toBeTruthy();

    // The other two panels must keep their content — only the Workspace
    // boundary swaps to its fallback.
    expect(screen.getByTestId("sidebar-panel").textContent).toBe("sidebar-content");
    expect(screen.getByTestId("inspector-panel").textContent).toBe("inspector-content");

    // Retry affordance is rendered so the user can recover the failed panel.
    expect(screen.getByRole("button", { name: /reset panel/i })).toBeTruthy();
  });
});
