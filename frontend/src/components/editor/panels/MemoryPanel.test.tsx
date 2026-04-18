import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/store", () => ({
  useApp: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  readFile: vi.fn().mockResolvedValue({ content: "" }),
  saveFile: vi.fn(),
  openRawFileInNewTab: vi.fn(),
}));

import { useApp } from "@/lib/store";
import { makeMockAppValue } from "@/test/panel-fixtures";
import MemoryPanel from "./MemoryPanel";

describe("MemoryPanel", () => {
  it("renders the context memory header and add-item action once loaded", async () => {
    vi.mocked(useApp).mockReturnValue(
      makeMockAppValue({ inspectorTab: "memory" })
    );

    render(<MemoryPanel />);

    expect(screen.getByText("Context Memory")).toBeTruthy();
    expect(await screen.findByText("Add Item")).toBeTruthy();
  });
});
