---
name: count_lines
description: Count the number of lines in a given file
version: 1.0
category: general/utilities
requires_tools: [read_file, python_repl]
requires_network: false
user_invocable: true
tags: [file, line-count, utility]
aliases: [line_counter]
stage: utilities
stability: stable
safety_level: low
---

# Count Lines Skill

## Purpose

Count the number of lines in a specified file that the agent is allowed to read.

## When to use

Use this skill when the user asks for the line count of a project file or wants a quick sanity check on file length.

## Required inputs

- **file_path**: The path to the file to count lines in, relative to the project root or an allowed read root.

## Steps

1. **Validate input**: If no file path is provided, ask the user which file to inspect.
2. **Read the file**: Use `read_file` to fetch the file content. Do not guess or fabricate the count.
3. **Count lines**: Use `python_repl` or a reliable internal count based on newline splitting.
4. **Return the result**: Report the line count and echo the file path you counted.

## Output format

- `File`: relative path
- `Line count`: integer
- `Note`: mention that empty lines are included

## Failure modes

- Missing file path: ask for the path.
- Read blocked or file missing: explain that the file could not be accessed.
- Binary or unsupported file: explain that line counting only applies to readable text content.

## Examples

User: "Count lines in `knowledge/golden-tasks.md`."
→ Read the file, count the lines, and report the total.