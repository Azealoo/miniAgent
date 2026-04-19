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
