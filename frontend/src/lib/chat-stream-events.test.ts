import { describe, expect, it, vi } from "vitest";
import {
  createChatStreamDispatcher,
  parseChatStreamChunk,
  parseChatStreamDataPayload,
} from "./chat-stream-events";

describe("parseChatStreamChunk", () => {
  it("surfaces a parse_error event for a malformed SSE data line", () => {
    const chunk = "data: {not-json}\n\n";

    const { events, bufferedRemainder } = parseChatStreamChunk("", chunk);

    expect(bufferedRemainder).toBe("");
    expect(events).toHaveLength(1);
    const [event] = events;
    expect(event.type).toBe("parse_error");
    if (event.type === "parse_error") {
      expect(event.error).toMatch(/JSON/i);
      expect(event.raw).toBe("{not-json}");
    }
  });

  it("dispatches malformed events through onParseError without ending the stream", () => {
    const onParseError = vi.fn();
    const onEvent = vi.fn();
    const dispatcher = createChatStreamDispatcher({ onParseError, onEvent });

    const { events } = parseChatStreamChunk("", "data: {not-json}\n\n");
    for (const event of events) {
      dispatcher.dispatch(event);
    }

    expect(onParseError).toHaveBeenCalledTimes(1);
    const [firstCallArg] = onParseError.mock.calls[0];
    expect(firstCallArg.type).toBe("parse_error");
    expect(firstCallArg.error).toMatch(/JSON/i);
    expect(firstCallArg.raw).toBe("{not-json}");
    expect(onEvent).toHaveBeenCalledTimes(1);
    expect(dispatcher.sawTerminalEvent()).toBe(false);
  });
});

describe("parseChatStreamChunk overflow", () => {
  it("propagates the overflow signal from the underlying SSE parser", () => {
    const cap = 32;
    const oversized = "data: " + "x".repeat(cap + 16);

    const { events, bufferedRemainder, overflow } = parseChatStreamChunk("", oversized, {
      maxBufferBytes: cap,
    });

    expect(events).toEqual([]);
    expect(bufferedRemainder).toBe(oversized);
    expect(overflow).toEqual({
      bufferedBytes: oversized.length,
      maxBufferBytes: cap,
    });
  });

  it("dispatches a stream_overflow event through onStreamOverflow and treats it as terminal", () => {
    const onStreamOverflow = vi.fn();
    const onEvent = vi.fn();
    const onError = vi.fn();
    const dispatcher = createChatStreamDispatcher({
      onStreamOverflow,
      onEvent,
      onError,
    });

    dispatcher.dispatch({
      type: "stream_overflow",
      bufferedBytes: 4_194_305,
      maxBufferBytes: 4_194_304,
    });

    expect(onStreamOverflow).toHaveBeenCalledTimes(1);
    const [arg] = onStreamOverflow.mock.calls[0];
    expect(arg.type).toBe("stream_overflow");
    expect(arg.bufferedBytes).toBe(4_194_305);
    expect(arg.maxBufferBytes).toBe(4_194_304);
    expect(onEvent).toHaveBeenCalledTimes(1);
    expect(onError).not.toHaveBeenCalled();
    expect(dispatcher.sawTerminalEvent()).toBe(true);
  });
});

