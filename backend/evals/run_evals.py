"""
Regression eval runner for canonical biologist tasks.

Usage (from the repo root, where ``backend/`` is the Python project root):

    cd backend
    python -m evals.run_evals                # run all tasks, write JSON report
    python -m evals.run_evals --dry-run      # skip LLM calls (CI smoke test)
    python -m evals.run_evals --tasks literature_lookup,gene_protein_lookup
    python -m evals.run_evals --output ../reports/eval-$(date +%F).json

The runner drives the live chat runtime via ``agent_manager.astream`` so
that tool selection, prompt assembly, and helper-agent wiring are
exercised end-to-end. Each task's ordered tool sequence is harvested from
the streamed ``tool_start`` / ``tool_end`` events, matched against a
per-task regex, and the final answer is scored by a judge LLM (the
verifier role by default — override with ``--judge-role``).

YAML schema and "how to add a task" live in ``backend/evals/README.md``.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

# Make ``backend/`` importable when invoked as ``python -m evals.run_evals``
# from inside backend/, and also when invoked as
# ``python -m backend.evals.run_evals`` from the repo root.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import yaml  # type: ignore[import-untyped]

TASKS_DIR = Path(__file__).resolve().parent / "tasks"

# Rubric prompt is isolated here so the judge role always sees the same
# instructions regardless of which LLM role is plugged in.
_JUDGE_SYSTEM_PROMPT = """
You are a strict evaluation judge for a biology research assistant.

You will be shown:
  - a user task prompt
  - the assistant's final answer
  - the ordered list of tools the assistant called
  - one rubric question with a max score

Score the answer against the rubric question only. Output a single JSON
object, nothing else, with these keys:
  - "score": integer, 0 to the stated max_score
  - "justification": one short paragraph explaining the score

