---
name: repo-workflow-validation-guidance
description: Choose the narrowest useful validation command for the current target, and return unresolved guidance when the target or command scope is still unclear.
---

# Repo Workflow Validation Guidance

## Purpose

Return task-level validation guidance for the current change scope.

This workflow is responsible for choosing the narrowest useful validation command only after the current target is sufficiently clear. When the target ownership, affected app, consumer scope, or command scope is still unclear, this workflow must not force a validation command. It should return unresolved guidance and explain what still needs confirmation.

This workflow does not load repository basics as its primary job, does not perform broad structure scanning, does not locate the final change target from scratch, and does not execute validation commands.

## Input Modes

Accept natural language requests, but first classify the current input into one of these modes.

Mode 1: upstream-scoped validation

- the input already contains an upstream-scoped target such as confirmed `root_path` / `file_path`, changed files, or a directly confirmed app / package target
- when the target is under `packages/**`, the input should preferably also include direct consumer clues such as consumer entry files, consuming app names, or consumer-facing changed files
- use this mode when the current context already contains an upstream-scoped target, typically from `repo-workflow-scope-change-targets`
- this mode is valid only when the current target scope is already confirmed enough for command selection
- if the upstream result still has multiple candidate targets, unresolved ownership, or unresolved shared-package consumer scope, do not treat it as a confirmed validation target
- if the upstream result has `requires confirmation: yes` but still narrows to one concrete target with one usable validation scope, you may return provisional validation guidance with a short confirmation note instead of stopping by default

Mode 2: direct-target validation

- the input comes from a direct user request that already names one precise target
- when `root_path` / `file_path` are not explicitly provided, the workflow may minimally confirm that target without broad exploration
- when the target is under `packages/**`, direct consumer clues are still preferred; without them, shared-package validation may remain unresolved
- use this mode when the user directly names one precise app, module, page, or shared package target
- this mode may perform only the minimum confirmation needed to map that one precise target to one validation scope
- this mode must not expand into broad structure scanning or replace `repo-workflow-scope-change-targets`

Mode 3: insufficient-context validation

- the input is only a general request such as "how should I validate this", "what command should I run", or "what is the smallest safe check"
- it does not clearly identify the owning app, shared package, framework surface, changed files, upstream-confirmed target scope, or package consumer scope when relevant
- in this mode, the workflow must not guess the final validation command; it should return unresolved guidance and state what target context still needs confirmation

If the current input maps to multiple apps, multiple shared packages, multiple same-level candidate targets, an unclear app-to-package ownership boundary, or a shared package without a confirmed consumer scope, treat it as insufficient context for command selection.

## Prerequisites

- Prefer to build on current context that has already loaded `repo-workflow-load-basics`.
- Prefer to build on target scope that has already been narrowed by `repo-workflow-scope-change-targets`, especially confirmed `root_path` / `file_path`, current changed files, or directly provided file paths.
- If the current context still lacks enough target information, only do minimal supplemental reading of `AGENTS.md`, `repo-profile.md`, and directly relevant target clues. Do not replace target-scoping workflows with broad source exploration here.

## Steps

1. Read `AGENTS.md` first.
2. Read the command and boundary sections from `repo-profile.md`.
3. Determine whether the current input is upstream-scoped validation, direct-target validation, or insufficient-context validation.
4. If the input is upstream-scoped validation, first check whether the upstream target is actually confirmed enough for validation selection. If the upstream result still has multiple candidates, unresolved ownership, or unresolved shared-package consumer scope, return unresolved guidance. If it narrows to one concrete target and one usable validation scope, you may still return provisional validation guidance with a short confirmation note.
5. If the input is direct-target validation and `root_path` / `file_path` are not explicitly available, do only the minimum confirmation needed to map that one precise target to one validation scope. Do not broaden this into structure scanning.
6. If the target is still unclear, maps to multiple apps or shared packages, or still lacks enough evidence to select one validation scope after upstream review or minimal confirmation, return unresolved guidance instead of forcing a command.
7. If the target is clear enough to map to one concrete validation scope, choose the narrowest meaningful validation scope using the current target app/module/shared package and directly relevant changed files or upstream-scoped `root_path` / `file_path`.
8. Treat validation commands as check commands first. Do not treat install, dev, or serve commands as the default validation result unless the user explicitly asks for runtime verification guidance, or the confirmed target is a runtime integration surface whose risk is not credibly covered by the recorded static checks alone.
9. Prefer the narrowest check command already recorded in `repo-profile.md` when that is enough for the confirmed target.
10. If `repo-profile.md` does not record a narrow enough command for a confirmed target, you may use a narrowly scoped command verified from current source evidence, but you must label it as source-verified rather than stable repo fact.
11. Do not recommend test or build commands as the default validated choice unless they are either explicitly recorded in `repo-profile.md` for the confirmed target surface, or narrowly verified from current source evidence for the confirmed target.
12. When the target is a shared package under `packages/**`, do not assume that the package-local command alone is sufficient.
13. Shared-package validation requires confirmed consumer scope unless `repo-profile.md` explicitly records a package-local check command that is sufficient for that package.
14. If a shared-package target already has confirmed consumer clues, first check whether `repo-profile.md` actually records any shared-package-local check command for that package.
15. If no shared-package-local check command is recorded, do not invent one from guesswork. You may still use a narrowly scoped package-local command only when current source files directly verify it, such as a package-local `package.json` script, a workspace script with an explicit package filter, or another target-specific script definition. Label it as source-verified rather than a repo-profile-recorded command; otherwise return only the smallest necessary consumer-scope check command set supported by `repo-profile.md`.
16. If a shared-package-local check command is explicitly recorded in `repo-profile.md`, or source-verified from the current source files, you may include it before the directly affected consumer-scope checks.
17. If a shared-package target does not yet have confirmed consumer scope, return unresolved guidance instead of giving only a generic warning.
18. In this repository, when the confirmed target crosses the React frontend, API, or Worker through startup linkage recorded in `repo-profile.md`, and recorded static checks cannot credibly cover that integration risk, you may return the narrowest runtime verification command set as a fallback. Label it as runtime verification guidance rather than a static check.
19. Return the selected validation commands directly when the command scope is clear. Add only the shortest explanation or caveat that materially affects execution.

