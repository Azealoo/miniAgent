import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/store", () => ({
  useApp: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  getSessionTokens: vi.fn().mockResolvedValue(null),
}));

import { useApp } from "@/lib/store";
import { makeMockAppValue } from "@/test/panel-fixtures";
import UsagePanel from "./UsagePanel";

describe("UsagePanel", () => {
  it("prompts the user to select a session when none is active", () => {
    vi.mocked(useApp).mockReturnValue(makeMockAppValue());

    render(<UsagePanel />);

    expect(screen.getByText("Usage")).toBeTruthy();
    expect(screen.getByText("Select a session to inspect token usage.")).toBeTruthy();
  });

  it("renders the empty state when a session is selected but has no messages", async () => {
    vi.mocked(useApp).mockReturnValue(
      makeMockAppValue({ currentSessionId: "session-alpha" })
    );

    render(<UsagePanel />);

    expect(
      await screen.findByText(
        "Send a message in this session to populate token usage here."
      )
    ).toBeTruthy();
  });
});
