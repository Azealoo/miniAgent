"""Sample workflow step executors used by authored BioAPEX workflow specs.

High-risk executors that materially read or write the project tree declare
a :class:`SandboxSpec` here so the runtime and audit tooling can inspect
the same per-runner contract that the tool policy layer enforces on the
LangChain tool surface. The runners themselves are plain Python functions
and are not dispatched through the ``PolicyWrappedTool`` path, so this is
a declarative "parallel" contract rather than an active wrapper gate.
"""

from __future__ import annotations

from tools.policy_types import SandboxSpec

WORKFLOW_RUNNER_SANDBOX_SPECS: dict[str, SandboxSpec] = {
    "workflows.runners.rna_seq_qc": SandboxSpec(
        allowed_file_roots=("artifacts/", "storage/", "workflows/"),
        allowed_env_vars=("PATH", "HOME", "LANG", "LC_ALL"),
        network_scope="none",
        max_wall_clock_seconds=600.0,
        max_output_bytes=200_000,
    ),
    "workflows.runners.rnaseq_qc_de": SandboxSpec(
        allowed_file_roots=("artifacts/", "storage/", "workflows/"),
        allowed_env_vars=("PATH", "HOME", "LANG", "LC_ALL"),
        network_scope="none",
        max_wall_clock_seconds=1_800.0,
        max_output_bytes=500_000,
    ),
    "workflows.runners.perturb_seq": SandboxSpec(
        allowed_file_roots=("artifacts/", "storage/", "workflows/"),
        allowed_env_vars=("PATH", "HOME", "LANG", "LC_ALL"),
        network_scope="none",
        max_wall_clock_seconds=3_600.0,
        max_output_bytes=500_000,
    ),
}


def sandbox_spec_for_runner(module: str) -> SandboxSpec | None:
    """Return the SandboxSpec declared for a workflow runner module, if any."""

    return WORKFLOW_RUNNER_SANDBOX_SPECS.get(module)
