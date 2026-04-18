"use client";

import ChatPanel from "@/components/chat/ChatPanel";
import ErrorBoundary from "@/components/ErrorBoundary";

export default function WorkspacePanel() {
  return (
    <ErrorBoundary label="Chat Panel">
      <ChatPanel />
    </ErrorBoundary>
  );
}
