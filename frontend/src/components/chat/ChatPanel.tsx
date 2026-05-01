"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, MessageSquarePlus, RefreshCw, ShieldAlert } from "lucide-react";
import SurfaceState from "@/components/layout/SurfaceState";
import { useApp } from "@/lib/store";
import { RETRY_MAX_ATTEMPTS } from "@/lib/retry-backoff";
import ChatInput from "./ChatInput";
import SessionHistorySummary from "@/components/session/SessionHistorySummary";

export default function ChatPanel() {
  const {
    accessByScope,
    hasInspectionAccess,
    hasExecutionAccess,
    currentSessionId,
    messages,
    isStreaming,
    isSessionLoading,
    sessionListStatus,
    sessionHistoryStatus,
    sessionHistoryError,
    sessionContinuitySummaries,
    lastFailedTurn,
    sendMessage,
    stopStreaming,
    reloadCurrentSession,
    clearLastFailedTurn,
    setInspectorTab,
    draftMessage,
    draftRevision,
    primeDraftMessage,
    clearDraftMessage,
  } = useApp();

  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const isNearBottomRef = useRef(true);
  const autoScrollRef = useRef(true);
  const userPausedAutoScrollRef = useRef(false);
  const lastScrollTopRef = useRef(0);

  const syncScrollState = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;

    const threshold = 80;
    const nearBottom =
      el.scrollHeight - el.scrollTop - el.clientHeight < threshold;

    isNearBottomRef.current = nearBottom;
    if (nearBottom && !userPausedAutoScrollRef.current) {
      autoScrollRef.current = true;
    }
  }, []);

  const handleScroll = () => {
    const el = containerRef.current;
    if (!el) return;

    const scrollingUp = el.scrollTop < lastScrollTopRef.current;
    lastScrollTopRef.current = el.scrollTop;

    syncScrollState();
    if (scrollingUp && !isNearBottomRef.current) {
      autoScrollRef.current = false;
      userPausedAutoScrollRef.current = true;
    }

    if (!scrollingUp && isNearBottomRef.current) {
      userPausedAutoScrollRef.current = false;
      autoScrollRef.current = true;
    }
  };

  useEffect(() => {
    if (messages.length === 0) {
      autoScrollRef.current = true;
      userPausedAutoScrollRef.current = false;
      lastScrollTopRef.current = 0;
      return;
    }

    if (autoScrollRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: isStreaming ? "auto" : "smooth" });
    }

    const frame = window.requestAnimationFrame(() => {
      syncScrollState();
      const el = containerRef.current;
      if (el) {
        lastScrollTopRef.current = el.scrollTop;
      }
    });

    return () => window.cancelAnimationFrame(frame);
  }, [isStreaming, messages, syncScrollState]);

  const handleSend = async (text: string) => {
    await sendMessage(text);
  };

  // Re-render once per second while a cooldown window is active so the
  // remaining-wait label stays current and the button re-enables on schedule.
  // Without this, the disabled state would only flip when something else in
  // the tree triggered a render.
  const [cooldownNow, setCooldownNow] = useState(() => Date.now());
  const cooldownTarget = lastFailedTurn?.nextAllowedRetryAt ?? 0;
  const isCooldownActive =
    !!lastFailedTurn &&
    !lastFailedTurn.reachedCap &&
    cooldownTarget > cooldownNow &&
    Number.isFinite(cooldownTarget);
  useEffect(() => {
    if (!isCooldownActive) return;
    const handle = window.setInterval(() => {
      setCooldownNow(Date.now());
    }, 250);
    return () => window.clearInterval(handle);
  }, [isCooldownActive]);

  const cooldownRemainingMs = isCooldownActive
    ? Math.max(0, cooldownTarget - cooldownNow)
    : 0;
  const cooldownRemainingSeconds = Math.ceil(cooldownRemainingMs / 1000);
  const reachedRetryCap = !!lastFailedTurn?.reachedCap;
  const retryDisabled = isStreaming || isCooldownActive || reachedRetryCap;

  const handleRetryFailedTurn = useCallback(() => {
    if (!lastFailedTurn || isStreaming) return;
    if (lastFailedTurn.reachedCap) return;
    if (
      Number.isFinite(lastFailedTurn.nextAllowedRetryAt) &&
      Date.now() < lastFailedTurn.nextAllowedRetryAt
    ) {
      return;
    }
    void sendMessage(lastFailedTurn.content, {
      requestId: lastFailedTurn.requestId,
    });
  }, [isStreaming, lastFailedTurn, sendMessage]);

  const chatDisabled = isSessionLoading || !hasExecutionAccess;
  const chatDisabledReason = !hasExecutionAccess
    ? accessByScope.execution.detail
    : "Loading workspace";
  const showSessionHistoryErrorBanner =
    Boolean(currentSessionId) &&
    sessionHistoryStatus === "error" &&
    messages.length > 0;
  const showWorkspaceSetupState =
    messages.length === 0 &&
    !currentSessionId &&
    sessionListStatus !== "loading" &&
    accessByScope.execution.status !== "checking" &&
    accessByScope.inspection.status !== "checking";

  return (
    <section className="apex-panel flex h-full min-h-0 flex-col overflow-hidden rounded-[18px] shadow-[var(--panel-shadow-soft)]">
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-[linear-gradient(180deg,rgba(248,250,246,0.92)_0%,rgba(244,246,242,0.82)_100%)]">
        <div
          ref={containerRef}
          onScroll={handleScroll}
          onWheelCapture={(event) => {
            if (event.deltaY < 0) {
              userPausedAutoScrollRef.current = true;
              autoScrollRef.current = false;
            }
          }}
          role="log"
          aria-live="polite"
          aria-relevant="additions text"
          aria-atomic="false"
          aria-label="Conversation transcript"
          className="flex-1 overflow-y-auto px-4 pt-4 sm:px-6 sm:pt-5 lg:px-8 lg:pt-7"
        >
          <div className="mx-auto flex min-h-full w-full max-w-[54rem] flex-col">
            {showSessionHistoryErrorBanner ? (
              <div className="pb-5">
                <SurfaceState
                  compact
                  tone="error"
                  eyebrow="Session History"
                  title="Saved history could not load"
                  description={
                    sessionHistoryError ??
                    "This session is selected, but its saved history is temporarily unavailable."
                  }
                  actions={
                    <InlineActionButton onClick={() => void reloadCurrentSession()}>
                      <RefreshCw size={12} />
                      Retry History
                    </InlineActionButton>
                  }
                />
              </div>
            ) : null}

            {messages.length === 0 ? (
              <EmptyState
                currentSessionId={currentSessionId}
                hasExecutionAccess={hasExecutionAccess}
                hasInspectionAccess={hasInspectionAccess}
                executionDetail={accessByScope.execution.detail}
                inspectionDetail={accessByScope.inspection.detail}
                inspectionStatus={accessByScope.inspection.status}
                executionStatus={accessByScope.execution.status}
                isSessionLoading={isSessionLoading}
                sessionListStatus={sessionListStatus}
                sessionHistoryStatus={sessionHistoryStatus}
                sessionHistoryError={sessionHistoryError}
                showWorkspaceSetupState={showWorkspaceSetupState}
                onRetryHistory={() => void reloadCurrentSession()}
              />
            ) : (
              <SessionHistorySummary
                currentSessionId={currentSessionId}
                messages={messages}
                continuitySummaries={sessionContinuitySummaries}
              />
            )}
            <div ref={bottomRef} className="h-px" />
          </div>
        </div>

        <div className="pointer-events-none h-5 bg-gradient-to-t from-[rgba(244,246,242,0.96)] via-[rgba(244,246,242,0.76)] to-transparent" />

        <div className="sticky bottom-0 z-10 px-3 pb-2 sm:px-5 sm:pb-3 lg:px-6 lg:pb-3">
          <div className="mx-auto w-full max-w-[56rem]">
            {lastFailedTurn && !isStreaming ? (
              <div className="mb-2">
                <SurfaceState
                  compact
                  tone="error"
                  eyebrow="Turn Failed"
                  title={
                    reachedRetryCap
                      ? "Turn failed — retry limit reached"
                      : "Turn failed — retry"
                  }
                  description={buildRetryBannerDescription({
                    requestId: lastFailedTurn.requestId,
                    attemptCount: lastFailedTurn.attemptCount,
                    reachedCap: reachedRetryCap,
                    cooldownRemainingSeconds: isCooldownActive
                      ? cooldownRemainingSeconds
                      : 0,
                  })}
                  actions={
                    <div className="flex flex-wrap gap-2">
                      <InlineActionButton
                        onClick={handleRetryFailedTurn}
                        disabled={retryDisabled}
                      >
                        <RefreshCw size={12} />
                        {isCooldownActive
                          ? `Retry in ${cooldownRemainingSeconds}s`
                          : reachedRetryCap
                            ? "No more retries"
                            : "Retry turn"}
                      </InlineActionButton>
                      <InlineActionButton onClick={clearLastFailedTurn}>
                        Dismiss
                      </InlineActionButton>
                    </div>
                  }
                />
              </div>
            ) : null}
            <ChatInput
              onSend={handleSend}
              onStop={stopStreaming}
              isStreaming={isStreaming}
              disabled={chatDisabled}
              disabledReason={chatDisabledReason}
              onOpenInspectorTab={setInspectorTab}
              onPrimeDraftMessage={primeDraftMessage}
              prefillText={draftMessage}
              prefillRevision={draftRevision}
              clearPrefill={clearDraftMessage}
            />
          </div>
        </div>
      </div>
    </section>
  );
}

