# Gold Path Trace: Tool-Using Chat

Capture type: route-level capture generated on 2026-03-18 by `backend/scripts/capture_chat_baseline.py`.

Raw capture artifact: `context/baselines/01-baseline-freeze/captures/tool-using-chat.json`

## Scenario

- Prompt triggers one tool call and then the model resumes text generation.
- This trace freezes the current segmented-assistant behavior around tool usage.

## Request

```http
POST /api/chat
Content-Type: application/json

{
  "message": "Read the current feature file and tell me its status.",
  "session_id": "<uuid>",
  "stream": true
}
```

## Captured SSE Sequence

```text
data: {"type":"token","content":"Let me check that."}
data: {"type":"tool_start","tool":"read_file","input":"context/current-feature.md"}
data: {"type":"tool_end","tool":"read_file","output":"# Current Feature"}
data: {"type":"new_response"}
data: {"type":"token","content":"The current feature is in progress."}
data: {"type":"done","content":"Let me check that. The current feature is in progress.","session_id":"<captured-uuid>"}
data: {"type":"title","session_id":"<captured-uuid>","title":"Captured Baseline Title"}
```

## Persistence Effects

1. User message is saved once `done` is processed.
2. The first assistant segment is saved as one assistant message.
3. The resumed assistant text after `new_response` is saved as a second assistant message.
4. The assistant segment that observed the tool receives a `tool_calls` array containing:

```json
[
  {
    "tool": "read_file",
    "input": "context/current-feature.md",
    "output": "# Current Feature"
  }
]
```

## Frontend State Effects

1. `tool_start` sets `pendingTool` on the current assistant message.
2. `tool_end` converts `pendingTool` into a completed `tool_calls` entry and clears `pendingTool`.
3. `new_response` closes the first assistant block and creates a fresh streaming assistant block.
4. Subsequent `token` events append to the new assistant block.
5. `done` clears streaming on the second block and refreshes the session list.

## Freeze Note

The backend currently does not include `run_id` in the SSE payload for `tool_start` or `tool_end`. The frontend therefore falls back to the tool name when matching tool events.
