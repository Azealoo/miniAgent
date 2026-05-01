import { describe, expect, it } from "vitest";
import {
  RETRY_BASE_DELAY_MS,
  RETRY_FACTOR,
  RETRY_MAX_ATTEMPTS,
  RETRY_MAX_DELAY_MS,
  computeRetryBackoffMs,
  hasReachedRetryCap,
} from "@/lib/retry-backoff";

describe("computeRetryBackoffMs", () => {
  it("returns the base delay on the first failure with zero jitter", () => {
    expect(computeRetryBackoffMs(1, { random: () => 0 })).toBe(
      RETRY_BASE_DELAY_MS
    );
  });

  it("doubles the delay with each subsequent failure (zero jitter)", () => {
    const rand = () => 0;
    expect(computeRetryBackoffMs(2, { random: rand })).toBe(
      RETRY_BASE_DELAY_MS * RETRY_FACTOR
    );
    expect(computeRetryBackoffMs(3, { random: rand })).toBe(
      RETRY_BASE_DELAY_MS * RETRY_FACTOR * RETRY_FACTOR
    );
    expect(computeRetryBackoffMs(4, { random: rand })).toBe(
      RETRY_BASE_DELAY_MS * Math.pow(RETRY_FACTOR, 3)
    );
  });

  it("applies up to ~20% jitter on top of the base delay", () => {
    const result = computeRetryBackoffMs(1, { random: () => 0.999_999 });
    expect(result).toBeGreaterThanOrEqual(RETRY_BASE_DELAY_MS);
    expect(result).toBeLessThanOrEqual(Math.ceil(RETRY_BASE_DELAY_MS * 1.2));
  });

  it("clamps the delay to RETRY_MAX_DELAY_MS even with maximum jitter", () => {
    // Attempt 10 would otherwise be 1000 * 2^9 = 512000ms.
    expect(computeRetryBackoffMs(10, { random: () => 0.999_999 })).toBe(
      RETRY_MAX_DELAY_MS
    );
  });

  it("returns 0 for non-positive or non-finite attempt counts", () => {
    const rand = () => 0.5;
    expect(computeRetryBackoffMs(0, { random: rand })).toBe(0);
    expect(computeRetryBackoffMs(-1, { random: rand })).toBe(0);
    expect(computeRetryBackoffMs(Number.NaN, { random: rand })).toBe(0);
    expect(
      computeRetryBackoffMs(Number.POSITIVE_INFINITY, { random: rand })
    ).toBe(0);
  });

  it("monotonically increases (or stays at the cap) as attempts grow with fixed jitter", () => {
    const rand = () => 0.5;
    let previous = -1;
    for (let attempt = 1; attempt <= 12; attempt += 1) {
      const value = computeRetryBackoffMs(attempt, { random: rand });
      expect(value).toBeGreaterThanOrEqual(previous);
      previous = value;
    }
  });
});

describe("hasReachedRetryCap", () => {
  it("returns false until RETRY_MAX_ATTEMPTS attempts have been recorded", () => {
    for (let attempt = 0; attempt < RETRY_MAX_ATTEMPTS; attempt += 1) {
      expect(hasReachedRetryCap(attempt)).toBe(false);
    }
  });

  it("returns true once RETRY_MAX_ATTEMPTS is reached", () => {
    expect(hasReachedRetryCap(RETRY_MAX_ATTEMPTS)).toBe(true);
    expect(hasReachedRetryCap(RETRY_MAX_ATTEMPTS + 1)).toBe(true);
  });

  it("treats non-finite attempt counts as below the cap", () => {
    expect(hasReachedRetryCap(Number.NaN)).toBe(false);
    expect(hasReachedRetryCap(Number.POSITIVE_INFINITY)).toBe(false);
  });
});
