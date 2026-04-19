import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useEffect, useRef, useState } from "react";
import { EMPTY_API_AUTH_STATE } from "@/lib/access-control";
import { useAccessScopeState } from "@/lib/access-scope-state";
import type * as api from "@/lib/api";
import { installMockFetch, jsonResponse, route } from "@/test/mock-fetch";
import { makeAccessProbe } from "@/test/fixtures";
import type { AccessScope } from "@/lib/types";

let activeFetchMock: ReturnType<typeof installMockFetch> | null = null;

afterEach(() => {
  activeFetchMock?.restore();
  activeFetchMock = null;
});

function baseRoutes() {
  return [
    route("GET", "/api/access/probe", (_request, url) => {
      const scope = url.searchParams.get("scope") as AccessScope;
      return jsonResponse(makeAccessProbe(scope));
    }),
  ];
}

function useAccessScopeHarness(pollIntervalMs?: number) {
  const [authState, setAuthState] = useState<api.ApiAuthState>({
    ...EMPTY_API_AUTH_STATE,
  });
  const authStateRef = useRef(authState);
  useEffect(() => {
    authStateRef.current = authState;
  }, [authState]);

  const access = useAccessScopeState(
    authState,
    authStateRef,
    true,
    pollIntervalMs
  );

  return { access, setAuthState };
}

describe("useAccessScopeState polling", () => {
  it("does not call the probe in a loop when auth state toggles", async () => {
    activeFetchMock = installMockFetch(baseRoutes());

    const { result } = renderHook(() => useAccessScopeHarness());

    // Wait for the initial three-scope probe fan-out to settle.
    await waitFor(() => {
      expect(result.current.access.hasInspectionAccess).toBe(true);
    });

    const initialCallCount = activeFetchMock.captured.length;
    // The initial probe should hit each of the three access scopes once.
    expect(initialCallCount).toBe(3);

    // Toggle the auth state repeatedly. Each change only triggers one probe
    // fan-out (three fetches), never a runaway loop driven by effect deps.
    await act(async () => {
      result.current.setAuthState((prev) => ({
        ...prev,
        inspectionBearerToken: "token-1",
      }));
    });

    await waitFor(() => {
      expect(activeFetchMock!.captured.length).toBe(initialCallCount + 3);
    });

    await act(async () => {
      result.current.setAuthState((prev) => ({
        ...prev,
        inspectionBearerToken: "token-2",
      }));
    });

    await waitFor(() => {
      expect(activeFetchMock!.captured.length).toBe(initialCallCount + 6);
    });

    // Give microtasks time to flush and confirm no additional requests land.
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(activeFetchMock.captured.length).toBe(initialCallCount + 6);
  });

  it("honors the configured poll interval for background recovery", async () => {
    vi.useFakeTimers({
      toFake: ["setInterval", "clearInterval", "setTimeout", "clearTimeout"],
    });

    try {
      activeFetchMock = installMockFetch([
        // Return a 500 so scopes land in `unavailable` and polling turns on.
        route("GET", "/api/access/probe", () =>
          jsonResponse({ detail: "offline" }, { status: 500 })
        ),
      ]);

      const { result } = renderHook(() => useAccessScopeHarness(500));

      await waitFor(() => {
        expect(
          result.current.access.accessByScope.inspection.status
        ).not.toBe("checking");
      });

      const afterInitial = activeFetchMock.captured.length;
      expect(afterInitial).toBe(3);

      // Advance past a single custom interval tick and confirm one fan-out
      // ran, proving the interval is configurable rather than hardcoded.
      await act(async () => {
        vi.advanceTimersByTime(500);
        await Promise.resolve();
      });

      await waitFor(() => {
        expect(activeFetchMock!.captured.length).toBe(afterInitial + 3);
      });
    } finally {
      vi.useRealTimers();
    }
  });
});
