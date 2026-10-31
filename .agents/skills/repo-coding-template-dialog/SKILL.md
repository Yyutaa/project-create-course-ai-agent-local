---
name: repo-coding-template-dialog
description: Choose same-app dialog references before using a fallback structure sketch.
---

# Repo Coding Template Dialog

## Purpose

Choose same-app dialog references before using a fallback structure sketch.

## Context Reading

- Read `AGENTS.md` for Repo Guide entry information.
- Read relevant `repo-profile.md` sections for stable facts and boundaries only; current same-app source is primary for coding decisions.
- Inspect current repository source files only when evidence is needed.

## Observed Evidence Entry Points

- React: `apps/web/src/llm-config-dialog.tsx`
- React: `apps/web/src/course-workflow-page.tsx`
- These sampled paths are evidence entry points only. They are not global mandatory implementation rules. Prefer same app, same framework, and same module examples over these anchors when they differ.
- Treat these as lookup anchors, not mandatory global rules, unless the user explicitly confirms a stable repository-level constraint.

## Framework-Specific Lookup

- React: Start from `apps/web/src/llm-config-dialog.tsx` and verify adjacent files in the target module.
- Vue: No evidence found in lightweight sampling
- H5: No evidence found in lightweight sampling

## What To Inspect

- Inspect open/close lifecycle, submit state, focus behavior, and evidenced dialog components.

## What To Avoid

- Do not copy the inline sketch as implementation or default to a hand-written modal.

## Requires Confirmation

- Confirm dialog ownership and library availability before implementation.

## Validation Hints

- Check the nearest changed files and run `npm --prefix apps/web run typecheck` for React/TypeScript changes; use the matching backend tests if the API contract changes.
- Use `repo-workflow-validation-guidance` to choose the narrowest task-specific command.

## Response Guidance

Use natural language. State the relevant current-source evidence, a narrow implementation rule, unresolved ownership, and a matching validation hint.

## Guardrails

- Do not write runtime scan results into `AGENTS.md` or `repo-profile.md`.
- Prefer current same-app, same-framework, and same-module source evidence over sampled anchors and stale assumptions.
- Keep raw source unchanged unless the user explicitly requests implementation changes.

## React Template

Structure sketch only; fallback only; not copy-ready code. Prefer same-app examples and the component libraries actually evidenced in the target repository.

```text
apps/web/src/<dialog>.tsx
  [evidenced component-library dialog/drawer] -> open/close/focus
  [evidenced component-library fields/actions] -> pending/error/confirm
owning page -> trigger and result handling
```

## H5 Template

Structure sketch only; use only after confirming an H5 target and its mobile component library. No H5 source was found in lightweight sampling.

```text
[confirmed H5 page root]/<page>
  [evidenced mobile component-library control] -> loading/error/action
  [same-app route and API entries] -> navigation and request
```

## Template Application Rules

- Confirm target app, root, and framework from `repo-profile.md` and current source.
- Prefer, in order: user reference module; same-app and same-framework example; evidenced component-library pattern; then the inline sketch.
- The current package manifest shows no dedicated UI component library; verify it again before choosing controls.
- Do not default to custom hand-written table, form, modal, drawer, list, or bottom-sheet UI.
- Use the sketch only for confirmed React or H5 targets when higher-priority references are unavailable. For Vue, inspect same-app Vue source and request confirmation.
- Link applicable route, API, component, and state rule skills before implementation.
