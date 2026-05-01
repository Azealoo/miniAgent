import * as api from "./api";
import {
  applyStreamEvent,
  createOptimisticAssistantMessage,
} from "./chat-stream-reducer";
import { uid } from "./utils";
import type {
  ChatStreamEvent,
  ChatStreamParseErrorEvent,
  Message,
} from "./types";

export interface ChatTurnRefs {
  messagesRef: React.MutableRefObject<Message[]>;
  streamingIdRef: React.MutableRefObject<string | null>;
  streamAbortControllerRef: React.MutableRefObject<AbortController | null>;
  userStoppedStreamRef: React.MutableRefObject<boolean>;
}

export interface ChatTurnCallbacks {
  setMessages: (messages: Message[]) => void;
  setIsStreaming: (value: boolean) => void;
  onTurnComplete: (messageCount: number) => void;
  /**
   * Fired when a turn terminates because an `error` event finalized the
   * stream. Carries the request_id the turn was correlated against (either
   * the caller-supplied override or the backend-generated id, if any).
   */
  onTurnError?: (requestId: string | undefined) => void;
  /**
   * Fired for every synthetic `parse_error` event surfaced by the stream
   * parser. Used by the catalog to maintain a session-level counter so the
   * UsagePanel can surface dropped-event telemetry.
   */
  onParseError?: (event: ChatStreamParseErrorEvent) => void;
  /**
   * Fired when the stream dispatcher drops an event because its
   * `request_id` doesn't match the one latched for this turn. Used by the
   * catalog to maintain a session-level counter alongside parse errors.
   */
  onRequestIdMismatch?: (event: ChatStreamEvent) => void;
}

export interface RunChatTurnParams {
  content: string;
  sessionId: string;
  refs: ChatTurnRefs;
  callbacks: ChatTurnCallbacks;
  /**
   * Optional request_id override — used when retrying a previously failed
   * turn so the new assistant message carries the original correlation id.
   */
  requestId?: string;
}

/**
 * Drives a single chat turn: seeds the optimistic user + assistant messages,
 * streams SSE events from the backend, and routes every live mutation through
 * `applyStreamEvent` so the reducer is the sole source of in-flight state
 * updates. The caller owns the React state/refs we mutate — we just wire them.
 */
export async function runChatTurn({
  content,
  sessionId,
  refs,
  callbacks,
  requestId,
}: RunChatTurnParams): Promise<void> {
  const userMsg: Message = {
    id: uid(),
    role: "user",
    content,
    request_id: requestId,
    blocks: [{ type: "text", text: content }],
  };
  const assistantMsg = createOptimisticAssistantMessage(
    uid(),
    Date.now(),
    requestId
  );
  refs.streamingIdRef.current = assistantMsg.id;

  const nextMessages = [...refs.messagesRef.current, userMsg, assistantMsg];
  refs.messagesRef.current = nextMessages;
  callbacks.setMessages(nextMessages);
  callbacks.setIsStreaming(true);

  const abortController = new AbortController();
  refs.streamAbortControllerRef.current = abortController;
  refs.userStoppedStreamRef.current = false;

  const applyAndCommitEvent = (event: ChatStreamEvent) => {
    if (event.type === "parse_error") {
      callbacks.onParseError?.(event);
    }
    const reduced = applyStreamEvent(
      {
        messages: refs.messagesRef.current,
        streamingMessageId: refs.streamingIdRef.current,
      },
      event,
      {
        createMessageId: uid,
        now: Date.now(),
      }
    );

    refs.messagesRef.current = reduced.messages;
    refs.streamingIdRef.current = reduced.streamingMessageId;
    callbacks.setMessages(reduced.messages);

    if (reduced.finished) {
      callbacks.setIsStreaming(false);
      if (event.type === "done") {
        callbacks.onTurnComplete(reduced.messages.length);
      } else if (event.type === "error") {
        callbacks.onTurnError?.(event.request_id ?? requestId);
      }
    }
  };

  try {
    await api.streamChat(
      content,
      sessionId,
      {
        signal: abortController.signal,
        onEvent: applyAndCommitEvent,
        onRequestIdMismatch: (event) => {
          callbacks.onRequestIdMismatch?.(event);
        },
      },
      { requestId }
    );
  } catch (error) {
    if (api.isAbortError(error) && refs.userStoppedStreamRef.current) {
      applyAndCommitEvent({
        type: "done",
        content: "Response stopped.",
      });
    } else {
      applyAndCommitEvent({
        type: "error",
        error:
          error instanceof Error
            ? error.message
            : "The response stream failed before completion.",
      });
    }
  } finally {
    refs.streamAbortControllerRef.current = null;
    refs.userStoppedStreamRef.current = false;
  }
}

export function stopChatTurn(refs: ChatTurnRefs): void {
  if (!refs.streamAbortControllerRef.current || !refs.streamingIdRef.current) {
    return;
  }

  refs.userStoppedStreamRef.current = true;
  refs.streamAbortControllerRef.current.abort();
}
