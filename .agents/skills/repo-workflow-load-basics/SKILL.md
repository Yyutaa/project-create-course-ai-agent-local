---
name: repo-workflow-load-basics
description: Load stable repository facts and confirmed boundaries from AGENTS.md and repo-profile.md before request-time analysis.
---

# Repo Workflow Load Basics

## Purpose

This skill is phase one of the Repo Guide workflow. It only loads repository-level stable facts, Repo Guide entry status, and confirmed boundaries, as the prerequisite layer for later structure scanning, target locating, impact analysis, and validation guidance.

This skill does not perform request-time structure scanning, does not locate change targets, does not analyze diffs, does not choose validation commands, and does not run validation.

## Inputs

Accept natural language requests. No extra structured input fields are required.

Interpret the current request in one of these two modes first:

- `entry-status mode`
  - the user is checking whether Repo Guide entry files and entry registration are present or complete
  - typical requests include Repo Guide entry status, bootstrap completeness, or whether repository facts are already recorded
- `stable-facts mode`
  - the user is asking for repository-level stable facts that depend on `repo-profile.md`, such as repo kind, framework map, app/package map, business scope, runtime model, shared-package boundaries, or repository-level command coverage

Common input scenarios include:

- load repository basics
- check which apps exist in this repository
- check how apps in this repository are started
- check Repo Guide entry status
- check where stable facts are recorded
- check repo kind, framework map, and app/package map
- check business scope, runtime model, and shared-package boundaries
- check repository-level command coverage
- confirm which established boundaries later workflow skills should build on

If the user only says something short such as "repo overview", "basic repo info", or "load repo info first", interpret it as natural language and return repository-level stable facts.

## Routing Boundaries

This workflow is only for repository-level stable facts, Repo Guide entry status, confirmed boundaries, and repository-level command coverage.

If the request is asking about a concrete page, module, route, file path, change target, impacted page, or task-level validation command choice, do not continue as `repo-workflow-load-basics`. Briefly explain that this workflow only returns repository-level stable facts, then point to the next workflow:

- repository-level app map, framework map, business scope, runtime model, or recorded command coverage -> stay in `repo-workflow-load-basics`
- tree-like structure, directory hierarchy, module layout, page-layer layout, or package-layout scanning -> `repo-workflow-scan-structure`
- change target or file-scope questions -> `repo-workflow-scope-change-targets`
- task-level validation choice -> `repo-workflow-validation-guidance`

## Steps

1. Read `AGENTS.md` first when it exists, and check the Repo Guide marker block, `repo-profile.md`, the skills root, workflow skills, and coding rule skills.
2. First determine whether the current request is `entry-status mode` or `stable-facts mode`.
3. In `entry-status mode`, first report the presence or absence of `AGENTS.md`, `repo-profile.md`, and the skills root, then check workflow skill registration and coding skill registration based on the files that do exist.
4. In `stable-facts mode`, read the stable-fact sections in `repo-profile.md` that are relevant to the current request.
5. By default, return results based only on `AGENTS.md` and `repo-profile.md`, without doing request-time structure scanning.
6. Only when `repo-profile.md` exists but is clearly stale or explicitly contradicted by current code, do the minimum necessary source verification. Do not broadly scan the whole source tree.
7. Return only repository-level stable facts, confirmed boundaries, repository-level command coverage summary, entry-status results when requested, and low-confidence facts that require confirmation.

## Allowed Supplemental Verification

When `repo-profile.md` exists but looks stale or contradicted, the supplemental verification must stay minimal. It may only be used to confirm:

- whether an app root or shared-package root still exists
- whether a framework classification can be confirmed from a package manifest or an app entry file
- whether a command recorded in `repo-profile.md` still exists in the current source

Do not expand this supplemental verification into:

- page-level structure scanning
- route-level ownership checking
- change-target locating
- impact analysis
- task-level validation choice

## Default Output

- Default to natural language text. Do not output JSON.
- Always start with:
  - `Status`: `resolved` | `partial` | `blocked`
  - `Summary`: 2 to 4 short bullets that answer only the most relevant repository-level conclusion for the current request
- Output only repository-level stable facts. Do not mix in request-time structure scans, change targets, impact analysis, or validation decisions.
- Tailor the answer to the current request as much as possible:
  - If the user only asks how the repository is started, prioritize repository-level command coverage summary and where command facts are recorded.
  - If the user only asks for app/package mapping, prioritize repo kind, framework map, and app/package map.
  - If the user only asks for Repo Guide entry status, prioritize `AGENTS.md`, `repo-profile.md`, the skills root, and registered skills information.
