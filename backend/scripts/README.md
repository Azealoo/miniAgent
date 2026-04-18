# backend/scripts

Operational scripts that drive the chat runtime outside the HTTP path. All
scripts assume `backend/` is on `sys.path` (they insert it themselves) and
expect to be run with the `miniAgent` conda env active.

## `capture_chat_baseline.py`

Exercises `/api/chat` and `/api/sessions` with a stubbed agent event stream
and writes captures to
`context/baselines/01-baseline-freeze/captures/`. Use it to freeze SSE
translation and session-persistence behavior in durable files before a
change.

```
python backend/scripts/capture_chat_baseline.py
```

## `replay_session.py`

Deterministically replays a recorded session through the current chat
runtime and reports a diff against the recording. Pairs with the
deterministic seed (`config.deterministic_seed`, see
`backend/tests/test_deterministic_seed.py`) to give you a regression signal
whenever `QueryEngine`, `TurnLedger`, session persistence, or SSE envelope
shaping changes.

```
python -m backend.scripts.replay_session <session_id>
```

### Inputs

- **Fixture.** The persisted session JSON at
  `backend/sessions/<session_id>.json`. No separate fixture format — the
  session file itself is the recording. If you need to produce one,
  `capture_chat_baseline.py` writes equivalent traces; any live session
  also works.
- **Archive batches** (`backend/sessions/archive/<session_id>_*.json`) are
  *not* replayed. Compressed history is summarized, not reproducible — use
  a session that has not been auto-compressed.

### What "live run" means

LLM calls are never issued. Provider APIs are not deterministic on seed
alone, so replay drives `QueryEngine.stream_turn_sse` with
`agent_manager.astream` stubbed to emit the internal event sequence
reconstructed from the recorded assistant blocks. That is the regression
signal the acceptance criteria actually need: does today's runtime produce
the same persisted session and SSE stream given yesterday's internal
events?

Auto-compaction and turn-boundary compaction are also stubbed out during
replay so they don't perturb the session shape.

### Outputs

Reports are written under
`backend/sessions/replays/<session_id>/<UTC timestamp>/`:

| File | Contents |
| --- | --- |
| `recorded.normalized.json` | Recorded session with volatile fields stripped (timestamps, `schema_version`, `title`, `deterministic` stamp, `request_id`s/`run_id`s remapped to ordinals) |
| `replayed.normalized.json` | Replayed session under the same normalization |
| `replayed.raw.json` | Replayed session as written to disk (pre-normalization) |
| `sse.jsonl` | One JSON line per SSE payload per turn: `{turn, type, ...}` |
| `diff.json` | Structural diff list (empty on match). Each entry has `path`, `kind`, and the differing values. |
| stdout | Human summary: turn count, diff count, first few diff paths. |

### Exit codes

- `0` — replay matched (or `--allow-diff` passed).
- `1` — diff detected. Use this to gate CI.
- `2` — input error (missing session file, empty session, unhandled exception).

### Flags

| Flag | Default | Purpose |
| --- | --- | --- |
| `--archive-dir` | `backend/sessions` | Directory holding `<session_id>.json` |
| `--output-dir` | `backend/sessions/replays` | Where to write the report directory |
| `--allow-diff` | off | Always exit `0`; the report is still written. |

### Scope and caveats

- Token granularity is not preserved: each recorded text block replays as
  a single `token` event, not the original character stream. The final
  persisted text is identical, which is what the diff compares.
- Fields compared: every top-level session field except
  `created_at`/`updated_at`/`schema_version`/`title`/`deterministic`, plus
  every message field. `request_id`s and `run_id`s are remapped to ordinals
  so new UUIDs do not register as diffs.
- Plan and verification blocks are re-derived from `plan_agent` /
  `verification_agent` `tool_end` events by `QueryEngine`; the replay
  emits the `tool_end` only and lets the runtime re-produce the helper
  event.
- Repair retries work when the recorded session contains both segments
  (the second astream call consumes the second recorded segment).
