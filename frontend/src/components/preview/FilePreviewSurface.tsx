"use client";

import { load as loadYaml } from "js-yaml";
import Image from "next/image";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { createRawFileObjectUrl, readRawFileText } from "@/lib/api";
import {
  getFilePreviewDescriptor,
  humanizePreviewToken,
  isRawObjectUrlPreviewMode,
  type FilePreviewDescriptor,
  type PreviewableFileInput,
} from "@/lib/file-preview";
import type { JsonValue } from "@/lib/types";
import { cn } from "@/lib/utils";

type PreviewStatus = "idle" | "loading" | "ready" | "error";

const MAX_INLINE_TEXT_BYTES = 160_000;
const MAX_INLINE_TEXT_CHARS = 160_000;
const MAX_STRUCTURED_ENTRIES = 16;
const MAX_STRUCTURED_DEPTH = 4;
const HTML_EXCERPT_LINES = 10;
const YAML_EXTENSIONS = new Set([".yaml", ".yml"]);

export interface FilePreviewTarget extends PreviewableFileInput {
  displayName?: string | null;
  runId?: string | null;
  sizeBytes?: number | null;
}

export interface UseFilePreviewResult {
  descriptor: FilePreviewDescriptor | null;
  status: PreviewStatus;
  textContent: string;
  structuredContent: JsonValue | null;
  htmlTitle: string | null;
  rawUrl: string | null;
  error: string | null;
  tooLargeMessage: string | null;
  refresh: () => void;
}

function getTooLargeMessage(descriptor: FilePreviewDescriptor): string {
  if (descriptor.mode === "html") {
    return "This HTML report is too large for inline reference preview here. Use Open raw to inspect the full report.";
  }

  if (descriptor.mode === "json") {
    return "This structured artifact is too large to render inline here. Use Open raw to inspect the full payload.";
  }

  if (descriptor.mode === "markdown") {
    return "This markdown file is too large to render inline here. Use Open raw to inspect the full content.";
  }

  return "This file is too large to render inline here. Use Open raw to inspect the full content.";
}

function shouldAttemptStructuredParse(
  descriptor: FilePreviewDescriptor,
  contentType: string | null,
  content: string
): boolean {
  if (descriptor.mode === "json") {
    return true;
  }

  if (contentType?.toLowerCase().includes("json")) {
    return true;
  }

  if (contentType?.toLowerCase().includes("yaml")) {
    return true;
  }

  if (descriptor.kind !== "structured") {
    return false;
  }

  const trimmed = content.trim();
  return (
    trimmed.startsWith("{") ||
    trimmed.startsWith("[") ||
    looksLikeYamlContent(content)
  );
}

function looksLikeYamlContent(content: string): boolean {
  const trimmed = content.trim();
  if (!trimmed || trimmed.startsWith("{") || trimmed.startsWith("[")) {
    return false;
  }

  return (
    /(^|\n)\s*[^#\s][^:\n]*:\s*(?:$|\S)/m.test(content) ||
    /(^|\n)\s*-\s+\S/m.test(content)
  );
}

function normalizeStructuredValue(value: unknown): JsonValue {
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "boolean"
  ) {
    return value;
  }

  if (typeof value === "number") {
    return Number.isFinite(value) ? value : String(value);
  }

  if (typeof value === "undefined") {
    return null;
  }

  if (Array.isArray(value)) {
    return value.map((entry) => normalizeStructuredValue(entry));
  }

  if (value instanceof Date) {
    return value.toISOString();
  }

  if (typeof value === "object") {
    const normalizedObject: { [key: string]: JsonValue } = {};
    for (const [key, entryValue] of Object.entries(
      value as Record<string, unknown>
    )) {
      normalizedObject[key] = normalizeStructuredValue(entryValue);
    }
    return normalizedObject;
  }

  return String(value);
}

function parseStructuredContent(
  descriptor: FilePreviewDescriptor,
  contentType: string | null,
  content: string
): JsonValue | null {
  const trimmed = content.trim();
  if (!trimmed) {
    return null;
  }

  try {
    return JSON.parse(content) as JsonValue;
  } catch {
    // Fall back to YAML for explicit YAML files and YAML-like structured payloads.
  }

  const lowerContentType = contentType?.toLowerCase() ?? "";
  const shouldTryYaml =
    YAML_EXTENSIONS.has(descriptor.extension) ||
    lowerContentType.includes("yaml") ||
    looksLikeYamlContent(content);

  if (!shouldTryYaml) {
    return null;
  }

  try {
    return normalizeStructuredValue(loadYaml(content));
  } catch {
    return null;
  }
}

