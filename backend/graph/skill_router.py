from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any

from tools.skills_scanner import collect_skill_entries

MAX_ROUTED_SKILLS = 6
MAX_ROUTING_HISTORY_MESSAGES = 6
MAX_ROUTING_ACTIVATION_PATHS = 24

_EXPLICIT_MATCH_SCORE = 10_000
_PATH_ACTIVATION_SCORE = 160
_HISTORY_PATH_ACTIVATION_SCORE = 110
_FIELD_WEIGHTS = {
    "name": 18,
    "aliases": 16,
    "tags": 12,
    "category": 10,
    "modality": 10,
    "stage": 6,
    "description": 4,
}
_STABILITY_BONUS = {
    "stable": 3,
    "evolving": 2,
    "experimental": 1,
}
_STOPWORDS = {
    "a",
    "an",
    "and",
    "can",
    "for",
    "from",
    "how",
    "i",
    "in",
    "me",
    "my",
    "of",
    "on",
    "or",
    "our",
    "please",
    "the",
    "to",
    "use",
    "we",
    "with",
    "you",
}
_QUERY_EXPANSIONS = (
    (("scrna", "single cell", "single-cell", "singlecell"), {"single", "cell", "rna", "single_cell_rna", "scrna"}),
    (("perturbseq", "perturb seq", "perturb-seq"), {"perturb", "seq", "perturb_seq", "perturbseq"}),
    (("wet lab", "wet-lab", "bench"), {"wet", "lab", "wet_lab", "molecular_lab"}),
    (("paper", "abstract", "literature", "pubmed", "manuscript"), {"literature", "paper", "abstract", "pubmed", "manuscript"}),
    (("crispr screen", "crispr-screen", "screen"), {"crispr", "screen", "crispr_screen"}),
)
_PATH_VALUE_KEYS = {
    "artifact_path",
    "artifact_relpath",
    "location",
    "path",
    "requested_path",
    "source",
}
_PATH_LIKE_EXTENSIONS = (
    ".csv",
    ".json",
    ".md",
    ".py",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
)


