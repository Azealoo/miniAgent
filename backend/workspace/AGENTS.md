# Agents Guide

This file defines your operational protocols. Follow these rules precisely.

---

## Skill Invocation Protocol

You have access to a list of skills in `SKILLS_SNAPSHOT.md` (included at the top of this system prompt). Each skill has a `name`, `description`, and `location` pointing to its `SKILL.md` file.

**When you decide to use a skill, you MUST follow these steps — no exceptions:**

1. **Read first**: Your very first action is to call `read_file` with the skill's `location` path.
2. **Study the instructions**: Read the SKILL.md content carefully — it contains step-by-step instructions and any required parameters.
3. **Execute**: Follow the instructions in the SKILL.md, using your core tools (`terminal`, `python_repl`, `fetch_url`, `read_file`, `write_file`, `search_knowledge_base`) as directed.

**DO NOT** guess how a skill works. **DO NOT** call a skill as if it were a Python function — there are no skill functions. The skill IS the Markdown file.

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

## Skills Creation Protocol
- Create a new skill using `write_file`: write to `skills/<name>/SKILL.md` with YAML frontmatter (name, description, category, etc.) and Markdown steps. Create the directory first with `terminal` if needed: `mkdir -p skills/<name>`.

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
