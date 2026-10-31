---
name: repo-workflow-scan-structure
description: Classify the frontend app repo kind and scan the current repository structure with framework-aware focus.
---

# Repo Workflow Scan Structure

## Purpose

First identify the repository shape, then scan only the directories that are actually relevant to the current request, and present the structure in a tree-like form so downstream steps can locate page roots, route roots, API, i18n, store, and shared-module boundaries.

## Inputs

Accept natural language requests. No extra structured input fields are required.

Common input scenarios include:

- scan the repository structure
- output the structure tree of a specific app
- explain the responsibility boundary between `apps/` and `packages/`
- inspect which app or module structures match a page or module clue
- inspect the module hierarchy under `views/` or `pages/` in an app
- find route / moduleEntries / api / i18n / store entry points
- compare where Vue, React, and H5 live and how their page layers are organized

If the user only provides a page name, module name, app name, directory fragment, or a one-line goal, first interpret it as natural language and then map it to the appropriate scan scope.

## Repository Structure Notes

The following meanings are interpretation hints rather than hard rules. Confirm them with nearby files, entry files, route registration, package scripts, and import relationships:

- `apps/`
  - Usually runnable apps or portal roots.
  - One app usually has its own business entry, startup script, routing layer, and page layer.
- `packages/`
  - Usually shared modules, shared page carriers, shared component libraries, common utilities, or cross-app reusable logic.
  - Do not classify the repository as a pure component library only because it has `packages/`; if `apps/` also exist, keep it in frontend business app scope first.
- `apps/*/src` or `packages/*/src`
  - Usually the primary source root of the app or shared package.
  - If `packages/*/src` contains additional business module directories, expand them as shared-module hierarchy instead of stopping at the package root.
- `src/views/`, `src/pages/`
  - Usually page-level or business-module-level directories.
  - Expand at least one level below them; inspect a second level when needed.
  - When the user input includes a page name, menu name, or page-level clues inside a module, you may continue expanding to page-level directories or key page entry files under the module.
- `src/router/`, `src/routes/`, `src/moduleEntries/`
  - Usually route registration, module registration, or portal exposure entry points.
  - In portal-style Vue apps, `moduleEntries/` may be a first-class exposure boundary rather than only a secondary registration detail.
- `src/api/`, `src/apis/`, `src/services/`, `src/request/`
  - Usually API definitions, request wrappers, or service call entry points.
- `src/lang/`, `src/i18n/`
  - Usually localization entry points.
- `src/store/`, `src/stores/`, `src/models/`, `src/state/`
  - Usually state management entry points.
- `src/components/`
  - Usually shared components or module-local common components; distinguish app-local components from cross-app shared components.
- `src/utils/`, `src/hooks/`, `src/types/`, `src/constants/`
  - Usually supporting code, not page roots by default.

## Structure Reference Example

Use the following as a repository-specific structure interpretation example:

```text
repo-root/
├── apps/
│   ├── web/
│   │   └── src/
│   │       ├── App.tsx                    # route registration
│   │       ├── courses-page.tsx           # course page
│   │       ├── course-workflow-page.tsx   # run and create pages
│   │       ├── api.ts                     # REST client and types
│   │       └── components/                # app-local components
│   └── api/
│       └── app/                           # FastAPI and Worker code
└── scripts/                               # local startup scripts
```

## Steps

1. Read `AGENTS.md` first.
2. Read the repository kind, app map, runtime model, boundary, and dependency topology sections from `repo-profile.md` that are relevant to the current request.
3. If `repo-profile.md` is missing, clearly insufficient, or inconsistent with the current directory structure, do a lightweight supplemental scan and make it explicit which conclusions come from current source inspection.
4. Classify the current repository as one of: `business-monorepo`, `single-app`, `micro-frontend`, `h5`, or `unknown`.
5. Decide the scan scope by repo kind:
   - `business-monorepo`: prioritize `apps/**`, `packages/**`, each app's `src` root, route roots, page roots, and shared package roots.
   - `single-app`: prioritize `src/**`, page roots, route roots, config roots, and embedded framework subtrees.
   - `micro-frontend`: prioritize host apps, remote apps, loaders, federation config, and standalone startup entries.
   - `h5`: prioritize H5 app roots, `pages`, `routes`, `core`, and environment config.