function InlineActionButton({
  children,
  onClick,
  disabled = false,
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="inline-flex items-center gap-2 rounded-full border border-[var(--shell-border)] bg-white/92 px-3 py-1.5 text-[11px] font-medium text-slate-600 transition-colors hover:bg-[var(--panel-soft)] hover:text-slate-800 disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:bg-white/92 disabled:hover:text-slate-600"
    >
      {children}
    </button>
  );
}

function buildRetryBannerDescription({
  requestId,
  attemptCount,
  reachedCap,
  cooldownRemainingSeconds,
}: {
  requestId: string | undefined;
  attemptCount: number;
  reachedCap: boolean;
  cooldownRemainingSeconds: number;
}): string {
  const reqSuffix = requestId
    ? ` Retry re-issues it with request ${requestId}.`
    : " Retry re-issues it with the same request id.";

  if (reachedCap) {
    return `The last turn failed ${attemptCount} time${attemptCount === 1 ? "" : "s"}; the retry limit (${RETRY_MAX_ATTEMPTS}) has been reached. Dismiss this banner and send a fresh message to try again.`;
  }
  if (cooldownRemainingSeconds > 0) {
    return `The last turn did not complete (attempt ${attemptCount} of ${RETRY_MAX_ATTEMPTS}). Cooling down ${cooldownRemainingSeconds}s before another retry is allowed.${reqSuffix}`;
  }
  return `The last turn did not complete (attempt ${attemptCount} of ${RETRY_MAX_ATTEMPTS}).${reqSuffix}`;
}

