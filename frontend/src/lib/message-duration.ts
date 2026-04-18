import { getMessageToolCalls } from "@/lib/message-blocks";
import type { Message, ToolCall, ToolResultEnvelope } from "@/lib/types";

function metadataNumber(result: ToolResultEnvelope | undefined, key: string): number | null {
  const value = result?.metadata?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function parseTimestampMs(value?: string | null): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function toolCallDurationMs(call: ToolCall): number | null {
  const durationSeconds = metadataNumber(call.result, "duration_seconds");
  if (durationSeconds !== null && durationSeconds >= 0) {
    return durationSeconds * 1000;
  }

  const durationMs = metadataNumber(call.result, "duration_ms");
  if (durationMs !== null && durationMs >= 0) {
    return durationMs;
  }

  return null;
}

function toolDurationSummaryMs(toolCalls?: ToolCall[]): number | null {
  if (!toolCalls || toolCalls.length === 0) {
    return null;
  }

  const durations = toolCalls
    .map((call) => toolCallDurationMs(call))
    .filter((value): value is number => value !== null);

  if (durations.length === 0) {
    return null;
  }

  return durations.reduce((total, value) => total + value, 0);
}

export function formatMessageDuration(ms: number): string {
  if (ms < 1000) {
    return `${Math.max(1, Math.round(ms))}ms`;
  }

  const seconds = ms / 1000;
  if (seconds >= 60) {
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = Math.round(seconds % 60);
    return `${minutes}m ${remainingSeconds}s`;
  }

  if (seconds >= 10) {
    return `${Math.round(seconds)}s`;
  }

  return `${seconds.toFixed(1)}s`;
}

export function messageElapsedMs(message: Message, nowMs = Date.now()): number | null {
  const startedAtMs = typeof message.startedAtMs === "number" ? message.startedAtMs : null;
  const endedAtMs = typeof message.endedAtMs === "number" ? message.endedAtMs : null;

  if (startedAtMs !== null) {
    return Math.max(0, (endedAtMs ?? nowMs) - startedAtMs);
  }

  return toolDurationSummaryMs(getMessageToolCalls(message));
}

export function streamingElapsedLabel(message: Message, nowMs = Date.now()): string | null {
  const elapsedMs = messageElapsedMs(message, nowMs);
  return elapsedMs === null ? null : `Elapsed ${formatMessageDuration(elapsedMs)} so far.`;
}

export function completedElapsedLabel(message: Message): string | null {
  const elapsedMs = messageElapsedMs(message);
  return elapsedMs === null ? null : `Worked for ${formatMessageDuration(elapsedMs)}.`;
}