- When the request is `entry-status mode`, missing entry files should be reported as current status, not treated as a hard failure by default.
- When the request is `stable-facts mode`, stop only when the requested stable facts depend on a missing entry file and cannot be answered from the remaining entry files.
- Use `Status: resolved` when the requested stable facts can be answered from the current Repo Guide entry files.
- Use `Status: partial` when part of the answer is available but some facts are stale, incomplete, low-confidence, or inconsistent.
- Use `Status: blocked` only when the requested stable facts depend on a missing critical entry file and cannot be answered from the remaining Repo Guide entries.
- Do not use `blocked` when the answer is still partially available. If the missing information is auxiliary rather than critical, prefer `partial`.
- For command-related content, only return a repository-level command coverage summary. Do not conclude which command should be run for the current task.
- If recorded stable facts are stale, incomplete, or contradicted by current code, clearly label a warning and name the file that should be re-checked.
- If a stable fact has low confidence, clearly mark that confirmation is required rather than filling it with a guess.
- In `entry-status mode`, the check should stay centered on:
  - `AGENTS.md`
  - `repo-profile.md`
  - the skills root
  - workflow skill registration
  - coding skill registration
- When reporting workflow skill registration or coding skill registration, prefer a compact result such as `complete` | `incomplete` | `inconsistent` rather than a long narrative label.
- `Warnings` is a conditional block and should be output only in the following cases:
  - `repo-profile.md` exists, but is stale or clearly contradicted by current code
  - repository entry files exist, but the recorded stable facts are clearly incomplete
- `Requires Confirmation` is a conditional block and should be output only in the following cases:
  - a stable fact has low confidence
  - an app / framework / shared package classification has multiple reasonable candidates
  - `AGENTS.md` and `repo-profile.md` are inconsistent in their stable-fact records
- When there is no content for `Warnings` or `Requires Confirmation`, omit the block entirely.

## Output Focus

- Status
- Summary
- Repo Guide entry status when requested
- repo kind, framework map, and app/package map when requested
- business scope when requested
- runtime model when requested
- repository-level command coverage summary when requested
- shared-package boundaries when requested
- Warnings when needed
- Requires Confirmation when needed

## Recommended Response Template

Use the following style by default. Keep the fixed head, then expand only the sections relevant to the current request. Do not expand this into structure scanning or validation advice.

Example 1: resolved

```text
Status
- resolved

Summary
- Stable repository facts are recorded in `repo-profile.md`.
- This repository is a single React frontend application with a companion local API.
- Task-level validation choice belongs to `repo-workflow-validation-guidance`.

Repo Guide entry status
- `AGENTS.md` exists
- `repo-profile.md` exists
- workflow skill registration: complete
- coding skill registration: complete

Repo profile summary
- Repository name: `AI Course Studio`
- Repository type: `single-app`
```

Example 2: partial

```text
Status
- partial

Summary
- Stable repository facts are recorded in `repo-profile.md`, but some current facts may need re-checking.
- The repository is still identifiable as a single React frontend application.

Repo Guide entry status
- `AGENTS.md` exists
- `repo-profile.md` exists
- workflow skill registration: complete
- coding skill registration: inconsistent

Warnings
- `repo-profile.md` framework mapping for `apps/web/` may be stale and should be re-checked.

Requires Confirmation
- the framework classification of `apps/web/` has low confidence and should be re-checked against entry files
```

## Guardrails

- Use natural language text, not JSON.
- Keep the output lightweight. Do not force every possible section to appear when the current request does not need it.
- Keep `Status` and `Summary` as the only fixed output head. Treat the other sections as request-driven or condition-driven blocks.
- Keep `Summary` short. Do not turn it into a repository overview paragraph.
- If the request is `entry-status mode`, report missing `AGENTS.md`, `repo-profile.md`, or skills-root items directly as status. Do not treat missing entry files as a hard failure by default.
- If the request is `stable-facts mode`, stop only when the requested stable facts depend on a missing entry file and cannot be answered from the remaining entry files.
- Do not fall back to source scanning and present the result as stable facts just because an entry file is missing.
- Do not return request-time structure scans, change targets, diff impact, or validation decisions as stable facts.
- Do not choose task-level validation commands or provide final validation conclusions; that belongs to `repo-workflow-validation-guidance`.
- Do not write the current request's page, module, diff, error, or validation issue back into stable repository facts.
- Do not rewrite `AGENTS.md` or `repo-profile.md` unless the user explicitly asks.
- If a fact depends on current code and the repo profile looks stale, say so and name the file that should be re-checked.
