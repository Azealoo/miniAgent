---
name: results_summarizer
description: Parse common pipeline log/output and summarize metrics and status.
category: bio/hpc
version: 1.0
requires_tools: [read_file, python_repl]
requires_network: false
user_invocable: true
---

# Results Summarizer

## When to use
User has a log file or pipeline output and wants a short summary of metrics, errors, or completion status.

## Inputs
- **file_path**: Path to log or output file (under project).

## Steps

1. **Read**: Use `read_file` to load the file (or first/last N lines if very large).

2. **Parse**: Look for common patterns:
   - "Error", "Exception", "failed"
   - Completion messages ("Done", "Saved", "Written")
   - Metrics (cells, genes, runtime, memory)
   - Slurm/Job output (exit code, time used)

3. **Summarize**: State: success/failure, key metrics if found, any errors, and suggested next step if failed.

## Output format
- Status: Success / Failure / Partial
- Key metrics (if any)
- Errors or warnings (if any)
- Suggested next step
