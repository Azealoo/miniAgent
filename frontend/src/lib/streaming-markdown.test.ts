import { describe, expect, it } from "vitest";
import { splitStreamingMarkdown } from "./streaming-markdown";

describe("splitStreamingMarkdown", () => {
  it("waits for a safe paragraph boundary before committing markdown", () => {
    expect(splitStreamingMarkdown("# Heading")).toEqual({
      committed: "",
      pending: "# Heading",
    });

    expect(splitStreamingMarkdown("# Heading\n\nParagraph\n\n")).toEqual({
      committed: "# Heading\n\nParagraph\n\n",
      pending: "",
    });
  });

  it("keeps fenced code buffered until the fence closes", () => {
    expect(splitStreamingMarkdown("```ts\nconst value = 1;\n")).toEqual({
      committed: "",
      pending: "```ts\nconst value = 1;\n",
    });

    expect(splitStreamingMarkdown("```ts\nconst value = 1;\n```\n")).toEqual({
      committed: "```ts\nconst value = 1;\n```\n",
      pending: "",
    });
  });

  it("commits only the completed leading blocks", () => {
    expect(splitStreamingMarkdown("Alpha\n\nBeta")).toEqual({
      committed: "Alpha\n\n",
      pending: "Beta",
    });
  });
});
