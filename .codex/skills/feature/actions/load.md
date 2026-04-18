# Load Action

1. Check $ARGUMENTS (after "load"):
   - If it looks like a filename (single word, no spaces): Look for `context/features/{name}.md`
   - If it's multiple words: Use as inline feature description, generate goals
   - If empty: Error - "load" requires a spec filename or feature description

2. Update current-feature.md:
   - Keep the H1 as `# Current Feature`
   - Set Status to "Not Started"
   - Write goals as direct, implementation-oriented bullet points under `## Goals`
   - Write implementation constraints, file paths, assumptions, and structure notes under `## Notes`
   - If useful, include the feature name as the first note line rather than changing the H1

3. The loaded feature should be specific enough that implementation can begin without guessing the logic.

4. Confirm the spec loaded and show:
   - feature name
   - goals
   - key notes or constraints
