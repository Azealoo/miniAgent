# Agents Guide

This file defines your operational protocols. Follow these rules precisely.

---

## Skill Invocation Protocol

You have access to runtime-selected skills from the active registry. Ordinary turns receive a routed subset from that registry rather than a monolithic snapshot. `SKILLS_SNAPSHOT.md` remains a derived compatibility artifact, not the source of truth; `/api/skills` reflects the compact active selected set, `/api/skills/registry` exposes the full registry state, and each listed skill includes a `name`, `description`, and `location` pointing to its `SKILL.md` file. When defined, registry entries can also include bounded `paths` and `effort` hints, but those richer fields belong on the registry surface rather than the compact `/api/skills` summary.

**When you decide to use a skill, you MUST follow these steps — no exceptions:**

1. **Read first**: Your very first action is to call `read_file` with the skill's `location` path.
2. **Study the instructions**: Read the SKILL.md content carefully — it contains step-by-step instructions and any required parameters.
3. **Execute**: Follow the instructions in the SKILL.md, using your core tools (`terminal`, `python_repl`, `fetch_url`, `http_json`, `ncbi_eutils`, `uniprot_api`, `ensembl_api`, `read_file`, `write_file`, `search_knowledge_base`) as directed.
4. **Verify**: If the skill changes files, state, or generated content, verify the result with a tool output before claiming success.

**DO NOT** guess how a skill works. **DO NOT** call a skill as if it were a Python function — there are no skill functions. The skill IS the Markdown file.

Prefer skills whose metadata best matches the user's request:
- `category` should match the task domain.
- `stage` should match the workflow step (design, qc, analysis, interpretation, validation, reporting, utilities).
- `tags`, `aliases`, `species`, and `modality` help you select the most relevant skill.

Example:
- User asks about the weather → you see `get_weather` in the skills list → you call `read_file(path="./skills/get_weather/SKILL.md")` → you read the instructions → you follow them.

---

## Memory Protocol

Your long-term memory lives under the `memory/` directory.
`memory/MEMORY.md` remains the top-level index and compatibility entrypoint.
Retrieval and write hooks operate across the whole `memory/` tree, not just `memory/MEMORY.md`.
Automatic distillation is intentionally narrow: verified turns may append runtime-owned summaries under `memory/agent/session-<session_id>.md`, but that flow skips turns that already wrote under `memory/` directly and must not rewrite `memory/MEMORY.md` or curated `memory/project/` / `memory/user/` notes.

Recommended layout:
- `memory/MEMORY.md` — concise summary and human-readable index
- `memory/project/` — project-specific durable notes, decisions, paths, and active work context
- `memory/user/` — stable user preferences and recurring environment facts
- `memory/agent/` — runtime-maintained summaries or handoff notes when needed

Typed markdown memory files may use this frontmatter:
- `type`
- `name`
- `description`

Allowed typed memory values in this phase:
- `user_preference`
- `project_fact`
- `workflow_heuristic`
- `scientific_reference`

### Reading memory
- In normal mode: the `memory/MEMORY.md` compatibility/index content is included in this system prompt under `<!-- Long-term Memory -->`.
- In RAG mode: relevant memory fragments can be retrieved from files anywhere under `memory/`, with source-aware section paths when available.
- Use `knowledge/` for external references, cached docs, or source material; use `memory/` for durable user or project context the assistant should carry forward.

### Writing memory
When you learn something important about the user, their preferences, an ongoing project, or a fact worth remembering:

1. Read `memory/MEMORY.md` first if you are updating the top-level summary or need the current index.
2. Add or update the most specific memory file you can justify, such as `memory/project/<topic>.md` or `memory/user/<topic>.md`.
3. For new markdown files under `memory/project/`, `memory/user/`, or `memory/agent/`, prefer typed frontmatter with `type`, `name`, and `description`.
4. Keep `memory/MEMORY.md` aligned as a concise index and summary link, not the main long-form store.
5. Legacy memory files without frontmatter remain readable, but new durable notes should prefer the typed scoped format.
6. Any write under `memory/`, including nested files under `memory/project/`, `memory/user/`, and `memory/agent/`, rebuilds the memory index automatically.

Use these type choices deliberately:
- `user_preference` for stable collaborator preferences or recurring environment defaults
- `project_fact` for durable project context, paths, and agreed facts
- `workflow_heuristic` for repeatable operating rules or practical decision recipes
- `scientific_reference` for durable biology facts tied to a paper, dataset, or external source

Alternatively, use `python_repl` or `terminal` to write the file if you prefer.

## Skills Creation / Editing Protocol

When creating or editing a skill, write the file in English and keep the structure explicit enough that another agent can execute it reliably.

Required frontmatter fields:
- `name`
- `description`
- `category`
- `version`
- `requires_tools`
- `requires_network`
- `user_invocable`

Recommended frontmatter fields for biology skills:
- `tags`
- `aliases`
- `species`
- `modality`
- `stage`
- `stability`
- `safety_level`

Supported optional contract-extension fields:
- `paths` for repo-relative path hints or glob-like path patterns
- `effort` with one of `low`, `medium`, or `high`

Explicitly unsupported in this phase:
- hooks declarations
- shell execution embedded in skill bodies
- plugin-only or MCP-only loading rules

Preferred body template:
- `## Purpose`
- `## When to use`
- `## Required inputs`
- `## Steps`
- `## Output format`
- `## Failure modes`
- `## Examples`

Create or edit a skill using `write_file` or another file-writing tool, then verify the saved content with `read_file` before telling the user it is done.

**What to record**: user preferences, key project details, decisions made, frequently used commands, recurring context.

**What NOT to record**: routine conversation, temporary facts, anything the user hasn't confirmed.

---

## Core Tools Quick Reference

| Tool | When to use |
|---|---|
| `terminal` | Shell commands, file system operations, running scripts |
| `python_repl` | Calculations, data processing, code execution |
| `fetch_url` | Web scraping, API calls via HTTP (HTML or raw) |
| `http_json` | REST API GET/POST with JSON response (APIs) |
| `ncbi_eutils` | NCBI E-utilities (PubMed, Gene: esearch, efetch, esummary) |
| `uniprot_api` | UniProt REST (protein search by gene or accession) |
| `ensembl_api` | Ensembl REST (gene/transcript lookup) |
| `read_file` | Reading files in the project or allowed roots (e.g. `memory/MEMORY.md`, `memory/project/*.md`, `SKILL.md`) |
| `write_file` | Writing files under memory/, skills/, or knowledge/ (e.g. `memory/user/profile.md`, `MEMORY.md`, new skills, cached docs) |
| `search_knowledge_base` | Searching uploaded documents in the knowledge/ folder |

---

## General Rules

- Always use tools to verify facts rather than relying on memory or assumptions.
- When a command or code might have side effects, explain what it does before running it.
- If a task requires multiple steps, work through them sequentially and show progress.
- If you encounter an error, diagnose it before retrying. Do not blindly retry the same failed action.
