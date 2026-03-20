"""Deterministic gate for when BioAPEX must enter evidence-review mode."""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tools.contracts import success_result

EVIDENCE_REVIEW_GATE_TOOL_NAME = "evidence_review_gate"

_BIOLOGY_KEYWORDS = (
    "biolog",
    "gene",
    "genes",
    "protein",
    "proteins",
    "pathway",
    "signaling",
    "cell",
    "cells",
    "tissue",
    "disease",
    "mutation",
    "phenotype",
    "expression",
    "transcript",
    "receptor",
    "kinase",
    "cytokine",
    "tumor",
    "cancer",
    "immune",
    "mouse",
    "mice",
    "human",
    "drug target",
    "biomarker",
)
_EVIDENCE_KEYWORDS = (
    "evidence",
    "citation",
    "citations",
    "pmid",
    "pubmed",
    "literature",
    "consensus",
    "study",
    "studies",
    "paper",
    "papers",
    "review",
)
_REPORT_KEYWORDS = (
    "report",
    "recommend",
    "recommendation",
    "conclusion",
    "interpret",
    "interpretation",
    "summarize",
    "summary",
    "write up",
    "write-up",
)
_FACTUAL_QUESTION_RE = re.compile(
    r"^\s*(?:what|which|how|does|do|is|are|can|should|why)\b",
    re.IGNORECASE,
)
_GENE_SYMBOL_TOKEN_RE = re.compile(r"\b[A-Z0-9]{2,10}\b")
_NON_BIOLOGY_GENE_SYMBOL_TOKENS = {
    "API",
    "ASCII",
    "CLI",
    "CPU",
    "CSS",
    "CSV",
    "DNS",
    "GPU",
    "HTML",
    "HTTP",
    "HTTPS",
    "JSON",
    "JWT",
    "NPM",
    "PATH",
    "PDF",
    "RAM",
    "REST",
    "SDK",
    "SHA",
    "SQL",
    "SSH",
    "SSL",
    "TCP",
    "TLS",
    "TTY",
    "UI",
    "URI",
    "URL",
    "UTF8",
    "UUID",
    "XML",
    "YAML",
}
_NON_BIOLOGY_HINTS = (
    "pytest",
    "fastapi",
    "typescript",
    "javascript",
    "react",
    "next.js",
    "nextjs",
    "frontend",
    "backend",
    "api route",
    "bug",
    "stack trace",
    "git ",
    "pull request",
    "npm ",
    "uvicorn",
)


class EvidenceReviewGateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_message: str
    attached_identifiers: list[str] = Field(default_factory=list)
    selected_workflow: str | None = None

    @field_validator("user_message")
    @classmethod
    def _validate_user_message(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("user_message must not be empty.")
        return cleaned

    @field_validator("attached_identifiers")
    @classmethod
    def _validate_attached_identifiers(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]

    @field_validator("selected_workflow")
    @classmethod
    def _validate_selected_workflow(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


@dataclass(frozen=True)
class EvidenceReviewGateResult:
    requires_review: bool
    reasons: list[str]
    tool_input: str
    tool_summary: str
    tool_result: dict
    system_message: str | None


def _has_gene_symbol_signal(message: str) -> bool:
    for token in _GENE_SYMBOL_TOKEN_RE.findall(message):
        if token.isdigit():
            continue
        if not any(char.isalpha() for char in token):
            continue
        if token in _NON_BIOLOGY_GENE_SYMBOL_TOKENS:
            continue
        return True
    return False


def run_evidence_review_gate(payload: EvidenceReviewGateInput) -> EvidenceReviewGateResult:
    lowered = payload.user_message.casefold()

    workflow_selected = payload.selected_workflow is not None
    non_biology_hint = any(keyword in lowered for keyword in _NON_BIOLOGY_HINTS)
    gene_symbol_signal = _has_gene_symbol_signal(payload.user_message)
    biology_signal = any(keyword in lowered for keyword in _BIOLOGY_KEYWORDS) or gene_symbol_signal
    evidence_signal = any(keyword in lowered for keyword in _EVIDENCE_KEYWORDS)
    report_signal = any(keyword in lowered for keyword in _REPORT_KEYWORDS)
    factual_question_signal = bool(_FACTUAL_QUESTION_RE.match(payload.user_message)) and biology_signal

    reasons: list[str] = []
    if workflow_selected:
        reasons.append("workflow-selected")
    if non_biology_hint:
        reasons.append("non-biology-request")
    if biology_signal:
        reasons.append("biology-signal")
    if gene_symbol_signal:
        reasons.append("gene-symbol-signal")
    if evidence_signal:
        reasons.append("evidence-intent")
    if report_signal:
        reasons.append("report-or-recommendation-intent")
    if factual_question_signal:
        reasons.append("factual-biology-question")

    requires_review = (
        not workflow_selected
        and not non_biology_hint
        and biology_signal
        and (evidence_signal or report_signal or factual_question_signal)
    )

    tool_input = payload.user_message[:400]
    if requires_review:
        tool_summary = "Evidence review is required before answering this biology request."
        warnings = ["evidence_review_required"]
        system_message = (
            "Evidence-review mode is required for this turn. Before you provide any substantive "
            "biology answer, you MUST call the `evidence_review` tool. Do not emit final answer "
            "text until that tool has completed. In the final answer, clearly separate extracted "
            "source facts from synthesized conclusions, and if the tool reports insufficient or "
            "mixed evidence, make unsupported claims explicit instead of overstating certainty."
        )
    else:
        tool_summary = "Evidence review is not required for this turn."
        warnings = []
        system_message = None

    _summary, tool_result = success_result(
        EVIDENCE_REVIEW_GATE_TOOL_NAME,
        tool_summary,
        structured_payload={
            "requires_review": requires_review,
            "reasons": reasons,
            "selected_workflow": payload.selected_workflow,
            "attached_identifiers": payload.attached_identifiers,
        },
        warnings=warnings,
        metadata={
            "requires_review": requires_review,
            "workflow_selected": workflow_selected,
            "biology_signal": biology_signal,
            "gene_symbol_signal": gene_symbol_signal,
            "evidence_signal": evidence_signal,
            "report_signal": report_signal,
            "factual_question_signal": factual_question_signal,
            "non_biology_hint": non_biology_hint,
        },
    )

    return EvidenceReviewGateResult(
        requires_review=requires_review,
        reasons=reasons,
        tool_input=tool_input,
        tool_summary=tool_summary,
        tool_result=tool_result,
        system_message=system_message,
    )
