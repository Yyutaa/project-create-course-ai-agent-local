---
name: repo-workflow-scope-change-targets
description: Scope the most likely primary change target root_path and related first-pass file_path list for a user request.
---

# Repo Workflow Scope Change Targets

## Purpose

Map a natural language request to the most likely primary change target and return the first-pass related file scope that should be checked first.

## Inputs

Accept natural language input. No extra structured fields are required.

Common input sources include:

- user requirement descriptions
- PRD / Jira / bug logs
- page names, menu names, module names, route names, or shared-module names
- optional structure scan results or upstream workflow output

Common input scenarios include:

- scope the change target for a requirement
- find where a feature lives
- identify the primary change root for a bug
- map business terminology to source files
- decide which existing page, module, or shared module a requirement should land in
- check whether a requested new module already exists in the current repository

If the user only provides a page name, module name, menu name, route name, shared-module name, or one-line goal, first interpret it as natural language and then map it to the most likely change scope.

## Prerequisites

- Prefer to build on repository structure knowledge that has already been loaded by `repo-workflow-scan-structure`.
- If the current context still lacks enough structure results, only do minimal supplemental reading of `AGENTS.md`, `repo-profile.md`, and directly relevant app / package / route / direct-target entry paths.
- Do not re-run a broad structure scan in this workflow; structure indexing belongs primarily to `repo-workflow-scan-structure`.

## Steps

1. Reuse the current `repo-workflow-scan-structure` result first, narrowing the search to the relevant app / package / direct target layer.
2. If the current context still lacks enough structure results, first read `repo-profile.md` for the relevant app map, runtime model, modification boundary, and repo-classification sections. Read `AGENTS.md` only when you need to confirm Repo Guide entry registration or workflow availability, then perform only minimal supplemental checks.
3. Based on the known structure, determine the relevant app, shared package, framework, and direct target layer; do not expand the result into broad structure analysis.
4. Verify page names, menu names, module names, route names, shared-module names, and other explicit path clues against current source first.
5. Inspect only the necessary categories according to the search-priority rules, and stop once the primary change target and first-pass change scope are sufficiently narrowed.
6. Follow the decision priority to return an exact match, a single existing candidate, a proposed target, multiple candidates, or unresolved output.
7. If the input covers multiple modules, pages, menus, shared modules, or PRD sections, output one independent target block per module instead of merging them into a shared parent directory.
8. Normalize every existing-match conclusion back to a directory-level `root_path`, even when the strongest evidence comes from a route file, page entry file, shared-module entry file, export entry, or consumer entry.
9. Return the most likely `root_path`, first-pass scoped `file_path`, evidence, confidence, and confirmation needs.

## Search Priority Rules

At minimum, prioritize these categories based on the input type:

- page name / module name input
  - If the name clearly points to an app-local page, check page/module directories, page entry files, and route registration first.
  - If the name clearly points to a shared package / shared module, check shared-module directories, shared-module entry files, export entry points, and consumer entry points first.
  - After an existing app-local page or module is matched, only check shared packages / shared modules when direct import, consumer-entry, or other immediate dependency clues show they are part of the first-pass linked scope; if so, include that shared module in `file_path`.
  - After the primary change target is matched, add directly related API / store / hook / permission / i18n files only when they are commonly part of the first-pass linked scope.
- menu name / route name input
  - Check route / menu registration, the direct target entry pointed to by the route, and the related module directory first.
  - After an existing app-local page or module is matched, only check shared packages / shared modules when direct import, consumer-entry, or other immediate dependency clues show they are part of the first-pass linked scope; if so, include that shared module in `file_path`.
  - After the primary change target is matched, add directly related moduleEntries, API / store / permission / i18n files only when they are commonly part of the first-pass linked scope.
- bug / feature input
  - Check the direct target entry, route, and related module directory first; if the issue clearly lands in a shared package, switch to shared-module directories, export entry points, and consumer entry points.
  - After an existing app-local page or module is matched, only check shared packages / shared modules when direct import, consumer-entry, or other immediate dependency clues show they are part of the first-pass linked scope; if so, include that shared module in `file_path`.
  - After the primary change target is matched, add directly related API / store / hook / permission / i18n files only when they are commonly part of the first-pass linked scope.
