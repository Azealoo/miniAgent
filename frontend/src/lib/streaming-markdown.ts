export interface StreamingMarkdownSegments {
  committed: string;
  pending: string;
}

export function splitStreamingMarkdown(markdown: string): StreamingMarkdownSegments {
  const boundary = findStreamingBoundary(markdown);

  if (boundary === null) {
    return {
      committed: "",
      pending: markdown,
    };
  }

  return {
    committed: markdown.slice(0, boundary),
    pending: markdown.slice(boundary),
  };
}

function findStreamingBoundary(markdown: string): number | null {
  let inFence = false;
  let lastBoundary: number | null = null;
  let cursor = 0;

  for (const line of markdown.split(/(?<=\n)/)) {
    const trimmed = line.trimStart();

    if (trimmed.startsWith("```") || trimmed.startsWith("~~~")) {
      inFence = !inFence;
      if (!inFence) {
        lastBoundary = cursor + line.length;
      }
      cursor += line.length;
      continue;
    }

    if (!inFence && trimmed.length === 0) {
      lastBoundary = cursor + line.length;
    }

    cursor += line.length;
  }

  return lastBoundary;
}