def _normalize_phrase(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


def _routing_tokens(value: str) -> set[str]:
    normalized = _normalize_phrase(value)
    if not normalized:
        return set()

    parts = [
        part
        for part in normalized.split()
        if len(part) > 1 and part not in _STOPWORDS
    ]
    if not parts:
        return set()

    tokens = set(parts)
    if len(parts) > 1:
        tokens.add("_".join(parts))
        tokens.add("".join(parts))
        if parts[0] == "bio" and len(parts) > 2:
            scoped = parts[1:]
            tokens.add("_".join(scoped))
            tokens.add("".join(scoped))
    return tokens


def _expand_query_tokens(query: str) -> tuple[str, set[str]]:
    normalized = _normalize_phrase(query)
    compact = normalized.replace(" ", "")
    tokens = _routing_tokens(query)

    for triggers, additions in _QUERY_EXPANSIONS:
        if any(trigger in normalized or trigger.replace(" ", "") in compact for trigger in triggers):
            tokens.update(additions)

    return normalized, tokens


def _phrase_is_mentioned(normalized_query: str, candidate: str) -> bool:
    normalized_candidate = _normalize_phrase(candidate)
    if not normalized_candidate:
        return False
    padded_query = f" {normalized_query} "
    return f" {normalized_candidate} " in padded_query


def _score_field(query_tokens: set[str], values: list[str] | tuple[str, ...] | set[str], weight: int) -> int:
    field_tokens: set[str] = set()
    for value in values:
        field_tokens.update(_routing_tokens(value))
    overlap = query_tokens & field_tokens
    if not overlap:
        return 0
    return len(overlap) * weight


def _score_skill_entry(
    entry: dict[str, Any],
    *,
    normalized_query: str,
    query_tokens: set[str],
) -> tuple[int, bool]:
    candidate_phrases = [entry.get("name", ""), *entry.get("aliases", [])]
    if any(_phrase_is_mentioned(normalized_query, phrase) for phrase in candidate_phrases):
        bonus = _STABILITY_BONUS.get(entry.get("stability", ""), 0)
        return _EXPLICIT_MATCH_SCORE + bonus, True

    score = 0
    score += _score_field(query_tokens, [entry.get("name", "")], _FIELD_WEIGHTS["name"])
    score += _score_field(query_tokens, entry.get("aliases", []), _FIELD_WEIGHTS["aliases"])
    score += _score_field(query_tokens, entry.get("tags", []), _FIELD_WEIGHTS["tags"])
    score += _score_field(query_tokens, [entry.get("category", "")], _FIELD_WEIGHTS["category"])
    score += _score_field(query_tokens, [entry.get("modality", "")], _FIELD_WEIGHTS["modality"])
    score += _score_field(query_tokens, [entry.get("stage", "")], _FIELD_WEIGHTS["stage"])
    score += _score_field(query_tokens, [entry.get("description", "")], _FIELD_WEIGHTS["description"])
    if score > 0:
        score += _STABILITY_BONUS.get(entry.get("stability", ""), 0)
    return score, False


def _strip_candidate_token(value: str) -> str:
    return value.strip().strip("`'\"“”‘’()[]{}<>,;:")


def _looks_like_path(value: str) -> bool:
    candidate = value.rstrip("/")
    if not candidate or "://" in candidate or candidate.startswith("app://"):
        return False
    if any(part in {".", ".."} for part in candidate.split("/") if part):
        return False
    if "/" in candidate:
        return True
    return any(candidate.endswith(ext) for ext in _PATH_LIKE_EXTENSIONS)


def _candidate_path_variants(base_dir: Path, raw_value: str) -> set[str]:
    candidate = _strip_candidate_token(raw_value)
    if "#" in candidate:
        candidate = candidate.split("#", 1)[0]
    candidate = candidate.replace("\\", "/")
    while candidate.startswith("./"):
        candidate = candidate[2:]
    candidate = re.sub(r"/{2,}", "/", candidate)

    repo_root = base_dir.parent.resolve()
    base_root = base_dir.resolve()

    if candidate.startswith("/"):
        absolute_candidate = Path(candidate)
        try:
            candidate = absolute_candidate.resolve().relative_to(repo_root).as_posix()
        except ValueError:
            try:
                candidate = absolute_candidate.resolve().relative_to(base_root).as_posix()
            except ValueError:
                return set()

    candidate = candidate.lstrip("/")
    if not _looks_like_path(candidate):
        return set()

    variants = {candidate}
    base_name = base_dir.name
    if base_name:
        prefix = f"{base_name}/"
        if candidate.startswith(prefix):
            trimmed = candidate[len(prefix):]
            if trimmed:
                variants.add(trimmed)
        else:
            variants.add(f"{prefix}{candidate}")
    return {variant for variant in variants if variant}


def _extract_query_paths(base_dir: Path, query: str) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for raw_token in query.split():
        stripped = _strip_candidate_token(raw_token)
        if not _looks_like_path(stripped):
            continue
        for variant in _candidate_path_variants(base_dir, stripped):
            if variant in seen:
                continue
            seen.add(variant)
            paths.append(variant)
            if len(paths) >= MAX_ROUTING_ACTIVATION_PATHS:
                return paths
    return paths


def _collect_paths_from_value(
    base_dir: Path,
    value: Any,
    *,
    limit: int,
    seen: set[str],
    collected: list[str],
) -> None:
    if len(collected) >= limit:
        return
    if isinstance(value, dict):
        for key, nested_value in value.items():
            if len(collected) >= limit:
                return
            if key in _PATH_VALUE_KEYS and isinstance(nested_value, str):
                for variant in _candidate_path_variants(base_dir, nested_value):
                    if variant in seen:
                        continue
                    seen.add(variant)
                    collected.append(variant)
                    if len(collected) >= limit:
                        return
                continue
            _collect_paths_from_value(
                base_dir,
                nested_value,
                limit=limit,
                seen=seen,
                collected=collected,
            )
        return
    if isinstance(value, list):
        for item in value:
            if len(collected) >= limit:
                return
            _collect_paths_from_value(
                base_dir,
                item,
                limit=limit,
                seen=seen,
                collected=collected,
            )


def _extract_history_paths(
    base_dir: Path,
    history: list[dict[str, Any]] | None,
) -> list[str]:
    if not history:
        return []

    collected: list[str] = []
    seen: set[str] = set()
    inspected_messages = 0

    for message in reversed(history):
        if not isinstance(message, dict):
            continue

        blocks = message.get("blocks")
        tool_calls = message.get("tool_calls")
        retrievals = message.get("retrievals")
        if not isinstance(blocks, list) and not isinstance(tool_calls, list) and not isinstance(retrievals, list):
            continue

        inspected_messages += 1
        _collect_paths_from_value(
            base_dir,
            {
                "blocks": blocks if isinstance(blocks, list) else [],
                "tool_calls": tool_calls if isinstance(tool_calls, list) else [],
                "retrievals": retrievals if isinstance(retrievals, list) else [],
            },
            limit=MAX_ROUTING_ACTIVATION_PATHS,
            seen=seen,
            collected=collected,
        )
        if (
            inspected_messages >= MAX_ROUTING_HISTORY_MESSAGES
            or len(collected) >= MAX_ROUTING_ACTIVATION_PATHS
        ):
            break

    return collected


def _normalize_path_hint(path_hint: str) -> str:
    normalized = path_hint.replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return re.sub(r"/{2,}", "/", normalized)


def _path_hint_specificity(path_hint: str) -> int:
    return min(24, len(re.sub(r"[\*\?\[\]]", "", path_hint).rstrip("/")))


def _path_hint_matches(path_hint: str, candidate_path: str) -> bool:
    normalized_hint = _normalize_path_hint(path_hint)
    normalized_candidate = _normalize_path_hint(candidate_path)
    if not normalized_hint or not normalized_candidate:
        return False

    if any(char in normalized_hint for char in "*?["):
        return fnmatch.fnmatch(normalized_candidate, normalized_hint)
    if normalized_hint.endswith("/"):
        return normalized_candidate.startswith(normalized_hint)
    return normalized_candidate == normalized_hint or normalized_candidate.startswith(
        f"{normalized_hint}/"
    )


def _score_path_activation(
    entry: dict[str, Any],
    *,
    query_paths: list[str],
    history_paths: list[str],
) -> tuple[int, bool]:
    """Return (activation_score, declared).

    `declared` is True iff the skill carries a non-empty `paths:` list;
    when score == 0 this signals the skill is path-gated rather than
    always-on.
    """
    path_hints = entry.get("paths", [])
    if not isinstance(path_hints, list):
        return 0, False
    valid_hints = [p for p in path_hints if isinstance(p, str) and p.strip()]
    if not valid_hints:
        return 0, False

    score = 0
    for path_hint in valid_hints:
        specificity = _path_hint_specificity(path_hint)
        if any(_path_hint_matches(path_hint, candidate) for candidate in query_paths):
            score = max(score, _PATH_ACTIVATION_SCORE + specificity)
        if any(_path_hint_matches(path_hint, candidate) for candidate in history_paths):
            score = max(score, _HISTORY_PATH_ACTIVATION_SCORE + specificity)
    return score, True


def select_skill_entries_for_query(
    base_dir: Path,
    query: str,
    *,
    history: list[dict[str, Any]] | None = None,
    max_skills: int = MAX_ROUTED_SKILLS,
) -> list[dict[str, Any]] | None:
    skill_entries = [
        entry
        for entry in collect_skill_entries(base_dir, respect_enabled=True)
        if entry.get("user_invocable", True)
    ]
    if not skill_entries:
        return []

    normalized_query, query_tokens = _expand_query_tokens(query)
    query_paths = _extract_query_paths(base_dir, query)
    history_paths = _extract_history_paths(base_dir, history)
    if not normalized_query and not query_paths and not history_paths:
        return None

    scored_entries: list[tuple[int, bool, dict[str, Any]]] = []
    for entry in skill_entries:
        text_score, explicit = _score_skill_entry(
            entry,
            normalized_query=normalized_query,
            query_tokens=query_tokens,
        )
        path_score, path_declared = _score_path_activation(
            entry,
            query_paths=query_paths,
            history_paths=history_paths,
        )
        # Skills declaring `paths:` are conditionally activated — only
        # injected when at least one declared hint matches the current
        # working set. Empty/absent paths remain always-on. Explicit
        # name/alias invocations bypass this gate so users can still
        # summon a path-scoped skill off-path.
        if not explicit and path_declared and path_score == 0:
            continue
        score = text_score + path_score
        if score > 0:
            scored_entries.append((score, explicit, entry))

    if not scored_entries:
        return None

    explicit_entries = [entry for _, explicit, entry in scored_entries if explicit]
    if explicit_entries:
        explicit_entries.sort(key=lambda entry: entry["name"])
        return explicit_entries[:max_skills]

    scored_entries.sort(
        key=lambda item: (
            -item[0],
            -_STABILITY_BONUS.get(item[2].get("stability", ""), 0),
            item[2]["name"],
        )
    )
    return [entry for _, _, entry in scored_entries[:max_skills]]
