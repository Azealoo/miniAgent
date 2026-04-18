import { compactText, humanizeToken } from "@/lib/format";
import {
  getMessageRetrievals,
  getMessageToolCalls,
} from "@/lib/message-blocks";
import type { Message } from "@/lib/types";

export { compactText, humanizeToken };

export function humanizeLabel(value?: string | null): string | null {
  const humanized = humanizeToken(value);
  if (!humanized) {
    return null;
  }

  return humanized.charAt(0).toUpperCase() + humanized.slice(1);
}

export function uniqueStrings(values: Array<string | null | undefined>): string[] {
  const seen = new Set<string>();
  const result: string[] = [];

  values.forEach((value) => {
    const trimmed = value?.trim();
    if (!trimmed || seen.has(trimmed)) {
      return;
    }

    seen.add(trimmed);
    result.push(trimmed);
  });

  return result;
}

export function pluralize(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

export function shortenPath(path: string, maxSegments = 2): string {
  const normalized = path.replaceAll("\\", "/");
  const segments = normalized.split("/").filter(Boolean);

  if (segments.length <= maxSegments) {
    return normalized;
  }

  return `.../${segments.slice(-maxSegments).join("/")}`;
}

export function formatCompactTokenValue(value: number): string {
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(value >= 100_000_000 ? 0 : 1)}M`;
  }

  if (value >= 1_000) {
    return `${(value / 1_000).toFixed(value >= 100_000 ? 0 : 1)}K`;
  }

  return value.toString();
}

export function normalizeMarkdownInline(value: string): string {
  return value
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\[(.+?)\]\(.+?\)/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
}

export function buildExportMarkdown(title: string, messages: Message[]): string {
  const lines: string[] = [
    `# ${title}`,
    "",
    `Exported: ${new Date().toISOString()}`,
    "",
  ];

  messages.forEach((message) => {
    lines.push(`## ${message.role === "user" ? "User" : "BioAPEX"}`);
    lines.push(message.content || "(empty response)");

    const retrievals = getMessageRetrievals(message);
    if (retrievals.length) {
      lines.push("");
      lines.push("Retrieved sources:");
      retrievals.forEach((result) => {
        lines.push(`- ${result.source} (score ${result.score.toFixed(3)})`);
      });
    }

    const toolCalls = getMessageToolCalls(message);
    if (toolCalls.length) {
      lines.push("");
      lines.push("Tool calls:");
      toolCalls.forEach((call) => {
        lines.push(`- ${call.tool}`);
      });
    }

    lines.push("");
  });

  return `${lines.join("\n").trim()}\n`;
}

export function exportFilename(title: string): string {
  return (
    title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") ||
    "bioapex-session"
  );
}
