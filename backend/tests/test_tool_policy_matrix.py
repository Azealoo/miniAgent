"""Pin the pre-tool policy decision for every (tool, posture) pair.

Today the authorization answer for each tool under each production-hardening
posture (``dev | trusted-lab | hosted-strict``) is implicit — it falls out of
the combination of ``ToolPolicyExecutionContext`` derived from the posture
defaults in ``hardening._POSTURE_DEFAULTS`` and the manifest flags set in
``tools/registry.py``. This matrix test makes the answer explicit: for each
(tool, posture) pair we assert that ``evaluate_pre_tool_policy`` returns
exactly one of ``allow`` / ``blocked`` / ``needs_approval``.

The per-posture context models the posture's semantics as follows:

* ``approved_tool_runs`` — the requires-approval tools the runtime would
  pre-approve given the posture's ``approval_threshold``:
    - ``none`` (dev): every requires-approval tool pre-approved.
    - ``destructive_only`` (trusted-lab): only non-destructive
      requires-approval tools pre-approved; destructive ones still gate.
    - ``all_risky`` (hosted-strict): nothing pre-approved.
* ``denied_tool_runs`` — tools the posture disables via its
  ``tools.*_enabled`` flags. A denial is modelled as an explicit reviewer
  rejection so ``evaluate_pre_tool_policy`` short-circuits to ``blocked``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from hardening import (  # noqa: E402
    VALID_POSTURES,
    HardeningPosture,
    ProductionHardeningPolicy,
)
from tools import get_tool_manifest_entries  # noqa: E402
from tools.policy import evaluate_pre_tool_policy  # noqa: E402
from tools.policy_types import (  # noqa: E402
    ToolPolicyExecutionContext,
    ToolPolicyStatus,
)
from tools.registry import (  # noqa: E402
    ToolClassificationError,
    ToolManifestEntry,
    is_concurrency_safe_tier,
    partition_manifests_by_risk,
    validate_tool_classifications,
)

# ``evaluate_pre_tool_policy`` defaults the args_hash to ``""`` when no kwargs
# flow through a wrapper. This matrix test is a synthetic policy-only probe,
# so pre-approvals use the same sentinel to pair with that default.
_NO_ARGS_HASH = ""


# Maps posture's ``tools.*_enabled`` field to the registered tool names it
# gates. Flags that do not correspond to a registered runtime tool (``slurm``,
# ``slurm_legacy_commands``) are intentionally omitted — those are enforced
# inside ``SlurmTool`` itself and are not part of this matrix.
_TOOLS_FLAG_TO_TOOL_NAMES: dict[str, tuple[str, ...]] = {
    "terminal_enabled": ("terminal",),
    "python_repl_enabled": ("python_repl",),
    "write_file_enabled": ("write_file",),
}


def _runtime_manifests() -> tuple[ToolManifestEntry, ...]:
    # The tools' base_dir is irrelevant for manifest metadata; any path works.
    return get_tool_manifest_entries(Path("/tmp/bioapex-tool-policy-matrix"))


_MANIFESTS: tuple[ToolManifestEntry, ...] = _runtime_manifests()
_MANIFEST_BY_NAME: dict[str, ToolManifestEntry] = {m.name: m for m in _MANIFESTS}
_TOOL_NAMES: tuple[str, ...] = tuple(m.name for m in _MANIFESTS)


def _disabled_tool_names(policy: ProductionHardeningPolicy) -> frozenset[str]:
    disabled: set[str] = set()
    for flag, tool_names in _TOOLS_FLAG_TO_TOOL_NAMES.items():
        if getattr(policy.tools, flag) is False:
            disabled.update(tool_names)
    return frozenset(disabled)


def _approved_tool_runs(
    policy: ProductionHardeningPolicy,
    manifests: tuple[ToolManifestEntry, ...],
    disabled: frozenset[str],
) -> frozenset[tuple[str, str]]:
    """Pre-approvals implied by the posture's approval threshold.

    A disabled tool is never pre-approved; the denial takes precedence so the
    policy produces ``blocked`` rather than ``allow``. Destructive manifests
    are intentionally never pre-approved — the policy layer always re-prompts
    for them regardless of what the posture says.
    """
    threshold = policy.approval_threshold
    approved: set[tuple[str, str]] = set()
    for manifest in manifests:
        if manifest.name in disabled:
            continue
        if not manifest.requires_approval:
            continue
        if manifest.destructive:
            # Destructive tools always re-prompt; an approval recorded here
            # would be ignored by ``_user_has_approved`` anyway.
            continue
        if threshold == "none":
            approved.add((manifest.name, _NO_ARGS_HASH))
        elif threshold == "destructive_only":
            approved.add((manifest.name, _NO_ARGS_HASH))
        elif threshold == "all_risky":
            # Every requires-approval tool still needs explicit approval.
            continue
    return frozenset(approved)


def _build_context(posture: HardeningPosture) -> ToolPolicyExecutionContext:
    policy = ProductionHardeningPolicy.from_posture(posture)
    disabled = _disabled_tool_names(policy)
    approved = _approved_tool_runs(policy, _MANIFESTS, disabled)
    denied = frozenset((name, _NO_ARGS_HASH) for name in disabled)
    return ToolPolicyExecutionContext(
        session_id=f"session-{posture}",
        request_id=f"request-{posture}",
        allowed_access_scope="execution",
        approved_tool_runs=approved,
        denied_tool_runs=denied,
    )


def _expected_status(
    manifest: ToolManifestEntry,
    posture: HardeningPosture,
) -> ToolPolicyStatus:
    policy = ProductionHardeningPolicy.from_posture(posture)
    disabled = _disabled_tool_names(policy)
    if manifest.name in disabled:
        return "blocked"
    if not manifest.requires_approval:
        return "allow"
    # Destructive tools always re-prompt regardless of the posture's
    # pre-approval semantics — ``_user_has_approved`` ignores stored
    # approvals for them.
    if manifest.destructive:
        return "needs_approval"
    if policy.approval_threshold == "none":
        return "allow"
    if policy.approval_threshold == "destructive_only":
        return "allow"
    # approval_threshold == "all_risky"
    return "needs_approval"


# The explicit expected-status matrix is the reviewable source of truth for
# this test. It is cross-checked against ``_expected_status`` below so an
# accidental drift in either the matrix or the derivation rule fails loudly.
EXPECTED_MATRIX: dict[tuple[str, str], ToolPolicyStatus] = {
    # dev — approval_threshold=none, nothing disabled ⇒ every tool allow.
    ("terminal", "dev"): "allow",
    ("python_repl", "dev"): "allow",
    ("fetch_url", "dev"): "allow",
    ("http_json", "dev"): "allow",
    ("ncbi_eutils", "dev"): "allow",
    ("evidence_retrieval", "dev"): "allow",
    ("evidence_review", "dev"): "allow",
    ("entity_grounding", "dev"): "allow",
    ("plan_agent", "dev"): "allow",
    ("verification_agent", "dev"): "allow",
    ("uniprot_api", "dev"): "allow",
    ("ensembl_api", "dev"): "allow",
    ("read_file", "dev"): "allow",
    ("write_file", "dev"): "needs_approval",
    ("search_knowledge_base", "dev"): "allow",
    # trusted-lab — python_repl disabled; destructive-only approval gates
    # write_file; other requires-approval tools pre-approved.
    ("terminal", "trusted-lab"): "allow",
    ("python_repl", "trusted-lab"): "blocked",
    ("fetch_url", "trusted-lab"): "allow",
    ("http_json", "trusted-lab"): "allow",
    ("ncbi_eutils", "trusted-lab"): "allow",
    ("evidence_retrieval", "trusted-lab"): "allow",
    ("evidence_review", "trusted-lab"): "allow",
    ("entity_grounding", "trusted-lab"): "allow",
    ("plan_agent", "trusted-lab"): "allow",
    ("verification_agent", "trusted-lab"): "allow",
    ("uniprot_api", "trusted-lab"): "allow",
    ("ensembl_api", "trusted-lab"): "allow",
    ("read_file", "trusted-lab"): "allow",
    ("write_file", "trusted-lab"): "needs_approval",
    ("search_knowledge_base", "trusted-lab"): "allow",
    # hosted-strict — terminal, python_repl, write_file disabled; nothing
    # else requires approval, so non-disabled tools fall through to allow.
    ("terminal", "hosted-strict"): "blocked",
    ("python_repl", "hosted-strict"): "blocked",
    ("fetch_url", "hosted-strict"): "allow",
    ("http_json", "hosted-strict"): "allow",
    ("ncbi_eutils", "hosted-strict"): "allow",
    ("evidence_retrieval", "hosted-strict"): "allow",
    ("evidence_review", "hosted-strict"): "allow",
    ("entity_grounding", "hosted-strict"): "allow",
    ("plan_agent", "hosted-strict"): "allow",
    ("verification_agent", "hosted-strict"): "allow",
    ("uniprot_api", "hosted-strict"): "allow",
    ("ensembl_api", "hosted-strict"): "allow",
    ("read_file", "hosted-strict"): "allow",
    ("write_file", "hosted-strict"): "blocked",
    ("search_knowledge_base", "hosted-strict"): "allow",
}


def test_matrix_covers_every_tool_and_posture():
    """The reviewable matrix must list every (tool, posture) pair exactly once."""
    expected_pairs = {(name, posture) for name in _TOOL_NAMES for posture in VALID_POSTURES}
    assert set(EXPECTED_MATRIX) == expected_pairs
    assert len(EXPECTED_MATRIX) == len(_TOOL_NAMES) * len(VALID_POSTURES)


def test_matrix_statuses_are_from_allowed_vocabulary():
    allowed: frozenset[ToolPolicyStatus] = frozenset({"allow", "blocked", "needs_approval"})
    for key, status in EXPECTED_MATRIX.items():
        assert status in allowed, f"{key} has unexpected status {status!r}"


@pytest.mark.parametrize(
    ("tool_name", "posture"),
    sorted(EXPECTED_MATRIX.keys()),
    ids=lambda v: v if isinstance(v, str) else str(v),
)
def test_policy_decision_for_tool_posture_matches_matrix(
    tool_name: str, posture: HardeningPosture
):
    manifest = _MANIFEST_BY_NAME[tool_name]
    context = _build_context(posture)

    decision = evaluate_pre_tool_policy(manifest, context)

    expected = EXPECTED_MATRIX[(tool_name, posture)]
    # Sanity-check that the hand-written matrix still matches the derivation
    # rule; if they diverge, either the matrix or ``_expected_status`` is
    # wrong and the reviewer should fix both together.
    assert _expected_status(manifest, posture) == expected, (
        f"derivation rule disagrees with EXPECTED_MATRIX for "
        f"{(tool_name, posture)!r}"
    )
    assert decision.status == expected, (
        f"Expected {expected!r} for tool={tool_name!r} posture={posture!r}, "
        f"got {decision.status!r} (block_reason={decision.block_reason!r}, "
        f"approval_reason={decision.approval_reason!r})"
    )
    assert decision.status in {"allow", "blocked", "needs_approval"}


# ---------- Startup classification validator --------------------------------


def _fake_manifest(
    name: str,
    *,
    read_only: bool = False,
    destructive: bool = False,
    concurrency_safe: bool = False,
) -> ToolManifestEntry:
    return ToolManifestEntry(
        name=name,
        description=f"fake {name}",
        args_schema=None,
        response_format="content_and_artifact",
        access_scope="inspection" if read_only else "execution",
        evidence_requirement="none",
        output_contract_version="tool_result.v1",
        source_module="tests.test_tool_policy_matrix",
        read_only=read_only,
        destructive=destructive,
        concurrency_safe=concurrency_safe,
        planner_exposed=read_only,
        verifier_exposed=read_only,
        interrupt_behavior="restartable" if read_only else "avoid_interrupting",
        tool_validates_input=False,
        activity_summary_hint="inspect",
        result_summary_hint="result",
    )


def test_validate_tool_classifications_accepts_runtime_registry():
    """The shipped manifest set must pass the startup validator."""
    # Should not raise; this pins the invariant across the real registry.
    validate_tool_classifications(_MANIFESTS)


def test_validate_tool_classifications_rejects_destructive_and_read_only():
    bad = (
        _fake_manifest("bad_dual_tool", read_only=True, destructive=True),
    )
    with pytest.raises(ToolClassificationError) as excinfo:
        validate_tool_classifications(bad)
    assert "bad_dual_tool" in str(excinfo.value)
    assert "destructive and read_only" in str(excinfo.value)


def test_validate_tool_classifications_rejects_destructive_and_concurrency_safe():
    bad = (
        _fake_manifest(
            "bad_destructive_parallel",
            destructive=True,
            concurrency_safe=True,
        ),
    )
    with pytest.raises(ToolClassificationError) as excinfo:
        validate_tool_classifications(bad)
    assert "bad_destructive_parallel" in str(excinfo.value)
    assert "destructive and concurrency_safe" in str(excinfo.value)


def test_validate_tool_classifications_rejects_concurrency_safe_without_read_only():
    bad = (
        _fake_manifest(
            "bad_parallel_write",
            read_only=False,
            destructive=False,
            concurrency_safe=True,
        ),
    )
    with pytest.raises(ToolClassificationError) as excinfo:
        validate_tool_classifications(bad)
    assert "bad_parallel_write" in str(excinfo.value)
    assert "concurrency_safe requires read_only" in str(excinfo.value)


def test_validate_tool_classifications_reports_every_violation():
    """A bad registry lists every offender in a single error."""
    bad = (
        _fake_manifest("first_bad", read_only=True, destructive=True),
        _fake_manifest("good_read", read_only=True, concurrency_safe=True),
        _fake_manifest(
            "second_bad",
            read_only=False,
            concurrency_safe=True,
        ),
    )
    with pytest.raises(ToolClassificationError) as excinfo:
        validate_tool_classifications(bad)
    message = str(excinfo.value)
    assert "first_bad" in message
    assert "second_bad" in message
    assert "good_read" not in message


def test_partition_manifests_by_risk_splits_tiers():
    read_safe = _fake_manifest(
        "read_safe", read_only=True, concurrency_safe=True
    )
    read_only_not_parallel = _fake_manifest(
        "read_only_serial", read_only=True, concurrency_safe=False
    )
    write = _fake_manifest("write", destructive=True)

    parallel, serial = partition_manifests_by_risk(
        [read_safe, write, read_only_not_parallel]
    )

    assert parallel == (read_safe,)
    assert serial == (write, read_only_not_parallel)
    assert is_concurrency_safe_tier(read_safe) is True
    assert is_concurrency_safe_tier(read_only_not_parallel) is False
    assert is_concurrency_safe_tier(write) is False
