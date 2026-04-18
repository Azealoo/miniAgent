/**
 * Pure SSE payload parser.
 *
 * Takes already-decoded string chunks from a `ReadableStream` reader and
 * returns the raw text of `data:` lines (one per payload) plus the buffered
 * remainder for payloads that were split across reader chunks. Does no JSON
 * parsing — routing the payloads through the runtime-event schema is the
 * responsibility of `chat-stream-events.ts`.
 */

export interface SseParseOptions {
  /**
   * When the underlying stream ends without a trailing blank line, callers set
   * `flush: true` so the last buffered payload is emitted instead of being
   * silently dropped.
   */
  flush?: boolean;
}

export interface SseParseResult {
  /** Text the parser held back because it may still be split across chunks. */
  bufferedRemainder: string;
  /** Raw text of every `data:` line surfaced during this call. */
  payloads: string[];
}

const DATA_PREFIX = "data: ";

export function parseSseChunk(
  previousBuffer: string,
  decodedChunk: string,
  options: SseParseOptions = {}
): SseParseResult {
  const combined = previousBuffer + decodedChunk;
  const rawEvents = combined.split("\n\n");
  const pending = rawEvents.pop() ?? "";

  const shouldFlushPending =
    options.flush === true && pending.trim().length > 0;
  const eventsToProcess = shouldFlushPending
    ? [...rawEvents, pending]
    : rawEvents;

  const payloads: string[] = [];
  for (const rawEvent of eventsToProcess) {
    for (const line of rawEvent.split("\n")) {
      if (line.startsWith(DATA_PREFIX)) {
        payloads.push(line.slice(DATA_PREFIX.length));
      }
    }
  }

  return {
    bufferedRemainder: shouldFlushPending ? "" : pending,
    payloads,
  };
}
