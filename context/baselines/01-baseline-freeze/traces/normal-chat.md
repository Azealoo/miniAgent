# Gold Path Trace: Normal Chat

Capture type: route-level capture generated on 2026-03-18 by `backend/scripts/capture_chat_baseline.py`.

Raw capture artifact: `context/baselines/01-baseline-freeze/captures/normal-chat.json`

## Scenario

- Prompt does not trigger tool use.
- No retrieval event is emitted.
- This may happen with RAG disabled, or with RAG enabled but no retrieval hits.

## Request

```http
POST /api/chat
Content-Type: application/json

{
  "message": "Summarize the current feature status.",
  "session_id": "<uuid>",
  "stream": true
}
```

## Captured SSE Sequence

```text
data: {"type":"token","content":"All "}
data: {"type":"token","content":"good."}
data: {"type":"done","content":"All good.","session_id":"<captured-uuid>"}
data: {"type":"title","session_id":"<captured-uuid>","title":"Captured Baseline Title"}
```

## Persistence Effects

1. User message is not saved at request receipt.
2. User message is saved when `done` is handled.
3. One assistant message is saved with content `All good.` and no `tool_calls`.
4. The captured first-turn response emitted a `title` event after `done`.

## Frontend State Effects

1. `sendMessage()` appends the local user message and a blank assistant placeholder immediately.
2. Each `token` appends text to the current assistant placeholder.
3. `done` marks the assistant message as no longer streaming and refreshes the session list.
4. `title` updates the matching session list entry if it arrives before timeout or disconnect.
