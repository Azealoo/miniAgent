import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function uid(): string {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  const now = new Date();
  const isToday = d.toDateString() === now.toDateString();
  if (isToday) {
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

export function formatRelativeTime(ts: number): string {
  const timestampMs = ts * 1000;
  const diffSeconds = Math.max(0, Math.floor((Date.now() - timestampMs) / 1000));

  if (diffSeconds < 45) {
    return "Just now";
  }

  if (diffSeconds < 60 * 60) {
    return `${Math.floor(diffSeconds / 60)}m ago`;
  }

  if (diffSeconds < 60 * 60 * 24) {
    return `${Math.floor(diffSeconds / (60 * 60))}h ago`;
  }

  if (diffSeconds < 60 * 60 * 24 * 2) {
    return "Yesterday";
  }

  if (diffSeconds < 60 * 60 * 24 * 7) {
    return `${Math.floor(diffSeconds / (60 * 60 * 24))}d ago`;
  }

  if (diffSeconds < 60 * 60 * 24 * 30) {
    return `${Math.floor(diffSeconds / (60 * 60 * 24 * 7))}w ago`;
  }

  if (diffSeconds < 60 * 60 * 24 * 365) {
    return `${Math.floor(diffSeconds / (60 * 60 * 24 * 30))}mo ago`;
  }

  return `${Math.floor(diffSeconds / (60 * 60 * 24 * 365))}y ago`;
}
