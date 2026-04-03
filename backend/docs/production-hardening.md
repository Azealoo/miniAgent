# Production Hardening Runbook

## Scope

This runbook defines the minimum deployment posture for BioAPEX once it moves beyond local development.

## Runtime policy knobs

BioAPEX now supports additive production-hardening controls in `backend/config.json`:

```json
{
  "production_hardening": {
    "tools": {
      "terminal_enabled": true,
      "python_repl_enabled": true,
      "slurm_enabled": true,
      "slurm_legacy_commands_enabled": true,
      "write_file_enabled": true
    },
    "api": {
      "files_write_enabled": true,
      "allow_loopback_without_auth": true,
      "trust_forwarded_loopback_headers": false,
      "inspection_bearer_token_env_var": null,
      "execution_bearer_token_env_var": null,
      "admin_bearer_token_env_var": null,
      "cors_allowed_origins": [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001"
      ]
    }
  }
}
```

High-risk routes default to direct loopback access and can be opened to trusted remote clients only by configuring bearer-token environment-variable names plus explicit CORS origins.

## Least-privilege expectations

- Disable `tools.terminal_enabled` and `tools.python_repl_enabled` for any shared or hosted deployment unless operators explicitly need live shell or REPL access.
- Disable `tools.slurm_legacy_commands_enabled` before enabling shared Slurm access; keep only structured submit/status flows where possible.
- Disable `api.files_write_enabled` when BioAPEX should be read-only or when file edits must go through a reviewed workflow.
- Treat credential-like files as unreadable and unwritable through BioAPEX surfaces. The backend blocks `.env*`, certificate/private-key files, and SSH private keys across the file API, file tools, terminal tool, and Python REPL guardrails.

## Authentication and authorization requirements

- Do not expose `/api/chat`, `/api/files` writes, or session mutation routes to unauthenticated traffic.
- Local development may rely on host-level access controls, but only on loopback or other trusted interfaces.
- The current backend enforces loopback-or-bearer access for read-only inspection routes such as session reads/lists, file reads, and skills listing.
- The current backend also enforces loopback-or-bearer access for `/api/chat`, `/api/files` writes, and session create/rename/delete/title routes.
- Use `production_hardening.api.inspection_bearer_token_env_var` for read-only remote inspection traffic, `production_hardening.api.execution_bearer_token_env_var` for execution-capable user traffic, and `production_hardening.api.admin_bearer_token_env_var` for operator/admin routes.
- Remote admin routes do not implicitly fall back to the execution token; if `admin_bearer_token_env_var` is unset, remote admin access remains disabled.
- Remote inspection routes do not implicitly fall back to execution or admin tokens; if `inspection_bearer_token_env_var` is unset, remote read-only inspection remains disabled.
- Keep `allow_loopback_without_auth` enabled only for trusted local development; disable it for shared or hosted deployments.
- Forwarded-client headers such as `Forwarded`, `X-Forwarded-For`, or `X-Real-IP` disable unauthenticated loopback trust by default, even when the immediate socket peer is loopback. Set `trust_forwarded_loopback_headers` only when you intentionally trust a same-host proxy chain and understand that this restores loopback bypass for proxied traffic.
- HPC deployments should sit behind cluster or campus authentication and should separate analyst access from operator/admin access.
- Hosted deployments should require authenticated identity, TLS, request logging, rate limiting, and role separation for read-only inspection, execution, and admin/configuration work.

## Secrets handling

