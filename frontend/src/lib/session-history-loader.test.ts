import { afterEach, describe, expect, it, vi } from "vitest";
import {
  loadSession,
  type ContinuitySummariesLoadingStatus,
  type SessionHistoryStatus,
  type SessionLoadSetters,
} from "./session-history-loader";
import type {
  Message,
  SessionContinuitySummary,
} from "./types";
import {
  installMockFetch,
  jsonResponse,
  route,
} from "@/test/mock-fetch";
import { makeSessionContinuitySummary } from "@/test/fixtures";

let activeFetchMock: ReturnType<typeof installMockFetch> | null = null;

afterEach(() => {
  activeFetchMock?.restore();
  activeFetchMock = null;
  vi.restoreAllMocks();
});

interface CapturedSetterCalls {
  continuityStatus: ContinuitySummariesLoadingStatus[];
  historyStatus: SessionHistoryStatus[];
  continuitySummaries: SessionContinuitySummary[][];
}

function makeRecordingSetters(): {
  setters: SessionLoadSetters;
  calls: CapturedSetterCalls;
} {
  const calls: CapturedSetterCalls = {
    continuityStatus: [],
    historyStatus: [],
    continuitySummaries: [],
  };
  const setters: SessionLoadSetters = {
    setMessages: () => {},
    setCurrentSessionId: () => {},
    setSessionHistoryStatus: (status) => {
      calls.historyStatus.push(status);
    },
    setSessionHistoryError: () => {},
    setSessionContinuitySummaries: (summaries) => {
      calls.continuitySummaries.push(summaries);
    },
    setSessionContinuitySummariesLoadingStatus: (status) => {
      calls.continuityStatus.push(status);
    },
  };
  return { setters, calls };
}

const emptySnapshot: {
  currentSessionId: string | null;
  messages: Message[];
  continuitySummaries: SessionContinuitySummary[];
} = {
  currentSessionId: null,
  messages: [],
  continuitySummaries: [],
};

describe("loadSession continuity loading status transitions", () => {
  it("transitions loading -> ready when history and continuity both resolve", async () => {
    activeFetchMock = installMockFetch([
      route("GET", "/api/sessions/session-alpha/history", () =>
        jsonResponse([])
      ),
      route("GET", "/api/sessions/session-alpha/continuity", () =>
        jsonResponse({ summaries: [makeSessionContinuitySummary()] })
      ),
    ]);

    const { setters, calls } = makeRecordingSetters();
    const getErrorMessage = (error: unknown) =>
      error instanceof Error ? error.message : "load error";

    await loadSession("session-alpha", emptySnapshot, setters, getErrorMessage);

    expect(calls.continuityStatus).toEqual(["loading", "ready"]);
    expect(calls.historyStatus).toEqual(["loading", "ready"]);
    expect(calls.continuitySummaries.length).toBeGreaterThanOrEqual(2);
    expect(calls.continuitySummaries.at(-1)?.length).toBe(1);
  });

  it("transitions loading -> error when the history fetch fails", async () => {
    activeFetchMock = installMockFetch([
      route(
        "GET",
        "/api/sessions/session-broken/history",
        () => new Response("session unavailable", { status: 500 })
      ),
      route("GET", "/api/sessions/session-broken/continuity", () =>
        jsonResponse({ summaries: [] })
      ),
    ]);

    const { setters, calls } = makeRecordingSetters();
    const getErrorMessage = (error: unknown) =>
      error instanceof Error ? error.message : "load error";

    await expect(
      loadSession("session-broken", emptySnapshot, setters, getErrorMessage)
    ).rejects.toBeDefined();

    expect(calls.continuityStatus).toEqual(["loading", "error"]);
    expect(calls.historyStatus).toEqual(["loading", "error"]);
  });
});
