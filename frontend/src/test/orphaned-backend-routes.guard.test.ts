import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const PROJECT_ROOT = path.resolve(__dirname, "../..");
const SRC_ROOT = path.resolve(__dirname, "..");
const TEXT_EXTENSIONS = new Set([".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"]);

// Backend routes deleted per backend/tests/test_chat_engine_health.py — the app
// module must not import api.audit, api.connectors, api.observability,
// api.skills_registry, or api.studies. The corresponding frontend helpers
// (listSkillsRegistry, /api/studies, etc.) have no server to call, so guard
// against accidental re-introduction here.
const ORPHANED_ROUTE_PATTERN =
  /\/api\/(studies|artifacts\/registry|audit\/events|observability|connectors\/registry|skills\/registry)(\/|["'`\s,)\]]|$)/;
const ORPHANED_IDENTIFIERS = ["listSkillsRegistry"] as const;

function listSourceFiles(dir: string): string[] {
  const results: string[] = [];
  const entries = readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    if (entry.name === "node_modules" || entry.name.startsWith(".")) continue;
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      results.push(...listSourceFiles(fullPath));
      continue;
    }
    if (!entry.isFile()) continue;
    if (!TEXT_EXTENSIONS.has(path.extname(entry.name))) continue;
    // Skip this guard file itself — its pattern literals would self-trigger.
    if (fullPath === __filename) continue;
    results.push(fullPath);
  }
  return results;
}

function relativeToProject(filePath: string): string {
  return path.relative(PROJECT_ROOT, filePath);
}

describe("frontend does not re-introduce orphaned backend surfaces", () => {
  const sourceFiles = listSourceFiles(SRC_ROOT).filter(
    (filePath) => statSync(filePath).size > 0
  );

  it("has source files to scan", () => {
    expect(sourceFiles.length).toBeGreaterThan(0);
  });

  it("does not reference removed API route paths", () => {
    const offenders = sourceFiles.filter((filePath) => {
      const contents = readFileSync(filePath, "utf8");
      return ORPHANED_ROUTE_PATTERN.test(contents);
    });

    expect(
      offenders.map(relativeToProject),
      "Frontend source references a backend route removed by the chat-engine trim. See backend/tests/test_chat_engine_health.py."
    ).toEqual([]);
  });

  it.each(ORPHANED_IDENTIFIERS)(
    "does not reference the removed identifier %s",
    (identifier) => {
      const needle = new RegExp(`\\b${identifier}\\b`);
      const offenders = sourceFiles.filter((filePath) => {
        const contents = readFileSync(filePath, "utf8");
        return needle.test(contents);
      });

      expect(
        offenders.map(relativeToProject),
        `Frontend source references ${identifier}, which was removed along with its backend route.`
      ).toEqual([]);
    }
  );
});
