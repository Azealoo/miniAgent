"use client";

import { AlertTriangle, RefreshCw } from "lucide-react";
import React, { Component, type ErrorInfo, type ReactNode } from "react";

import { log } from "@/lib/telemetry";

interface ErrorBoundaryProps {
  children: ReactNode;
  /** Optional custom fallback. Receives the caught error and a `reset` callback. */
  fallback?: (error: Error, reset: () => void) => ReactNode;
  /** Invoked when a descendant throws. Useful for logging / telemetry. */
  onError?: (error: Error, info: ErrorInfo) => void;
  /** Debug label surfaced in the default fallback. */
  label?: string;
}

interface ErrorBoundaryState {
  error: Error | null;
}

export default class ErrorBoundary extends Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    log.error(
      {
        event: "error_boundary",
        message: error.message,
        stack: error.stack,
        meta: {
          label: this.props.label ?? "unknown",
          component_stack: info.componentStack ?? "",
        },
      },
    );
    this.props.onError?.(error, info);
  }

  reset = () => {
    this.setState({ error: null });
  };

  render() {
    const { error } = this.state;
    if (!error) {
      return this.props.children;
    }

    if (this.props.fallback) {
      return this.props.fallback(error, this.reset);
    }

    return (
      <div
        role="alert"
        className="flex h-full min-h-0 flex-col items-center justify-center gap-3 rounded-[18px] border border-[rgba(248,113,113,0.24)] bg-[rgba(254,242,242,0.96)] p-8 text-center text-rose-900/80"
      >
        <div className="flex h-10 w-10 items-center justify-center rounded-[14px] bg-white/80 text-rose-700">
          <AlertTriangle size={18} />
        </div>
        <div className="max-w-md">
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-rose-700">
            {this.props.label ?? "Panel Error"}
          </p>
          <h3 className="mt-1 text-[1rem] font-semibold tracking-[-0.02em] text-slate-900">
            This panel hit an unexpected error
          </h3>
          <p className="mt-2 text-sm leading-6">
            {error.message || "Something went wrong rendering this section."}
          </p>
        </div>
        <button
          type="button"
          onClick={this.reset}
          className="inline-flex items-center gap-2 rounded-full border border-[var(--shell-border)] bg-white/92 px-3 py-1.5 text-[11px] font-medium text-slate-700 transition-colors hover:bg-slate-50"
        >
          <RefreshCw size={12} />
          Reset panel
        </button>
      </div>
    );
  }
}