describe("createChatStreamDispatcher request-id correlation", () => {
  it("latches on to the first request_id and applies events that match", () => {
    const onEvent = vi.fn();
    const onRequestIdMismatch = vi.fn();
    const onToken = vi.fn();
    const dispatcher = createChatStreamDispatcher({
      onEvent,
      onToken,
      onRequestIdMismatch,
    });

    dispatcher.dispatch({ type: "token", content: "hello ", request_id: "req-1" });
    dispatcher.dispatch({ type: "token", content: "world", request_id: "req-1" });

    expect(onEvent).toHaveBeenCalledTimes(2);
    expect(onToken).toHaveBeenNthCalledWith(1, "hello ");
    expect(onToken).toHaveBeenNthCalledWith(2, "world");
    expect(onRequestIdMismatch).not.toHaveBeenCalled();
    expect(dispatcher.expectedRequestId()).toBe("req-1");
  });

  it("drops subsequent events that carry a mismatched request_id", () => {
    const onEvent = vi.fn();
    const onToken = vi.fn();
    const onRequestIdMismatch = vi.fn();
    const dispatcher = createChatStreamDispatcher({
      onEvent,
      onToken,
      onRequestIdMismatch,
    });

    dispatcher.dispatch({ type: "token", content: "first", request_id: "req-1" });
    dispatcher.dispatch({
      type: "token",
      content: "stale echo",
      request_id: "req-stale",
    });

    expect(onEvent).toHaveBeenCalledTimes(1);
    expect(onToken).toHaveBeenCalledTimes(1);
    expect(onToken).toHaveBeenCalledWith("first");
    expect(onRequestIdMismatch).toHaveBeenCalledTimes(1);
    const [droppedEvent] = onRequestIdMismatch.mock.calls[0];
    expect(droppedEvent.type).toBe("token");
    expect(droppedEvent.request_id).toBe("req-stale");
    expect(dispatcher.expectedRequestId()).toBe("req-1");
  });

  it("applies events without a request_id regardless of the latched id", () => {
    const onEvent = vi.fn();
    const onToken = vi.fn();
    const onRequestIdMismatch = vi.fn();
    const dispatcher = createChatStreamDispatcher({
      onEvent,
      onToken,
      onRequestIdMismatch,
    });

    dispatcher.dispatch({ type: "token", content: "pinned", request_id: "req-1" });
    dispatcher.dispatch({ type: "token", content: "no-id-token" });

    expect(onEvent).toHaveBeenCalledTimes(2);
    expect(onToken).toHaveBeenNthCalledWith(2, "no-id-token");
    expect(onRequestIdMismatch).not.toHaveBeenCalled();
  });

  it("applies events when no expected id has been set yet", () => {
    const onEvent = vi.fn();
    const onToken = vi.fn();
    const onRequestIdMismatch = vi.fn();
    const dispatcher = createChatStreamDispatcher({
      onEvent,
      onToken,
      onRequestIdMismatch,
    });

    dispatcher.dispatch({ type: "token", content: "before-id" });
    dispatcher.dispatch({ type: "token", content: "also-before-id" });

    expect(onEvent).toHaveBeenCalledTimes(2);
    expect(onRequestIdMismatch).not.toHaveBeenCalled();
    expect(dispatcher.expectedRequestId()).toBeUndefined();
  });

  it("honors a pre-seeded expected request id", () => {
    const onEvent = vi.fn();
    const onRequestIdMismatch = vi.fn();
    const dispatcher = createChatStreamDispatcher(
      { onEvent, onRequestIdMismatch },
      { expectedRequestId: "req-seeded" }
    );

    dispatcher.dispatch({ type: "token", content: "match", request_id: "req-seeded" });
    dispatcher.dispatch({ type: "token", content: "drop", request_id: "req-other" });
    dispatcher.dispatch({ type: "token", content: "always-apply" });

    expect(onEvent).toHaveBeenCalledTimes(2);
    expect(onRequestIdMismatch).toHaveBeenCalledTimes(1);
    expect(dispatcher.expectedRequestId()).toBe("req-seeded");
  });
});

describe("parseChatStreamDataPayload", () => {
  it("preserves the raw payload when the JSON parser rejects it", () => {
    const event = parseChatStreamDataPayload("definitely not json");
    expect(event.type).toBe("parse_error");
    if (event.type === "parse_error") {
      expect(event.raw).toBe("definitely not json");
    }
  });

  it("truncates very large raw payloads so telemetry stays bounded", () => {
    const giant = "x".repeat(3000);
    const event = parseChatStreamDataPayload(giant);
    expect(event.type).toBe("parse_error");
    if (event.type === "parse_error") {
      expect(event.raw?.length).toBeLessThanOrEqual(2001);
      expect(event.raw?.endsWith("…")).toBe(true);
    }
  });
});