function EmptyState({
  currentSessionId,
  hasExecutionAccess,
  hasInspectionAccess,
  executionDetail,
  inspectionDetail,
  inspectionStatus,
  executionStatus,
  isSessionLoading,
  sessionListStatus,
  sessionHistoryStatus,
  sessionHistoryError,
  showWorkspaceSetupState,
  onRetryHistory,
}: {
  currentSessionId: string | null;
  hasExecutionAccess: boolean;
  hasInspectionAccess: boolean;
  executionDetail: string;
  inspectionDetail: string;
  inspectionStatus: "checking" | "granted" | "token_required" | "server_misconfigured" | "forbidden" | "unavailable";
  executionStatus: "checking" | "granted" | "token_required" | "server_misconfigured" | "forbidden" | "unavailable";
  isSessionLoading: boolean;
  sessionListStatus: "idle" | "loading" | "ready" | "error";
  sessionHistoryStatus: "idle" | "loading" | "ready" | "error";
  sessionHistoryError: string | null;
  showWorkspaceSetupState: boolean;
  onRetryHistory: () => void;
}) {
  if (inspectionStatus === "checking" || executionStatus === "checking" || isSessionLoading) {
    return (
      <div className="flex flex-1 items-center justify-center px-8 py-16">
        <SurfaceState
          tone="accent"
          eyebrow="Workspace Loading"
          title="Loading the active workspace"
          description="BioAPEX is checking access and syncing the selected session so the center panel can show the latest conversation state."
        />
      </div>
    );
  }

  if (currentSessionId && sessionHistoryStatus === "error") {
    return (
      <div className="flex flex-1 items-center justify-center px-8 py-16">
        <SurfaceState
          tone="error"
          eyebrow="Session History"
          title="Saved history could not load"
          description={
            sessionHistoryError ??
            "The selected session is available, but its saved history could not be rendered right now."
          }
          actions={
            <InlineActionButton onClick={onRetryHistory}>
              <RefreshCw size={12} />
              Retry History
            </InlineActionButton>
          }
        />
      </div>
    );
  }

  if (!hasExecutionAccess && !currentSessionId) {
    return (
      <div className="flex flex-1 items-center justify-center px-8 py-16">
        <SurfaceState
          tone="warning"
          eyebrow="Execution Access"
          title="Chat is unavailable from this client"
          description={executionDetail}
        />
      </div>
    );
  }

  if (!hasInspectionAccess && currentSessionId) {
    return (
      <div className="flex flex-1 items-center justify-center px-8 py-16">
        <SurfaceState
          tone="warning"
          eyebrow="Inspection Access"
          title="Saved session content is unavailable"
          description={inspectionDetail}
        />
      </div>
    );
  }

  if (sessionListStatus === "error" && !currentSessionId) {
    return (
      <div className="flex flex-1 items-center justify-center px-8 py-16">
        <SurfaceState
          tone="error"
          eyebrow="Session Workspace"
          title="The workspace list is unavailable"
          description="BioAPEX could not load the saved session list, so there is no active workspace to display in the center panel yet."
        />
      </div>
    );
  }

  if (showWorkspaceSetupState) {
    return (
      <div className="flex flex-1 items-center justify-center px-8 py-16">
        <SurfaceState
          tone="neutral"
          eyebrow="Conversation Workspace"
          title="Select a session or start a new one"
          description="Use the sidebar to open a saved workspace or create a new session before you start a BioAPEX conversation."
          actions={
            <span className="inline-flex items-center gap-2 rounded-full border border-[rgba(211,219,210,0.88)] bg-white/88 px-3 py-1.5 text-[11px] font-medium text-slate-600">
              <ArrowRight size={12} />
              Sidebar sessions control the active workspace
            </span>
          }
        />
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col items-center justify-center px-8 py-16 text-center">
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-[16px] bg-[var(--apex-accent-soft)]">
        {currentSessionId ? (
          <ShieldAlert size={24} className="text-[var(--apex-accent)]" />
        ) : (
          <MessageSquarePlus size={24} className="text-[var(--apex-accent)]" />
        )}
      </div>
      <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-[var(--apex-accent-strong)]">
        Conversation Workspace
      </p>
      <h2 className="mt-3 text-[1.05rem] font-semibold tracking-[-0.01em] text-slate-800">
        {currentSessionId ? "This session is ready for the next turn" : "Start a BioAPEX conversation"}
      </h2>
      <p className="mt-2 max-w-lg text-sm leading-6 text-slate-500">
        {currentSessionId
          ? "Ask a biology question, inspect a dataset, review evidence, or start a structured analysis when you need one. New requests in this session will appear here as the conversation grows."
          : "Ask a biology question, inspect a dataset, review evidence, or start a structured analysis when you need one. The center workspace is ready for the active conversation."}
      </p>
    </div>
  );
}
