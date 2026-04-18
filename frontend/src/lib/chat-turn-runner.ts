import * as api from "./api";
import {
  applyStreamEvent,
  createOptimisticAssistantMessage,
} from "./chat-stream-reducer";
import { uid } from "./utils";
import type { ChatStreamEvent, Message } from "./types";

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
}

export interface RunChatTurnParams {
  content: string;
  sessionId: string;
  refs: ChatTurnRefs;
  callbacks: ChatTurnCallbacks;
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
}: RunChatTurnParams): Promise<void> {
  const userMsg: Message = {
    id: uid(),
    role: "user",
    content,
    blocks: [{ type: "text", text: content }],
  };
  const assistantMsg = createOptimisticAssistantMessage(uid(), Date.now());
  refs.streamingIdRef.current = assistantMsg.id;

  const nextMessages = [...refs.messagesRef.current, userMsg, assistantMsg];
  refs.messagesRef.current = nextMessages;
  callbacks.setMessages(nextMessages);
  callbacks.setIsStreaming(true);

  const abortController = new AbortController();
  refs.streamAbortControllerRef.current = abortController;
  refs.userStoppedStreamRef.current = false;

  const applyAndCommitEvent = (event: ChatStreamEvent) => {
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
      }
    }
  };

  try {
    await api.streamChat(content, sessionId, {
      signal: abortController.signal,
      onEvent: applyAndCommitEvent,
    });
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
