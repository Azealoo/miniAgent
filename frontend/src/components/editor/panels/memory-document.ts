import type {
  MemoryInspectorItem,
  MemoryInspectorItemKind,
  MemoryItemDraft,
  ParsedMemoryDocument,
} from "./types";
import {
  compactText,
  normalizeMarkdownInline,
} from "./shared-utils";

export const MEMORY_PATH = "memory/MEMORY.md";

function deriveMemoryKeyAndValue(text: string): { key: string; value: string } {
  const normalized = normalizeMarkdownInline(text);

  if (!normalized) {
    return {
      key: "Memory note",
      value: "",
    };
  }

  const colonMatch = normalized.match(/^([^:]{1,48}):\s*(.+)$/);
  if (colonMatch) {
    return {
      key: colonMatch[1].trim(),
      value: colonMatch[2].trim(),
    };
  }

  if (normalized.length <= 56) {
    return {
      key: normalized,
      value: "",
    };
  }

  const sentence = normalized.split(/[.!?](?:\s|$)/)[0]?.trim();
  if (sentence && sentence.length <= 48) {
    return {
      key: sentence,
      value: normalized,
    };
  }

  return {
    key: compactText(normalized, 42) ?? "Memory note",
    value: normalized,
  };
}

function buildMemoryItemId(namespace: string, key: string, index: number): string {
  const normalizedNamespace = namespace
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  const normalizedKey = key
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");

  return `${normalizedNamespace || "memory"}-${normalizedKey || "item"}-${index}`;
}

function extractMemoryItemText(
  rawLines: string[],
  kind: MemoryInspectorItemKind
): string {
  if (rawLines.length === 0) {
    return "";
  }

  if (kind === "block") {
    return rawLines.map((line) => line.trim()).join(" ").trim();
  }

  const firstLine = rawLines[0]?.trim() ?? "";
  const firstLineWithoutMarker =
    kind === "numbered"
      ? firstLine.replace(/^\d+\.\s+/, "")
      : firstLine.replace(/^-\s+/, "");
  const continuation = rawLines
    .slice(1)
    .map((line) => line.trim())
    .filter(Boolean);

  return [firstLineWithoutMarker, ...continuation].join(" ").trim();
}

function renderMemoryItemLines(
  kind: MemoryInspectorItemKind,
  key: string,
  value: string
): string[] {
  const normalizedKey = key.trim() || "Memory note";
  const normalizedValue = value.trim();
  const baseText =
    normalizedValue && normalizedValue.toLowerCase() !== normalizedKey.toLowerCase()
      ? `**${normalizedKey}**: ${normalizedValue}`
      : normalizedValue || normalizedKey;
  const textLines = baseText
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  if (textLines.length === 0) {
    return kind === "block" ? ["Memory note"] : ["- Memory note"];
  }

  if (kind === "block") {
    return textLines;
  }

  const marker = kind === "numbered" ? "1." : "-";
  return textLines.map((line, index) =>
    index === 0 ? `${marker} ${line}` : `  ${line}`
  );
}

