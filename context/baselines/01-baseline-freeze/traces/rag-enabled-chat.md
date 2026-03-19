# Gold Path Trace: RAG-Enabled Chat

Capture type: route-level capture generated on 2026-03-18 by `backend/scripts/capture_chat_baseline.py`.

Raw capture artifact: `context/baselines/01-baseline-freeze/captures/rag-enabled-chat.json`

## Scenario

- `rag_mode` is enabled.
- Memory retrieval returns at least one hit.
- The retrieval payload is shown to the frontend before assistant text begins streaming.

## Preconditions

- Current repo config already sets `backend/config.json` to `{"rag_mode": true, ...}`.
- `AgentManager.memory_indexer.retrieve(message)` returns one or more results.

## Request

```http
POST /api/chat
Content-Type: application/json

{
  "message": "What do you remember about my main project?",
  "session_id": "<uuid>",
  "stream": true
}
```

## Captured SSE Sequence

```text
data: {"type":"retrieval","query":"What do you remember about my main project?","results":[{"text":"...","score":0.91,"source":"memory/MEMORY.md"}]}
data: {"type":"token","content":"Based on memory, your main project is Perturb-seq on T cells."}
data: {"type":"done","content":"Based on memory, your main project is Perturb-seq on T cells.","session_id":"<captured-uuid>"}
data: {"type":"title","session_id":"<captured-uuid>","title":"Captured Baseline Title"}
```

## Backend Effects

1. The captured route emitted `retrieval` before any assistant token.
2. The retrieval payload contained one result from `memory/MEMORY.md`.
3. The route then streamed assistant text and finished with `done` and `title`.

## Frontend State Effects

1. `onRetrieval` attaches the retrieval results to the current streaming assistant message.
2. Retrieval cards are therefore available before or alongside the first streamed assistant token.
3. Remaining handling is the same as the normal chat flow unless tools are also used.

## Freeze Note

If `rag_mode` is enabled but retrieval returns no hits, this trace collapses to the normal chat trace and no `retrieval` SSE event is sent.
