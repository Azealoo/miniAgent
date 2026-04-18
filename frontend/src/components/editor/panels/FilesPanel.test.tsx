import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/store", () => ({
  useApp: vi.fn(),
}));

import { useApp } from "@/lib/store";
import type { Message } from "@/lib/types";
import { makeMockAppValue } from "@/test/panel-fixtures";
import FilesPanel from "./FilesPanel";

describe("FilesPanel", () => {
  it("renders empty states when the session has no messages", () => {
    vi.mocked(useApp).mockReturnValue(makeMockAppValue());

    render(<FilesPanel />);

    expect(screen.getByText("Current Turn")).toBeTruthy();
    expect(
      screen.getByText(
        "Send a message to populate generated files and source detail here."
      )
    ).toBeTruthy();
    expect(
      screen.getByText(
        "Generated files will appear here once tool calls materialize inspectable artifacts."
      )
    ).toBeTruthy();
  });

  it("shows the message count stats when messages exist", () => {
    const messages: Message[] = [
      {
        id: "user-1",
        role: "user",
        content: "Please run analysis",
        blocks: [{ type: "text", text: "Please run analysis" }],
      },
      {
        id: "assistant-1",
        role: "assistant",
        content: "Ok.",
        blocks: [{ type: "text", text: "Ok." }],
      },
    ];
    vi.mocked(useApp).mockReturnValue(makeMockAppValue({ messages }));

    render(<FilesPanel />);

    expect(screen.getByText("Messages")).toBeTruthy();
    expect(screen.getByText("Artifacts")).toBeTruthy();
  });
});
