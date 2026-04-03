# Claude Code Src Response UX Notes

Date: 2026-04-02
Analyst: Codex
Source repo: https://github.com/ponponon/claude_code_src
Source commit inspected: `9680ff29a8360e15307306a5f44b5513bfa2dc38`

## Question

What should BioAPEX copy from `claude_code_src` if the goal is to make streamed assistant responses feel the same in the browser?

## Executive Summary

BioAPEX should copy the response grammar, not the literal terminal container.

The strongest reusable patterns in `claude_code_src` are:

1. assistant turns sit in a flat transcript instead of bubble cards
2. live work is shown with tiny status signals instead of heavy loading chrome
3. tool and thinking rows read like process lines, not mini panels
4. the final answer settles into a quiet transcript once the turn completes

That means the browser version should prefer:

- slim speaker markers instead of avatar chips
- a subtle live rail for thinking and tool activity
- small blinking dots and cursor timing for motion
- low-chrome status labels
- dense but readable assistant prose

## Source Evidence

Relevant files inspected:

- `README.md`
- `src/hooks/useBlink.ts`
- `src/components/ToolUseLoader.tsx`
- `src/components/Spinner.tsx`
- `src/components/VirtualMessageList.tsx`
- `src/components/messages/AssistantTextMessage.tsx`
- `src/components/messages/AssistantThinkingMessage.tsx`
- `src/components/messages/AssistantToolUseMessage.tsx`

## What The Reference Actually Does

### 1. Assistant text is almost unframed

The assistant transcript is rendered as plain rows with a tiny leading marker rather than a boxed message bubble. The visual emphasis stays on text, not chrome.

### 2. Thinking state is compact and dim

Thinking is shown as a small status line with restrained styling. It feels active without competing with the answer.

### 3. Tool activity is line-oriented

Tool use is presented as short rows with a tiny loader or marker, a tool name, and a terse inline status. It does not use large icons or card stacks.

### 4. Motion is minimal and rhythmic

The most noticeable motion is the synchronized blink cadence from `useBlink.ts` plus small loading markers. There is very little ornamental animation.

### 5. Scroll stability matters

`VirtualMessageList.tsx` and the surrounding message rendering avoid unnecessary layout jump while a response is still growing.

## What BioAPEX Should Copy

### Safe To Copy Directly

- flat transcript composition
- tiny leading assistant marker
- compact `Thinking` lead-in
- minimal tool/status rows
- fast blink timing around 600ms
- quiet final transcript after streaming

### Should Be Adapted, Not Cloned

- terminal aesthetics
- literal monochrome terminal palette
- terminal-only spacing assumptions
- purely text-only rows when BioAPEX needs warning/compliance semantics

## Implementation Direction For BioAPEX

BioAPEX should keep its scientific palette and richer compliance truth, but render them with the lighter interaction contract above:

- `ChatMessage.tsx` should use transcript markers instead of avatars
- `TurnActivityFeed.tsx` should become a slim live rail
- `ThoughtChain.tsx` should compress tool results into process lines
- `globals.css` should supply blink timing and subtle transcript entrance motion

## Decision

Copy the response feel from `claude_code_src`, not the literal terminal UI.

The browser version should make users think:

"the assistant is working in a live transcript"

not:

"the assistant opened a stack of status cards under the answer"
