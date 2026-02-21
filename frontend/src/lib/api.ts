import type { Session, Skill, TokenStats } from "./types";

function getBase(): string {
  if (typeof window === "undefined") return "http://localhost:8002";
  return `http://${window.location.hostname}:8002`;
}

async function req<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(`${getBase()}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

// ────────────────────────────────────────────────────────────────
// Sessions
// ────────────────────────────────────────────────────────────────

export const listSessions = () => req<Session[]>("/api/sessions");

export const createSession = () =>
  req<Session>("/api/sessions", { method: "POST" });

export const renameSession = (id: string, title: string) =>
  req<Session>(`/api/sessions/${id}`, {
    method: "PUT",
    body: JSON.stringify({ title }),
  });

export const deleteSession = (id: string) =>
  fetch(`${getBase()}/api/sessions/${id}`, { method: "DELETE" });

export const getHistory = (id: string) =>
  req<object[]>(`/api/sessions/${id}/history`);

export const generateTitle = (id: string) =>
  req<{ session_id: string; title: string }>(
    `/api/sessions/${id}/generate-title`,
    { method: "POST" }
  );

// ────────────────────────────────────────────────────────────────
// Files
// ────────────────────────────────────────────────────────────────

export const readFile = (path: string) =>
  req<{ path: string; content: string }>(
    `/api/files?path=${encodeURIComponent(path)}`
  );

export const saveFile = (path: string, content: string) =>
  req<{ path: string; saved: boolean }>("/api/files", {
    method: "POST",
    body: JSON.stringify({ path, content }),
  });

export const listSkills = () => req<Skill[]>("/api/skills");

// ────────────────────────────────────────────────────────────────
// Tokens
// ────────────────────────────────────────────────────────────────

export const getSessionTokens = (id: string) =>
  req<TokenStats>(`/api/tokens/session/${id}`);

// ────────────────────────────────────────────────────────────────
// Compression
// ────────────────────────────────────────────────────────────────

export const compressSession = (id: string) =>
  req<{ archived_count: number; remaining_count: number; summary: string }>(
    `/api/sessions/${id}/compress`,
    { method: "POST" }
  );

// ────────────────────────────────────────────────────────────────
// RAG config
// ────────────────────────────────────────────────────────────────

export const getRagMode = () =>
  req<{ rag_mode: boolean }>("/api/config/rag-mode");

export const setRagMode = (enabled: boolean) =>
  req<{ rag_mode: boolean }>("/api/config/rag-mode", {
    method: "PUT",
    body: JSON.stringify({ enabled }),
  });

// ────────────────────────────────────────────────────────────────
// Chat streaming (custom SSE parser — POST-based)
// ────────────────────────────────────────────────────────────────

export interface StreamCallbacks {
  onRetrieval: (query: string, results: object[]) => void;
  onToken: (content: string) => void;
  onToolStart: (tool: string, input: string, runId: string) => void;
  onToolEnd: (tool: string, output: string, runId: string) => void;
  onNewResponse: () => void;
  onDone: (content: string) => void;
  onTitle: (title: string) => void;
  onError: (error: string) => void;
}

export async function streamChat(
  message: string,
  sessionId: string,
  callbacks: StreamCallbacks
): Promise<void> {
  const response = await fetch(`${getBase()}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId, stream: true }),
  });

  if (!response.ok || !response.body) {
    callbacks.onError(`HTTP ${response.status}: ${response.statusText}`);
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Split on event boundaries (\n\n)
      const events = buffer.split("\n\n");
      buffer = events.pop() ?? "";

      for (const event of events) {
        for (const line of event.split("\n")) {
          if (!line.startsWith("data: ")) continue;
          try {
            const data = JSON.parse(line.slice(6));
            switch (data.type) {
              case "retrieval":
                callbacks.onRetrieval(data.query, data.results);
                break;
              case "token":
                callbacks.onToken(data.content);
                break;
              case "tool_start":
                callbacks.onToolStart(data.tool, data.input, data.run_id ?? data.tool);
                break;
              case "tool_end":
                callbacks.onToolEnd(data.tool, data.output, data.run_id ?? data.tool);
                break;
              case "new_response":
                callbacks.onNewResponse();
                break;
              case "done":
                callbacks.onDone(data.content ?? "");
                break;
              case "title":
                callbacks.onTitle(data.title);
                break;
              case "error":
                callbacks.onError(data.error ?? "Unknown error");
                break;
            }
          } catch {
            // Skip malformed lines
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
