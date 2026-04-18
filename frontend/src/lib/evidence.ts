import type {
  ConfidenceLevel,
  EvidenceArtifactReference,
  EvidenceRetrievalCardSummary,
  EvidenceRetrievalFailure,
  EvidenceRetrievalPayload,
  EvidenceReviewConclusion,
  EvidenceReviewExcludedEvidence,
  EvidenceReviewPayload,
  EvidenceReviewSourceFact,
  EvidenceReviewStatus,
  JsonValue,
  ToolResultEnvelope,
} from "./types";

export interface EvidenceArtifactMetadata {
  artifactType: string;
  title: string | null;
  identifier: string | null;
  studyType: string | null;
  confidence: ConfidenceLevel | null;
}

function asRecord(
  value: JsonValue | undefined | null
): Record<string, JsonValue> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }

  return value as Record<string, JsonValue>;
}

function asArray(value: JsonValue | undefined): JsonValue[] {
  return Array.isArray(value) ? value : [];
}

function asString(value: JsonValue | undefined): string | null {
  return typeof value === "string" ? value : null;
}

function asBoolean(value: JsonValue | undefined): boolean | null {
  return typeof value === "boolean" ? value : null;
}

function asNumber(value: JsonValue | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asStringArray(value: JsonValue | undefined): string[] {
  return asArray(value).filter((item): item is string => typeof item === "string");
}

function asConfidenceLevel(value: JsonValue | undefined): ConfidenceLevel | null {
  if (value === "low" || value === "medium" || value === "high") {
    return value;
  }

  return null;
}

function asEvidenceReviewStatus(
  value: JsonValue | undefined
): EvidenceReviewStatus | null {
  if (
    value === "supported" ||
    value === "mixed" ||
    value === "insufficient_evidence"
  ) {
    return value;
  }

  return null;
}

function parseArtifactReference(value: JsonValue): EvidenceArtifactReference | null {
  const record = asRecord(value);
  if (!record) {
    return null;
  }

  const artifactType = asString(record.artifact_type);
  const path = asString(record.path);
  if (!artifactType || !path) {
    return null;
  }

  return {
    artifact_type: artifactType,
    path,
    id: asString(record.id),
    run_id: asString(record.run_id),
  };
}

function stripQuotedScalar(value: string): string {
  const trimmed = value.trim();
  if (
    (trimmed.startsWith('"') && trimmed.endsWith('"')) ||
    (trimmed.startsWith("'") && trimmed.endsWith("'"))
  ) {
    return trimmed.slice(1, -1);
  }

  return trimmed;
}

function readYamlTopLevelScalar(content: string, key: string): string | null {
  const escapedKey = key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = content.match(new RegExp(`^${escapedKey}:\\s*(.+)$`, "m"));
  if (!match?.[1]) {
    return null;
  }

  const value = stripQuotedScalar(match[1]);
  if (value === "" || value === "null") {
    return null;
  }

  return value;
}

function readRecordMetadata(
  record: Record<string, unknown>
): EvidenceArtifactMetadata | null {
  const artifactType =
    typeof record.artifact_type === "string" ? record.artifact_type : null;
  if (!artifactType) {
    return null;
  }

  const title = typeof record.title === "string" ? record.title : null;
  const identifier =
    typeof record.stable_identifier === "string"
      ? record.stable_identifier
      : typeof record.id === "string"
        ? record.id
        : null;
  const studyType =
    typeof record.study_type === "string" ? record.study_type : null;
  const confidence = asConfidenceLevel(record.confidence as JsonValue | undefined);

  return {
    artifactType,
    title,
    identifier,
    studyType,
    confidence,
  };
}

function parseEvidenceRetrievalCard(
  value: JsonValue
): EvidenceRetrievalCardSummary | null {
  const record = asRecord(value);
  if (!record) {
    return null;
  }

  const pmid = asString(record.pmid);
  const title = asString(record.title);
  const stableIdentifier = asString(record.stable_identifier);
  const artifactPath = asString(record.artifact_path);
  if (!pmid || !title || !stableIdentifier || !artifactPath) {
    return null;
  }

  return {
    pmid,
    title,
    stable_identifier: stableIdentifier,
    study_type: asString(record.study_type),
    artifact_path: artifactPath,
    cached_raw_payload_path: asString(record.cached_raw_payload_path),
    retrieval_context_path: asString(record.retrieval_context_path),
    esearch_payload_path: asString(record.esearch_payload_path),
    esummary_payload_path: asString(record.esummary_payload_path),
    run_id: asString(record.run_id),
    claim_count: asNumber(record.claim_count) ?? 0,
    limitation_count: asNumber(record.limitation_count) ?? 0,
    entity_tags: record.entity_tags,
    grounded_entities: record.grounded_entities,
    grounding_results: record.grounding_results,
    grounding_requires_clarification:
      asBoolean(record.grounding_requires_clarification) ?? false,
    entity_grounding_path: asString(record.entity_grounding_path),
  };
}

function parseEvidenceRetrievalFailure(
  value: JsonValue
): EvidenceRetrievalFailure | null {
  const record = asRecord(value);
  if (!record) {
    return null;
  }

  const pmid = asString(record.pmid);
  const error = asString(record.error);
  if (!pmid || !error) {
    return null;
  }

  return { pmid, error };
}

function parseEvidenceReviewExcluded(
  value: JsonValue
): EvidenceReviewExcludedEvidence | null {
  const record = asRecord(value);
  if (!record) {
    return null;
  }

  const evidenceId = asString(record.evidence_id);
  const reason = asString(record.reason);
  if (!evidenceId || !reason) {
    return null;
  }

  return {
    evidence_id: evidenceId,
    artifact: parseArtifactReference(record.artifact) ?? null,
    reason,
  };
}

function parseEvidenceReviewSourceFact(
  value: JsonValue
): EvidenceReviewSourceFact | null {
  const record = asRecord(value);
  if (!record) {
    return null;
  }

  const statement = asString(record.statement);
  if (!statement) {
    return null;
  }

  return {
    statement,
    claim_id: asString(record.claim_id),
    stable_identifier: asString(record.stable_identifier),
    evidence: parseArtifactReference(record.evidence) ?? null,
    confidence: asConfidenceLevel(record.confidence),
  };
}

function parseEvidenceReviewConclusion(
  value: JsonValue
): EvidenceReviewConclusion | null {
  const record = asRecord(value);
  if (!record) {
    return null;
  }

  const statement = asString(record.statement);
  if (!statement) {
    return null;
  }

  return {
    statement,
    support_status: asEvidenceReviewStatus(record.support_status),
    confidence: asConfidenceLevel(record.confidence),
    supporting_evidence: asArray(record.supporting_evidence)
      .map(parseArtifactReference)
      .filter((item): item is EvidenceArtifactReference => item !== null),
    limitation_notes: asStringArray(record.limitation_notes),
    conflict_notes: asStringArray(record.conflict_notes),
  };
}

export function getEvidenceRetrievalPayload(
  result?: ToolResultEnvelope
): EvidenceRetrievalPayload | null {
  const record = asRecord(result?.structured_payload);
  if (!record || !Array.isArray(record.cards)) {
    return null;
  }

  return {
    query: asString(record.query),
    candidate_records: asArray(record.candidate_records),
    selected_pmids: asStringArray(record.selected_pmids),
    retrieval_context_run_id: asString(record.retrieval_context_run_id),
    retrieval_context_path: asString(record.retrieval_context_path),
    esearch_payload_path: asString(record.esearch_payload_path),
    esummary_payload_path: asString(record.esummary_payload_path),
    cards: asArray(record.cards)
      .map(parseEvidenceRetrievalCard)
      .filter((item): item is EvidenceRetrievalCardSummary => item !== null),
    failures: asArray(record.failures)
      .map(parseEvidenceRetrievalFailure)
      .filter((item): item is EvidenceRetrievalFailure => item !== null),
  };
}

export function getEvidenceReviewPayload(
  result?: ToolResultEnvelope
): EvidenceReviewPayload | null {
  const record = asRecord(result?.structured_payload);
  if (
    !record ||
    (typeof record.review_status !== "string" &&
      typeof record.requires_review !== "boolean")
  ) {
    return null;
  }

  return {
    question: asString(record.question),
    review_status: asEvidenceReviewStatus(record.review_status),
    confidence: asConfidenceLevel(record.confidence),
    unsupported_claims_present:
      asBoolean(record.unsupported_claims_present) ?? undefined,
    artifact_path: asString(record.artifact_path),
    evidence_included: asArray(record.evidence_included)
      .map(parseArtifactReference)
      .filter((item): item is EvidenceArtifactReference => item !== null),
    evidence_excluded: asArray(record.evidence_excluded)
      .map(parseEvidenceReviewExcluded)
      .filter((item): item is EvidenceReviewExcludedEvidence => item !== null),
    limitations: asStringArray(record.limitations),
    unresolved_conflicts: asStringArray(record.unresolved_conflicts),
    source_facts: asArray(record.source_facts)
      .map(parseEvidenceReviewSourceFact)
      .filter((item): item is EvidenceReviewSourceFact => item !== null),
    synthesized_conclusions: asArray(record.synthesized_conclusions)
      .map(parseEvidenceReviewConclusion)
      .filter((item): item is EvidenceReviewConclusion => item !== null),
    requires_review: asBoolean(record.requires_review) ?? undefined,
    reasons: asStringArray(record.reasons),
  };
}

export function parseEvidenceArtifactMetadata(
  path: string,
  content: string
): EvidenceArtifactMetadata | null {
  const normalizedPath = path.toLowerCase();

  if (normalizedPath.endsWith(".json")) {
    try {
      const parsed = JSON.parse(content) as unknown;
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        return null;
      }
      return readRecordMetadata(parsed as Record<string, unknown>);
    } catch {
      return null;
    }
  }

  if (normalizedPath.endsWith(".yaml") || normalizedPath.endsWith(".yml")) {
    const artifactType = readYamlTopLevelScalar(content, "artifact_type");
    if (!artifactType) {
      return null;
    }

    return {
      artifactType,
      title: readYamlTopLevelScalar(content, "title"),
      identifier:
        readYamlTopLevelScalar(content, "stable_identifier") ??
        readYamlTopLevelScalar(content, "id"),
      studyType: readYamlTopLevelScalar(content, "study_type"),
      confidence: asConfidenceLevel(
        readYamlTopLevelScalar(content, "confidence") as JsonValue | undefined
      ),
    };
  }

  return null;
}
