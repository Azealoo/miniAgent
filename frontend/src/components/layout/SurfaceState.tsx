"use client";

import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { AlertTriangle, Clock3, Info, ShieldAlert } from "lucide-react";
import { cn } from "@/lib/utils";

type SurfaceStateTone = "neutral" | "accent" | "warning" | "error";

const DEFAULT_ICONS: Record<SurfaceStateTone, LucideIcon> = {
  neutral: Info,
  accent: Clock3,
  warning: ShieldAlert,
  error: AlertTriangle,
};

export default function SurfaceState({
  title,
  description,
  eyebrow = "Workspace State",
  tone = "neutral",
  icon,
  actions,
  compact = false,
}: {
  title: string;
  description: string;
  eyebrow?: string;
  tone?: SurfaceStateTone;
  icon?: LucideIcon;
  actions?: ReactNode;
  compact?: boolean;
}) {
  const Icon = icon ?? DEFAULT_ICONS[tone];

  return (
    <div
      className={cn(
        "rounded-[20px] border px-4 py-4",
        compact ? "text-left" : "text-center",
        tone === "neutral" &&
          "border-[rgba(211,219,210,0.9)] bg-[rgba(251,252,248,0.94)] text-slate-600",
        tone === "accent" &&
          "border-[rgba(35,130,83,0.18)] bg-[rgba(246,251,247,0.96)] text-slate-600",
        tone === "warning" &&
          "border-[rgba(245,158,11,0.24)] bg-[rgba(255,251,235,0.96)] text-amber-900/80",
        tone === "error" &&
          "border-[rgba(248,113,113,0.24)] bg-[rgba(254,242,242,0.96)] text-rose-900/80"
      )}
    >
      <div
        className={cn(
          "flex gap-3",
          compact ? "items-start" : "flex-col items-center justify-center"
        )}
      >
        <div
          className={cn(
            "flex h-10 w-10 shrink-0 items-center justify-center rounded-[14px]",
            tone === "neutral" && "bg-white/80 text-slate-500",
            tone === "accent" && "bg-[var(--apex-accent-soft)] text-[var(--apex-accent-strong)]",
            tone === "warning" && "bg-white/80 text-amber-700",
            tone === "error" && "bg-white/80 text-rose-700"
          )}
        >
          <Icon size={18} />
        </div>

        <div className={cn("min-w-0", compact ? "flex-1" : "max-w-xl")}>
          <p
            className={cn(
              "text-[10px] font-semibold uppercase tracking-[0.18em]",
              tone === "neutral" && "text-slate-400",
              tone === "accent" && "text-[var(--apex-accent-strong)]",
              tone === "warning" && "text-amber-700",
              tone === "error" && "text-rose-700"
            )}
          >
            {eyebrow}
          </p>
          <h3 className="mt-2 text-[1rem] font-semibold tracking-[-0.02em] text-slate-900">
            {title}
          </h3>
          <p className="mt-2 text-sm leading-6">{description}</p>
          {actions ? (
            <div
              className={cn(
                "mt-3 flex flex-wrap gap-2",
                compact ? "justify-start" : "justify-center"
              )}
            >
              {actions}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