6. Using real directories and entry files, identify within each relevant app or shared package:
   - source roots
   - page roots such as `views` or `pages`
   - route / module registration entry points
   - API / i18n / store / components / utils entry points
7. If `views/` or `pages/` exist, expand to the next module level; inspect a second level when needed.
8. When the user input includes a page name, menu name, or a need for a finer page-layer index, you may continue expanding page-level directories, typical subpage directories, or key page entry files under a module, such as `index.vue`, `index.tsx`, `detail/`, `log/`, or `create-edit/`.
9. If `packages/*/src` contains shared modules, shared pages, or business subdirectories, expand those to the next module level as well; inspect a second level when needed.
10. Output the repository structure in tree-like text and always include concise key evidence paths.
11. If the current request needs a final ownership or change-target conclusion, stop at directory indexing and evidence only, and make it explicit that this workflow does not perform target convergence.

## Default Output

- Default to natural language plus a tree-like structure. Do not dump raw command output.
- Always start with:
  - `Status`: `resolved` | `partial`
  - `Summary`: 2 to 4 short bullets covering only the most relevant structure conclusion for the current request
- The structure output should prioritize:
  - relevant app roots and shared package roots
  - the `src` primary root of each relevant app
  - the `src` primary root of each relevant shared package
  - module hierarchy under `views/` or `pages/`
  - page-level directories, typical subpage directories, or key page entry files under modules
  - shared module or shared page hierarchy under `packages/*/src`
  - key entry points such as route / moduleEntries / api / i18n / store
- If the user asks where a page or module clue appears in the repository, the result must make clear:
  - which app or shared-package structures contain that clue
  - where the matching page root is
  - which level the matching module sits under in `views/` or `pages/`
  - which page-level directories or key page entry files are present under that module
- For mixed-framework repositories, explain Vue, React, and H5 separately rather than flattening them into one folder list.
- Use `Status: resolved` when the current request maps cleanly to one repository-kind conclusion and one coherent structure scope.
- Use `Status: partial` when the current request matches multiple app/package structures, when the repository kind cannot be confirmed confidently, or when part of the structure conclusion depends on lightweight supplemental source inspection.
- Do not use `partial` only because the user asked for a narrow app-level or module-level scan. If the requested scan scope is intentionally narrow but the structure conclusion inside that scope is clear, keep `resolved`.
- The output must include:
  - `Repository kind`
  - `Matched structures`
  - `Structure tree`
  - `Key entry points`
  - `Key evidence`
- `Key evidence` is fixed output, but keep it to 1 to 3 critical paths only.
- `Matched structures` should briefly list the app / package / module scopes that directly match the current request before expanding the tree.
- When there is no content for `Matched structures` beyond a single obvious target, keep it to one short line rather than a long list.
- `Matched structures` is only for matched app / package / module scopes. Do not place evidence explanations, confidence discussion, or ownership conclusions in this block.

## Recommended Response Template

Use the following output order by default. Empty items may be omitted, but do not change the overall sequence:

1. Status
   - `resolved` or `partial`
2. Summary
   - 2 to 4 short bullets only
   - Do not restate the full tree
   - Do not repeat `Key evidence` here
3. Repository kind
   - For example: `business-monorepo`
   - If frameworks are mixed, immediately state how Vue / React / H5 are distributed
4. Matched structures
   - List the most direct matching app / package / module scopes first
   - Keep it short; do not turn it into a full evidence list
   - Do not mix in explanations that belong to `Key evidence` or the optional note