- create / migrate / implement new module input
  - First check whether `repo-profile.md` defines a default landing area for new modules.
  - If `repo-profile.md` already defines one, follow that app / package target layer first.
  - If `repo-profile.md` does not define one, do not default to any framework. Keep the target unresolved unless the current request or current source evidence already makes the app / framework clear.
  - Treat natural-language signals such as a new menu branch, a new parent menu layer, a requested menu path that includes `New`, `new`, `新增`, `新`, or a clearly additive sibling menu under an existing parent as new-module signals even when the user does not explicitly say `create`, `new module`, or `implement`.
  - When those new-module signals are present, and the requested leaf target does not exist as a current direct target, prioritize constructing one proposed `root_path` from the confirmed app / framework / direct target layer instead of broadening into multiple semantic candidates.
  - Only inspect or propose a shared-package target when the request explicitly asks for a shared package, or current evidence shows the capability should be reused as a shared module.
  - Then check existing direct target directories, sibling modules, route / moduleEntries, and whether a same-name leaf target already exists.
  - Do not reverse-search large sets of API / store / hook / component files only to fill `file_path` for a proposed `root_path`.

If multiple categories are applicable, use this priority:

1. direct target directories
2. direct target entry files
3. route / menu / moduleEntries / shared export entry / consumer entry
4. API / store / hook / permission / i18n
5. components

When direct target directories, direct target entry files, or route / export-entry evidence are already enough to scope `root_path`, stop widening the search. If the primary change target is already matched, you may still add directly related API / store / hook / permission / i18n files to `file_path` when they are commonly part of the first-pass linked scope. Once `file_path` already covers the entry and the main linked surface, stop; do not backfill adjacent but unrelated files only to make the list look complete.

## Default Output

- Default to natural language text. Do not output JSON.
- Always start with:
  - `Status`: `resolved` | `partial` | `unresolved`
  - `Summary`: 2 to 4 short bullets covering only the most relevant target-scoping conclusion for the current request
- Keep the output centered on `root_path` and `file_path`; do not expand into broad structure analysis or impact analysis.
- If the input involves multiple modules, pages, menus, or shared modules, output them separately instead of merging them.
- Each target block must have exactly one `root_path`. If one input clearly maps to multiple direct target entries, output multiple target blocks instead of placing multiple `root_path` values in one block. Only when even a proposed path cannot be reliably constructed may you return an unresolved result without a target block.
- Use `Status: resolved` when the current request narrows to one concrete target block, whether exact-match or one reasonable existing/proposed target.
- Use `Status: partial` when the current request still has multiple candidate target blocks, or when the request covers multiple independent modules that each need their own target block.
- Use `Status: unresolved` only when even one reliable proposed `root_path` cannot be constructed.
- `root_path` means the primary change target directory. When an existing target is matched, return the actual directory; when the target is proposed, return the proposed directory.
- `root_path` must always be a directory path. If the strongest evidence is a file-level hit, convert it to the owning target directory and keep the file evidence in `file_path` or `evidence`.
- `file_path` means the first-pass check file list around the primary change target. It is not an exhaustive module file list, and not every file must live under `root_path`.
- When there are no first-pass files to include, write `file_path: none` instead of leaving the field visually blank.
- When an existing target is matched, `file_path` may include directly related route, API, store, hook, permission, i18n, export-entry, consumer-entry, or directly dependent shared-module files when they are commonly part of the first-pass linked scope. Those files may live inside `root_path`, or on the direct consumer/dependency side. Do not include files that are only adjacent in the directory tree.
- Clearly mark `requires confirmation` when there are unresolved items, naming conflicts, or lower-confidence conclusions.
- Tie `confidence` to the decision outcome:
  - exact match -> `high`
  - single existing candidate -> `medium`
  - one proposed target -> `low`
  - multiple candidates -> `low`
  - unresolved -> omit `confidence`
- Prefer natural-language readability over a rigid schema. When there is one clear target, a short list is enough; when there are multiple targets or clear ambiguity, expand into multiple target blocks.

## Output Focus

- `Status`
- `Summary`
- `root_path`: the primary change target directory; if it is not an exact existing match, explain the reasoning in `evidence`
- `file_path`: the first-pass check file list around the primary change target, usually covering the entry and the main linked surface; direct consumer-side or dependency-side files are allowed when they are part of the same immediate linked scope
- `evidence`: 1 to 3 most direct paths or clues that support the conclusion
- `confidence`: only `high` / `medium` / `low`
- `requires confirmation` and unresolved items

## Decision Priority

Use this order. Do not mix levels.

1. Exact match
   - The page name, module name, menu name, route name, shared-module name, or explicit path clues map exactly to a current direct target directory, direct target entry file, shared-module directory, shared-module entry, or route.
   - If the strongest exact match is file-level, convert it to the owning target directory before returning `root_path`.
   - `confidence: high`
   - Return one target block directly with `requires confirmation: no`.
