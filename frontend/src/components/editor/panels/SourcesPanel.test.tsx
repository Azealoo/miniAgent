import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/store", () => ({
  useApp: vi.fn(),
}));

import { useApp } from "@/lib/store";
import { makeMockAppValue } from "@/test/panel-fixtures";
import SourcesPanel from "./SourcesPanel";

describe("SourcesPanel", () => {
  it("renders the citations heading and empty state when no evidence is available", () => {
    vi.mocked(useApp).mockReturnValue(makeMockAppValue());

    render(<SourcesPanel />);

    expect(screen.getByText("Citations")).toBeTruthy();
    expect(
      screen.getByText(
        /No reviewed evidence or retrieval-backed citations are linked to the current turn yet\./i
      )
    ).toBeTruthy();
    expect(screen.getByText("Source checklist")).toBeTruthy();
  });
});
