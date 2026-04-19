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
import type { Message } from "@/lib/types";
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

  it("shows the parse-error counter once the stream has dropped a malformed payload", () => {
    const messages: Message[] = [
      {
        id: "user-1",
        role: "user",
        content: "hi",
        blocks: [{ type: "text", text: "hi" }],
      },
      {
        id: "assistant-1",
        role: "assistant",
        content: "hello",
        blocks: [{ type: "text", text: "hello" }],
      },
    ];

    vi.mocked(useApp).mockReturnValue(
      makeMockAppValue({
        currentSessionId: "session-with-drops",
        messages,
        parseErrorCount: 3,
      })
    );

    render(<UsagePanel />);

    expect(screen.getByText("Parse errors")).toBeTruthy();
    expect(screen.getByText("3")).toBeTruthy();
  });

  it("omits the parse-error row when no malformed payloads have been seen", () => {
    const messages: Message[] = [
      {
        id: "user-1",
        role: "user",
        content: "hi",
        blocks: [{ type: "text", text: "hi" }],
      },
      {
        id: "assistant-1",
        role: "assistant",
        content: "hello",
        blocks: [{ type: "text", text: "hello" }],
      },
    ];

    vi.mocked(useApp).mockReturnValue(
      makeMockAppValue({
        currentSessionId: "session-clean",
        messages,
        parseErrorCount: 0,
      })
    );

    render(<UsagePanel />);

    expect(screen.queryByText("Parse errors")).toBeNull();
  });
});
