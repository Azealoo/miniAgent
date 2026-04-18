"use client";

import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export function TabButton({
  active,
  icon: Icon,
  label,
  ariaLabel,
  onClick,
}: {
  active: boolean;
  icon: LucideIcon;
  label: string;
  ariaLabel: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={ariaLabel}
      className={cn(
        "flex min-h-[44px] flex-col items-center justify-center gap-0.5 rounded-[10px] border px-1 py-1 text-center transition-colors",
        active
          ? "border-[rgba(35,130,83,0.18)] bg-[rgba(35,130,83,0.1)] text-[var(--apex-accent-strong)]"
          : "border-transparent text-slate-500 hover:border-[var(--shell-border)] hover:bg-white/80 hover:text-slate-700"
      )}
    >
      <Icon size={12} strokeWidth={1.8} />
      <span className="text-[9px] font-medium leading-tight">{label}</span>
    </button>
  );
}

export function InspectorCard({
  title,
  meta,
  controls,
  children,
}: {
  title: string;
  meta?: string;
  controls?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rounded-[14px] border border-[rgba(211,219,210,0.86)] bg-[rgba(255,255,255,0.88)] px-3 py-3 shadow-[0_1px_2px_rgba(32,43,35,0.03)] backdrop-blur-sm">
      <div className="mb-3 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">
            {title}
          </h3>
          {meta ? (
            <p className="mt-1 truncate text-[10px] leading-4 text-slate-500">
              {meta}
            </p>
          ) : null}
        </div>
        {controls ? (
          <div className="flex shrink-0 items-center gap-1">{controls}</div>
        ) : null}
      </div>
      {children}
    </section>
  );
}

export function ActionButton({
  onClick,
  disabled,
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium transition-colors",
        disabled
          ? "cursor-not-allowed border-[var(--shell-border)] bg-[rgba(247,249,245,0.92)] text-slate-400"
          : "border-[var(--shell-border)] bg-white/85 text-slate-500 hover:bg-[var(--panel-soft)] hover:text-slate-700"
      )}
    >
      {children}
    </button>
  );
}

export function MemoryCardActionButton({
  onClick,
  title,
  tone = "default",
  children,
}: {
  onClick: () => void;
  title: string;
  tone?: "default" | "danger";
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className={cn(
        "inline-flex h-8 w-8 items-center justify-center rounded-[10px] transition-colors",
        tone === "danger"
          ? "text-slate-500 hover:bg-rose-50 hover:text-rose-600"
          : "text-slate-600 hover:bg-[rgba(35,130,83,0.08)] hover:text-[var(--apex-accent-strong)]"
      )}
    >
      {children}
    </button>
  );
}

export function PrimaryActionButton({
  onClick,
  disabled,
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[10px] font-semibold transition-colors",
        disabled
          ? "cursor-not-allowed bg-slate-200 text-slate-400"
          : "bg-[var(--apex-accent)] text-white hover:bg-[var(--apex-accent-strong)]"
      )}
    >
      {children}
    </button>
  );
}

export function WideActionButton({
  onClick,
  disabled,
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "inline-flex w-full items-center justify-center gap-1.5 rounded-full border px-3 py-2 text-[11px] font-semibold transition-colors",
        disabled
          ? "cursor-not-allowed border-[var(--shell-border)] bg-[rgba(247,249,245,0.92)] text-slate-400"
          : "border-[rgba(211,219,210,0.92)] bg-white text-slate-700 shadow-[0_1px_2px_rgba(32,43,35,0.03)] hover:border-[rgba(35,130,83,0.2)] hover:bg-[var(--panel-soft)] hover:text-[var(--apex-accent-strong)]"
      )}
    >
      {children}
    </button>
  );
}

export function MetaBadge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "accent" | "success" | "warning";
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.08em]",
        tone === "accent" &&
          "border-[rgba(35,130,83,0.16)] bg-[rgba(35,130,83,0.08)] text-[var(--apex-accent-strong)]",
        tone === "success" &&
          "border-emerald-200 bg-emerald-50 text-emerald-700",
        tone === "warning" &&
          "border-amber-200 bg-amber-50 text-amber-700",
        tone === "neutral" &&
          "border-[rgba(211,219,210,0.8)] bg-[rgba(251,252,248,0.92)] text-slate-500"
      )}
    >
      {children}
    </span>
  );
}

export function MiniStat({
  label,
  value,
  accent = false,
  detail,
}: {
  label: string;
  value: string;
  accent?: boolean;
  detail?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-[10px] border px-2.5 py-2",
        accent
          ? "border-[rgba(35,130,83,0.14)] bg-[rgba(35,130,83,0.08)]"
          : "border-[rgba(211,219,210,0.72)] bg-[rgba(251,252,248,0.9)]"
      )}
    >
      <p
        className={cn(
          "text-[9px] font-semibold uppercase tracking-[0.16em]",
          accent ? "text-[var(--apex-accent-strong)]" : "text-slate-400"
        )}
      >
        {label}
      </p>
      <p
        className={cn(
          "mt-0.5 text-xs font-semibold",
          accent ? "text-[var(--apex-accent-strong)]" : "text-slate-700"
        )}
      >
        {value}
      </p>
      {detail ? (
        <p className="mt-1 text-[10px] leading-4 text-slate-500">{detail}</p>
      ) : null}
    </div>
  );
}

export function UsageMetricRow({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3 text-[12px] leading-5">
      <span className="text-slate-400">{label}</span>
      <span className="font-semibold text-slate-700">{value}</span>
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-[12px] border border-dashed border-[rgba(211,219,210,0.92)] bg-[rgba(251,252,248,0.78)] px-3 py-3 text-[11px] leading-5 text-slate-500">
      {children}
    </div>
  );
}

export function LoadingState({ label }: { label: string }) {
  return (
    <div className="rounded-[12px] border border-dashed border-[rgba(211,219,210,0.92)] bg-[rgba(251,252,248,0.78)] px-2.5 py-5 text-center text-[11px] text-slate-400">
      {label}
    </div>
  );
}

export function PreviewPane({
  content,
  className,
}: {
  content: string;
  className?: string;
}) {
  return (
    <pre
      className={cn(
        "max-h-[360px] overflow-y-auto whitespace-pre-wrap break-words rounded-[12px] border border-[rgba(211,219,210,0.8)] bg-[rgba(248,250,246,0.96)] px-2.5 py-2.5 text-[11px] leading-5 text-slate-600",
        className
      )}
    >
      {content}
    </pre>
  );
}
