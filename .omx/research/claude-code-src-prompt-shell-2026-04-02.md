# Claude Code Src Prompt Shell Notes

Date: 2026-04-02
Analyst: Codex
Source repo: https://github.com/ponponon/claude_code_src
Source commit inspected: `9680ff29a8360e15307306a5f44b5513bfa2dc38`

## Question

What should BioAPEX copy from `claude_code_src` if the goal is to make the browser prompt box feel like the same product grammar?

## Executive Summary

BioAPEX should copy the prompt grammar, not the literal terminal control surface.

The strongest reusable patterns in `claude_code_src` are:

1. one quiet prompt shell instead of stacked nested cards
2. inline placeholder and command-hint behavior inside the text flow
3. command-first affordances where the text label matters more than icon chrome
4. minimal motion that comes mostly from cursor activity instead of animated panels

## Source Evidence

Relevant files inspected:

- `src/components/TextInput.tsx`
- `src/components/BaseTextInput.tsx`
- `src/components/PromptInput/PromptInput.tsx`

## What The Reference Actually Does

### 1. The input line is the main event

`BaseTextInput.tsx` renders the placeholder and command argument hint inline with the typed value. The prompt does not split these cues into separate boxed help cards.

### 2. Motion stays focused on the cursor

`TextInput.tsx` treats cursor behavior as the strongest live signal. Even when it adds richer states like voice input, the animation budget stays small and local to the active prompt.

### 3. Surrounding controls orbit the prompt instead of nesting inside it

`PromptInput.tsx` wires many pickers and footer controls around a single core prompt surface. The shell stays text-first even when the CLI exposes many capabilities.

## What BioAPEX Should Copy

- a flatter single-shell composer
- monospace prompt cues and a visible prompt sigil
- inline command labels instead of icon-heavy quick-action pills
- helper rails for command matching and analysis-mode selection
- restrained footer controls and cursor-like live state

## Should Not Be Copied Literally

- the terminal-specific footer complexity
- CLI-only keybinding density
- monochrome terminal styling
- prompt behavior that depends on terminal focus or Ink cursor APIs

## Decision

Adapt the composer to browser constraints, but keep the interaction feeling of a live command line.
