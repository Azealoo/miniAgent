import { useEffect } from "react";

export const DEFAULT_ACCESS_PROBE_POLL_INTERVAL_MS = 30_000;

export interface UseAccessProbeOptions {
  /**
   * Invoked on window `focus`, `online`, and (when `shouldPoll` is true) on a
   * recurring interval. The hook only fires this when the browser is online —
   * callers can treat it as a best-effort background probe.
   */
  probe: () => void;
  /**
   * Gate the focus/online/interval wiring. When false (e.g., before auth state
   * has hydrated) the hook is a no-op.
   */
  enabled: boolean;
  /**
   * Enables the recurring interval. Focus/online listeners stay attached even
   * when this is false so recovery still happens on visibility changes.
   */
  shouldPoll: boolean;
  /**
   * Interval in milliseconds. Exposed so tests and callers can override the
   * default (30s).
   */
  pollIntervalMs?: number;
}

/**
 * Background access-recovery polling. Listens for focus/online events and,
 * when `shouldPoll` is set, also fires on a timer. The probe must be stable
 * across renders (typically wrapped in `useCallback` with ref-backed inputs)
 * so the hook does not tear down and reinstall listeners on every render.
 */
export function useAccessProbe({
  probe,
  enabled,
  shouldPoll,
  pollIntervalMs = DEFAULT_ACCESS_PROBE_POLL_INTERVAL_MS,
}: UseAccessProbeOptions): void {
  useEffect(() => {
    if (!enabled || typeof window === "undefined") {
      return;
    }

    const handleBackgroundProbe = () => {
      if (!window.navigator.onLine) {
        return;
      }
      probe();
    };

    window.addEventListener("focus", handleBackgroundProbe);
    window.addEventListener("online", handleBackgroundProbe);

    const intervalId = shouldPoll
      ? window.setInterval(handleBackgroundProbe, pollIntervalMs)
      : null;

    return () => {
      window.removeEventListener("focus", handleBackgroundProbe);
      window.removeEventListener("online", handleBackgroundProbe);
      if (intervalId !== null) {
        window.clearInterval(intervalId);
      }
    };
  }, [enabled, probe, shouldPoll, pollIntervalMs]);
}