Do not invent facts about the assistant's answer. If the answer is empty,
score 0. If the rubric asks about tool grounding and the tool list is
empty, treat that as a strong signal against the answer.
""".strip()


# --------------------------------------------------------------------------- #
# Task loading                                                                  #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RubricQuestion:
    id: str
    question: str
    max_score: int


@dataclass(frozen=True)
class TaskSpec:
    id: str
    name: str
    description: str
    prompt: str
    tool_regex: str
    tool_regex_description: str
    rubric: tuple[RubricQuestion, ...]
    source_path: Path
    tags: tuple[str, ...] = field(default_factory=tuple)


def _require(condition: bool, msg: str) -> None:
    if not condition:
        raise ValueError(msg)


def _parse_rubric(raw: Any, *, task_id: str) -> tuple[RubricQuestion, ...]:
    _require(
        isinstance(raw, list) and raw,
        f"Task '{task_id}': rubric must be a non-empty list.",
    )
    questions: list[RubricQuestion] = []
    for idx, entry in enumerate(raw):
        _require(
            isinstance(entry, dict),
            f"Task '{task_id}': rubric entry #{idx} must be a mapping.",
        )
        question = entry.get("question")
        qid = entry.get("id") or f"q{idx + 1}"
        max_score = entry.get("max_score", 5)
        _require(
            isinstance(question, str) and question.strip(),
            f"Task '{task_id}': rubric entry '{qid}' is missing 'question'.",
        )
        try:
            max_score_int = int(max_score)
        except (TypeError, ValueError):
            raise ValueError(
                f"Task '{task_id}': rubric entry '{qid}' has non-integer max_score."
            )
        _require(
            max_score_int > 0,
            f"Task '{task_id}': rubric entry '{qid}' has non-positive max_score.",
        )
        questions.append(
            RubricQuestion(
                id=str(qid),
                question=question.strip(),
                max_score=max_score_int,
            )
        )
    return tuple(questions)


def load_task(path: Path) -> TaskSpec:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    _require(isinstance(raw, dict), f"{path}: top level must be a mapping.")

    task_id = raw.get("id") or path.stem
    _require(
        isinstance(task_id, str) and task_id.strip(),
        f"{path}: 'id' must be a non-empty string.",
    )

    input_section = raw.get("input") or {}
    _require(
        isinstance(input_section, dict),
        f"Task '{task_id}': 'input' must be a mapping.",
    )
    prompt = input_section.get("prompt")
    _require(
        isinstance(prompt, str) and prompt.strip(),
        f"Task '{task_id}': 'input.prompt' must be a non-empty string.",
    )

    expected = raw.get("expected_tool_sequence") or {}
    _require(
        isinstance(expected, dict),
        f"Task '{task_id}': 'expected_tool_sequence' must be a mapping.",
    )
    regex = expected.get("regex")
    _require(
        isinstance(regex, str) and regex.strip(),
        f"Task '{task_id}': 'expected_tool_sequence.regex' must be a non-empty string.",
    )
    try:
        re.compile(regex)
    except re.error as exc:
        raise ValueError(
            f"Task '{task_id}': expected_tool_sequence.regex is not a valid "
            f"regular expression: {exc}"
        )

    tags = raw.get("tags") or []
    _require(
        isinstance(tags, list) and all(isinstance(t, str) for t in tags),
        f"Task '{task_id}': 'tags' must be a list of strings.",
    )

    return TaskSpec(
        id=task_id.strip(),
        name=str(raw.get("name") or task_id),
        description=str(raw.get("description") or ""),
        prompt=prompt.strip(),
        tool_regex=regex,
        tool_regex_description=str(expected.get("description") or ""),
        rubric=_parse_rubric(raw.get("rubric"), task_id=task_id),
        source_path=path,
        tags=tuple(tags),
    )


def discover_tasks(task_dir: Path) -> list[TaskSpec]:
    _require(task_dir.exists(), f"Task directory not found: {task_dir}")
    specs = [load_task(path) for path in sorted(task_dir.glob("*.yaml"))]
    _require(specs, f"No .yaml tasks found under {task_dir}")
    return specs


# --------------------------------------------------------------------------- #
# Runtime execution                                                             #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TaskRun:
    tool_sequence: tuple[str, ...]
    final_answer: str
    error: str | None
    duration_seconds: float


def _tool_sequence_from_events(events: Iterable[dict[str, Any]]) -> list[str]:
    """Collect tool names in the order they were invoked.

    We use ``tool_start`` events when present (they appear first in the
    stream) and fall back to ``tool_end`` events so that a drop in
    ``tool_start`` emission does not silently hide tool use.
    """
    seen_run_ids: set[str] = set()
    ordered: list[str] = []
    for event in events:
        event_type = event.get("type")
        if event_type not in {"tool_start", "tool_end"}:
            continue
        tool_name = event.get("tool")
        run_id = event.get("run_id")
        if not isinstance(tool_name, str):
            continue
        key = f"{run_id}:{tool_name}" if isinstance(run_id, str) else f"_:{tool_name}:{len(ordered)}"
        if key in seen_run_ids:
            continue
        seen_run_ids.add(key)
        ordered.append(tool_name)
    return ordered


async def _drive_runtime(task: TaskSpec) -> TaskRun:
    """Run one task against the live ``agent_manager`` in-process."""
    from graph.agent import agent_manager

    if agent_manager.base_dir is None:
        agent_manager.initialize(_BACKEND_ROOT)

    start = time.perf_counter()
    tool_events: list[dict[str, Any]] = []
    token_chunks: list[str] = []
    error: str | None = None

    try:
        async for event in agent_manager.astream(task.prompt, []):
            event_type = event.get("type")
            if event_type == "token":
                content = event.get("content")
                if isinstance(content, str):
                    token_chunks.append(content)
            elif event_type in {"tool_start", "tool_end"}:
                tool_events.append(event)
            elif event_type == "error":
                error_val = event.get("error")
                error = str(error_val) if error_val is not None else "unknown error"
                break
    except Exception as exc:  # pragma: no cover - defensive, surfaces in report
        error = f"{type(exc).__name__}: {exc}"

    duration = time.perf_counter() - start
    return TaskRun(
        tool_sequence=tuple(_tool_sequence_from_events(tool_events)),
        final_answer="".join(token_chunks).strip(),
        error=error,
        duration_seconds=duration,
    )


# --------------------------------------------------------------------------- #
# Judge scoring                                                                 #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RubricScore:
    question_id: str
    question: str
    max_score: int
    score: int
    justification: str
    error: str | None = None


def _build_judge_user_prompt(
    *,
    task: TaskSpec,
    run: TaskRun,
    question: RubricQuestion,
) -> str:
    tool_list = ", ".join(run.tool_sequence) if run.tool_sequence else "(none)"
    answer = run.final_answer or "(empty answer)"
    return (
        f"Task: {task.name}\n"
        f"User prompt:\n{task.prompt}\n\n"
        f"Assistant tool sequence (in call order): {tool_list}\n\n"
        f"Assistant final answer:\n{answer}\n\n"
        f"Rubric question (score 0 to {question.max_score}):\n{question.question}\n\n"
        'Return only a JSON object: {"score": <int>, "justification": "<one paragraph>"}.'
    )


def _parse_judge_response(text: str, *, max_score: int) -> tuple[int, str]:
    """Extract ``(score, justification)`` from a judge LLM response."""
    from runtime.helper_agent_runner import extract_json_object

    parsed = extract_json_object(text)
    raw_score = parsed.get("score")
    try:
        score = int(raw_score)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ValueError(f"Judge did not return an integer 'score': {raw_score!r}")
    score = max(0, min(max_score, score))
    justification = parsed.get("justification") or ""
    if not isinstance(justification, str):
        justification = str(justification)
    return score, justification.strip()


async def _score_rubric(
    *,
    task: TaskSpec,
    run: TaskRun,
    judge_role: str,
) -> list[RubricScore]:
    from runtime.model_factory import build_chat_model
    from langchain_core.messages import HumanMessage, SystemMessage

    try:
        judge = build_chat_model(judge_role, streaming=False)  # type: ignore[arg-type]
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        return [
            RubricScore(
                question_id=q.id,
                question=q.question,
                max_score=q.max_score,
                score=0,
                justification="",
                error=f"Failed to build judge model: {err}",
            )
            for q in task.rubric
        ]

    scores: list[RubricScore] = []
    for question in task.rubric:
        user_prompt = _build_judge_user_prompt(task=task, run=run, question=question)
        try:
            response = await judge.ainvoke(
                [
                    SystemMessage(content=_JUDGE_SYSTEM_PROMPT),
                    HumanMessage(content=user_prompt),
                ]
            )
            content = getattr(response, "content", "")
            text = content if isinstance(content, str) else str(content)
            score, justification = _parse_judge_response(text, max_score=question.max_score)
            scores.append(
                RubricScore(
                    question_id=question.id,
                    question=question.question,
                    max_score=question.max_score,
                    score=score,
                    justification=justification,
                )
            )
        except Exception as exc:
            scores.append(
                RubricScore(
                    question_id=question.id,
                    question=question.question,
                    max_score=question.max_score,
                    score=0,
                    justification="",
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
    return scores


# --------------------------------------------------------------------------- #
# Orchestration                                                                 #
# --------------------------------------------------------------------------- #


def _matches_tool_sequence(task: TaskSpec, run: TaskRun) -> bool:
    if not run.tool_sequence:
        # An empty sequence only passes if the regex explicitly matches "".
        return re.search(task.tool_regex, "") is not None
    joined = " ".join(run.tool_sequence)
    return re.search(task.tool_regex, joined) is not None


def _dry_run_result(task: TaskSpec) -> dict[str, Any]:
    return {
        "task_id": task.id,
        "task_name": task.name,
        "description": task.description,
        "tags": list(task.tags),
        "prompt": task.prompt,
        "dry_run": True,
        "tool_sequence": [],
        "tool_regex": task.tool_regex,
        "tool_regex_description": task.tool_regex_description,
        "tool_regex_matched": False,
        "final_answer": "",
        "duration_seconds": 0.0,
        "error": None,
        "rubric": [
            {
                "question_id": q.id,
                "question": q.question,
                "max_score": q.max_score,
                "score": 0,
                "justification": "dry-run: judge skipped",
                "error": None,
            }
            for q in task.rubric
        ],
        "total_score": 0,
        "total_max_score": sum(q.max_score for q in task.rubric),
        "passed": False,
    }


async def run_all(
    tasks: list[TaskSpec],
    *,
    judge_role: str,
    dry_run: bool,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for task in tasks:
        if dry_run:
            results.append(_dry_run_result(task))
            continue

        run = await _drive_runtime(task)
        tool_regex_matched = _matches_tool_sequence(task, run)
        rubric_scores = await _score_rubric(
            task=task,
            run=run,
            judge_role=judge_role,
        )
        total_score = sum(score.score for score in rubric_scores)
        total_max = sum(q.max_score for q in task.rubric)
        results.append(
            {
                "task_id": task.id,
                "task_name": task.name,
                "description": task.description,
                "tags": list(task.tags),
                "prompt": task.prompt,
                "dry_run": False,
                "tool_sequence": list(run.tool_sequence),
                "tool_regex": task.tool_regex,
                "tool_regex_description": task.tool_regex_description,
                "tool_regex_matched": tool_regex_matched,
                "final_answer": run.final_answer,
                "duration_seconds": round(run.duration_seconds, 3),
                "error": run.error,
                "rubric": [
                    {
                        "question_id": score.question_id,
                        "question": score.question,
                        "max_score": score.max_score,
                        "score": score.score,
                        "justification": score.justification,
                        "error": score.error,
                    }
                    for score in rubric_scores
                ],
                "total_score": total_score,
                "total_max_score": total_max,
                "passed": tool_regex_matched
                and run.error is None
                and total_max > 0
                and total_score / total_max >= 0.6,
            }
        )
    return results


# --------------------------------------------------------------------------- #
# CLI                                                                           #
# --------------------------------------------------------------------------- #


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m evals.run_evals",
        description="Run the regression eval suite against the current backend.",
    )
    parser.add_argument(
        "--tasks",
        default="",
        help="Comma-separated task IDs to run (default: all tasks in the task dir).",
    )
    parser.add_argument(
        "--task-dir",
        default=str(TASKS_DIR),
        help="Directory containing *.yaml task specs (default: backend/evals/tasks/).",
    )
    parser.add_argument(
        "--output",
        default="",
        help=(
            "Output path for the JSON report. Default: "
            "backend/evals/reports/eval-<timestamp>.json"
        ),
    )
    parser.add_argument(
        "--judge-role",
        default="verifier",
        choices=["verifier", "planner", "executor", "title"],
        help="Model role to use as the rubric judge (default: verifier).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Validate task YAMLs and emit a stub report without calling the "
            "backend or the judge model. Useful for CI smoke tests."
        ),
    )
    return parser.parse_args(argv)


def _select_tasks(all_tasks: list[TaskSpec], filter_csv: str) -> list[TaskSpec]:
    if not filter_csv.strip():
        return all_tasks
    wanted = {name.strip() for name in filter_csv.split(",") if name.strip()}
    selected = [task for task in all_tasks if task.id in wanted]
    missing = wanted - {task.id for task in selected}
    _require(not missing, f"Unknown task id(s): {', '.join(sorted(missing))}")
    return selected


def _default_report_path() -> Path:
    reports_dir = Path(__file__).resolve().parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    return reports_dir / f"eval-{stamp}.json"


def _summarize(report: dict[str, Any]) -> str:
    lines = [
        f"Eval suite finished: {len(report['results'])} task(s), "
        f"mode={'dry-run' if report['dry_run'] else 'live'}",
    ]
    for result in report["results"]:
        flag = "PASS" if result["passed"] else "FAIL"
        regex_flag = "ok" if result["tool_regex_matched"] else "miss"
        score = f"{result['total_score']}/{result['total_max_score']}"
        lines.append(
            f"  [{flag}] {result['task_id']:<24} "
            f"tools={regex_flag} score={score} "
            f"error={result['error'] or '-'}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    task_dir = Path(args.task_dir).expanduser().resolve()
    all_tasks = discover_tasks(task_dir)
    tasks = _select_tasks(all_tasks, args.tasks)

    report_path = (
        Path(args.output).expanduser().resolve() if args.output else _default_report_path()
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)

    results = asyncio.run(
        run_all(tasks, judge_role=args.judge_role, dry_run=args.dry_run)
    )

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "backend_root": str(_BACKEND_ROOT),
        "task_dir": str(task_dir),
        "judge_role": args.judge_role,
        "dry_run": args.dry_run,
        "tasks_requested": [task.id for task in tasks],
        "env": {
            "BIOAPEX_DETERMINISTIC_SEED": os.getenv("BIOAPEX_DETERMINISTIC_SEED"),
            "DEEPSEEK_API_KEY_present": bool(os.getenv("DEEPSEEK_API_KEY")),
            "OPENAI_API_KEY_present": bool(os.getenv("OPENAI_API_KEY")),
        },
        "results": results,
    }

    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(_summarize(report))
    print(f"Report written to {report_path}")

    any_failed = any(not result["passed"] for result in results)
    return 1 if (any_failed and not args.dry_run) else 0


if __name__ == "__main__":
    raise SystemExit(main())
