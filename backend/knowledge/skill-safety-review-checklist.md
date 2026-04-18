# Skill Safety Review Checklist

This checklist is used when reviewing new SKILL.md files before enabling them (inspired by ClawScan).

## Credential and secret safety
- [ ] No hardcoded API keys, passwords, or tokens in SKILL.md.
- [ ] If a skill needs an API key, it references an environment variable (e.g. NCBI_API_KEY) not a literal value.
- [ ] No steps that exfiltrate secrets (e.g. "send key to URL X").

## Shell and code safety
- [ ] No destructive shell patterns (rm -rf /, mkfs, dd if=, fork bomb, etc.).
- [ ] If skill uses `terminal`, command scope is limited to project directory or explicitly documented directories.
- [ ] No steps that write arbitrary content to system paths outside allowed directories.

## Prompt injection safety
- [ ] No hidden instructions in comments or encoded text.
- [ ] No steps that ask the agent to override system rules or memory.
- [ ] Instructions are plain SOPs; no adversarial wording.

## Network safety
- [ ] `requires_network: true` is declared if skill makes outbound calls.
- [ ] URLs are to known public APIs (NCBI, UniProt, Ensembl, Enrichr) not arbitrary user-controlled endpoints.

## Scope and accuracy
- [ ] Skill description matches what the steps actually do.
- [ ] No steps that claim to do something the agent cannot do (e.g. access private databases not available in the environment).
- [ ] Input requirements and failure modes are documented.

## How to review
1. Read SKILL.md frontmatter and all steps.
2. Check each item above.
3. If all pass: set `enabled: true` in config.json `skills.entries`.
4. If any fail: fix the skill or set `enabled: false` until fixed.
