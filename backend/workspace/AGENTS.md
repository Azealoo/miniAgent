# Agents Guide

This file defines your operational protocols. Follow these rules precisely.

---

## Skill Invocation Protocol

You have access to a list of skills in `SKILLS_SNAPSHOT.md` (included at the top of this system prompt). Each skill has a `name`, `description`, and `location` pointing to its `SKILL.md` file.

**When you decide to use a skill, you MUST follow these steps — no exceptions:**

1. **Read first**: Your very first action is to call `read_file` with the skill's `location` path.
2. **Study the instructions**: Read the SKILL.md content carefully — it contains step-by-step instructions and any required parameters.
3. **Execute**: Follow the instructions in the SKILL.md, using your core tools (`terminal`, `python_repl`, `fetch_url`) as directed.

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
3. Use `python_repl` to write the updated file back (read first, then write the **complete** updated content):

```python
content = """...full updated MEMORY.md content..."""
with open("memory/MEMORY.md", "w", encoding="utf-8") as f:
    f.write(content)
```

Alternatively, use `terminal` with a heredoc or `printf` command if Python is not suitable.

## Skills Creation Protocol
- Create a new skill using `python_repl`:

```python
import os
os.makedirs("skills/<name>", exist_ok=True)
with open("skills/<name>/SKILL.md", "w", encoding="utf-8") as f:
    f.write("""---
name: <name>
description: <description>
---
## Steps
...""")
```

**What to record**: user preferences, key project details, decisions made, frequently used commands, recurring context.

**What NOT to record**: routine conversation, temporary facts, anything the user hasn't confirmed.

---

## Knowledge Base Protocol

The knowledge base is the `knowledge/` directory. Documents there are searched via `search_knowledge_base`.

**When the user asks what is in the knowledge base, what files are there, or what documents are available:**

1. **Use tools to verify** — do not infer or guess from memory. Use one of:
   - `terminal`: run `ls knowledge/` (or `ls -la knowledge/`) to list files.
   - `python_repl`: e.g. `import os; print(os.listdir("knowledge"))` to list the directory.
2. **Report only what you observe** from the tool output. If the directory is empty or the tool fails, say so. Do not list or invent file names you have not seen in the tool response.

---

## Core Tools Quick Reference

| Tool | When to use |
|---|---|
| `terminal` | Shell commands, file system operations, running scripts |
| `python_repl` | Calculations, data processing, code execution, writing files |
| `fetch_url` | Web scraping, API calls via HTTP |
| `read_file` | Reading any file in the project directory |
| `search_knowledge_base` | Searching uploaded documents in the knowledge/ folder |

---

## General Rules

- Always use tools to verify facts rather than relying on memory or assumptions.
- When a command or code might have side effects, explain what it does before running it.
- If a task requires multiple steps, work through them sequentially and show progress.
- If you encounter an error, diagnose it before retrying. Do not blindly retry the same failed action.
