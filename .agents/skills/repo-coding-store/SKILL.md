---
name: repo-coding-store
description: Discover remote and local state ownership before changing page state.
---

# Repo Coding Store

## Purpose

Discover remote and local state ownership before changing page state.

## Context Reading

- Read `AGENTS.md` for Repo Guide entry information.
- Read relevant `repo-profile.md` sections for stable facts and boundaries only; current same-app source is primary for coding decisions.
- Inspect current repository source files only when evidence is needed.

## Observed Evidence Entry Points

- React: `apps/web/src/main.tsx`
- React: `apps/web/src/course-workflow-page.tsx`
- These sampled paths are evidence entry points only. They are not global mandatory implementation rules. Prefer same app, same framework, and same module examples over these anchors when they differ.
- Treat these as lookup anchors, not mandatory global rules, unless the user explicitly confirms a stable repository-level constraint.

## Framework-Specific Lookup

- React: Start from `apps/web/src/main.tsx` and verify adjacent files in the target module.
- Vue: No evidence found in lightweight sampling
- H5: No evidence found in lightweight sampling

## What To Inspect

- Inspect QueryClient, query keys, invalidation, polling, and component-local state.

## What To Avoid

- Do not promote React Query cache into authoritative Run facts.

## Requires Confirmation

- Confirm whether new state must survive navigation or refresh.

## Validation Hints

- Check the nearest changed files and run `npm --prefix apps/web run typecheck` for React/TypeScript changes; use the matching backend tests if the API contract changes.
- Use `repo-workflow-validation-guidance` to choose the narrowest task-specific command.

## Response Guidance

Use natural language. State the relevant current-source evidence, a narrow implementation rule, unresolved ownership, and a matching validation hint.

## Guardrails

- Do not write runtime scan results into `AGENTS.md` or `repo-profile.md`.
- Prefer current same-app, same-framework, and same-module source evidence over sampled anchors and stale assumptions.
- Keep raw source unchanged unless the user explicitly requests implementation changes.