function extractHtmlTitle(content: string): string | null {
  const titleMatch = content.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
  if (titleMatch?.[1]) {
    const normalized = titleMatch[1].replace(/\s+/g, " ").trim();
    return normalized || null;
  }

  const headingMatch = content.match(/<h1[^>]*>([\s\S]*?)<\/h1>/i);
  if (!headingMatch?.[1]) {
    return null;
  }

  const normalized = headingMatch[1]
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return normalized || null;
}

function buildHtmlExcerpt(content: string): string {
  const lines = content
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, HTML_EXCERPT_LINES);

  return lines.join("\n");
}

export function useFilePreview(
  target: FilePreviewTarget | null
): UseFilePreviewResult {
  const [descriptor, setDescriptor] = useState<FilePreviewDescriptor | null>(null);
  const [status, setStatus] = useState<PreviewStatus>("idle");
  const [textContent, setTextContent] = useState("");
  const [structuredContent, setStructuredContent] = useState<JsonValue | null>(null);
  const [htmlTitle, setHtmlTitle] = useState<string | null>(null);
  const [rawUrl, setRawUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tooLargeMessage, setTooLargeMessage] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const revokeRef = useRef<(() => void) | null>(null);
  const targetPath = target?.path ?? null;
  const targetArtifactType = target?.artifactType ?? null;
  const targetDisplayName = target?.displayName ?? null;
  const targetOutputName = target?.outputName ?? null;
  const targetSizeBytes = target?.sizeBytes ?? null;

  useEffect(() => {
    return () => {
      revokeRef.current?.();
      revokeRef.current = null;
    };
  }, []);

  useEffect(() => {
    let active = true;
    const nextDescriptor = targetPath
      ? getFilePreviewDescriptor({
          path: targetPath,
          artifactType: targetArtifactType,
          label: targetDisplayName,
          outputName: targetOutputName,
        })
      : null;

    revokeRef.current?.();
    revokeRef.current = null;
    setRawUrl(null);
    setTextContent("");
    setStructuredContent(null);
    setHtmlTitle(null);
    setError(null);
    setTooLargeMessage(null);
    setDescriptor(nextDescriptor);

    if (!targetPath || !nextDescriptor) {
      setStatus("idle");
      return () => {
        active = false;
      };
    }

    if (nextDescriptor.mode === "unsupported") {
      setStatus("ready");
      return () => {
        active = false;
      };
    }

    if (
      !isRawObjectUrlPreviewMode(nextDescriptor.mode) &&
      typeof targetSizeBytes === "number" &&
      targetSizeBytes > MAX_INLINE_TEXT_BYTES
    ) {
      setStatus("ready");
      setTooLargeMessage(getTooLargeMessage(nextDescriptor));
      return () => {
        active = false;
      };
    }

    const controller = new AbortController();
    setStatus("loading");

    if (isRawObjectUrlPreviewMode(nextDescriptor.mode)) {
      void createRawFileObjectUrl(targetPath, controller.signal)
        .then((result) => {
          if (!active) {
            result.revoke();
            return;
          }

          revokeRef.current = result.revoke;
          setRawUrl(result.url);
          setStatus("ready");
        })
        .catch((previewError) => {
          if (!active) {
            return;
          }

          setStatus("error");
          setError(
            previewError instanceof Error
              ? previewError.message
              : "Could not load the raw preview."
          );
        });
    } else {
      void readRawFileText(targetPath, controller.signal)
        .then((result) => {
          if (!active) {
            return;
          }

          const nextHtmlTitle =
            nextDescriptor.mode === "html" ? extractHtmlTitle(result.content) : null;
          const parsedStructuredContent = shouldAttemptStructuredParse(
            nextDescriptor,
            result.contentType,
            result.content
          )
            ? parseStructuredContent(
                nextDescriptor,
                result.contentType,
                result.content
              )
            : null;

          setHtmlTitle(nextHtmlTitle);
          setTextContent(result.content);
          setStructuredContent(parsedStructuredContent);

          if (result.content.length > MAX_INLINE_TEXT_CHARS) {
            setTooLargeMessage(getTooLargeMessage(nextDescriptor));
          }

          setStatus("ready");
        })
        .catch((previewError) => {
          if (!active) {
            return;
          }

          setStatus("error");
          setError(
            previewError instanceof Error
              ? previewError.message
              : "Could not load the raw preview."
          );
        });
    }

    return () => {
      active = false;
      controller.abort();
    };
  }, [
    reloadKey,
    targetArtifactType,
    targetDisplayName,
    targetOutputName,
    targetPath,
    targetSizeBytes,
  ]);

  return {
    descriptor,
    status,
    textContent,
    structuredContent,
    htmlTitle,
    rawUrl,
    error,
    tooLargeMessage,
    refresh: () => setReloadKey((value) => value + 1),
  };
}

