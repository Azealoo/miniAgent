import React from "react";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/store", () => ({
  useApp: vi.fn(),
}));

vi.mock("@/components/chat/ChatInput", () => ({
  default: () => <div data-testid="chat-input-stub" />,
}));

vi.mock("@/components/session/SessionHistorySummary", () => ({
  default: () => <div data-testid="session-history-stub" />,
}));

import { useApp } from "@/lib/store";
import ChatPanel from "@/components/chat/ChatPanel";
import { RETRY_MAX_ATTEMPTS } from "@/lib/retry-backoff";
import { makeMockAppValue } from "@/test/panel-fixtures";
import type { FailedTurnState } from "@/lib/session-catalog";

function findRetryButton(): HTMLButtonElement {
  const buttons = screen.getAllByRole("button") as HTMLButtonElement[];
  const match = buttons.find((b) =>
    /Retry( turn| in | failed)|No more retries/i.test(b.textContent ?? "")
  );
  if (!match) {
    throw new Error("Retry button not found in rendered ChatPanel");
  }
  return match;
}

describe("ChatPanel retry banner", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T00:00:00.000Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  function renderWithFailedTurn(failedTurn: FailedTurnState) {
    const sendMessage = vi.fn(async () => {});
    const clearLastFailedTurn = vi.fn();
    vi.mocked(useApp).mockReturnValue(
      makeMockAppValue({
        lastFailedTurn: failedTurn,
        sendMessage,
        clearLastFailedTurn,
      })
    );
    const result = render(<ChatPanel />);
    return { sendMessage, clearLastFailedTurn, ...result };
  }

  it("disables the Retry button while the cooldown window is active", () => {
    const now = Date.now();
    renderWithFailedTurn({
      content: "ping",
      requestId: "req-1",
      attemptCount: 1,
      nextAllowedRetryAt: now + 5_000,
      reachedCap: false,
    });

    const button = findRetryButton();
    expect(button.disabled).toBe(true);
    expect(button.textContent).toMatch(/Retry in \d+s/);
  });

  it("re-enables the Retry button once the cooldown elapses", () => {
    const now = Date.now();
    const { sendMessage } = renderWithFailedTurn({
      content: "ping",
      requestId: "req-1",
      attemptCount: 1,
      nextAllowedRetryAt: now + 1_000,
      reachedCap: false,
    });

    expect(findRetryButton().disabled).toBe(true);

    act(() => {
      vi.advanceTimersByTime(1_500);
    });

    const button = findRetryButton();
    expect(button.disabled).toBe(false);
    expect(button.textContent).toMatch(/Retry turn/);

    act(() => {
      button.click();
    });
    expect(sendMessage).toHaveBeenCalledTimes(1);
    expect(sendMessage).toHaveBeenCalledWith("ping", { requestId: "req-1" });
  });

  it("disables the Retry button and shows 'No more retries' once the cap is hit", () => {
    const { sendMessage } = renderWithFailedTurn({
      content: "ping",
      requestId: "req-1",
      attemptCount: RETRY_MAX_ATTEMPTS,
      nextAllowedRetryAt: Number.POSITIVE_INFINITY,
      reachedCap: true,
    });

    const button = findRetryButton();
    expect(button.disabled).toBe(true);
    expect(button.textContent).toMatch(/No more retries/);

    act(() => {
      button.click();
    });
    expect(sendMessage).not.toHaveBeenCalled();
  });

  it("surfaces the retry-limit copy in the banner description when capped", () => {
    renderWithFailedTurn({
      content: "ping",
      requestId: "req-1",
      attemptCount: RETRY_MAX_ATTEMPTS,
      nextAllowedRetryAt: Number.POSITIVE_INFINITY,
      reachedCap: true,
    });

    expect(
      screen.getByText(
        new RegExp(`retry limit \\(${RETRY_MAX_ATTEMPTS}\\) has been reached`, "i")
      )
    ).toBeTruthy();
  });

  it("triggers sendMessage with the original requestId on a fresh failure (no cooldown remaining)", () => {
    const now = Date.now();
    const { sendMessage } = renderWithFailedTurn({
      content: "hello",
      requestId: "req-7",
      attemptCount: 1,
      nextAllowedRetryAt: now - 1, // already past — no cooldown remaining
      reachedCap: false,
    });

    const button = findRetryButton();
    expect(button.disabled).toBe(false);

    act(() => {
      button.click();
    });
    expect(sendMessage).toHaveBeenCalledWith("hello", { requestId: "req-7" });
  });
});
