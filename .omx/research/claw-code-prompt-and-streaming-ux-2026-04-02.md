# Claw Code Prompt And Streaming UX Note

Date: 2026-04-02
Analyst: Codex
Source repo: https://github.com/Azealoo/claw-code
Source commit inspected: `7030d26e7a9ca7fef5c74f463eede01a59403847`

## Question

How does `claw-code` handle prompt entry and response animation, and what is the closest browser-native mapping for BioAPEX?

## Findings

### Prompt entry

- `rust/crates/claw-cli/src/input.rs` implements a custom line editor on top of `crossterm`.
- The prompt surface is terminal-first:
  - raw key event handling
  - history recall
  - slash-command completion
  - optional Vim-style modes (`INSERT`, `NORMAL`, `VISUAL`, `COMMAND`)
  - fallback stdin mode outside a TTY

### Streaming output

- `rust/crates/claw-cli/src/main.rs` starts each turn with a spinner (`🦀 Thinking...`) and keeps a visible progress affordance until the turn resolves.
- The same file accumulates streaming text deltas in `MarkdownStreamState`.
- `rust/crates/claw-cli/src/render.rs` only flushes rendered markdown at "safe" boundaries:
  - blank lines between paragraphs
  - closed fenced code blocks
- Tool calls are printed as their own transcript events once the full tool input is known.

### UX implication

- The perceived animation is not a browser-style typewriter effect.
- It is:
  1. a persistent live status line
  2. compact tool/progress events
  3. incremental transcript reveal in completed markdown chunks

## BioAPEX Mapping

- Keep the browser UI; do not literal-clone the terminal.
- Borrow the interaction contract:
  - prompt-like composer with slash discovery
  - persistent live turn header while streaming
  - safe-boundary markdown reveal for assistant output
  - detailed truth preserved in inspector/session blocks