2. Non-exact but single existing candidate
   - The input name differs from current code naming, but direct-target evidence narrows to exactly one reasonable existing candidate with no competing near matches at the same level.
   - Use this outcome only when the leaf-name difference is still near enough that one current page/module can reasonably be treated as the intended target.
   - `confidence: medium`
   - Return that existing candidate target block with `requires confirmation: yes`.
3. No existing leaf target, but one proposed target can be constructed
   - The input name differs from current code naming, and the current page/module should not be backfilled as the target.
   - This includes cases where the user expresses a new menu branch or new parent layer in natural language, the requested leaf target does not exist, and the app / framework / direct target layer are already clear enough.
   - `confidence: low`
   - If the parent menu, app, framework, and direct target layer are clear enough to construct one reasonable proposed path, return one target block with that proposed `root_path`, `file_path` empty, and `requires confirmation: yes`.
4. Non-exact and multiple candidates
   - The input name differs from current code naming, and there are multiple app, module, or direct-target candidates.
   - `confidence: low` for each candidate block
   - Return multiple candidate target blocks with `requires confirmation: yes`.
5. Unresolved
   - The candidate layer still cannot be narrowed, or the app / framework / direct target layer is unclear enough that even one proposed `root_path` cannot be reliably constructed.
   - In this case, return an unresolved result instead of inventing a `root_path`.

## Guardrails

- This is a narrow change-scoping workflow.
- Keep `Status` and `Summary` as the only fixed output head.
- Keep `Summary` short. Do not turn it into a full reasoning trace.
- Do not treat `AGENTS.md` as the source of stable repo facts such as app map, runtime model, modification boundary, or dependency topology; those belong to `repo-profile.md`.
- `root_path` must represent the primary change target directory, not only a route module directory.
- When a route points to a page component, return the directory containing that page entry component as `root_path`; keep route registration files in `file_path`.
- When a page entry file, shared-module entry file, export entry, or consumer entry is the strongest hit, return the owning target directory as `root_path`; keep the matched file itself in `file_path` or `evidence`.
- When the primary target lands in a shared package, shared-module directory, or other non-page directory, return that real primary change directory instead of forcing a fallback to a page directory.
- For existing module/page scenarios, shared packages / shared modules are linked-scope checks only when direct dependency clues show they are part of the first-pass change surface; only make them the `root_path` when the evidence shows they are the true primary change target.
- Do not treat a module as the target only because its name appears in the request, it has a similar name, or it is mentioned as old / reference / similar / existing behavior.
- If explicit path terms do not match exactly, do not decide immediately; continue through the decision priority and decide whether the result is a single candidate, multiple candidates, or unresolved.
- If explicit path terms hit multiple app / package / direct-target directories, do not force one; return candidates and mark `requires confirmation`.
- If the direct target index or shared-module directories already show same-name directories, typical subdirectories, key entry files, or shared-module entries, prioritize those direct-target clues when determining `root_path`.
- When the input name differs from current code naming, narrow candidates in this order:
  1. direct target directories, key entry files, shared-module directories, or shared-module entries with the same or near name
  2. route / menu / moduleEntries / export-entry / consumer-entry direct pointers
  3. app / framework / direct target layer already known
  4. parent module / parent menu hit
  5. API / store / permission / i18n supporting clues
- If naming differs but direct-target evidence narrows to one existing candidate with no same-level competitors, you may return one candidate target block, but only when the leaf-name difference is still near enough that the current page/module can reasonably be treated as the intended target; `requires confirmation` must be `yes`.
- If naming differs and the current leaf page/module name is materially different from the requested leaf name, do not treat the existing page/module as the target only because parent menu, route layer, or feature semantics converge. In that case, return a proposed `root_path` built from the confirmed app/framework/parent layer, and keep `file_path` empty.
- If the request expresses a new menu branch, a new parent layer, or another additive menu-path signal, and the requested leaf target does not exist, do not upgrade semantically related existing capabilities into multiple candidate targets just because they share business meaning. Return one proposed `root_path` when the app / framework / direct target layer are already clear.
- If naming differs and there are multiple app, module, or direct-target candidates, do not decide; return multiple target blocks and require confirmation.
- If only parent modules, parent menus, or approximate business semantics are hit, but there is no direct-target evidence, do not treat the nearest name as the final target.
- If the leaf target does not exist, or the requested leaf name is materially different from every existing leaf target while the parent menu, app, or framework is already clear, you may return a proposed `root_path`; in that case `file_path` must be empty.
- Proposed `root_path` is primarily for explicit create / migrate / implement new-module cases where the leaf target does not yet exist in source, and also for materially different leaf-name scenarios where parent-level convergence is clear but no existing leaf target should be backfilled as the target.
- For new-module signals expressed through menu paths rather than explicit `create` wording, semantically related existing modules may still be cited in `evidence` as reference-only context, but they must not be promoted to candidate targets unless the user explicitly indicates that the new request should land in one of those existing leaves.
- For new-module scenarios, follow `repo-profile.md` first. If `repo-profile.md` does not define a landing area, do not default to a framework-specific target layer; keep the target unresolved unless the current request or current source evidence already makes the app / framework clear.
- Only propose a shared-package target when the request explicitly asks for a shared package, or current evidence shows the target should be designed as a reusable shared module.
- Only derive a proposed `root_path` from a parent module or parent menu after direct-target indexes, direct-target entry directories, shared-module directories, and explicit path clues all fail to hit an existing leaf target.
- When `root_path` is proposed rather than an exact existing match, clearly say so in `evidence`.
- When the app / framework is clear, build the proposed path from current direct-target conventions, such as:
  - React app page: inspect `apps/web/src/App.tsx` and neighboring page files; this repository currently places page files directly under `apps/web/src/`.
