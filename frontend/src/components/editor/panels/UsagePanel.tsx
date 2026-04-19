"use client";

import { useEffect, useState } from "react";
import { getSessionTokens } from "@/lib/api";
import { useApp } from "@/lib/store";
import {
  summarizeSessionUsage,
  type UsageSummaryOrigin,
} from "@/lib/token-usage";
import type { TokenStats } from "@/lib/types";
import {
  EmptyState,
  InspectorCard,
  LoadingState,
  MetaBadge,
  UsageMetricRow,
} from "./primitives";
import { formatCompactTokenValue } from "./shared-utils";

export default function UsagePanel() {
  const {
    accessByScope,
    hasInspectionAccess,
    currentSessionId,
    messages,
    isStreaming,
    parseErrorCount,
  } = useApp();

  const [tokens, setTokens] = useState<TokenStats | null>(null);
  const [usageLoading, setUsageLoading] = useState(false);
  const [usageLoadError, setUsageLoadError] = useState("");
  const [usageBaselineMessageCount, setUsageBaselineMessageCount] = useState(0);

  const inspectionAccessStatus = accessByScope.inspection.status;

  useEffect(() => {
    if (!currentSessionId) {
      setTokens(null);
      setUsageLoading(false);
      setUsageLoadError("");
      setUsageBaselineMessageCount(0);
      return;
    }

    if (!hasInspectionAccess) {
      setUsageLoading(false);
      return;
    }

    if (isStreaming) {
      setUsageLoading(false);
      setTokens((current) =>
        current?.session_id === currentSessionId ? current : null
      );
      setUsageBaselineMessageCount((current) =>
        current > messages.length ? 0 : current
      );
      setUsageLoadError("");
      return;
    }

    let cancelled = false;
    setUsageLoading(true);
    setUsageLoadError("");

    void getSessionTokens(currentSessionId)
      .then((nextTokens) => {
        if (cancelled) {
          return;
        }

        setTokens(nextTokens);
        setUsageBaselineMessageCount(messages.length);
        setUsageLoadError("");
      })
      .catch(() => {
        if (cancelled) {
          return;
        }

        setTokens(null);
        setUsageBaselineMessageCount(0);
        setUsageLoadError(
          "Could not load tracked token usage. Showing a live estimate instead."
        );
      })
      .finally(() => {
        if (!cancelled) {
          setUsageLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [currentSessionId, hasInspectionAccess, isStreaming, messages.length]);

  useEffect(() => {
    if (
      inspectionAccessStatus === "granted" ||
      inspectionAccessStatus === "checking" ||
      inspectionAccessStatus === "unavailable"
    ) {
      return;
    }

    setTokens(null);
    setUsageLoading(false);
    setUsageLoadError(accessByScope.inspection.detail);
    setUsageBaselineMessageCount(0);
  }, [accessByScope.inspection.detail, inspectionAccessStatus]);

  const usageSummary = summarizeSessionUsage({
    sessionId: currentSessionId,
    messages,
    exactTokens:
      currentSessionId && tokens?.session_id === currentSessionId ? tokens : null,
    exactMessageCount: usageBaselineMessageCount,
  });
  const sessionUsage = usageSummary?.stats ?? null;
  const usageOrigin: UsageSummaryOrigin | null = usageSummary?.origin ?? null;
  const trackedTotalTokens =
    sessionUsage?.tracked_total_tokens ?? sessionUsage?.total_tokens ?? 0;
  const promptContextTokens = sessionUsage?.total_tokens ?? 0;
  const contextWindowRatio =
    sessionUsage?.context_window_tokens && sessionUsage.context_window_tokens > 0
      ? Math.min(promptContextTokens / sessionUsage.context_window_tokens, 1)
      : null;
  const contextWindowLabel = sessionUsage?.context_window_tokens
    ? `${formatCompactTokenValue(promptContextTokens)} / ${formatCompactTokenValue(sessionUsage.context_window_tokens)}`
    : null;
  const usageStatusLabel =
    usageOrigin === "tracked_live"
      ? "Live"
      : usageOrigin === "tracked"
        ? "Tracked"
        : "Estimated";

  return (
    <div className="space-y-2">
      <InspectorCard
        title="Usage"
        controls={
          <MetaBadge tone={usageOrigin === "tracked_live" ? "accent" : "neutral"}>
            {usageStatusLabel}
          </MetaBadge>
        }
      >
        {!currentSessionId ? (
          <EmptyState>Select a session to inspect token usage.</EmptyState>
        ) : usageLoading && !sessionUsage ? (
          <LoadingState label="Loading usage..." />
        ) : sessionUsage && (trackedTotalTokens > 0 || messages.length > 0) ? (
          <div className="space-y-4">
            <div className="pt-1 text-center">
              <p className="text-[40px] font-semibold tracking-[-0.06em] text-slate-800">
                {trackedTotalTokens.toLocaleString()}
              </p>
              <p className="mt-1 text-[11px] text-slate-400">Total tokens</p>
            </div>

            <div className="space-y-1.5">
              <UsageMetricRow
                label="Input"
                value={sessionUsage.input_tokens.toLocaleString()}
              />
              <UsageMetricRow
                label="Output"
                value={sessionUsage.output_tokens.toLocaleString()}
              />
              <UsageMetricRow
                label="Tools"
                value={sessionUsage.tool_tokens.toLocaleString()}
              />
              {parseErrorCount > 0 ? (
                <UsageMetricRow
                  label="Parse errors"
                  value={parseErrorCount.toLocaleString()}
                />
              ) : null}
            </div>

            <div className="space-y-1.5 pt-0.5">
              <div className="flex items-center justify-between gap-3 text-[12px] leading-5">
                <span>Context</span>
                <span className="font-semibold text-slate-700">
                  {contextWindowLabel ?? "Unavailable"}
                </span>
              </div>
              <div className="h-[2px] overflow-hidden rounded-full bg-[rgba(211,219,210,0.76)]">
                {contextWindowRatio !== null ? (
                  <div
                    className="h-full rounded-full bg-[var(--apex-accent)]"
                    style={{ width: `${contextWindowRatio * 100}%` }}
                  />
                ) : null}
              </div>
              {contextWindowLabel ? null : (
                <p className="text-[10px] leading-4 text-slate-500">
                  Context-window budget is not configured for this model.
                </p>
              )}
            </div>

          </div>
        ) : usageLoading ? (
          <LoadingState label="Loading usage..." />
        ) : (
          <EmptyState>
            Send a message in this session to populate token usage here.
          </EmptyState>
        )}
      </InspectorCard>
    </div>
  );
}