export function parseMemoryDocument(content: string): ParsedMemoryDocument {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const items: MemoryInspectorItem[] = [];
  let title = "Long-term Memory";
  let currentNamespace = "General";
  let itemIndex = 0;

  const pushItem = (rawLines: string[], kind: MemoryInspectorItemKind) => {
    const normalized = extractMemoryItemText(rawLines, kind);
    if (!normalized) {
      return;
    }

    const { key, value } = deriveMemoryKeyAndValue(normalized);
    items.push({
      id: buildMemoryItemId(currentNamespace, key, itemIndex),
      namespace: currentNamespace,
      key,
      value,
      kind,
      rawLines,
    });
    itemIndex += 1;
  };

  let lineIndex = 0;

  while (lineIndex < lines.length) {
    const line = lines[lineIndex];
    const trimmed = line.trim();

    if (!trimmed) {
      lineIndex += 1;
      continue;
    }

    if (trimmed.startsWith("# ")) {
      title = trimmed.replace(/^#\s+/, "").trim() || title;
      lineIndex += 1;
      continue;
    }

    if (trimmed.startsWith("## ")) {
      currentNamespace = trimmed.replace(/^##\s+/, "").trim() || "General";
      lineIndex += 1;
      continue;
    }

    if (trimmed.match(/^-\s+/) || trimmed.match(/^\d+\.\s+/)) {
      const kind: MemoryInspectorItemKind = trimmed.match(/^\d+\.\s+/)
        ? "numbered"
        : "bullet";
      const rawLines = [line];
      lineIndex += 1;

      while (lineIndex < lines.length) {
        const nextLine = lines[lineIndex];
        const nextTrimmed = nextLine.trim();
        if (
          !nextTrimmed ||
          nextTrimmed.startsWith("# ") ||
          nextTrimmed.startsWith("## ") ||
          nextTrimmed.match(/^-\s+/) ||
          nextTrimmed.match(/^\d+\.\s+/)
        ) {
          break;
        }
        if (nextLine.match(/^\s+/)) {
          rawLines.push(nextLine);
          lineIndex += 1;
          continue;
        }
        break;
      }

      pushItem(rawLines, kind);
      continue;
    }

    const rawLines = [line];
    lineIndex += 1;
    while (lineIndex < lines.length) {
      const nextLine = lines[lineIndex];
      const nextTrimmed = nextLine.trim();
      if (
        !nextTrimmed ||
        nextTrimmed.startsWith("# ") ||
        nextTrimmed.startsWith("## ") ||
        nextTrimmed.match(/^-\s+/) ||
        nextTrimmed.match(/^\d+\.\s+/)
      ) {
        break;
      }
      rawLines.push(nextLine);
      lineIndex += 1;
    }

    pushItem(rawLines, "block");
  }

  return {
    title,
    items,
  };
}

export function serializeMemoryDocument(document: ParsedMemoryDocument): string {
  const sections = new Map<string, MemoryInspectorItem[]>();

  document.items.forEach((item) => {
    const namespace = item.namespace.trim() || "General";
    const existing = sections.get(namespace);
    if (existing) {
      existing.push(item);
    } else {
      sections.set(namespace, [item]);
    }
  });

  const lines = [`# ${document.title || "Long-term Memory"}`, ""];

  if (sections.size === 0) {
    lines.push("## General", "");
  }

  sections.forEach((sectionItems, namespace) => {
    lines.push(`## ${namespace}`);

    sectionItems.forEach((item) => {
      const key = normalizeMarkdownInline(item.key);
      const value = normalizeMarkdownInline(item.value);
      const rawLines =
        item.rawLines.length > 0
          ? item.rawLines
          : renderMemoryItemLines(item.kind, key, value);

      rawLines.forEach((line) => lines.push(line));
    });

    lines.push("");
  });

  return `${lines.join("\n").trimEnd()}\n`;
}

export function upsertMemoryDocumentItem(
  document: ParsedMemoryDocument,
  draft: MemoryItemDraft
): ParsedMemoryDocument {
  const namespace = draft.namespace.trim() || "General";
  const key = draft.key.trim() || "Memory note";
  const value = draft.value.trim();
  const sourceItem =
    draft.mode === "edit" && draft.targetId
      ? document.items.find((item) => item.id === draft.targetId) ?? null
      : null;
  const nextKind = sourceItem?.kind ?? "bullet";
  const shouldPreserveRawLines =
    sourceItem !== null &&
    sourceItem.namespace === namespace &&
    sourceItem.key === key &&
    sourceItem.value === value;
  const nextItem: MemoryInspectorItem = {
    id:
      draft.mode === "edit" && draft.targetId
        ? draft.targetId
        : buildMemoryItemId(namespace, key, document.items.length),
    namespace,
    key,
    value,
    kind: nextKind,
    rawLines: shouldPreserveRawLines
      ? [...(sourceItem?.rawLines ?? [])]
      : renderMemoryItemLines(nextKind, key, value),
  };

  if (draft.mode === "edit" && draft.targetId) {
    return {
      ...document,
      items: document.items.map((item) =>
        item.id === draft.targetId ? nextItem : item
      ),
    };
  }

  return {
    ...document,
    items: [...document.items, nextItem],
  };
}

export function duplicateMemoryDocumentItem(
  document: ParsedMemoryDocument,
  itemId: string
): ParsedMemoryDocument {
  const index = document.items.findIndex((item) => item.id === itemId);
  if (index === -1) {
    return document;
  }

  const source = document.items[index];
  const duplicate: MemoryInspectorItem = {
    ...source,
    id: buildMemoryItemId(source.namespace, `${source.key} copy`, document.items.length),
    rawLines: [...source.rawLines],
  };
  const nextItems = [...document.items];
  nextItems.splice(index + 1, 0, duplicate);

  return {
    ...document,
    items: nextItems,
  };
}

export function removeMemoryDocumentItem(
  document: ParsedMemoryDocument,
  itemId: string
): ParsedMemoryDocument {
  return {
    ...document,
    items: document.items.filter((item) => item.id !== itemId),
  };
}