- If the app / framework is unclear, keep `root_path` unresolved instead of inventing a proposed path.
- Do not backfill `file_path` from parent menus, existing list pages, sibling pages, nearby routes, API, store, hook, or components only because they are structurally adjacent.
- When an existing target is matched, you may include directly related API / store / hook / permission / i18n / route / export-entry / consumer-entry files, but do not include files that are only nearby in structure and not directly related.
- `file_path` should cover the first-pass check scope, not all possible implementation files under the module. It may cross outside the `root_path` directory, but only for immediate linked files rather than structurally nearby ones. Stop once the entry and main linked surface are covered.
- Do not treat reference-only, old, or similar modules as the target unless the user explicitly says they are the target.
- When returning candidate blocks, explicitly call out the naming differences and why the result narrowed to those candidates.
- When this workflow returns one concrete target block, it can feed later target-aware workflows such as coding guidance.
- When this workflow returns multiple candidate target blocks or an unresolved result, do not treat that as ready for task-level validation choice yet.

## Recommended Response Template

This template is only a recommended organization, not a required schema. If there is one clear target, a short answer is enough. If there are multiple targets or obvious ambiguity, output multiple target blocks in user-input order. Each target block should contain only one `root_path`. If the result is truly unresolved because even a proposed path cannot be reliably constructed, use the unresolved template instead of forcing a target block.

```text
Status
- resolved

Summary
- The current request narrows to one concrete target block.
- The first-pass file scope is limited to the directly linked surface.

Target 1
- root_path: `...`
- file_path:
  - `...`
  - `...`
- evidence:
  - `...`
  - `...`
- confidence: high | medium | low
- requires confirmation: yes | no
```

For truly unresolved cases, you may use:

```text
Status
- unresolved

Summary
- The current request cannot be narrowed to one reliable target scope yet.

Unresolved
- reason: the app / framework / direct target layer is still unclear, so a reliable proposed `root_path` cannot be constructed
- evidence:
  - `...`
  - `...`
- requires confirmation: yes
```

Example 1: resolved

```text
Status
- resolved

Summary
- The current request narrows to an existing React page area.
- The first-pass scope covers directly linked route and API files.

Target 1
- root_path: `apps/web/src`
- file_path:
  - `apps/web/src/course-workflow-page.tsx`
  - `apps/web/src/App.tsx`
  - `apps/web/src/api.ts`
- evidence:
  - `apps/web/src/course-workflow-page.tsx`
  - `apps/web/src/App.tsx`
- confidence: high
- requires confirmation: no
```

Example 2: partial

```text
Status
- partial

Summary
- The request may refer to several page files, so the target needs confirmation.

Target 1
- root_path: `apps/web/src`
- file_path:
  - `apps/web/src/courses-page.tsx`
  - `apps/web/src/course-workflow-page.tsx`
- evidence:
  - `apps/web/src/pages.tsx`
- confidence: low
- requires confirmation: yes
```

When a shared package is treated as the primary change target but the conclusion still relies on consumer-side entry evidence to converge, `confidence: medium` with `requires confirmation: yes` is appropriate.

`file_path` is for the first-pass check scope. It does not have to contain only route / page files. If the requirement usually needs linked checks in API, permission, i18n, store, hook, export-entry, consumer-entry, or directly dependent shared-module files, and those files are directly related to the primary change target, include them in `file_path`. Those files may cross outside the `root_path` directory, but only when they are part of the immediate linked surface rather than merely structurally nearby. Stop once the primary entry and the main linked surface are covered.
