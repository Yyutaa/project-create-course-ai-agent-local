---
name: repo-workflow-coding-guidance
description: Combine relevant coding skills, repo facts, and current source evidence into request-specific coding guidance.
---

# Repo Workflow Coding Guidance

## Purpose

Return request-specific coding guidance by combining the relevant coding rule skills, stable repo facts, and current source evidence.

This workflow is not only responsible for listing which coding skills are involved. It must digest those skills into directly actionable implementation guidance and code-generation rules for the current request scope.

## Inputs

Accept natural language requests, but split them into two input types.

Type 1: targeted coding-guidance input

- the input already contains clear target context, such as a page, module, route, shared package, changed files, or a change target already confirmed by an upstream workflow
- it may also directly provide `root_path`, `file_path`, target file paths, or a confirmed change scope
- for this input type, the workflow should directly return coding guidance for that target

Type 2: insufficient-context input

- the input is only a requirement description, a pattern question, a generalized question, or something like "how is this kind of scenario usually implemented"
- it does not include a clear page, module, route, shared package, file path, or confirmed change target
- for this input type, the workflow must not infer the final change target; it should return unresolved guidance and point out which coding categories should be confirmed first

If the target context maps to multiple apps, portals, shared packages, or multiple same-level candidate targets, the workflow must not give targeted implementation guidance either. It should return unresolved guidance and request confirmation.

## Relevant Skill Selection Signals

Relevant coding skills should be selected from these three signal groups in the current request, rather than by broadly listing anything that might be related:

- input categories, such as menu, route, API, i18n, permission, store, shared module, or template type
- target path signals, such as `router/routes`, `api/service`, `locale/i18n`, `store/model`, or `packages/**`
- change intent, such as add page, change route, change API payload, translate UI copy, add permission, or modify a shared package

## Steps

1. Read `AGENTS.md` first.
2. First determine whether the current input is a targeted coding-guidance input or an insufficient-context input, and whether it already contains enough target context such as a page, module, route, shared package, changed files, or upstream-confirmed `root_path` / `file_path`.
3. If the current input is an insufficient-context input, or the target context maps to multiple apps, portals, shared packages, or multiple same-level candidate targets, return unresolved guidance. First explain which target context is missing or conflicting, and ask to confirm the target context first, such as the owning app / portal, target page or module, `root_path`, whether the target is under `packages/**`, and the direct consumer or direct entry file. Only when the current input already contains partial target clues should you additionally narrow the confirmation categories from the registered coding-rule categories that are actually relevant in the current case, such as `menu`, `route`, `api`, `shared-module`, `permission`, `i18n`, `store`, `hooks`, `enum`, `time`, `file-operation`, or template categories.
4. If the target context is clear, load only the coding skills that are truly relevant to the current request.
5. Filter the relevant coding skills according to the "Relevant Skill Selection Signals" section.
6. Read the matching `repo-profile.md` boundary and template sections.
7. Before suggesting an implementation direction, prefer same-app, same-framework, and same-module source evidence.
8. Return implementation guidance and code-generation rules with concrete file anchors, rather than stopping at a list of coding skill names.

## Output Focus

- keep `Status` and `Summary` as the only fixed head
- the truly relevant rule categories for the current request
- same-app source anchors that should take priority over generalized samples
- shared-package or cross-framework risks
- targeted implementation guidance and code-generation rules

## Default Output

Always start with:

- `Status`
- `Summary`

Use `Status: resolved` only when the current input already contains a clear and sufficiently narrow target context, and the workflow can collapse the relevant coding skills into targeted implementation guidance for that target.

Use `Status: unresolved` when:

- the current input is still an insufficient-context input
- the target context maps to multiple apps, portals, shared packages, or same-level candidate targets
- the current input still lacks the owning app / portal, target page or module, `root_path`, whether the target is under `packages/**`, or the direct consumer / direct entry file needed to ground implementation guidance

Keep `Summary` to 2 to 4 short bullets. It should state the current coding-guidance conclusion, not restate every source anchor or reproduce the full implementation guidance.

When `Status: resolved`, default to this output order:

1. `Status`
2. `Summary`
3. the coding categories that are truly relevant to the current request
4. same-app, same-framework, same-module source anchors that should be followed first
5. directly actionable implementation guidance and code-generation rules
6. shared-package or cross-framework risk only when it is necessary and evidenced

Do not return only a list of coding skill names. If the target context is already sufficient, the relevant skills must be collapsed into direct guidance for the current request.

