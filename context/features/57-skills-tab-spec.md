# Skills Tab Spec

## Overview

Implement the `Skills` inspector tab shown in `skills.png`. This phase should turn the skills surface into a lightweight registry view where users can see active capabilities, understand available extensions, and eventually manage skill installation or enablement without losing the current BioAPEX inspector style.

## Requirements

- Add a designed `Skills` tab layout that matches the screenshot structure.
- Include an `Active` section at the top showing currently active skills.
- Each active skill row should include:
  - skill name
  - version string
  - small visual cue indicating the row represents a skill/capability
- Add a second explanatory section for available skills or capability expansion.
- Include an `Install Skill` primary action styled to match the screenshot.
- Keep the tab light and readable in a narrow inspector.
- Preserve room for future controls such as:
  - enable / disable
  - inspect skill metadata
  - open skill file
  - install from registry or path
- Align this tab with the real backend skill registry and file-based skills model instead of treating it as a generic app settings surface.
- Preserve the inspector export footer at the bottom.
- Define sensible empty states for:
  - no active skills
  - no installable skills available

## References

- @context/screenshots/skills.png
- @frontend/src/components/editor/InspectorPanel.tsx
- @frontend/src/lib/api.ts
- @frontend/src/lib/types.ts
- @backend/api/skills_registry.py
- @backend/tools/skills_scanner.py