5. Structure tree
   - Use tree-like hierarchical text
   - Expand only the app / package scope relevant to the current request
   - Expand at least one level under `views/`, `pages/`, or `packages/*/src`
   - When the request involves a page name, you may continue expanding to page-level directories or key page entry files under the module
6. Key entry points
   - List directly relevant `router/routes`, `moduleEntries`, `api`, `i18n`, `store`, `components`, and similar entry points
   - Keep this section to the 2 to 5 most directly relevant entries
   - Prefer this order when available: page root, route entry, module entry, then API / store / i18n entry
7. Key evidence
   - Always output this section
   - Limit it to 1 to 3 critical paths; do not turn it into a long list
8. Optional note when needed
   - Use this only when the user is implicitly asking for final ownership or change scope
   - In that case, say that this workflow provides structure indexing and evidence only, and that final target convergence belongs to a later change-scoping step

Example 1: resolved

```text
Status
- resolved

Summary
- The repository is a `single-app` frontend with a companion local API.
- The current request maps to the React structure under `apps/web`.

Repository kind
- single-app
- React frontend with FastAPI companion

Matched structures
- `apps/web/src`

Structure tree
apps/
├── web/
│   └── src/
│       ├── App.tsx
│       ├── courses-page.tsx
│       └── course-workflow-page.tsx
└── api/
    └── app/

Key entry points
- Route entry: `apps/web/src/App.tsx`
- Page entry: `apps/web/src/course-workflow-page.tsx`

Key evidence
- `apps/web/package.json`
- `apps/web/src/App.tsx`
```

Example 2: partial

```text
Status
- partial

Summary
- The repository kind is identifiable as `single-app`.
- The page clue maps to several React files, so this workflow stops at structure indexing.

Repository kind
- single-app

Matched structures
- `apps/web/src/courses-page.tsx`
- `apps/web/src/course-workflow-page.tsx`

Structure tree
apps/web/src/
├── courses-page.tsx
└── course-workflow-page.tsx

Key entry points
- Route entry: `apps/web/src/App.tsx`

Key evidence
- `apps/web/src/pages.tsx`
- `apps/web/src/App.tsx`
```

## Guardrails

- Ignore `skills/bootstrap/**`, `node_modules`, `dist`, `build`, `coverage`, `report`, build artifacts, and generated files.
- Keep `Status` and `Summary` as the only fixed output head.
- Keep `Summary` short. Do not turn it into a repository walkthrough.
- Do not repeat the same information across `Summary`, `Matched structures`, `Structure tree`, and `Key evidence`. Each block should have one clear role.
- Keep the scan scoped to the user request, but when presenting structure, you may include the necessary upper-level directory semantics for the current target app.
- Do not dump the entire repository tree; focus on relevant apps / packages and their `views` / `pages` / `packages/*/src` module hierarchy.
- Page-layer expansion is only for richer structure understanding and directory indexing; do not use it to rank candidates or give a final page-target conclusion.
- Page-layer expansion may reach page-level directories and key entry files, but it should still stop at structure indexing and evidence rather than converging to a final owner or final `root_path`.
- Do not keep expanding hooks, utils, const, types, or ordinary components just to make page-layer output denser.
- Do not output a flat folder list only; explain directory semantics and organize the result into a readable tree-like structure.
- Do not write scan results back into Repo Guide files.
- Do not guess business ownership when evidence is insufficient; low-confidence cases should be called out as pending confirmation.
- Final ownership convergence and change-target scoping are outside this workflow.
- Do not output `root_path`, `file_path`, candidate ranking, or final owner conclusions. Those belong to later change-scoping workflows.
- Do not add the target-convergence disclaimer by default. Use it only when the user is actually asking for final ownership or final change scope.
- If a page name, module name, or directory fragment matches multiple apps / packages, or the repo kind cannot be confirmed, output only the matching structures and evidence. Do not rank them or give a final ownership conclusion.
