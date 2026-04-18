export function compactText(
  value?: string | null,
  maxLength = 160
): string | null {
  if (!value) return null;

  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized) return null;
  if (normalized.length <= maxLength) return normalized;
  return `${normalized.slice(0, maxLength - 1).trimEnd()}…`;
}

export function humanizeToken(value?: string | null): string | null {
  if (!value) return null;
  return value.replaceAll("_", " ").replaceAll("-", " ");
}

export function shortIdentifier(value?: string | null): string | null {
  if (!value) return null;
  if (value.length <= 18) return value;
  return `${value.slice(0, 8)}…${value.slice(-6)}`;
}
