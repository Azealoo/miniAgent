"use client";

import { Brain, Clock3, Download, FileText, Hash, Search } from "lucide-react";
import FilesPanel from "@/components/editor/panels/FilesPanel";
import MemoryPanel from "@/components/editor/panels/MemoryPanel";
import SourcesPanel from "@/components/editor/panels/SourcesPanel";
import TurnsPanel from "@/components/editor/panels/TurnsPanel";
import UsagePanel from "@/components/editor/panels/UsagePanel";
import { TabButton } from "@/components/editor/panels/primitives";
import {
  buildExportMarkdown,
  exportFilename,
} from "@/components/editor/panels/shared-utils";
import { useApp } from "@/lib/store";
import { cn } from "@/lib/utils";
import type { InspectorTab } from "@/lib/types";

const INSPECTOR_TABS = [
  { id: "files", label: "Files", icon: FileText, Component: FilesPanel },
  { id: "sources", label: "Sources", icon: Search, Component: SourcesPanel },
  { id: "memory", label: "Memory", icon: Brain, Component: MemoryPanel },
  { id: "usage", label: "Usage", icon: Hash, Component: UsagePanel },
  { id: "turns", label: "Turns", icon: Clock3, Component: TurnsPanel },
] as const satisfies ReadonlyArray<{
  id: InspectorTab;
  label: string;
  icon: typeof FileText;
  Component: () => JSX.Element;
}>;

export default function InspectorPanel() {
  const {
    currentSessionId,
    sessions,
    messages,
    inspectorTab,
    setInspectorTab,
  } = useApp();

  const activeSession =
    sessions.find((session) => session.id === currentSessionId) ?? null;

  const handleInspectorExport = () => {
    if (typeof window === "undefined" || messages.length === 0) {
      return;
    }

    const title =
      activeSession?.title?.trim() || currentSessionId || "BioAPEX Session";
    const content = buildExportMarkdown(title, messages);
    const blob = new Blob([content], {
      type: "text/markdown;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");

    link.href = url;
    link.download = `${exportFilename(title)}.md`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  };

  const ActivePanel =
    INSPECTOR_TABS.find((tab) => tab.id === inspectorTab)?.Component ?? FilesPanel;

  return (
    <aside className="apex-panel apex-panel-muted flex h-full flex-col overflow-hidden rounded-[18px]">
      <div className="border-b border-[var(--shell-border)] bg-white/70 px-2 py-1.5">
        <div className="grid grid-cols-5 gap-0.5">
          {INSPECTOR_TABS.map((tab) => (
            <TabButton
              key={tab.id}
              active={inspectorTab === tab.id}
              icon={tab.icon}
              label={tab.label}
              ariaLabel={`Inspector ${tab.label}`}
              onClick={() => setInspectorTab(tab.id)}
            />
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
        <ActivePanel />
      </div>

      <div className="border-t border-[var(--shell-border)] bg-white/70 px-2 py-2">
        <button
          type="button"
          onClick={handleInspectorExport}
          disabled={messages.length === 0}
          className={cn(
            "inline-flex w-full items-center justify-center gap-1.5 rounded-full border px-3 py-2 text-[11px] font-semibold transition-colors",
            messages.length === 0
              ? "cursor-not-allowed border-[var(--shell-border)] bg-[rgba(247,249,245,0.92)] text-slate-400"
              : "border-[rgba(211,219,210,0.92)] bg-white text-slate-700 shadow-[0_1px_2px_rgba(32,43,35,0.03)] hover:border-[rgba(35,130,83,0.2)] hover:bg-[var(--panel-soft)] hover:text-[var(--apex-accent-strong)]"
          )}
          title={
            messages.length === 0
              ? "Start a conversation to export this workspace."
              : "Export the current session transcript."
          }
        >
          <Download size={14} />
          Export
        </button>
      </div>
    </aside>
  );
}
