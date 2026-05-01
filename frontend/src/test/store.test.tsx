import React, { useState } from "react";
import { act, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AppProvider, useApp } from "@/lib/store";
import {
  loadSession,
  type SessionLoadSetters,
} from "@/lib/session-history-loader";
import { makeAccessProbe } from "@/test/fixtures";
import { installMockFetch, jsonResponse, route } from "@/test/mock-fetch";
import type { AccessScope } from "@/lib/types";

let activeFetchMock: ReturnType<typeof installMockFetch> | null = null;

afterEach(() => {
  activeFetchMock?.restore();
  activeFetchMock = null;
});

function baseRoutes() {
  return [
    route("GET", "/", () => jsonResponse({ service: "miniOpenClaw", status: "ok" })),
    route("GET", "/api/access/probe", (_request, url) => {
      const scope = url.searchParams.get("scope") as AccessScope;
      return jsonResponse(makeAccessProbe(scope));
    }),
    route("GET", "/api/sessions", () => jsonResponse([])),
  ];
}

describe("AppProvider context value memoization", () => {
  it("preserves the useApp() value identity across a parent re-render with no state change", async () => {
    activeFetchMock = installMockFetch(baseRoutes());

    const captured: {
      value: ReturnType<typeof useApp> | null;
      renderCount: number;
    } = { value: null, renderCount: 0 };

    const forceRef: { current: () => void } = { current: () => {} };

    function Capture(): React.ReactElement | null {
      captured.value = useApp();
      captured.renderCount += 1;
      return null;
    }

    function Harness(): React.ReactElement {
      const [, setCounter] = useState(0);
      forceRef.current = () => setCounter((prev) => prev + 1);
      return (
        <AppProvider>
          <Capture />
        </AppProvider>
      );
    }

    render(<Harness />);

    // Let access probes and the (empty) session list settle so later renders
    // observe a steady state — otherwise the second sample would legitimately
    // differ from the first because state is still landing.
    await waitFor(() => {
      expect(captured.value?.hasInspectionAccess).toBe(true);
      expect(captured.value?.sessionListStatus).toBe("ready");
      expect(captured.value?.isSessionLoading).toBe(false);
    });

    const before = captured.value;
    const rendersBefore = captured.renderCount;

    // Force the parent to re-render. Nothing AppProvider depends on has
    // changed, so its useMemo should return the same object reference and
    // the context consumer should see an identity-equal value.
    act(() => {
      forceRef.current();
    });

    expect(captured.renderCount).toBeGreaterThan(rendersBefore);
    expect(Object.is(captured.value, before)).toBe(true);
  });
});

describe("loadSession atomic counter reset on session switch", () => {
  // Regression for issue #267: when the active session changes,
  // `parseErrorCount` and `requestIdMismatchCount` must reset in the same
  // synchronous setter batch as `setCurrentSessionId(id)`. Otherwise the
  // UsagePanel briefly shows the new session id alongside the previous
  // session's counters during the in-between render.

  function recorderSetters(): {
    calls: Array<[name: keyof SessionLoadSetters, args: unknown[]]>;
    setters: SessionLoadSetters;
  } {
    const calls: Array<[keyof SessionLoadSetters, unknown[]]> = [];
    const record =
      <K extends keyof SessionLoadSetters>(name: K) =>
      (...args: unknown[]) => {
        calls.push([name, args]);
      };
    return {
      calls,
      setters: {
        setMessages: record("setMessages"),
        setCurrentSessionId: record("setCurrentSessionId"),
        setSessionHistoryStatus: record("setSessionHistoryStatus"),
        setSessionHistoryError: record("setSessionHistoryError"),
        setSessionContinuitySummaries: record("setSessionContinuitySummaries"),
        setParseErrorCount: record("setParseErrorCount"),
        setRequestIdMismatchCount: record("setRequestIdMismatchCount"),
      },
    };
  }

  function installLoaderRoutes(): ReturnType<typeof installMockFetch> {
    return installMockFetch([
      route("GET", "/api/sessions/session-A/history", () => jsonResponse([])),
      route("GET", "/api/sessions/session-A/continuity", () =>
        jsonResponse({ summaries: [] })
      ),
      route("GET", "/api/sessions/session-B/history", () => jsonResponse([])),
      route("GET", "/api/sessions/session-B/continuity", () =>
        jsonResponse({ summaries: [] })
      ),
    ]);
  }

  it("resets parse-error and request-id-mismatch counters in the same synchronous block as setCurrentSessionId when the id changes", async () => {
    activeFetchMock = installLoaderRoutes();

    const { calls, setters } = recorderSetters();

    await loadSession(
      "session-B",
      { currentSessionId: "session-A", messages: [], continuitySummaries: [] },
      setters,
      (error) => String(error)
    );

    // The success-path setters fire after `await Promise.all([...])`. From
    // that point forward the call sequence is straight-line synchronous, so
    // every recorded setter belongs to a single React commit.
    const setIdIndex = calls.findIndex(
      ([name, args]) =>
        name === "setCurrentSessionId" && args[0] === "session-B"
    );
    const setParseIndex = calls.findIndex(
      ([name, args]) => name === "setParseErrorCount" && args[0] === 0
    );
    const setMismatchIndex = calls.findIndex(
      ([name, args]) =>
        name === "setRequestIdMismatchCount" && args[0] === 0
    );

    // All three must have fired during the success path.
    expect(setIdIndex).toBeGreaterThanOrEqual(0);
    expect(setParseIndex).toBeGreaterThanOrEqual(0);
    expect(setMismatchIndex).toBeGreaterThanOrEqual(0);

    // The counter resets must be adjacent to the id change (no other state
    // is mutated between them), so they land in one React batch.
    expect(Math.abs(setParseIndex - setIdIndex)).toBeLessThanOrEqual(2);
    expect(Math.abs(setMismatchIndex - setIdIndex)).toBeLessThanOrEqual(2);
  });

  it("does not reset counters when reloading the same session", async () => {
    activeFetchMock = installLoaderRoutes();

    const { calls, setters } = recorderSetters();

    await loadSession(
      "session-A",
      { currentSessionId: "session-A", messages: [], continuitySummaries: [] },
      setters,
      (error) => String(error)
    );

    const names = calls.map(([name]) => name);
    expect(names).toContain("setCurrentSessionId");
    // Reload should not zero counters that belong to the same session.
    expect(names).not.toContain("setParseErrorCount");
    expect(names).not.toContain("setRequestIdMismatchCount");
  });
});
