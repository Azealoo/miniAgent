import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useSessionCatalog } from "@/lib/session-catalog";
import type { AccessScope, AccessScopeState } from "@/lib/types";

const runChatTurnMock = vi.fn();

vi.mock("@/lib/chat-turn-runner", () => ({
  runChatTurn: (...args: unknown[]) => runChatTurnMock(...args),
  stopChatTurn: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    listSessions: vi.fn(async () => []),
    createSession: vi.fn(async () => ({
      id: "session-race",
      title: "New Chat",
      updated_at: 0,
      message_count: 0,
    })),
    generateSessionTitle: vi.fn(async () => ({
      session_id: "session-race",
      title: "t",
    })),
    getHistory: vi.fn(async () => []),
  };
});

function grantedScope(scope: AccessScope): AccessScopeState {
  return {
    scope,
    status: "granted",
    authorizationMode: "loopback",
    hasToken: false,
    detail: "",
  };
}

function buildHookParams() {
  return {
    hasLoadedApiAuthState: true,
    accessByScope: {
      inspection: grantedScope("inspection"),
      execution: grantedScope("execution"),
      admin: grantedScope("admin"),
    } as Record<AccessScope, AccessScopeState>,
    hasInspectionAccess: true,
    hasExecutionAccess: true,
    promoteInspectionScopeError: vi.fn(),
    getSessionListErrorMessage: (_error: unknown) => "list-error",
    getSessionHistoryErrorMessage: (_error: unknown) => "history-error",
    resetDraftAndInspector: vi.fn(),
  };
}

describe("useSessionCatalog sendMessage — concurrent send guard", () => {
  beforeEach(() => {
    runChatTurnMock.mockReset();
  });

  it("bails out on a second sendMessage while refs from the first turn are still populated", async () => {
    // Mirror what the real runChatTurn does synchronously before its await
    // boundary: populate the refs the guard now inspects. Then hang forever
    // so the refs stay dirty for the rest of the test.
    runChatTurnMock.mockImplementation(async ({ refs }) => {
      refs.streamingIdRef.current = "assistant-1";
      refs.streamAbortControllerRef.current = new AbortController();
      refs.userStoppedStreamRef.current = false;
      await new Promise<void>(() => {});
    });

    const { result } = renderHook(() => useSessionCatalog(buildHookParams()));

    await waitFor(() => {
      expect(result.current.sessionListStatus).toBe("ready");
    });

    // Fire both calls inside the same synchronous tick: the first claims the
    // refs; the second observes them still non-null and must bail, even
    // though `isStreaming` in the useCallback closure is still false (no
    // re-render has committed yet).
    await act(async () => {
      void result.current.sendMessage("first");
      void result.current.sendMessage("second");
      // Let microtasks drain so both calls reach the guard.
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(runChatTurnMock).toHaveBeenCalledTimes(1);
    expect(runChatTurnMock.mock.calls[0][0].content).toBe("first");
  });

  it("allows a subsequent sendMessage once the prior turn's refs are cleared", async () => {
    const turns: Array<{ content: string }> = [];
    runChatTurnMock.mockImplementation(async ({ content, refs }) => {
      turns.push({ content });
      refs.streamingIdRef.current = `assistant-${turns.length}`;
      refs.streamAbortControllerRef.current = new AbortController();
      refs.userStoppedStreamRef.current = false;
      // Simulate a clean finish: reducer would null streamingIdRef on `done`,
      // and the finally block of real runChatTurn nulls the controller.
      refs.streamingIdRef.current = null;
      refs.streamAbortControllerRef.current = null;
    });

    const { result } = renderHook(() => useSessionCatalog(buildHookParams()));

    await waitFor(() => {
      expect(result.current.sessionListStatus).toBe("ready");
    });

    await act(async () => {
      await result.current.sendMessage("first");
    });
    await act(async () => {
      await result.current.sendMessage("second");
    });

    expect(runChatTurnMock).toHaveBeenCalledTimes(2);
    expect(turns.map((t) => t.content)).toEqual(["first", "second"]);
  });
});
