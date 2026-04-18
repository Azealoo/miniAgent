"use client";

export type PreviewableFileKind =
  | "table"
  | "plot"
  | "structured"
  | "report"
  | "archive"
  | "file";

export type InlinePreviewMode =
  | "text"
  | "markdown"
  | "json"
  | "html"
  | "image"
  | "pdf"
  | "unsupported";

export interface PreviewableFileInput {
  path: string;
  artifactType?: string | null;
  outputName?: string | null;
  label?: string | null;
}

export interface FilePreviewDescriptor {
  extension: string;
  kind: PreviewableFileKind;
  mode: InlinePreviewMode;
  label: string;
  title: string;
  unsupportedMessage: string | null;
}

const IMAGE_EXTENSIONS = new Set([
  ".avif",
  ".gif",
  ".jpeg",
  ".jpg",
  ".png",
  ".svg",
  ".webp",
]);

const ARCHIVE_EXTENSIONS = new Set([
  ".gz",
  ".tar",
  ".tar.gz",
  ".tgz",
  ".zip",
]);

const HTML_EXTENSIONS = new Set([".html", ".htm", ".xhtml"]);

const STRUCTURED_DATA_EXTENSIONS = new Set([".json", ".yaml", ".yml"]);

const UNSUPPORTED_INLINE_EXTENSIONS = new Set([
  ".bam",
  ".bcf",
  ".bin",
  ".cram",
  ".feather",
  ".mtx",
  ".parquet",
  ".tif",
  ".tiff",
  ".vcf.gz",
  ".xls",
  ".xlsx",
]);

const UNSUPPORTED_ARTIFACT_TYPES = new Set([
  "artifact_directory",
  "generated_output_group",
  "ro_crate",
]);

export function getPathExtension(path: string): string {
  const fileName = path.split("/").pop()?.toLowerCase() ?? path.toLowerCase();

  if (fileName.endsWith(".tar.gz")) {
    return ".tar.gz";
  }

  if (fileName.endsWith(".vcf.gz")) {
    return ".vcf.gz";
  }

  const lastDot = fileName.lastIndexOf(".");
  return lastDot >= 0 ? fileName.slice(lastDot) : "";
}

export function inferPreviewableFileKind(
  input: PreviewableFileInput
): PreviewableFileKind {
  const extension = getPathExtension(input.path);
  const artifactType = input.artifactType?.toLowerCase() ?? "";
  const outputName = input.outputName?.toLowerCase() ?? "";
  const label = input.label?.toLowerCase() ?? "";

  if (
    extension === ".csv" ||
    extension === ".tsv" ||
    extension === ".xls" ||
    extension === ".xlsx" ||
    extension === ".parquet" ||
    extension === ".mtx" ||
    artifactType.includes("matrix") ||
    artifactType.includes("results") ||
    outputName.includes("table") ||
    label.includes("matrix")
  ) {
    return "table";
  }

  if (
    IMAGE_EXTENSIONS.has(extension) ||
    extension === ".tif" ||
    extension === ".tiff" ||
    artifactType === "figure" ||
    outputName.includes("plot") ||
    outputName.includes("figure")
  ) {
    return "plot";
  }

  if (
    extension === ".json" ||
    extension === ".yaml" ||
    extension === ".yml" ||
    artifactType.includes("manifest") ||
    artifactType.includes("summary") ||
    artifactType.includes("metrics")
  ) {
    return "structured";
  }

  if (
    extension === ".html" ||
    extension === ".htm" ||
    extension === ".xhtml" ||
    extension === ".pdf" ||
    extension === ".md" ||
    artifactType.includes("report")
  ) {
    return "report";
  }

  if (ARCHIVE_EXTENSIONS.has(extension)) {
    return "archive";
  }

  return "file";
}

export function getPreviewableFileLabel(input: PreviewableFileInput): string {
  const extension = getPathExtension(input.path);
  const kind = inferPreviewableFileKind(input);

  if (extension === ".csv") return "CSV";
  if (extension === ".tsv") return "TSV";
  if (extension === ".json") return "JSON";
  if (extension === ".yaml" || extension === ".yml") return "YAML";
  if (extension === ".html" || extension === ".htm" || extension === ".xhtml") {
    return "HTML";
  }
  if (extension === ".md") return "MD";
  if (extension === ".pdf") return "PDF";
  if (IMAGE_EXTENSIONS.has(extension)) return "Image";
  if (kind === "table") return "Table";
  if (kind === "plot") return "Plot";
  if (kind === "structured") return "Data";
  if (kind === "report") return "Report";
  if (kind === "archive") return "Archive";
  return "File";
}