When `Status: unresolved`, default to this output order:

1. `Status`
2. `Summary`
3. `Target context to confirm first`
4. `Rule categories to confirm next` only when the current input already provides enough clues to narrow the blocking categories

For unresolved guidance:

- clearly explain that the target context is missing, or that there are multiple candidate targets and targeted coding guidance cannot be given yet
- ask to confirm the target context first, such as the owning app / portal, target page or module, `root_path`, whether the target is under `packages/**`, and the direct consumer or direct entry file
- only when the current input already provides partial target clues, narrow the registered coding-rule categories that could realistically block implementation judgment in the current case, such as `menu`, `route`, `api`, `shared-module`, `permission`, `i18n`, `store`, `hooks`, `enum`, `time`, `file-operation`, or template categories
- narrow that list to the 2 to 4 categories that actually block implementation judgment in the current case whenever the current input provides enough evidence
- only fall back to a broader unresolved category list when the current input provides too little evidence to narrow the blocking categories further
- ask for confirmation instead of presenting those categories as a default implementation conclusion

## Recommended Response Template

Respond in natural language. Prefer this shape when useful:

```text
Status
- resolved

Summary
- `...`

Relevant rule categories
- `...`

Source anchors
- `...`

Implementation guidance
- `...`

Code-generation rules
- `...`

Risk warnings
- `...`
```

If the current input is an insufficient-context input, or the target context maps to multiple candidate targets, use:

```text
Status
- unresolved

Summary
- `...`

Target context to confirm first
- `...`
- `...`

Rule categories to confirm next
- `...`
- `...`
```

## Minimal Examples

Example 1: resolved

```text
Status
- resolved

Summary
- The target context is already narrow enough to follow app-local route, API, and components patterns directly.
- Same-app source anchors should take priority over repo-wide generic examples.

Relevant rule categories
- `route`
- `api`
- `components`

Source anchors
- `apps/web/src/App.tsx`
- `apps/web/src/course-workflow-page.tsx`
- `apps/web/src/components/layout.tsx`

Implementation guidance
- Follow the route registration pattern already used by the target page's app instead of switching to another app's entry pattern.
- Reuse the existing request/response handling style in the current module instead of inventing a separate abstraction layer.

Code-generation rules
- Keep route organization, page implementation, and component composition consistent with the current app.
- If the same module already has a similar capability example, copy that organization pattern first and then make the smallest necessary changes.
```

Example 2: unresolved

```text
Status
- unresolved

Summary
- Targeted coding guidance cannot be given yet because a clear target context is still missing.
- Confirm the owner and target scope first before selecting route or API patterns.

Target context to confirm first
- owning app / portal
- target page or module
- whether the target is under `packages/**`

Rule categories to confirm next
- `route`
- `api`
```

## Guardrails

- Treat coding skills as guidance workflows, not fixed law.
- Keep `Status` and `Summary` as the only fixed head. All other sections are conditional on what the current request actually needs.
- When same-app examples differ from repo-wide generic anchors, prefer the current same-app examples.
- When `Status: resolved`, keep `Relevant rule categories` narrow to the categories that actually govern the current request. Do not broaden it into a repo-wide checklist.
- When `Status: resolved`, prefer 2 to 5 concrete `Source anchors` that come from the same app, framework, and module whenever the evidence exists.
- When the target context is clear, do not stop at a list of coding skill names. You must collapse them into implementation guidance and code-generation rules.
- When the current input is an insufficient-context input, or the target context maps to multiple candidate targets, do not pretend that an implementation conclusion already exists. Return unresolved guidance first and ask to confirm the target context first. Only when the current input already provides partial target clues should you use the registered coding-rule categories that are actually plausible blockers in the current case, narrowing them to the 2 to 4 categories that most directly block implementation judgment.
- When `Status: unresolved`, do not emit `Implementation guidance` or `Code-generation rules` as if the target were already confirmed.
- Do not cite unregistered categories as if they were coding-rule skills. If current source evidence points to module registration or exposure files, fold that need back into the nearest registered category such as `menu`, `route`, or `shared-module`, and name the concrete source anchors directly.
- Do not broadly list coding categories without grounding them in input categories, path signals, and change intent.
- Do not recommend a UI library or architecture that conflicts with the target app framework.
- Do not mix validation-command selection into this workflow. Validation commands belong to `repo-workflow-validation-guidance`.
- Output natural language text only.
