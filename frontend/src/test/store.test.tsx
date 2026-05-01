import React, { useState } from "react";
import { act, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AppProvider, useApp } from "@/lib/store";
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
