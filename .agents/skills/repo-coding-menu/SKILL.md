---
name: repo-coding-menu
description: Discover navigation registration and ownership for the target app.
---

# Repo Coding Menu

## Purpose

Discover navigation registration and ownership for the target app.

## Context Reading

- Read `AGENTS.md` for Repo Guide entry information.
- Read relevant `repo-profile.md` sections for stable facts and boundaries only; current same-app source is primary for coding decisions.
- Inspect current repository source files only when evidence is needed.

## Observed Evidence Entry Points

- React: `apps/web/src/components/layout.tsx`
- React: `apps/web/src/App.tsx`
- These sampled paths are evidence entry points only. They are not global mandatory implementation rules. Prefer same app, same framework, and same module examples over these anchors when they differ.
- Treat these as lookup anchors, not mandatory global rules, unless the user explicitly confirms a stable repository-level constraint.

## Framework-Specific Lookup

- React: Start from `apps/web/src/components/layout.tsx` and verify adjacent files in the target module.
- Vue: No evidence found in lightweight sampling
- H5: No evidence found in lightweight sampling

## What To Inspect

- Inspect the active navigation list, route destinations, and page entry before changing a menu item.

## What To Avoid

- Do not infer a portal or permission system from a visible navigation item.

## Requires Confirmation

- Confirm a new navigation destination when the request does not identify its page.

## Validation Hints

- Check the nearest changed files and run `npm --prefix apps/web run typecheck` for React/TypeScript changes; use the matching backend tests if the API contract changes.
- Use `repo-workflow-validation-guidance` to choose the narrowest task-specific command.

## Response Guidance

Use natural language. State the relevant current-source evidence, a narrow implementation rule, unresolved ownership, and a matching validation hint.

## Guardrails

- Do not write runtime scan results into `AGENTS.md` or `repo-profile.md`.
- Prefer current same-app, same-framework, and same-module source evidence over sampled anchors and stale assumptions.
- Keep raw source unchanged unless the user explicitly requests implementation changes.
