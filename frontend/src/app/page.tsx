"use client";

import { useState, useCallback } from "react";
import { AppProvider } from "@/lib/store";
import Navbar from "@/components/layout/Navbar";
import Sidebar from "@/components/layout/Sidebar";
import ResizeHandle from "@/components/layout/ResizeHandle";
import ChatPanel from "@/components/chat/ChatPanel";
import InspectorPanel from "@/components/editor/InspectorPanel";

const SIDEBAR_MIN = 200;
const SIDEBAR_MAX = 400;
const INSPECTOR_MIN = 280;
const INSPECTOR_MAX = 600;

export default function Home() {
  const [sidebarWidth, setSidebarWidth] = useState(260);
  const [inspectorWidth, setInspectorWidth] = useState(340);

  const resizeSidebar = useCallback((dx: number) => {
    setSidebarWidth((w) => Math.max(SIDEBAR_MIN, Math.min(SIDEBAR_MAX, w + dx)));
  }, []);

  const resizeInspector = useCallback((dx: number) => {
    // Dragging right → inspector gets smaller, left → larger
    setInspectorWidth((w) =>
      Math.max(INSPECTOR_MIN, Math.min(INSPECTOR_MAX, w - dx))
    );
  }, []);

  return (
    <AppProvider>
      <div className="flex flex-col h-screen select-none overflow-hidden">
        <Navbar />

        <div className="flex flex-1 overflow-hidden">
          {/* Left sidebar */}
          <div
            style={{ width: sidebarWidth }}
            className="flex-shrink-0 overflow-hidden"
          >
            <Sidebar />
          </div>

          <ResizeHandle onResize={resizeSidebar} />

          {/* Centre — chat */}
          <div className="flex-1 overflow-hidden">
            <ChatPanel />
          </div>

          <ResizeHandle onResize={resizeInspector} />

          {/* Right — inspector */}
          <div
            style={{ width: inspectorWidth }}
            className="flex-shrink-0 overflow-hidden"
          >
            <InspectorPanel />
          </div>
        </div>
      </div>
    </AppProvider>
  );
}
