/**
 * Backoff/cap policy for the user-triggered "Retry turn" flow.
 *
 * The retry button on a failed SSE stream re-issues the original turn. Without
 * a cap or cooldown a user can spam-click it (or a tight failure loop can
 * stampede the backend). We bound that with a small exponential schedule plus
 * a hard attempt limit; the math lives here so it can be unit-tested in
 * isolation from React state.
 */

export const RETRY_BASE_DELAY_MS = 1000;
export const RETRY_FACTOR = 2;
export const RETRY_MAX_DELAY_MS = 30_000;
export const RETRY_MAX_ATTEMPTS = 5;
const RETRY_JITTER_FRACTION = 0.2;

export interface ComputeRetryBackoffOptions {
  /** Override Math.random() for deterministic tests. Must return [0, 1). */
  random?: () => number;
}

/**
 * Returns the cooldown (ms) the UI should wait after `attemptCount` failed
 * attempts before allowing another retry. `attemptCount` is the number of
 * failures observed so far (1 after the first failure). The result is bounded
 * by RETRY_MAX_DELAY_MS and includes additive jitter in [0, 20%) to spread
 * concurrent retries across clients.
 */
export function computeRetryBackoffMs(
  attemptCount: number,
  options: ComputeRetryBackoffOptions = {}
): number {
  if (!Number.isFinite(attemptCount) || attemptCount <= 0) {
    return 0;
  }
  const random = options.random ?? Math.random;
  const exponent = Math.max(0, Math.floor(attemptCount) - 1);
  const base = RETRY_BASE_DELAY_MS * Math.pow(RETRY_FACTOR, exponent);
  const jitter = random() * RETRY_JITTER_FRACTION;
  const withJitter = base * (1 + jitter);
  return Math.min(RETRY_MAX_DELAY_MS, Math.round(withJitter));
}

/**
 * True when the user has hit the configured max-attempts ceiling and we
 * should refuse further retries from the inline error UI.
 */
export function hasReachedRetryCap(attemptCount: number): boolean {
  return Number.isFinite(attemptCount) && attemptCount >= RETRY_MAX_ATTEMPTS;
}