## Decision Rules

Use this priority order when choosing the output.

1. Clear single-target command
   - the owning app or shared package is clear
   - the validation scope can be narrowed to one meaningful command
   - return that command directly
2. Clear target but multiple required checks
   - the owning target is clear, and the shared-package consumer scope or cross-surface verification scope is also clear
   - one command is not enough because the directly affected consumer scope must be checked, because a cross-surface runtime linkage must be verified, or because an additional shared-package-local check may be included only when it is explicitly recorded in `repo-profile.md` or directly source-verified from current source files
   - return the smallest necessary command set in execution order, and explain why more than one check is required
3. Provisional single-target guidance
   - the upstream result still has `requires confirmation: yes`, but it already narrows to one concrete target and one usable validation scope
   - return the narrowest useful command with a short note about what still needs confirmation
4. Unresolved validation guidance
   - the owning app, shared package, framework surface, changed-file scope, or shared-package consumer scope is still unclear
   - or an upstream-scoped input still cannot be narrowed to one concrete validation scope
   - or a precise natural-language target still cannot be minimally confirmed into one validation scope
   - return unresolved guidance and name the missing confirmation points rather than guessing

## Output Focus

- keep `Status` and `Summary` as the only fixed head
- the exact validation commands the user should run
- the smallest necessary command set when a clear shared-package or cross-surface target requires more than one check
- unresolved guidance when the target or command scope is still unclear
- prerequisites or caveats only when they materially affect execution

## Default Output

Always start with:

- `Status`
- `Summary`

Use `Status: resolved` when the target and command scope are clear enough to return one concrete validation command or one smallest necessary command set.

Use `Status: provisional` when the upstream result still carries `requires confirmation: yes`, but it already narrows to one concrete target and one usable validation scope.

Use `Status: unresolved` when target ownership, affected app, shared-package consumer scope, framework surface, or command scope is still too unclear to choose one validation scope.

Keep `Summary` to 2 to 4 short bullets. It should state the validation conclusion, not restate every command line or repeat all missing confirmation points.

When `Status: resolved` or `Status: provisional`, prefer this output shape:

```text
Status
- resolved

Summary
- `...`

Validation commands
- `...`
```

If more than one check is required, keep the output equally compact:

```text
Status
- resolved

Summary
- `...`

Validation commands
- `...`
- `...`

Why these checks
- `...`
```

For provisional single-target guidance, you may use:

```text
Status
- provisional

Summary
- `...`

Validation commands
- `...`

Needs confirmation
- `...`
```

When the target is still unclear, prefer unresolved guidance:

```text
Status
- unresolved

Summary
- `...`

Needs confirmation
- the confirmed `root_path`
- the first-pass `file_path`
- whether the upstream scope is already confirmed
- whether the target is app-local or under `packages/**`
- the consumer app or consumer entry, if `root_path` is under `packages/**`
```

## Guardrails

- Do not execute commands.
- Keep `Status` and `Summary` as the only fixed head. All other sections are conditional on what the current request actually needs.
- Do not restate broad repository overview content unless it changes the validation choice.
- Do not use this workflow as a substitute for `repo-workflow-load-basics`; repository-level command coverage summary belongs there.
- Do not use this workflow as a substitute for `repo-workflow-scope-change-targets`; if the target is still ambiguous, return unresolved guidance first.
- Do not treat upstream candidate targets, multi-candidate upstream results, or unresolved shared-package consumer scope as confirmed validation scope.
- Do not block on `requires confirmation: yes` by default when the upstream result still narrows to one concrete target and one usable validation scope; in that case return provisional guidance with a short note instead.
- When `Status: unresolved`, do not emit `Validation commands`, `Why these checks`, or `Note` as if command scope had already been finalized.
- When `Status: resolved` or `Status: provisional`, return the narrowest meaningful command scope. Do not widen into repo-level command menus.
- Do not force one command when multiple apps, shared packages, or framework surfaces are still in play.
- Do not return install, dev, or serve commands as validation conclusions by default. They are allowed only when the user explicitly asks for runtime verification guidance, or when the confirmed target is a runtime-linked integration surface that is not credibly covered by the recorded static checks alone.
- Do not claim that a shared-package change is fully validated by one command unless the package boundary and consumer impact are already clear.
- Do not recommend test or build commands by default when they are not explicitly recorded in `repo-profile.md` for the confirmed target surface, unless the command is narrowly source-verified for the confirmed target from current source files.
- Prefer this command-source priority: 1) commands explicitly recorded in `repo-profile.md` for the confirmed target surface; 2) narrowly scoped commands directly source-verified from current source files; 3) runtime verification guidance only when the first two are not enough to credibly cover a confirmed integration risk.
- If a command is not explicitly recorded in `repo-profile.md` and cannot be directly verified from current source files, do not recommend it.
- When a command is derived from current source evidence rather than `repo-profile.md`, do not expand into process explanation; only add a short note if that distinction materially affects how confidently the user should treat the command.
- When `repo-profile.md` already records a runtime linkage for the confirmed target surface, you may use that recorded startup chain as runtime verification guidance when static checks alone are not enough; keep the returned command set as small as possible.
- Output natural language text only.
