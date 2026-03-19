"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Terminal, Code2, Globe, FileText, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import type { JsonValue, ToolCall, ToolResultEnvelope } from "@/lib/types";

const TOOL_ICONS: Record<string, React.ReactNode> = {
  terminal: <Terminal size={12} />,
  python_repl: <Code2 size={12} />,
  fetch_url: <Globe size={12} />,
  read_file: <FileText size={12} />,
  search_knowledge_base: <Search size={12} />,
  slurm_tool: <Terminal size={12} />,
  ncbi_eutils: <Globe size={12} />,
  uniprot_api: <Globe size={12} />,
  ensembl_api: <Globe size={12} />,
  write_file: <FileText size={12} />,
};

const MAX_RENDERED_JSON_CHARS = 8_000;

function formatJsonValue(value: JsonValue | undefined): string {
  if (value === undefined) return "";
  const rendered = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  if (rendered.length <= MAX_RENDERED_JSON_CHARS) {
    return rendered;
  }
  return `${rendered.slice(0, MAX_RENDERED_JSON_CHARS)}\n...[display truncated]`;
}

function outcomeBadgeClass(result?: ToolResultEnvelope): string {
  if (!result) return "bg-gray-100 text-gray-500";
  if (result.status === "error") return "bg-red-100 text-red-700";
  if (result.outcome === "success_empty") return "bg-amber-100 text-amber-700";
  return "bg-emerald-100 text-emerald-700";
}

function ToolIcon({ name }: { name: string }) {
  return (
    <span className="text-gray-500">
      {TOOL_ICONS[name] ?? <Terminal size={12} />}
    </span>
  );
}

interface SingleCallProps {
  call: ToolCall;
}

function SingleCall({ call }: SingleCallProps) {
  const [open, setOpen] = useState(false);
  const structuredPayload = call.result?.structured_payload;
  const artifactRefs = call.result?.artifact_refs ?? [];
  const warnings = call.result?.warnings ?? [];
  const sourcePayload = call.result?.source_payload;

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 bg-gray-50 hover:bg-gray-100 transition-colors text-left"
      >
        <ToolIcon name={call.tool} />
        <span className="text-xs font-medium text-gray-700 font-mono">
          {call.tool}
        </span>
        <span className="flex-1 text-xs text-gray-400 truncate">
          {call.input}
        </span>
        {call.result && (
          <span
            className={cn(
              "rounded-full px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide",
              outcomeBadgeClass(call.result)
            )}
          >
            {call.result.outcome.replace("_", " ")}
          </span>
        )}
        {open ? (
          <ChevronDown size={12} className="text-gray-400 flex-shrink-0" />
        ) : (
          <ChevronRight size={12} className="text-gray-400 flex-shrink-0" />
        )}
      </button>

      {/* Body */}
      {open && (
        <div className="divide-y divide-gray-200">
          <div className="px-3 py-2">
            <p className="text-[10px] uppercase tracking-wide text-gray-400 mb-1">
              Input
            </p>
            <pre className="text-xs font-mono text-gray-700 whitespace-pre-wrap break-all bg-gray-50 p-2 rounded">
              {call.input}
            </pre>
          </div>
          <div className="px-3 py-2">
            <p className="text-[10px] uppercase tracking-wide text-gray-400 mb-1">
              Output
            </p>
            <pre className="text-xs font-mono text-gray-600 whitespace-pre-wrap break-all bg-gray-50 p-2 rounded max-h-48 overflow-y-auto">
              {call.output || "(no output)"}
            </pre>
          </div>
          {call.result?.error && (
            <div className="px-3 py-2">
              <p className="text-[10px] uppercase tracking-wide text-gray-400 mb-1">
                Error
              </p>
              <pre className="text-xs font-mono text-red-700 whitespace-pre-wrap break-all bg-red-50 p-2 rounded">
                {call.result.error.code}: {call.result.error.message}
              </pre>
            </div>
          )}
          {warnings.length > 0 && (
            <div className="px-3 py-2">
              <p className="text-[10px] uppercase tracking-wide text-gray-400 mb-1">
                Warnings
              </p>
              <pre className="text-xs font-mono text-amber-700 whitespace-pre-wrap break-all bg-amber-50 p-2 rounded">
                {warnings.join("\n")}
              </pre>
            </div>
          )}
          {artifactRefs.length > 0 && (
            <div className="px-3 py-2">
              <p className="text-[10px] uppercase tracking-wide text-gray-400 mb-1">
                Artifact Refs
              </p>
              <pre className="text-xs font-mono text-gray-700 whitespace-pre-wrap break-all bg-gray-50 p-2 rounded max-h-40 overflow-y-auto">
                {artifactRefs
                  .map((ref) => ref.path || ref.identifier || ref.label || "(unnamed ref)")
                  .join("\n")}
              </pre>
            </div>
          )}
          {structuredPayload !== undefined && (
            <div className="px-3 py-2">
              <p className="text-[10px] uppercase tracking-wide text-gray-400 mb-1">
                Structured Payload
              </p>
              <pre className="text-xs font-mono text-gray-700 whitespace-pre-wrap break-all bg-gray-50 p-2 rounded max-h-56 overflow-y-auto">
                {formatJsonValue(structuredPayload)}
              </pre>
            </div>
          )}
          {sourcePayload !== undefined && (
            <div className="px-3 py-2">
              <p className="text-[10px] uppercase tracking-wide text-gray-400 mb-1">
                Source Payload
              </p>
              <pre className="text-xs font-mono text-gray-700 whitespace-pre-wrap break-all bg-gray-50 p-2 rounded max-h-56 overflow-y-auto">
                {formatJsonValue(sourcePayload)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface ThoughtChainProps {
  toolCalls: ToolCall[];
  pendingTool?: { tool: string; input: string } | null;
}

export default function ThoughtChain({ toolCalls, pendingTool }: ThoughtChainProps) {
  const [collapsed, setCollapsed] = useState(false);

  const hasItems = toolCalls.length > 0 || !!pendingTool;
  if (!hasItems) return null;

  return (
    <div className="mt-2 border border-gray-200 rounded-xl overflow-hidden bg-white">
      {/* Section header */}
      <button
        onClick={() => setCollapsed((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 bg-gray-50/80 text-left hover:bg-gray-100 transition-colors"
      >
        {collapsed ? (
          <ChevronRight size={13} className="text-gray-400" />
        ) : (
          <ChevronDown size={13} className="text-gray-400" />
        )}
        <span className="text-xs font-medium text-gray-500">
          Tool calls ({toolCalls.length + (pendingTool ? 1 : 0)})
        </span>
      </button>

      {!collapsed && (
        <div className="px-3 pb-3 pt-1 space-y-2">
          {toolCalls.map((call, i) => (
            <SingleCall key={call.run_id ?? `${call.tool}-${i}`} call={call} />
          ))}

          {/* Pending / in-progress tool */}
          {pendingTool && (
            <div className="border border-dashed border-[#002FA7]/40 rounded-lg px-3 py-2 flex items-center gap-2">
              <ToolIcon name={pendingTool.tool} />
              <span className="text-xs font-mono text-[#002FA7]">
                {pendingTool.tool}
              </span>
              <span className="text-xs text-gray-400 truncate">
                {pendingTool.input}
              </span>
              <span className="ml-auto flex gap-0.5">
                {[0, 1, 2].map((i) => (
                  <span
                    key={i}
                    className="inline-block w-1 h-1 bg-[#002FA7] rounded-full animate-bounce"
                    style={{ animationDelay: `${i * 150}ms` }}
                  />
                ))}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