function PreviewMessage({
  children,
  tone = "default",
}: {
  children: ReactNode;
  tone?: "default" | "error";
}) {
  return (
    <div
      className={cn(
        "rounded-[16px] border px-4 py-4 text-sm leading-6",
        tone === "error"
          ? "border-[rgba(244,63,94,0.16)] bg-[rgba(255,241,242,0.9)] text-rose-700"
          : "border-[rgba(214,221,212,0.86)] bg-[rgba(248,250,246,0.95)] text-slate-600"
      )}
    >
      {children}
    </div>
  );
}

function PreviewContext({
  target,
  descriptor,
  compact,
}: {
  target: FilePreviewTarget;
  descriptor: FilePreviewDescriptor;
  compact?: boolean;
}) {
  const metadata = [
    descriptor.label,
    humanizePreviewToken(target.artifactType),
    target.runId,
  ].filter((value): value is string => Boolean(value));

  return (
    <div className="space-y-2">
      {metadata.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {metadata.map((value) => (
            <span
              key={`${target.path}-${value}`}
              className={cn(
                "inline-flex items-center rounded-full border border-[rgba(214,221,212,0.86)] bg-[rgba(248,250,246,0.95)] px-2.5 py-1 font-medium text-slate-600",
                compact ? "text-[10px]" : "text-[11px]"
              )}
            >
              {value}
            </span>
          ))}
        </div>
      ) : null}
      <p
        className={cn(
          "break-all font-mono text-slate-400",
          compact ? "text-[10px]" : "text-[11px]"
        )}
      >
        {target.path}
      </p>
    </div>
  );
}

function StructuredPrimitive({
  value,
}: {
  value: string | number | boolean | null;
}) {
  if (typeof value === "string") {
    return (
      <p className="whitespace-pre-wrap break-words rounded-[12px] bg-[rgba(248,250,246,0.96)] px-3 py-2 font-mono text-[12px] leading-6 text-slate-700">
        {value}
      </p>
    );
  }

  return (
    <span className="inline-flex items-center rounded-full border border-[rgba(214,221,212,0.86)] bg-[rgba(248,250,246,0.95)] px-2.5 py-1 font-mono text-[12px] text-slate-700">
      {String(value)}
    </span>
  );
}

function StructuredValue({
  value,
  depth = 0,
}: {
  value: JsonValue;
  depth?: number;
}) {
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return <StructuredPrimitive value={value} />;
  }

  if (depth >= MAX_STRUCTURED_DEPTH) {
    return (
      <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded-[12px] bg-[rgba(248,250,246,0.96)] px-3 py-3 font-mono text-[12px] leading-6 text-slate-700">
        {JSON.stringify(value, null, 2)}
      </pre>
    );
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return (
        <p className="text-[12px] leading-5 text-slate-500">This list is empty.</p>
      );
    }

    const visibleItems = value.slice(0, MAX_STRUCTURED_ENTRIES);
    return (
      <div className="space-y-2">
        {visibleItems.map((entry, index) => (
          <div
            key={`array-${depth}-${index}`}
            className="rounded-[14px] border border-[rgba(214,221,212,0.86)] bg-white/94 px-3 py-3"
          >
            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
              Item {index + 1}
            </p>
            <div className="mt-2">
              <StructuredValue value={entry} depth={depth + 1} />
            </div>
          </div>
        ))}
        {value.length > visibleItems.length ? (
          <PreviewMessage>
            Showing the first {visibleItems.length} items in this list. Use Open raw
            to inspect the full payload.
          </PreviewMessage>
        ) : null}
      </div>
    );
  }

  const entries = Object.entries(value);
  if (entries.length === 0) {
    return (
      <p className="text-[12px] leading-5 text-slate-500">
        This object is empty.
      </p>
    );
  }

  const visibleEntries = entries.slice(0, MAX_STRUCTURED_ENTRIES);
  return (
    <div className="space-y-2">
      {visibleEntries.map(([key, entryValue]) => (
        <div
          key={`${depth}-${key}`}
          className="rounded-[14px] border border-[rgba(214,221,212,0.86)] bg-white/94 px-3 py-3"
        >
          <p className="break-all text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
            {key}
          </p>
          <div className="mt-2">
            <StructuredValue value={entryValue} depth={depth + 1} />
          </div>
        </div>
      ))}
      {entries.length > visibleEntries.length ? (
        <PreviewMessage>
          Showing the first {visibleEntries.length} fields in this object. Use Open
          raw to inspect the full payload.
        </PreviewMessage>
      ) : null}
    </div>
  );
}

