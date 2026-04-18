import { describe, expect, it } from "vitest";
import { parseSseChunk } from "./sse-parser";

describe("parseSseChunk", () => {
  it("returns an empty result when no full event has been received yet", () => {
    const result = parseSseChunk("", "data: {\"type\":\"");
    expect(result.payloads).toEqual([]);
    expect(result.bufferedRemainder).toBe('data: {"type":"');
  });

  it("surfaces payloads split across reader chunks once the terminator arrives", () => {
    const first = parseSseChunk("", 'data: {"type":"tok');
    expect(first.payloads).toEqual([]);
    expect(first.bufferedRemainder).toBe('data: {"type":"tok');

    const second = parseSseChunk(
      first.bufferedRemainder,
      'en","content":"hello"}\n\n'
    );
    expect(second.payloads).toEqual(['{"type":"token","content":"hello"}']);
    expect(second.bufferedRemainder).toBe("");
  });

  it("emits multiple payloads when a single chunk contains several events", () => {
    const chunk =
      'data: {"type":"token","content":"a"}\n\n' +
      'data: {"type":"token","content":"b"}\n\n';
    const result = parseSseChunk("", chunk);
    expect(result.payloads).toEqual([
      '{"type":"token","content":"a"}',
      '{"type":"token","content":"b"}',
    ]);
    expect(result.bufferedRemainder).toBe("");
  });

  it("preserves the trailing partial event for the next call", () => {
    const chunk =
      'data: {"type":"token","content":"a"}\n\n' +
      'data: {"type":"tok';
    const result = parseSseChunk("", chunk);
    expect(result.payloads).toEqual(['{"type":"token","content":"a"}']);
    expect(result.bufferedRemainder).toBe('data: {"type":"tok');
  });

  it("flushes the final buffered event when the stream ends without a blank line", () => {
    const pending = 'data: {"type":"done","content":"final"}';
    const result = parseSseChunk(pending, "", { flush: true });
    expect(result.payloads).toEqual(['{"type":"done","content":"final"}']);
    expect(result.bufferedRemainder).toBe("");
  });

  it("does not flush when the buffered remainder is whitespace-only", () => {
    const result = parseSseChunk("   \n", "", { flush: true });
    expect(result.payloads).toEqual([]);
    expect(result.bufferedRemainder).toBe("   \n");
  });

  it("ignores non-data SSE lines (comments, event:, id:)", () => {
    const chunk =
      ": heartbeat\n" +
      "event: token\n" +
      "id: 42\n" +
      'data: {"type":"token","content":"ok"}\n\n';
    const result = parseSseChunk("", chunk);
    expect(result.payloads).toEqual(['{"type":"token","content":"ok"}']);
    expect(result.bufferedRemainder).toBe("");
  });

  it("handles a boundary that lands mid-separator between two events", () => {
    const chunkA = 'data: {"type":"token","content":"a"}\n';
    const chunkB = '\ndata: {"type":"token","content":"b"}\n\n';

    const first = parseSseChunk("", chunkA);
    expect(first.payloads).toEqual([]);
    expect(first.bufferedRemainder).toBe(chunkA);

    const second = parseSseChunk(first.bufferedRemainder, chunkB);
    expect(second.payloads).toEqual([
      '{"type":"token","content":"a"}',
      '{"type":"token","content":"b"}',
    ]);
    expect(second.bufferedRemainder).toBe("");
  });

  it("returns raw payload text without attempting to JSON.parse — malformed JSON is the caller's problem", () => {
    const result = parseSseChunk("", "data: {not-json}\n\n");
    expect(result.payloads).toEqual(["{not-json}"]);
    expect(result.bufferedRemainder).toBe("");
  });
});
