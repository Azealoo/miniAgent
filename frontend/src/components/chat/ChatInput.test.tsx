import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ChatInput from "./ChatInput";

function renderChatInput() {
  const props = {
    onSend: vi.fn(),
    isStreaming: false,
    isReferenceUploading: false,
    disabled: false,
    disabledReason: undefined,
    attachedIdentifiers: [],
    onOpenInspectorTab: vi.fn(),
    onPrimeDraftMessage: vi.fn(),
    onUploadReferenceFile: vi.fn(async () => undefined),
    onRemoveAttachedIdentifier: vi.fn(),
    onClearAttachedIdentifiers: vi.fn(),
    prefillText: "",
    prefillRevision: 0,
    clearPrefill: vi.fn(),
  };

  render(<ChatInput {...props} />);
  return props;
}

describe("ChatInput", () => {
  it("keeps the composer visually minimal by removing the command rail and prompt sigil", () => {
    renderChatInput();

    expect(screen.queryByText("Command Rail")).toBeNull();
    expect(screen.queryByText("BioAPEX")).toBeNull();
    const textbox = screen.getByPlaceholderText("Ask any biology related questions");
    expect(textbox).toBeTruthy();
    expect(textbox.getAttribute("rows")).toBe("1");
    expect(screen.queryByText("BioAPEX can make mistakes.")).toBeNull();
  });

  it("shows slash-command suggestions and completes them with Tab", async () => {
    const user = userEvent.setup();
    renderChatInput();

    const textbox = screen.getByRole("textbox");
    await user.type(textbox, "/rn");

    expect(screen.getByText("Matching Commands")).toBeTruthy();
    expect(screen.getByText("/rnaseq")).toBeTruthy();

    fireEvent.keyDown(textbox, { key: "Tab" });

    expect(screen.getByDisplayValue("/rnaseq")).toBeTruthy();
  });

  it("executes exact slash commands that prime structured analysis prompts", async () => {
    const user = userEvent.setup();
    const props = renderChatInput();

    const textbox = screen.getByRole("textbox");
    await user.type(textbox, "/rnaseq");

    fireEvent.keyDown(textbox, { key: "Enter" });

    expect(props.onPrimeDraftMessage).toHaveBeenCalledWith(
      expect.stringContaining(
        "Review the attached RNA-seq dataset context, outline the QC and differential expression steps you recommend"
      )
    );
    expect(props.onSend).not.toHaveBeenCalled();
  });

  it("routes slash commands to inspector surfaces without a quick-action row", async () => {
    const user = userEvent.setup();
    const props = renderChatInput();

    const textbox = screen.getByRole("textbox");
    await user.type(textbox, "/sources");
    fireEvent.keyDown(textbox, { key: "Enter" });

    expect(props.onOpenInspectorTab).toHaveBeenCalledWith("sources");

    await user.clear(textbox);
    await user.type(textbox, "/files");
    fireEvent.keyDown(textbox, { key: "Enter" });

    expect(props.onOpenInspectorTab).toHaveBeenCalledWith("files");
  });
});
