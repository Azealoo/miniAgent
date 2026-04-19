import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  __resetTelemetryForTests,
  __scrubForTests,
  log,
} from "@/lib/telemetry";

describe("telemetry scrub", () => {
  it("removes query strings and fragments from URLs in messages", () => {
    const envelope = __scrubForTests("error", {
      event: "error_boundary",
      message:
        "Failed at https://example.invalid/api/thing?token=sk-hunter&id=42#frag",
    });
    expect(envelope.message).toBe(
      "Failed at https://example.invalid/api/thing"
    );
  });

  it("redacts secret-looking meta keys", () => {
    const envelope = __scrubForTests("error", {
      event: "test",
      meta: {
        token: "sk-live-abc",
        password: "hunter2",
        api_key: "key",
        cookie: "session=abc",
        safe: "ok",
      },
    });
    expect(envelope.meta).toMatchObject({
      token: "[redacted]",
      password: "[redacted]",
      api_key: "[redacted]",
      cookie: "[redacted]",
      safe: "ok",
    });
  });

  it("drops stack frames that point at absolute filesystem paths", () => {
    const stack = [
      "Error: kaboom",
      "    at doStuff (/home/alice/secret-project/app.js:12:3)",
      "    at otherStuff (/_next/static/chunks/webpack.js:1:1)",
      "    at nextStuff (webpack-internal:///./src/lib/api.ts:22:9)",
    ].join("\n");
    const envelope = __scrubForTests("error", {
      event: "test",
      stack,
    });
    expect(envelope.stack).toBeDefined();
    expect(envelope.stack).not.toContain("/home/alice");
    expect(envelope.stack).toContain("/_next/static/chunks/webpack.js");
    expect(envelope.stack).toContain("webpack-internal:");
  });

  it("truncates very long messages and stacks", () => {
    const message = "x".repeat(5_000);
    const stack = "y".repeat(20_000);
    const envelope = __scrubForTests("error", {
      event: "test",
      message,
      stack,
    });
    expect(envelope.message?.length ?? 0).toBeLessThanOrEqual(500);
    expect(envelope.stack?.length ?? 0).toBeLessThanOrEqual(4_000);
  });
});

describe("log.error transport", () => {
  let fetchSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    __resetTelemetryForTests();
    fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify({ recorded: true }), { status: 200 }));
  });

  afterEach(() => {
    fetchSpy.mockRestore();
    __resetTelemetryForTests();
  });

  it("POSTs a scrubbed envelope to /api/audit/client with keepalive", async () => {
    log.error({
      event: "error_boundary",
      message: "oops",
      meta: { label: "Workspace" },
    });

    // Fire-and-forget; flush the microtask queue.
    await Promise.resolve();
    await Promise.resolve();

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0];
    expect(String(url)).toContain("/api/audit/client");
    expect(init?.method).toBe("POST");
    expect(init?.keepalive).toBe(true);

    const body = JSON.parse(String(init?.body));
    expect(body).toMatchObject({
      level: "error",
      event: "error_boundary",
      message: "oops",
      meta: { label: "Workspace" },
    });
  });

  it("never throws when fetch rejects", async () => {
    fetchSpy.mockRejectedValue(new Error("network down"));

    expect(() =>
      log.error({ event: "error_boundary", message: "oops" })
    ).not.toThrow();

    // Flush the fire-and-forget promise so the rejection is handled and
    // does not surface as an unhandled rejection.
    await Promise.resolve();
    await Promise.resolve();
  });

  it("stops sending after a 429 response until reset", async () => {
    fetchSpy.mockResolvedValue(new Response(null, { status: 429 }));

    log.error({ event: "error_boundary", message: "first" });
    await Promise.resolve();
    await Promise.resolve();

    log.error({ event: "error_boundary", message: "second" });
    await Promise.resolve();
    await Promise.resolve();

    // Only the first call goes through; the second is suppressed.
    expect(fetchSpy).toHaveBeenCalledTimes(1);

    __resetTelemetryForTests();
    log.error({ event: "error_boundary", message: "third" });
    await Promise.resolve();
    await Promise.resolve();
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });
});
