# Chat transcript — accessibility live regions

Tracks the aria-live wiring that lets screen readers announce new tokens as
assistant turns stream in (issue #104).

## What is wired up

- `ChatPanel.tsx` — the scrolling transcript container carries
  `role="log"` with `aria-live="polite"`, `aria-relevant="additions text"`,
  `aria-atomic="false"`, and `aria-label="Conversation transcript"`. The
  whole transcript acts as a polite log region so screen readers announce
  new content as turns are appended.
- `ChatMessage.tsx` — the assistant `<article aria-label="Assistant
  response">` sets `aria-live="polite"` plus `aria-busy={isStreaming}`.
  The user-prompt branch returns before this markup, so user messages are
  not announced as live content and do not echo back.
- `TurnActivityFeed.tsx` — already uses `role="status"` +
  `aria-live="polite"` while a turn is live, so planning/tool activity is
  announced alongside the streaming prose.

`aria-atomic="false"` is intentional — without it, screen readers would
re-read the entire transcript each time a token lands.

## Verification

### Automated axe scan

Run the app locally (`./start-backend.sh` + `./start-frontend.sh`),
open the chat route, and scan with either
[axe DevTools](https://www.deque.com/axe/devtools/) or
`@axe-core/react`. Target: **no critical issues** on the chat surface.
Send at least one message so the transcript contains a user prompt plus a
streaming assistant response while the scan runs.

### Manual screen-reader smoke test

Repeat once on NVDA (Windows) or VoiceOver (macOS):

1. Load the chat route and focus the message input.
2. Send a prompt that triggers a streaming response.
3. Confirm the reader announces assistant tokens as they arrive without
   re-reading the prior transcript.
4. Confirm the user prompt is not re-announced after submission.
5. Confirm planning / tool activity ("Plan created", "Tool started", …)
   is announced while the turn is live.

Capture the reader name/version and a one-line summary of the observed
behavior in the PR description.
