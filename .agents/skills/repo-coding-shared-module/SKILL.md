---
name: repo-coding-shared-module
description: Discover shared package and consumer ownership before proposing cross-app reuse.
---

# Repo Coding Shared Module

## Purpose

Discover shared package and consumer ownership before proposing cross-app reuse.

## Context Reading

- Read `AGENTS.md` for Repo Guide entry information.
- Read relevant `repo-profile.md` sections for stable facts and boundaries only; current same-app source is primary for coding decisions.
- Inspect current repository source files only when evidence is needed.

## Observed Evidence Entry Points

- No evidence found in lightweight sampling
- These sampled paths are evidence entry points only. They are not global mandatory implementation rules. Prefer same app, same framework, and same module examples over these anchors when they differ.
- Treat these as lookup anchors, not mandatory global rules, unless the user explicitly confirms a stable repository-level constraint.

## Framework-Specific Lookup

- React: No evidence found in lightweight sampling
- Vue: No evidence found in lightweight sampling
- H5: No evidence found in lightweight sampling

## What To Inspect

- Check for an actual packages root, imports, and consumers before proposing extraction.

## What To Avoid

- Do not classify apps/api as a frontend shared package.

## Requires Confirmation

- Confirm consumers and ownership before creating a new shared package.

## Validation Hints

- Check the nearest changed files and run `npm --prefix apps/web run typecheck` for React/TypeScript changes; use the matching backend tests if the API contract changes.
- Use `repo-workflow-validation-guidance` to choose the narrowest task-specific command.

## Response Guidance

Use natural language. State the relevant current-source evidence, a narrow implementation rule, unresolved ownership, and a matching validation hint.

## Guardrails

- Do not write runtime scan results into `AGENTS.md` or `repo-profile.md`.
- Prefer current same-app, same-framework, and same-module source evidence over sampled anchors and stale assumptions.
- Keep raw source unchanged unless the user explicitly requests implementation changes.
