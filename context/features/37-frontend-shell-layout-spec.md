# Frontend Shell Layout Spec

## Overview

Build the main BioAPEX desktop shell that matches the revised dashboard design in `@context/screenshots/dashboard.png`. This phase should establish the overall page structure only: top bar, compact left rail, dominant center workspace, and right inspector. The goal is to lock in proportions, spacing, and panel behavior before refining individual components.

## Requirements

- Implement a three-column desktop application shell with:
  - a compact left sidebar for navigation and session context
  - a dominant center workspace for the active conversation and workflow state
  - a lighter right inspector for run, files, and supporting metadata
- Keep the top navigation bar fixed at the top and visually separate it from the working surface.
- Update default panel widths so the center workspace is the clear primary focus.
- Keep resize handles usable, but make them visually quiet so they do not dominate the interface.
- Preserve the white/light neutral background and the green-centered BioAPEX visual language used in the dashboard reference.
- Make the shell feel calm and premium:
  - generous horizontal rhythm
  - subtle borders
  - restrained shadows
  - rounded panel corners
- Ensure the shell still works at common laptop widths before any mobile-specific design work begins.
- Do not introduce placeholder panels. Even in this phase, each column should have realistic structure and spacing so downstream component phases inherit a stable frame.

## References

- @context/screenshots/dashboard.png
- @frontend/src/app/page.tsx
- @frontend/src/app/globals.css
- @frontend/src/components/layout/Navbar.tsx
- @frontend/src/components/layout/Sidebar.tsx
- @frontend/src/components/chat/ChatPanel.tsx
- @frontend/src/components/editor/InspectorPanel.tsx
- @frontend/src/components/layout/ResizeHandle.tsx

