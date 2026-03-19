# Start Action

1. Read current-feature.md - verify Goals are populated
2. If empty, error: "Run /feature load first"
3. Set Status to "In Progress"
4. Read any relevant files in `context/features/`, `context/project-overview.md`, `context/coding-standards.md`, and `context/ai-interaction.md`
5. Identify the concrete backend, frontend, schema, workflow, or artifact files that the feature touches
6. List the goals, then implement them one by one
7. Preserve existing contracts unless the feature explicitly changes them:
   - session compatibility
   - SSE event shapes
   - file API behavior
   - skill loading behavior
8. Only create or switch branches if the user explicitly wants branch workflow for the task