function isStructuredPreviewModeCandidate(
  input: PreviewableFileInput,
  kind: PreviewableFileKind
): boolean {
  const extension = getPathExtension(input.path);

  if (STRUCTURED_DATA_EXTENSIONS.has(extension)) {
    return true;
  }

  if (kind !== "structured") {
    return false;
  }

  if (
    IMAGE_EXTENSIONS.has(extension) ||
    HTML_EXTENSIONS.has(extension) ||
    extension === ".md" ||
    extension === ".pdf" ||
    ARCHIVE_EXTENSIONS.has(extension) ||
    UNSUPPORTED_INLINE_EXTENSIONS.has(extension)
  ) {
    return false;
  }

  return true;
}

function getPreviewTitle(mode: InlinePreviewMode): string {
  if (mode === "image") return "Inline image";
  if (mode === "pdf") return "Inline document";
  if (mode === "markdown") return "Markdown preview";
  if (mode === "json") return "Structured data";
  if (mode === "html") return "HTML report reference";
  if (mode === "text") return "Inline text";
  return "Open-backed artifact";
}

export function getUnsupportedPreviewMessage(input: PreviewableFileInput): string {
  const extension = getPathExtension(input.path);
  const artifactType = input.artifactType?.toLowerCase() ?? "";

  if (ARCHIVE_EXTENSIONS.has(extension)) {
    return "Archive previews are not available inline yet. Use Open raw to inspect or download the artifact.";
  }

  if (extension === ".tif" || extension === ".tiff") {
    return "This image format is not previewed inline yet. Use Open raw to inspect the artifact.";
  }

  if (
    extension === ".xls" ||
    extension === ".xlsx" ||
    extension === ".parquet" ||
    extension === ".mtx"
  ) {
    return "This generated table format is not previewed inline yet. Use Open raw to inspect the artifact.";
  }

  if (UNSUPPORTED_ARTIFACT_TYPES.has(artifactType)) {
    return "This artifact is tracked as a structured directory or package. Use Open raw or the run record to inspect it.";
  }

  return "This file is not previewed inline yet. Use Open raw to inspect the artifact.";
}

export function getFilePreviewDescriptor(
  input: PreviewableFileInput
): FilePreviewDescriptor {
  const extension = getPathExtension(input.path);
  const artifactType = input.artifactType?.toLowerCase() ?? "";
  const kind = inferPreviewableFileKind(input);

  let mode: InlinePreviewMode = "text";
  if (UNSUPPORTED_ARTIFACT_TYPES.has(artifactType)) {
    mode = "unsupported";
  } else if (IMAGE_EXTENSIONS.has(extension)) {
    mode = "image";
  } else if (extension === ".pdf") {
    mode = "pdf";
  } else if (extension === ".md") {
    mode = "markdown";
  } else if (HTML_EXTENSIONS.has(extension)) {
    mode = "html";
  } else if (isStructuredPreviewModeCandidate(input, kind)) {
    mode = "json";
  } else if (
    ARCHIVE_EXTENSIONS.has(extension) ||
    UNSUPPORTED_INLINE_EXTENSIONS.has(extension)
  ) {
    mode = "unsupported";
  }

  return {
    extension,
    kind,
    mode,
    label: getPreviewableFileLabel(input),
    title: getPreviewTitle(mode),
    unsupportedMessage:
      mode === "unsupported" ? getUnsupportedPreviewMessage(input) : null,
  };
}

export function isTextLikePreviewMode(mode: InlinePreviewMode): boolean {
  return (
    mode === "text" ||
    mode === "markdown" ||
    mode === "json" ||
    mode === "html"
  );
}

export function isRawObjectUrlPreviewMode(mode: InlinePreviewMode): boolean {
  return mode === "image" || mode === "pdf";
}

export function humanizePreviewToken(value?: string | null): string | null {
  if (!value) {
    return null;
  }

  return value.replaceAll("_", " ").replaceAll("-", " ");
}
