---
name: repo-workflow-analyze-impact
description: Return impacted page menu paths from changed files, plus compact evidenced warnings for cross-app or shared risks.
---

# Repo Workflow Analyze Impact

## Purpose

Summarize the likely user-facing impact of changed files with the narrowest credible user-facing impact first.

This workflow only analyzes impact from existing change evidence. It must not backtrack from a requirement description to guess where the change should be made.

## Prerequisites

- Prefer to rely on repository structure context that has already been established by `repo-workflow-scan-structure`.
- If the current context does not yet contain enough structure results, then read `AGENTS.md` and `repo-profile.md`, and inspect only the minimum relevant route / menu / shared package / generated-artifact paths.
- Do not re-run a broad structure scan inside this workflow. Structure indexing belongs primarily to `repo-workflow-scan-structure`.

## Inputs

Accept change-centered inputs such as changed-file lists, diff summaries, PR change descriptions, or copied git output.

Natural language context is acceptable only when it already includes explicit change evidence. If the input is only a requirement description, page name, menu name, or bug symptom without changed files or diff evidence, this workflow should stop instead of inferring impact.

Common input scenarios include:

- analyze which pages are affected by a set of changed files
- determine impacted menu paths from a diff summary
- determine which apps may be affected by a shared-package change
- determine whether generated-artifact, tooling, or configuration changes need extra warnings

## Steps

1. Read `AGENTS.md` first.
2. Confirm that the input contains explicit changed files, a diff summary, PR change details, or equivalent change evidence.
3. If no change evidence is available, stop the impact analysis and explain that impacted pages cannot be determined from the current input.
4. Prefer to reuse `repo-workflow-scan-structure` context that is already loaded in the current thread. If that context is still insufficient, then read the app map, business entries, runtime model, boundaries, and dependency topology from `repo-profile.md`.
5. First map changed files to the narrowest credible user-facing surface. Use page or menu paths only when current change evidence already supports them directly. Only when that primary mapping is not enough to determine shared-package, cross-app, generated-artifact, or tooling risk should you inspect the related entry points.
6. Follow the default output pattern: return impacted page or menu paths when they are directly evidenced; otherwise return impacted surfaces or confirmed consumer apps. Add a short warning only when it is truly necessary, and add minimal path evidence only when the primary impact output alone is not enough to support the conclusion.

## Output Focus

- keep `Status` and `Summary` as the only fixed head
- impacted page or menu paths by app when they are directly evidenced
- impacted surfaces or confirmed consumer apps when page or menu paths are not a credible output
- warnings only when the evidence shows cross-app, cross-framework, or generated-artifact risk

## Default Output

Always start with:

- `Status`
- `Summary`

Use `Status: resolved` when the current input contains usable change evidence and the workflow can produce a narrow, credible impact conclusion from that evidence.

Use `Status: unresolved` when the current input does not contain changed files, diff summaries, PR change details, or equivalent change evidence.

Keep `Summary` to 2 to 4 short bullets. It should state the current impact conclusion, not restate the full evidence set or repeat every impacted page line.

When `Status: resolved`, default to this output order:

1. `Status`
2. `Summary`
3. impacted page or menu paths when they are directly evidenced
4. when page or menu paths are not credible, impacted surfaces or confirmed consumer apps
5. short warnings only when they are necessary and evidenced, for example shared-package, cross-app, tooling, or generated-artifact risk
6. minimal path evidence only when the primary impact output alone is not enough to support the conclusion

If the changed files clearly map to concrete page or menu paths, return only those paths. Do not add evidence, app/package/tooling sections, or validation sections by default.

If the changed files do not credibly map to page or menu paths, do not force that output. Return the narrowest credible impacted surfaces or confirmed consumer apps instead.

When `Status: unresolved`, default to this output order:

1. `Status`
2. `Summary`

If no usable change evidence is available, do not guess impacted pages. Explain that the current input is insufficient for impact analysis.

## Recommended Response Template

Respond in natural language. Prefer this shape when useful:

```text
Status
- resolved

Summary
- `...`

Impacted pages
- `apps/web` / `课程`
- `apps/web` / `新建课程`

Warnings
- `...`
```

If the page menu paths are already clear, keep only the `Impacted pages` section.

If menu-path output is not credible, you may use:

```text
Status
- resolved

Summary
- `...`

Impacted surfaces
- `apps/web/src` when evidence identifies only the frontend application surface
```

Only add minimal evidence when the page mapping alone is not self-explanatory, for example:

```text
Evidence
- `...`
```

If no usable change evidence is available, use:

```text
Status
- unresolved

Summary
- `...`
```

## Minimal Examples

Example 1: resolved

```text
Status
- resolved

Summary
- The changed files map directly to page-local flows in `AI Course Studio`.
- Page-level menu paths are already the narrowest credible impact output.

Impacted pages
- `AI Course Studio` / `课程`
- `AI Course Studio` / `新建课程`
```

Example 2: unresolved

```text
Status
- unresolved

Summary
- Impacted pages cannot be analyzed because no changed files, diff summary, or equivalent change evidence was provided.
```

## Guardrails

- Default to the narrowest credible user-facing impact, not a full architecture essay.
- Keep `Status` and `Summary` as the only fixed head. All other sections are conditional on what the current request actually needs.
- If there are no changed files, diff summaries, PR change details, or equivalent change evidence, stop and explain that impact cannot be analyzed from the current input. Do not mix in change-target guessing, page locating, or module inference.
- When `Status: resolved`, use `Impacted pages` only when current change evidence credibly supports page or menu-level mapping.
- When `Status: resolved`, use `Impacted surfaces` when the evidence only supports module-level, app-level, shared-package, or confirmed consumer-level impact.
- When `Status: unresolved`, do not emit `Impacted pages`, `Impacted surfaces`, `Warnings`, or `Evidence` as if impact had already been established.
- When page or menu paths are already clear, do not add evidence by default.
- When page or menu paths are not credible for the current change, do not force them; use impacted surfaces or confirmed consumer apps instead.
- Do not reverse-infer page or menu paths when current change evidence supports only module-level, app-level, shared-package, or consumer-level impact.
- When the changed files are ordinary page files, route files, or clearly page-local implementations, do not expand into app/package/tooling classifications.
- Do not expand into impact taxonomies, architecture overviews, or validation guidance.
- Do not recommend validation commands by default. That belongs to `repo-workflow-validation-guidance`.
- Add short warnings only when the changed files clearly touch shared packages, generated/tooling files, locale/permission/error-code/enum infrastructure, build/config scripts, or cross-app consumers.
- Ignore bootstrap skill files and generated output unless the diff directly touched them.
- Do not mix "where should this change go" target-scoping behavior into this workflow.
- Output natural language text only.