function HtmlReferencePreview({
  target,
  preview,
}: {
  target: FilePreviewTarget;
  preview: UseFilePreviewResult;
}) {
  const title =
    preview.htmlTitle ??
    target.displayName ??
    target.path.split("/").pop() ??
    "HTML report";

  return (
    <div className="space-y-3">
      <div className="rounded-[16px] border border-[rgba(214,221,212,0.86)] bg-[linear-gradient(180deg,rgba(248,250,246,0.98),rgba(255,255,255,0.98))] px-4 py-4">
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
          HTML Report Reference
        </p>
        <h5 className="mt-2 text-base font-semibold text-slate-900">{title}</h5>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          Active report content stays on the backend raw-file path so BioAPEX can
          reference the report safely without rendering app-origin HTML inline.
        </p>
      </div>

      {preview.tooLargeMessage ? (
        <PreviewMessage>{preview.tooLargeMessage}</PreviewMessage>
      ) : preview.textContent ? (
        <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded-[16px] border border-[rgba(214,221,212,0.86)] bg-[rgba(248,250,246,0.96)] px-4 py-4 font-mono text-[12px] leading-6 text-slate-700">
          {buildHtmlExcerpt(preview.textContent)}
        </pre>
      ) : null}
    </div>
  );
}

export function FilePreviewSurface({
  target,
  preview,
  emptyMessage,
  compact = false,
  className,
}: {
  target: FilePreviewTarget | null;
  preview: UseFilePreviewResult;
  emptyMessage: string;
  compact?: boolean;
  className?: string;
}) {
  if (!target || !preview.descriptor) {
    return <PreviewMessage>{emptyMessage}</PreviewMessage>;
  }

  const descriptor = preview.descriptor;
  const contentHeightClass = compact ? "max-h-[360px]" : "max-h-[30rem]";

  return (
    <div className={cn("space-y-3", className)}>
      <PreviewContext target={target} descriptor={descriptor} compact={compact} />

      {preview.status === "loading" ? (
        <PreviewMessage>Loading raw preview…</PreviewMessage>
      ) : preview.status === "error" ? (
        <PreviewMessage tone="error">
          {preview.error ?? "Could not load the raw preview."}
        </PreviewMessage>
      ) : descriptor.mode === "unsupported" ? (
        <PreviewMessage>
          {descriptor.unsupportedMessage ??
            "This file is not previewed inline yet. Use Open raw to inspect it."}
        </PreviewMessage>
      ) : preview.tooLargeMessage && descriptor.mode !== "html" ? (
        <PreviewMessage>{preview.tooLargeMessage}</PreviewMessage>
      ) : descriptor.mode === "image" && preview.rawUrl ? (
        <div className="overflow-hidden rounded-[16px] border border-[rgba(214,221,212,0.86)] bg-[rgba(248,250,246,0.95)] p-2">
          <Image
            src={preview.rawUrl}
            alt={
              target.displayName ??
              target.path.split("/").pop() ??
              "Generated artifact"
            }
            width={1600}
            height={900}
            unoptimized
            className={cn("h-auto w-full rounded-[12px] object-contain", contentHeightClass)}
          />
        </div>
      ) : descriptor.mode === "pdf" && preview.rawUrl ? (
        <iframe
          src={preview.rawUrl}
          title={
            target.displayName ??
            target.path.split("/").pop() ??
            "Generated artifact"
          }
          className={cn(
            "w-full rounded-[16px] border border-[rgba(214,221,212,0.86)] bg-white",
            compact ? "h-[360px]" : "h-[30rem]"
          )}
        />
      ) : descriptor.mode === "markdown" ? (
        <div
          className={cn(
            "overflow-y-auto rounded-[16px] border border-[rgba(214,221,212,0.86)] bg-white/96 px-5 py-4 prose prose-sm max-w-none prose-headings:font-semibold prose-headings:text-slate-900 prose-p:text-slate-700 prose-li:text-slate-700 prose-code:text-slate-700",
            contentHeightClass
          )}
        >
          <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
            {preview.textContent}
          </ReactMarkdown>
        </div>
      ) : descriptor.mode === "json" && preview.structuredContent !== null ? (
        <div
          className={cn(
            "overflow-y-auto rounded-[16px] border border-[rgba(214,221,212,0.86)] bg-[rgba(248,250,246,0.96)] px-4 py-4",
            contentHeightClass
          )}
        >
          <StructuredValue value={preview.structuredContent} />
        </div>
      ) : descriptor.mode === "html" ? (
        <HtmlReferencePreview target={target} preview={preview} />
      ) : (
        <pre
          className={cn(
            "overflow-auto whitespace-pre-wrap break-words rounded-[16px] border border-[rgba(214,221,212,0.86)] bg-[rgba(248,250,246,0.96)] px-4 py-4 font-mono text-[12px] leading-6 text-slate-700",
            contentHeightClass
          )}
        >
          {preview.textContent}
        </pre>
      )}
    </div>
  );
}
