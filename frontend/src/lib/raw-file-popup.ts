/**
 * Presentation + open-in-new-tab flow for the authenticated raw-file viewer.
 *
 * This module keeps the HTML popup chrome separate from `api.ts` (which stays
 * a thin HTTP client). It depends on `api.ts` for the underlying fetch
 * primitives, but `api.ts` does not import back from here — that one-way
 * dependency is intentional to avoid ESM cycles.
 */

import {
  createRawFileObjectUrl,
  getRawFileUrl,
  readRawFileText,
  resolveBearerToken,
} from "./api";

const RAW_ACTIVE_CONTENT_EXTENSIONS = new Set([".htm", ".html", ".svg", ".xhtml"]);

function getPathExtension(path: string): string {
  const cleanPath = path.split("?")[0] ?? path;
  const index = cleanPath.lastIndexOf(".");
  return index >= 0 ? cleanPath.slice(index).toLowerCase() : "";
}

function shouldKeepRawOpenOffAppOrigin(path: string): boolean {
  return RAW_ACTIVE_CONTENT_EXTENSIONS.has(getPathExtension(path));
}

function rawFileName(path: string): string {
  const parts = path.split("/").filter(Boolean);
  return parts.at(-1) ?? "raw-file";
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function writePopupMessage(popup: Window, title: string, message: string): void {
  popup.document.title = title;
  popup.document.body.innerHTML =
    `<div style="font-family: sans-serif; padding: 16px; color: #334155;">${message}</div>`;
}

function renderAuthenticatedRawSourceView(
  popup: Window,
  path: string,
  content: string,
  contentType: string | null
): void {
  const downloadUrl = URL.createObjectURL(
    new Blob([content], {
      type: contentType ?? "text/plain; charset=utf-8",
    })
  );
  const cleanup = () => URL.revokeObjectURL(downloadUrl);
  // `pagehide` covers browsers that skip `beforeunload` (iOS Safari, bfcache).
  popup.addEventListener("beforeunload", cleanup, { once: true });
  popup.addEventListener("pagehide", cleanup, { once: true });
  window.setTimeout(cleanup, 5 * 60_000);

  const escapedPath = escapeHtml(path);
  const escapedContent = escapeHtml(content);
  const escapedType = escapeHtml(contentType ?? "text/plain");
  const escapedName = escapeHtml(rawFileName(path));

  popup.document.open();
  popup.document.write(`<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Raw Source View</title>
    <style>
      :root {
        color-scheme: light;
        font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      }
      body {
        margin: 0;
        background: #f4f5ef;
        color: #162116;
      }
      main {
        max-width: 1100px;
        margin: 0 auto;
        padding: 32px 20px 40px;
      }
      .panel {
        border: 1px solid rgba(179, 190, 176, 0.8);
        border-radius: 20px;
        background: rgba(255, 255, 255, 0.96);
        box-shadow: 0 10px 28px rgba(29, 42, 33, 0.08);
        overflow: hidden;
      }
      .hero {
        padding: 22px 24px 18px;
        border-bottom: 1px solid rgba(214, 221, 212, 0.9);
        background: linear-gradient(180deg, rgba(246, 248, 241, 0.98), rgba(255, 255, 255, 0.98));
      }
      .eyebrow {
        margin: 0;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.16em;
        text-transform: uppercase;
        color: #6b7280;
      }
      h1 {
        margin: 10px 0 0;
        font-size: 24px;
        line-height: 1.2;
      }
      p {
        margin: 12px 0 0;
        line-height: 1.6;
        color: #475569;
      }
      .meta {
        margin-top: 14px;
        font-size: 12px;
        color: #64748b;
        word-break: break-all;
      }
      .actions {
        display: flex;
        gap: 12px;
        align-items: center;
        margin-top: 18px;
      }
      .button {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: 10px 14px;
        border-radius: 999px;
        border: 1px solid rgba(35, 130, 83, 0.18);
        background: rgba(223, 242, 228, 0.92);
        color: #166534;
        font-size: 13px;
        font-weight: 700;
        text-decoration: none;
      }
      pre {
        margin: 0;
        padding: 24px;
        overflow: auto;
        background: #f8faf7;
        color: #1f2937;
        font: 12px/1.65 "IBM Plex Mono", "SFMono-Regular", monospace;
        white-space: pre-wrap;
        word-break: break-word;
      }
    </style>
  </head>
  <body>
    <main>
      <section class="panel">
        <div class="hero">
          <p class="eyebrow">Raw Source View</p>
          <h1>${escapedName}</h1>
          <p>
            Active raw content is shown as source here so authenticated opens do not mint a
            same-origin document inside the BioAPEX app.
          </p>
          <div class="meta">Path: ${escapedPath}<br />Content-Type: ${escapedType}</div>
          <div class="actions">
            <a class="button" href="${downloadUrl}" download="${escapedName}">Download Raw File</a>
          </div>
        </div>
        <pre>${escapedContent}</pre>
      </section>
    </main>
  </body>
</html>`);
  popup.document.close();
}

export const openRawFileInNewTab = async (path: string): Promise<void> => {
  if (typeof window === "undefined") return;

  if (shouldKeepRawOpenOffAppOrigin(path) && !resolveBearerToken("inspection")) {
    window.open(getRawFileUrl(path), "_blank", "noopener,noreferrer");
    return;
  }

  const popup = window.open("", "_blank");
  if (popup) {
    // Keep the synchronous popup for browser popup-blocker compatibility,
    // but sever opener access before any same-origin blob navigation occurs.
    popup.opener = null;
    writePopupMessage(popup, "Loading raw file", "Loading raw file...");
  }

  try {
    if (shouldKeepRawOpenOffAppOrigin(path)) {
      if (!popup || popup.closed) {
        throw new Error("Could not open a safe raw-source window.");
      }
      const { content, contentType } = await readRawFileText(path);
      renderAuthenticatedRawSourceView(popup, path, content, contentType);
      return;
    }

    const { url } = await createRawFileObjectUrl(path);
    const revoke = () => URL.revokeObjectURL(url);

    if (popup && !popup.closed) {
      popup.location.replace(url);
      // `popup.location.replace` navigates the blank popup to the blob URL,
      // which would fire the popup's own `beforeunload`/`pagehide` before the
      // blob loads and revoke the URL too early. Poll `popup.closed` instead
      // so memory is reclaimed as soon as the user closes the popup, with
      // the timeout kept only as a safety net.
      const safetyTimer = window.setTimeout(revoke, 60_000);
      const pollId = window.setInterval(() => {
        if (popup.closed) {
          window.clearInterval(pollId);
          window.clearTimeout(safetyTimer);
          revoke();
        }
      }, 1_000);
      return;
    }
    // noopener fallback: no window reference, so rely on the timeout.
    window.open(url, "_blank", "noopener,noreferrer");
    window.setTimeout(revoke, 60_000);
  } catch (error) {
    if (popup && !popup.closed) {
      writePopupMessage(
        popup,
        "Raw file unavailable",
        '<span style="color: #991b1b;">Could not load the raw file.</span>'
      );
    }
    throw error;
  }
};
