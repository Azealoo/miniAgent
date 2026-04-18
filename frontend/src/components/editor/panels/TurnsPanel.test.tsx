import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/store", () => ({
  useApp: vi.fn(),
}));

import { useApp } from "@/lib/store";
import type { Message } from "@/lib/types";
import { makeMockAppValue } from "@/test/panel-fixtures";
import TurnsPanel from "./TurnsPanel";

describe("TurnsPanel", () => {
  it("renders the empty state when no messages exist", () => {
    vi.mocked(useApp).mockReturnValue(makeMockAppValue());

    render(<TurnsPanel />);

    expect(
      screen.getByText("Start a conversation to inspect turn details.")
    ).toBeTruthy();
  });

  it("renders the turn details heading and message count when messages exist", () => {
    const messages: Message[] = [
      {
        id: "user-1",
        role: "user",
        content: "Hi.",
        blocks: [{ type: "text", text: "Hi." }],
      },
      {
        id: "assistant-1",
        role: "assistant",
        content: "Hello.",
        blocks: [{ type: "text", text: "Hello." }],
      },
    ];
    vi.mocked(useApp).mockReturnValue(makeMockAppValue({ messages }));

    render(<TurnsPanel />);

    expect(screen.getByText("Turn Details")).toBeTruthy();
    expect(screen.getByText("2 messages")).toBeTruthy();
  });
});
