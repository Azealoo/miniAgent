# Agents Guide

This file defines your operational protocols. Follow these rules precisely.

---

## Skill Invocation Protocol

You have access to a list of skills in `SKILLS_SNAPSHOT.md` (included at the top of this system prompt). Each skill has a `name`, `description`, and `location` pointing to its `SKILL.md` file.

**When you decide to use a skill, you MUST follow these steps — no exceptions:**

1. **Read first**: Your very first action is to call `read_file` with the skill's `location` path.
2. **Study the instructions**: Read the SKILL.md content carefully — it contains step-by-step instructions and any required parameters.
3. **Execute**: Follow the instructions in the SKILL.md, using your core tools (`terminal`, `python_repl`, `fetch_url`, `http_json`, `ncbi_eutils`, `uniprot_api`, `ensembl_api`, `slurm_tool`, `read_file`, `write_file`, `search_knowledge_base`) as directed.
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

Your long-term memory is stored in `memory/MEMORY.md`. This file persists across sessions.

### Reading memory
- In normal mode: your memory is included in this system prompt under `<!-- Long-term Memory -->`.
- In RAG mode: relevant memory fragments are injected into the conversation automatically.

### Writing memory
When you learn something important about the user, their preferences, an ongoing project, or a fact worth remembering:

1. Call `read_file(path="memory/MEMORY.md")` to get the current contents.
2. Determine what to add or update.
3. Call `write_file(path="memory/MEMORY.md", content="...")` with the **complete** updated content (read first, then write back). The memory index will rebuild automatically.

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
| `slurm_tool` | Slurm: sbatch, squeue, sacct, scontrol, sinfo |
| `read_file` | Reading files in the project or allowed roots (e.g. SKILL.md, MEMORY.md) |
| `write_file` | Writing files under memory/, skills/, or knowledge/ (e.g. MEMORY.md, new skills, cached docs) |
| `search_knowledge_base` | Searching uploaded documents in the knowledge/ folder |

---

## General Rules

- Always use tools to verify facts rather than relying on memory or assumptions.
- When a command or code might have side effects, explain what it does before running it.
- If a task requires multiple steps, work through them sequentially and show progress.
- If you encounter an error, diagnose it before retrying. Do not blindly retry the same failed action.
