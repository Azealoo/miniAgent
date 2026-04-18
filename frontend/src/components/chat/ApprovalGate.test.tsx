import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ApprovalGate from "./ApprovalGate";
import type { SessionApprovalGateBlock } from "@/lib/types";

const submitApprovalDecisionMock = vi.fn(async () => {});

vi.mock("@/lib/store", () => ({
  useApp: () => ({
    submitApprovalDecision: submitApprovalDecisionMock,
    isStreaming: false,
    hasExecutionAccess: true,
  }),
  useAppOptional: () => ({
    submitApprovalDecision: submitApprovalDecisionMock,
    isStreaming: false,
    hasExecutionAccess: true,
  }),
}));

function makeBlock(
  overrides: Partial<SessionApprovalGateBlock> = {}
): SessionApprovalGateBlock {
  return {
    type: "approval_gate",
    tool: "terminal",
    input: '{"command": "rm -rf /"}',
    run_id: "run-42",
    reason: "requires_approval",
    message: "Approve before running.",
    ...overrides,
  };
}

afterEach(() => {
  submitApprovalDecisionMock.mockClear();
});

describe("ApprovalGate", () => {
  it("renders the rationale, preview, and approve/deny controls", () => {
    render(<ApprovalGate block={makeBlock()} sessionId="session-alpha" />);

    expect(screen.getByText("Approval required")).toBeDefined();
    expect(screen.getByText("terminal")).toBeDefined();
    expect(screen.getByText("Approve before running.")).toBeDefined();
    expect(screen.getByText("Argument preview")).toBeDefined();
    expect(screen.getByRole("button", { name: "Approve" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Deny" })).toBeDefined();
  });

  it("submits the decision with the reviewer rationale on approve click", async () => {
    render(<ApprovalGate block={makeBlock()} sessionId="session-alpha" />);

    const textarea = screen.getByPlaceholderText(
      "Why are you approving or denying?"
    );
    fireEvent.change(textarea, {
      target: { value: "Verified on a disposable VM." },
    });

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => {
      expect(submitApprovalDecisionMock).toHaveBeenCalledTimes(1);
    });
    expect(submitApprovalDecisionMock).toHaveBeenCalledWith({
      sessionId: "session-alpha",
      runId: "run-42",
      toolName: "terminal",
      decision: "approve",
      rationale: "Verified on a disposable VM.",
    });

    await waitFor(() => {
      expect(screen.getByText(/Approved terminal/)).toBeDefined();
    });
  });

  it("shows a denied state after a deny click", async () => {
    render(<ApprovalGate block={makeBlock()} sessionId="session-alpha" />);

    fireEvent.click(screen.getByRole("button", { name: "Deny" }));

    await waitFor(() => {
      expect(submitApprovalDecisionMock).toHaveBeenCalledWith(
        expect.objectContaining({ decision: "deny" })
      );
    });
    await waitFor(() => {
      expect(screen.getByText(/Denied terminal/)).toBeDefined();
    });
  });
});
