import * as api from "./api";
import {
  normalizeMessageContent,
  normalizeTurnMessages,
} from "./message-blocks";
import { uid } from "./utils";
import type {
  Message,
  SessionContentBlock,
  SessionContinuitySummary,
  SessionHistoryMessage,
} from "./types";

export type SessionHistoryStatus = "idle" | "loading" | "ready" | "error";

export interface SessionLoadSnapshot {
  currentSessionId: string | null;
  messages: Message[];
  continuitySummaries: SessionContinuitySummary[];
}

export interface SessionLoadSetters {
  setMessages: (messages: Message[]) => void;
  setCurrentSessionId: (id: string | null) => void;
  setSessionHistoryStatus: (status: SessionHistoryStatus) => void;
  setSessionHistoryError: (error: string | null) => void;
  setSessionContinuitySummaries: (summaries: SessionContinuitySummary[]) => void;
}

function groupHistoryMessagesIntoTurns<T extends { role: string }>(
  messages: T[]
): T[][] {
  const turns: T[][] = [];
  let currentTurn: T[] = [];

  for (const message of messages) {
    if (message.role === "user") {
      if (currentTurn.length > 0) {
        turns.push(currentTurn);
      }
      currentTurn = [message];
      continue;
    }

    if (currentTurn.length === 0) {
      currentTurn = [message];
      continue;
    }

    currentTurn.push(message);
  }

  if (currentTurn.length > 0) {
    turns.push(currentTurn);
  }

  return turns;
}

export function historyToMessages(raw: SessionHistoryMessage[]): Message[] {
  const filtered = raw.filter((m) => m.role === "user" || m.role === "assistant");
  const normalizedHistory = groupHistoryMessagesIntoTurns(filtered).flatMap((turn) =>
    normalizeTurnMessages(turn)
  );

  return normalizedHistory.map((m) => {
    const normalized: { content: string; blocks: SessionContentBlock[] } =
      normalizeMessageContent(m);
    return {
      id: uid(),
      role: m.role as "user" | "assistant",
      content: normalized.content,
      request_id: m.request_id,
      blocks: normalized.blocks,
    };
  });
}

function getPreservedSessionLoadErrorMessage(baseMessage: string): string {
  const trimmed = baseMessage.trim();
  if (!trimmed) {
    return "BioAPEX could not open that saved session, so the previous conversation is still in view.";
  }
  return `BioAPEX could not open that saved session, so the previous conversation is still in view. ${trimmed}`;
}

export async function loadSession(
  id: string,
  snapshot: SessionLoadSnapshot,
  setters: SessionLoadSetters,
  getErrorMessage: (error: unknown) => string
): Promise<void> {
  const hadPriorContext =
    snapshot.currentSessionId !== null || snapshot.messages.length > 0;

  setters.setSessionHistoryStatus("loading");
  setters.setSessionHistoryError(null);
  setters.setSessionContinuitySummaries([]);
  try {
    const [history, continuity] = await Promise.all([
      api.getHistory(id),
      api.getSessionContinuity(id).catch(() => ({ summaries: [] })),
    ]);
    const messages = historyToMessages(history);
    setters.setCurrentSessionId(id);
    setters.setMessages(messages);
    setters.setSessionContinuitySummaries(continuity.summaries);
    setters.setSessionHistoryStatus("ready");
    setters.setSessionHistoryError(null);
  } catch (error) {
    const nextErrorMessage =
      hadPriorContext && snapshot.currentSessionId !== id
        ? getPreservedSessionLoadErrorMessage(getErrorMessage(error))
        : getErrorMessage(error);

    if (hadPriorContext) {
      setters.setCurrentSessionId(snapshot.currentSessionId);
      setters.setMessages(snapshot.messages);
      setters.setSessionContinuitySummaries(snapshot.continuitySummaries);
    } else {
      setters.setCurrentSessionId(id);
      setters.setMessages([]);
      setters.setSessionContinuitySummaries([]);
    }
    setters.setSessionHistoryStatus("error");
    setters.setSessionHistoryError(nextErrorMessage);
    throw error;
  }
}
