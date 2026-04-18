import { describe, expect, it } from "vitest";
import { compactText, humanizeToken, shortIdentifier } from "./index";

describe("compactText", () => {
  it("returns null for nullish or empty input", () => {
    expect(compactText(null)).toMatchInlineSnapshot(`null`);
    expect(compactText(undefined)).toMatchInlineSnapshot(`null`);
    expect(compactText("")).toMatchInlineSnapshot(`null`);
    expect(compactText("   \n\t  ")).toMatchInlineSnapshot(`null`);
  });

  it("collapses internal whitespace and trims", () => {
    expect(
      compactText("  hello   world\nwith\ttabs  ")
    ).toMatchInlineSnapshot(`"hello world with tabs"`);
  });

  it("returns the normalized string when shorter than maxLength", () => {
    expect(compactText("short text", 64)).toMatchInlineSnapshot(`"short text"`);
  });

  it("truncates with a single-character ellipsis when longer than maxLength", () => {
    expect(compactText("abcdefghij", 5)).toMatchInlineSnapshot(`"abcd…"`);
  });

  it("returns the full value when length equals maxLength", () => {
    expect(compactText("abcde", 5)).toMatchInlineSnapshot(`"abcde"`);
  });

  it("handles unicode characters when truncating", () => {
    expect(compactText("αβγδεζηθ", 4)).toMatchInlineSnapshot(`"αβγ…"`);
  });

  it("trims trailing whitespace before appending the ellipsis", () => {
    expect(compactText("hello world goodbye", 7)).toMatchInlineSnapshot(
      `"hello…"`
    );
  });

  it("uses the default maxLength of 160", () => {
    const input = "x".repeat(200);
    const result = compactText(input);
    expect(result).not.toBeNull();
    expect(result!.length).toBe(160);
    expect(result!.endsWith("…")).toBe(true);
  });
});

describe("humanizeToken", () => {
  it("returns null for nullish or empty input", () => {
    expect(humanizeToken(null)).toMatchInlineSnapshot(`null`);
    expect(humanizeToken(undefined)).toMatchInlineSnapshot(`null`);
    expect(humanizeToken("")).toMatchInlineSnapshot(`null`);
  });

  it("replaces underscores and hyphens with spaces", () => {
    expect(humanizeToken("tool_result")).toMatchInlineSnapshot(`"tool result"`);
    expect(humanizeToken("quick-start")).toMatchInlineSnapshot(`"quick start"`);
    expect(humanizeToken("mixed_token-value")).toMatchInlineSnapshot(
      `"mixed token value"`
    );
  });

  it("leaves tokens without separators unchanged", () => {
    expect(humanizeToken("plain")).toMatchInlineSnapshot(`"plain"`);
  });

  it("does not alter casing", () => {
    expect(humanizeToken("MixedCase_Token")).toMatchInlineSnapshot(
      `"MixedCase Token"`
    );
  });
});

describe("shortIdentifier", () => {
  it("returns null for nullish or empty input", () => {
    expect(shortIdentifier(null)).toMatchInlineSnapshot(`null`);
    expect(shortIdentifier(undefined)).toMatchInlineSnapshot(`null`);
    expect(shortIdentifier("")).toMatchInlineSnapshot(`null`);
  });

  it("returns the full value when <= 18 chars", () => {
    expect(shortIdentifier("short-id")).toMatchInlineSnapshot(`"short-id"`);
    expect(shortIdentifier("a".repeat(18))).toMatchInlineSnapshot(
      `"aaaaaaaaaaaaaaaaaa"`
    );
  });

  it("abbreviates a 19-char identifier", () => {
    expect(shortIdentifier("exactlyeighteenchar")).toMatchInlineSnapshot(
      `"exactlye…enchar"`
    );
  });

  it("abbreviates longer identifiers with an ellipsis between prefix and suffix", () => {
    expect(
      shortIdentifier("0123456789abcdef0123456789")
    ).toMatchInlineSnapshot(`"01234567…456789"`);
  });

  it("abbreviates request-id style UUIDs", () => {
    expect(
      shortIdentifier("req_01HV6M9PXVGFJTXZ2A4B7RQX6W")
    ).toMatchInlineSnapshot(`"req_01HV…7RQX6W"`);
  });
});
