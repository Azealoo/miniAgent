import * as api from "./api";
import { getSessionCorruptDetail } from "./api";
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
  // Counter resets fire inside the same synchronous setter batch as
  // `setCurrentSessionId(id)` so UsagePanel never observes the new session id
  // alongside the previous session's parse-error / request-id-mismatch counts.
  setParseErrorCount: (count: number) => void;
  setRequestIdMismatchCount: (count: number) => void;
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

function buildSessionCorruptMessage(
  detail: ReturnType<typeof getSessionCorruptDetail>
): string {
  if (!detail) {
    return "Session corrupt: this saved session's file could not be read and has been quarantined.";
  }
  const base = `Session corrupt: ${detail.message}`;
  return detail.quarantinePath
    ? `${base} (moved to ${detail.quarantinePath})`
    : base;
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
    if (snapshot.currentSessionId !== id) {
      // Reset session-scoped error counters in the same synchronous setter
      // batch as the new session id so a switch never commits with the new
      // id and the previous session's counters visible to consumers.
      setters.setParseErrorCount(0);
      setters.setRequestIdMismatchCount(0);
    }
    setters.setMessages(messages);
    setters.setSessionContinuitySummaries(continuity.summaries);
    setters.setSessionHistoryStatus("ready");
    setters.setSessionHistoryError(null);
  } catch (error) {
    const corruptDetail = getSessionCorruptDetail(error);
    const baseMessage = corruptDetail
      ? buildSessionCorruptMessage(corruptDetail)
      : getErrorMessage(error);
    const nextErrorMessage =
      hadPriorContext && snapshot.currentSessionId !== id
        ? getPreservedSessionLoadErrorMessage(baseMessage)
        : baseMessage;

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
