"use client";

import { useCallback, useState } from "react";
import { AppProvider } from "@/lib/store";
import ChatPanel from "@/components/chat/ChatPanel";
import InspectorPanel from "@/components/editor/InspectorPanel";
import Navbar from "@/components/layout/Navbar";
import ResizeHandle from "@/components/layout/ResizeHandle";
import Sidebar from "@/components/layout/Sidebar";

const SIDEBAR_MIN = 236;
const SIDEBAR_MAX = 312;
const INSPECTOR_MIN = 264;
const INSPECTOR_MAX = 344;

export default function AppShell() {
  const [sidebarWidth, setSidebarWidth] = useState(264);
  const [inspectorWidth, setInspectorWidth] = useState(292);

  const resizeSidebar = useCallback((dx: number) => {
    setSidebarWidth((width) =>
      Math.max(SIDEBAR_MIN, Math.min(SIDEBAR_MAX, width + dx))
    );
  }, []);

  const resizeInspector = useCallback((dx: number) => {
    // Dragging right shrinks the inspector; dragging left expands it.
    setInspectorWidth((width) =>
      Math.max(INSPECTOR_MIN, Math.min(INSPECTOR_MAX, width - dx))
    );
  }, []);

  return (
    <AppProvider>
      <div className="flex min-h-screen flex-col overflow-hidden bg-[var(--shell-canvas)] text-slate-900">
        <Navbar />

        <main className="min-h-0 flex-1 overflow-hidden pt-[var(--navbar-height)]">
          <div className="mx-auto flex h-full min-h-0 w-full max-w-[1460px] gap-3 px-3 pb-3 pt-3 sm:gap-4 sm:px-5 sm:pb-5 sm:pt-5">
            <div className="flex min-h-0 flex-1 items-stretch gap-0">
              <div
                style={{ width: sidebarWidth }}
                className="min-h-0 flex-shrink-0 overflow-hidden"
              >
                <Sidebar />
              </div>

              <ResizeHandle onResize={resizeSidebar} />

              <div className="min-h-0 min-w-0 flex-1 overflow-hidden">
                <ChatPanel />
              </div>

              <ResizeHandle onResize={resizeInspector} />

              <div
                style={{ width: inspectorWidth }}
                className="min-h-0 flex-shrink-0 overflow-hidden"
              >
                <InspectorPanel />
              </div>
            </div>
          </div>
        </main>
      </div>
    </AppProvider>
  );
}