- Keep secrets in environment variables or an external secret manager. Do not store raw credentials in `backend/config.json`.
- Store only bearer-token environment-variable names in `backend/config.json`; keep the actual token values in environment injection or a secret manager.
- Do not commit `.env`, private-key, certificate, or token-bearing files to the repository or artifacts tree.
- The Python REPL guard blocks secret-path reads through `open(...)`, imported `builtins.open(...)`, `sys.modules[...]` lookups for wrapped runtime modules, native low-level modules such as `posix.open(...)` and `_io.FileIO(...)`, and it blocks native FFI modules such as `ctypes`, `_ctypes`, and `cffi` that would otherwise bypass guarded Python file entry points; `os.open(...)`, `io.open(...)`, `codecs.open(...)`, and `pathlib.Path(...).read_text()/read_bytes()/open()` remain guarded as well, including variable-bound `Path` objects that persist across REPL calls. Child-process execution from the REPL is blocked as well, including `subprocess` helpers, `asyncio` subprocess helpers, `pty.spawn(...)`, and `os.system`/`os.popen`/`os.posix_spawn*`/`os.exec*`/`os.spawn*`, because spawned processes would bypass the guarded Python file APIs. The REPL now temporarily patches the live import/module table during execution so newly imported launcher modules inherit those blocked process APIs instead of seeing the host interpreter's real ones.
- The terminal guard blocks literal secret-path references even when they appear inside interpreter subprocess command strings, and it checks shell-expanded glob/brace/env-var path matches before execution rather than only direct `cat`/`grep`-style reads. That precheck still allows simple named-variable expansion such as `$HOME` and static shell-local assignments like `secret=.env.local; cat $secret`, but it now refuses dynamic shell scripting features that can mutate runtime state after the pre-execution checks have already finished: braced parameter expansion, positional or special parameters, `set --` / `shift`, control-flow constructs like `for` / `while` / `case`, `declare` / `typeset` / `local` / `readonly`, `printf -v`, shell array assignment, shell command substitution like `` `...` `` and `$()`, shell process substitution like `<(...)` / `>(...)`, stdin-driven argument expansion through `xargs`, `find -exec` / `-ok` nested execution, shell `read` / `mapfile` / `readarray` flows, shell sourcing via `source` or `.`, nested shell interpreter launches such as `sh -c ...` / `bash -c ...` or `sh script.sh`, variable-hidden child shells such as `"$SHELL" -c ...`, nested Python interpreter execution beyond metadata-only help/version flags, other arbitrary-code interpreters such as `perl`, `awk`, `ruby`, `node`, `php`, `lua`, `tclsh`, `Rscript`, and `julia`, plus file-driven or wrapper launchers such as `make`, `just`, `ninja`, `tox`, `nox`, `npm run`, `pnpm run`, `yarn run`, `bun run`, `poetry run`, `pipenv run`, and `uv run`, because those entry points can hide nested execution in project files or wrapper subcommands that cannot be inspected safely before execution.
- These terminal guardrails are defense-in-depth, not a full shell sandbox. Shared or hosted deployments should still disable the terminal tool instead of relying on exhaustive shell-language coverage.
- Rotate credentials if a secret-like file appears in a writable BioAPEX path or if an audit review finds unsafe secret exposure.
- Review audit and session retention before production use so secret values are not persisted in logs or chat history.

## Backup and restore expectations

The minimum backup set is:

- `backend/sessions/`
- `backend/artifacts/`
- `backend/storage/artifact_registry/registry.json`
- `backend/storage/audit/`
- `backend/storage/compliance_audit/`
- `backend/config.json`

Restore procedure:

1. Stop active writers or take the instance out of service.
2. Restore `config.json`, sessions, artifacts, registry, and audit directories from the same backup point.
3. Rebuild derived indexes during service startup if the restored registry or memory index is missing or stale.
4. Verify session listing, artifact reads, registry counts, and audit query responses before reopening write or execution paths.

## Failure-recovery expectations

- Interrupted workflow runs should be recovered from the durable run directory and `run.json`, not from chat memory.
- Partial exports should remain non-discoverable or be regenerated before they are treated as valid outputs.
- Transient external API failures should be retried only for idempotent reads and should remain visible in audit or run artifacts.
- After filesystem restoration, rebuild derived indexes such as the artifact registry before declaring recovery complete.

## Deployment checklist

### Local

- Use loopback-only binding when possible.
- Keep config and storage paths on a trusted filesystem.
- Verify backup coverage before enabling real project data.

### HPC

- Front the service with cluster authentication or a protected reverse proxy.
- Disable terminal and Python REPL unless the cluster security review explicitly approves them.
- Keep Slurm access limited to structured flows whenever possible.
- Store secrets in scheduler-approved secret locations or environment injection mechanisms.

### Hosted

- Require authenticated identity, TLS, and role-based authorization.
- Disable high-risk tools by default.
- Set `allow_loopback_without_auth` to `false`, configure bearer-token environment variables, and restrict CORS to approved origins only.
- Run backup and restore drills on a schedule.
- Review audit logs and secret-handling posture before each release.
