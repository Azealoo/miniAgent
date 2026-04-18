import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ChatInput from "./ChatInput";

function renderChatInput() {
  const props = {
    onSend: vi.fn(),
    onStop: vi.fn(),
    isStreaming: false,
    disabled: false,
    disabledReason: undefined,
    onOpenInspectorTab: vi.fn(),
    onPrimeDraftMessage: vi.fn(),
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
    expect(screen.queryByRole("button", { name: /upload reference file/i })).toBeNull();
  });

  it("shows slash-command suggestions and completes them with Tab", async () => {
    const user = userEvent.setup();
    renderChatInput();

    const textbox = screen.getByRole("textbox");
    await user.type(textbox, "/pap");

    expect(screen.getByText("Matching Commands")).toBeTruthy();
    expect(screen.getByText("/papers")).toBeTruthy();

    fireEvent.keyDown(textbox, { key: "Tab" });

    expect(screen.getByDisplayValue("/papers")).toBeTruthy();
  });

  it("executes exact slash commands that prime structured analysis prompts", async () => {
    const user = userEvent.setup();
    const props = renderChatInput();

    const textbox = screen.getByRole("textbox");
    await user.type(textbox, "/primers");

    fireEvent.keyDown(textbox, { key: "Enter" });

    expect(props.onPrimeDraftMessage).toHaveBeenCalledWith(
      expect.stringContaining("Design PCR primers for <TARGET>")
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

  it("turns the submit button into an active stop control while streaming", async () => {
    const user = userEvent.setup();
    const props = {
      onSend: vi.fn(),
      onStop: vi.fn(),
      isStreaming: true,
      disabled: false,
      disabledReason: undefined,
      onOpenInspectorTab: vi.fn(),
      onPrimeDraftMessage: vi.fn(),
      prefillText: "",
      prefillRevision: 0,
      clearPrefill: vi.fn(),
    };

    render(
      <ChatInput
        {...props}
      />
    );

    const stopButton = screen.getByRole("button", { name: /stop response/i });
    expect(stopButton.hasAttribute("disabled")).toBe(false);

    await user.click(stopButton);

    expect(props.onStop).toHaveBeenCalledTimes(1);
    expect(props.onSend).not.toHaveBeenCalled();
  });
});
