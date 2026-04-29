"""Pin planner/verifier tool exposure for every reachable manifest combination.

The exposure filter under test is
``runtime.helper_agent_runner.filter_tools_by_exposure``, which keys off the
manifest flags built by ``tools.registry.build_tool_manifest_entry``. Two
derivation inversions in that builder collapse parts of the input space and
must remain pinned:

* ``planner_exposed = (policy.planner_exposed or read_only) and name not in
  _PLANNER_HIDDEN_TOOL_NAMES`` — a hidden read-only tool (live example:
  ``ncbi_eutils``) is suppressed from the planner's view so it cannot drown
  out the richer ``evidence_retrieval`` sibling.
* ``verifier_exposed = policy.verifier_exposed and not policy.destructive`` —
  destructive tools can never be verifier-exposed even if their policy asks
  for it.

This matrix lists the expected ``(planner_exposed, verifier_exposed)`` pair
for every shipped tool, cross-checks it against an explicit derivation rule
that encodes both inversions, and verifies that ``filter_tools_by_exposure``
agrees. Combinations the inversions render unreachable at runtime — a
manifest that is both ``destructive`` and ``verifier_exposed``, or both
``read_only`` and ``destructive`` (rejected by ``validate_tool_classifications``) —
are intentionally omitted; asserting them would only test the test.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools import get_runtime_tools, get_tool_manifest_entries  # noqa: E402
from tools import registry  # noqa: E402
from tools.registry import ToolPolicyMetadata  # noqa: E402
from runtime.helper_agent_runner import filter_tools_by_exposure  # noqa: E402


# Expected manifest exposure per shipped tool, after both inversions are
# applied. Reviewable source of truth — cross-checked against
# ``_expected_exposure`` below so an accidental drift in either the table or
# the derivation rule fails loudly.
EXPECTED_EXPOSURE: dict[str, tuple[bool, bool]] = {
    # Plain execution-scope tools with no exposure policy: neither role sees
    # them. Today these reach the (False, False) state purely through lacking
    # the policy bits — no inversion is involved.
    "terminal": (False, False),
    "python_repl": (False, False),
    "entity_grounding": (False, False),
    "plan_agent": (False, False),
    "verification_agent": (False, False),

    # Plain read-only lookups. The planner inherits them via the ``read_only``
    # clause; the verifier gets them via explicit policy.
    "fetch_url": (True, True),
    "http_json": (True, True),
    "uniprot_api": (True, True),
    "ensembl_api": (True, True),
    "evidence_retrieval": (True, True),
    "read_file": (True, True),
    "search_knowledge_base": (True, True),

    # read_only + hidden ⇒ NOT planner_exposed. ``ncbi_eutils`` is the live
    # example of the planner-hidden inversion: it would otherwise be inherited
    # via ``read_only``, but the hidden-set strips it back out so the planner
    # reaches for ``evidence_retrieval`` instead.
    "ncbi_eutils": (False, True),

    # Verifier-only execution-scope tool. ``evidence_review`` is not
    # ``read_only`` (so the planner does not auto-inherit it) but it is
    # ``verifier_exposed`` by policy and not ``destructive``.
    "evidence_review": (False, True),

    # Destructive tool. ``write_file`` pins the destructive guard's floor:
    # even if its policy ever requested verifier exposure, the derivation
    # would strip the bit back off via ``not policy.destructive``.
    "write_file": (False, False),
}


def _expected_exposure(name: str) -> tuple[bool, bool]:
    """Derive expected exposure from the inputs the registry actually reads.

    Inputs mirror ``build_tool_manifest_entry``:
    ``policy.planner_exposed``, ``policy.verifier_exposed``,
    derived ``read_only`` (policy bit OR membership in
    ``_READ_ONLY_TOOL_NAMES``), ``policy.destructive`` (== manifest
    ``destructive``), and ``hidden`` (membership in
    ``_PLANNER_HIDDEN_TOOL_NAMES``).
    """
    policy = registry._POLICY_OVERRIDES.get(
        name, ToolPolicyMetadata(access_scope="execution")
    )
    read_only = policy.read_only or name in registry._READ_ONLY_TOOL_NAMES
    destructive = policy.destructive
    hidden = name in registry._PLANNER_HIDDEN_TOOL_NAMES

    planner_exposed = (policy.planner_exposed or read_only) and not hidden
    verifier_exposed = policy.verifier_exposed and not destructive
    return planner_exposed, verifier_exposed


@pytest.fixture(scope="module")
def base_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.mktemp("verifier-exposure")
    (base / "knowledge").mkdir()
    (base / "storage").mkdir()
    return base


@pytest.fixture(scope="module")
def planner_tool_names(base_dir: Path) -> frozenset[str]:
    tools = get_runtime_tools(base_dir)
    exposed = filter_tools_by_exposure(tools, "planner")
    return frozenset(getattr(tool, "name", "") for tool in exposed)


@pytest.fixture(scope="module")
def verifier_tool_names(base_dir: Path) -> frozenset[str]:
    tools = get_runtime_tools(base_dir)
    exposed = filter_tools_by_exposure(tools, "verifier")
    return frozenset(getattr(tool, "name", "") for tool in exposed)


def test_matrix_covers_every_runtime_tool(base_dir: Path) -> None:
    """The expected-exposure table must list every shipped tool exactly once.

    This is the row-coverage guarantee: every read-only lookup the verifier
    relies on (``fetch_url``, ``http_json``, ``ncbi_eutils``,
    ``uniprot_api``, ``ensembl_api``, ``evidence_retrieval``, ``read_file``,
    ``search_knowledge_base``) is pinned by name in ``EXPECTED_EXPOSURE``, so
    a registry edit that silently drops one would break this test before any
    parametrized row.
    """
    runtime_names = {m.name for m in get_tool_manifest_entries(base_dir)}
    assert set(EXPECTED_EXPOSURE) == runtime_names, (
        "EXPECTED_EXPOSURE drifted from the live registry. Add or remove "
        "rows together with the matching registry change so the inversions "
        "stay explicit."
    )


def test_derivation_rule_matches_matrix() -> None:
    """The hand-written matrix must agree with the derivation rule.

    If they diverge, either the table or ``_expected_exposure`` is wrong;
    fix both together so the inversions remain explicit on both sides.
    """
    for name, expected in EXPECTED_EXPOSURE.items():
        assert _expected_exposure(name) == expected, (
            f"derivation rule disagrees with EXPECTED_EXPOSURE for {name!r}: "
            f"derived {_expected_exposure(name)!r}, expected {expected!r}"
        )


@pytest.mark.parametrize("tool_name", sorted(EXPECTED_EXPOSURE))
def test_filter_tools_by_exposure_matches_matrix(
    tool_name: str,
    planner_tool_names: frozenset[str],
    verifier_tool_names: frozenset[str],
) -> None:
    expected_planner, expected_verifier = EXPECTED_EXPOSURE[tool_name]
    actual_planner = tool_name in planner_tool_names
    actual_verifier = tool_name in verifier_tool_names
    assert actual_planner is expected_planner, (
        f"planner exposure for {tool_name!r}: expected {expected_planner!r}, "
        f"got {actual_planner!r}"
    )
    assert actual_verifier is expected_verifier, (
        f"verifier exposure for {tool_name!r}: expected {expected_verifier!r}, "
        f"got {actual_verifier!r}"
    )
