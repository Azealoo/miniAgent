import type { FeedTone } from "./types";

export function lineToneClass(tone: FeedTone): string {
  if (tone === "active" || tone === "success") {
    return "text-[var(--apex-accent-strong)]";
  }
  if (tone === "warning") {
    return "text-amber-700";
  }
  if (tone === "error") {
    return "text-rose-700";
  }
  return "text-slate-500";
}

export function blockToneClass(tone: FeedTone): string {
  if (tone === "active") {
    return "border-[rgba(35,130,83,0.16)] bg-[linear-gradient(180deg,rgba(248,251,248,0.98),rgba(242,247,243,0.98))]";
  }
  if (tone === "success") {
    return "border-emerald-200 bg-emerald-50/90";
  }
  if (tone === "warning") {
    return "border-amber-200 bg-amber-50/90";
  }
  if (tone === "error") {
    return "border-rose-200 bg-rose-50/90";
  }
  return "border-[rgba(32,43,35,0.08)] bg-white/92";
}

export function badgeToneClass(tone: FeedTone): string {
  if (tone === "active") {
    return "border-[rgba(35,130,83,0.16)] bg-[rgba(35,130,83,0.1)] text-[var(--apex-accent-strong)]";
  }
  if (tone === "success") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  if (tone === "warning") {
    return "border-amber-200 bg-amber-50 text-amber-700";
  }
  if (tone === "error") {
    return "border-rose-200 bg-rose-50 text-rose-700";
  }
  return "border-[rgba(32,43,35,0.08)] bg-white/78 text-slate-500";
}
