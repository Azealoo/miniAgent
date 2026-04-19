/**
 * Pure SSE payload parser.
 *
 * Takes already-decoded string chunks from a `ReadableStream` reader and
 * returns the raw text of `data:` lines (one per payload) plus the buffered
 * remainder for payloads that were split across reader chunks. Does no JSON
 * parsing — routing the payloads through the runtime-event schema is the
 * responsibility of `chat-stream-events.ts`.
 */

/** Default cap on the unterminated buffered remainder (4 MB). */
export const DEFAULT_SSE_MAX_BUFFER_BYTES = 4 * 1024 * 1024;

export interface SseParseOptions {
  /**
   * When the underlying stream ends without a trailing blank line, callers set
   * `flush: true` so the last buffered payload is emitted instead of being
   * silently dropped.
   */
  flush?: boolean;
  /**
   * Cap (in characters, treated as a byte ballpark) on the unterminated
   * `bufferedRemainder` carried between chunks. When exceeded, the parser
   * still returns the remainder and any complete payloads from this chunk,
   * but also surfaces an `overflow` signal so callers can abort the stream
   * before unbounded memory growth turns into a DoS. Defaults to
   * `DEFAULT_SSE_MAX_BUFFER_BYTES` (4 MB). Pass `Infinity` to disable.
   */
  maxBufferBytes?: number;
}

export interface SseOverflowSignal {
  /** Size of the unterminated remainder that tripped the cap. */
  bufferedBytes: number;
  /** The cap value that was exceeded. */
  maxBufferBytes: number;
}

export interface SseParseResult {
  /** Text the parser held back because it may still be split across chunks. */
  bufferedRemainder: string;
  /** Raw text of every `data:` line surfaced during this call. */
  payloads: string[];
  /**
   * Set when the unterminated remainder exceeded `maxBufferBytes`. Callers
   * should treat this as a terminal signal — typically dispatch a synthetic
   * overflow event and cancel the reader.
   */
  overflow?: SseOverflowSignal;
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

  const bufferedRemainder = shouldFlushPending ? "" : pending;
  const maxBufferBytes = options.maxBufferBytes ?? DEFAULT_SSE_MAX_BUFFER_BYTES;
  if (bufferedRemainder.length > maxBufferBytes) {
    return {
      bufferedRemainder,
      payloads,
      overflow: {
        bufferedBytes: bufferedRemainder.length,
        maxBufferBytes,
      },
    };
  }

  return {
    bufferedRemainder,
    payloads,
  };
}
