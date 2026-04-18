# Docs Workspace Spec

## Overview

Build the `Docs` workspace shown in `docs.png`. This phase should create a dedicated documentation surface for protocols, specs, and reference materials so BioAPEX can support structured reading and implementation work directly inside the app.

## Requirements

- Render a dedicated `Documentation` center workspace when the `Docs` mode is selected.
- Include a page title and subtitle that position the area as a home for SOPs, specs, and reference material.
- Split the center workspace into two coordinated areas:
  - a document list or navigator
  - a selected document reading pane
- In the document list, support rows/cards that show:
  - document title
  - document type label such as SOP, Reference, or Spec
  - active/selected document state
- In the reading pane, support:
  - document title
  - document type badge
  - lightweight document metadata such as updated time or section count
  - structured sections rendered as readable content cards
- Make the reading experience feel purpose-built for BioAPEX specs and protocols:
  - strong section headings
  - comfortable body text
  - clearly segmented sections
- Ensure the structure can naturally support documents that follow:
  - Overview
  - Requirements
  - References
- Keep the visual density moderate so longer documents remain readable.
- Define empty and loading states for both the document list and the selected document pane.

## References

- @context/screenshots/docs.png
- @context/project-overview.md
- @context/coding-standards.md
- @context/ai-interaction.md
- @context/current-feature.md
- @frontend/src/app/page.tsx
- @frontend/src/components/layout/Sidebar.tsx

