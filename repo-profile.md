# Repo Profile

## Profile

- Repo name: AI Course Studio（本地版）
- Repo type: 本地优先的课程生成应用仓库，含前端、API 与独立 Worker
- Last verified at: 2026-10-31

## Frontend App Repo Classification

- Repo kind: single-app（前端业务应用；同仓库包含配套后端）
- Frameworks:
  - React: yes
  - Vue: no evidence found in source roots
  - H5: no evidence found in source roots
- App / framework map:
  - App/root: `apps/web/`
    - Framework: React + TypeScript + Vite
    - Role: 本机课程生成工作台
    - Source roots:
      - `apps/web/src/`
    - Page roots:
      - `apps/web/src/courses-page.tsx`
      - `apps/web/src/course-workflow-page.tsx`
      - `apps/web/src/workflow-page.tsx`
    - Route roots:
      - `apps/web/src/App.tsx`
    - API roots:
      - `apps/web/src/api.ts`

## Business Scope

### PC

- Business scope:
  - 本机创建、观察和人工审批七阶段课程生成 Run；阅读课程与交付证据。
- Service portals:
  - Portal: AI Course Studio 本机工作台
    - Apps:
      - `apps/web/`

### Mobile

- Business scope: unknown；轻量采样未发现独立移动端或 H5 应用。
- Service apps: unknown。

## Commands

### Install

- Command: `npm --prefix apps/web install`（前端；首次启动脚本也会安装缺失依赖）
- Command: `apps/api/.venv/bin/python -m pip install -e apps/api`（后端；需先创建 Python 3.12 虚拟环境）
- CWD: 仓库根目录

### Dev / Serve

- 本机完整应用:
  - Command: `bash scripts/start-agent.sh`（macOS）或 `.\scripts\start-agent.ps1`（Windows PowerShell）
  - Example: 前端 127.0.0.1:5176、API 127.0.0.1:8003、独立 Worker 无 HTTP 端口

### Build

- Command: `npm --prefix apps/web run build`

### Lint / Fix

- Command: `npm --prefix apps/web run typecheck`（前端已登记的静态检查）
- Command: `apps/api/.venv/bin/python -m ruff check apps/api`（Ruff 依赖和配置可见；仓库未登记统一 lint 脚本）

### Runtime verification entrypoints

- API 健康检查:
  - `curl http://127.0.0.1:8003/api/health`
- 前端回归:
  - `npm --prefix apps/web run test:v0`
- 后端回归:
  - `apps/api/.venv/bin/python -m pytest apps/api/tests`

## Shared Package Scope

- 未发现仓库内 `packages/` 共享包或工作区包；`apps/web/` 通过 REST API 使用 `apps/api/`，后者是服务而非前端共享包。

## App Runtime Topology

- Runtime type: 单个 React 前端 + 本机 FastAPI + 独立本地 Worker
- App: `apps/web/`
  - Portal: AI Course Studio 本机工作台
  - Service app: N/A
  - Runtime role:
    - 通过 REST API 读取 Run 事实并提交人工命令；不执行 Graph。
  - Dependency:
    - `apps/api/` 提供 API，Worker 独立处理已受理 Command。
  - Startup linkage example:
    - 1. `scripts/start-agent.sh` 启动 API、Worker 与 Vite。
    - 2. Vite 将 `/api` 请求代理到本机 API。
  - Notes:
    - 前端固定端口 5176；API 固定端口 8003；Worker 无 HTTP 端口。

## App-to-Package Dependency Map

- React app to shared package map: 未发现仓库内共享包。
- Shared package to direct consumer apps: 不适用。
- Cross-framework shared usage exists: 未发现。
- Mobile dependency status: 未发现独立移动端或 H5 源码。
- Service dependency: `apps/web/` -> `apps/api/`（REST API；并非包依赖）。

## Modification Boundary

- Treat shared packages as shared surfaces; verify consuming apps before broad refactors.
- Prefer same-app, same-framework, same-module evidence over generic cross-app examples.
- App-local menu ownership and route ownership belong to app routing layers.
- 当前页面与路由入口以 `apps/web/src/App.tsx` 和邻近页面源码为准；不得把模板中的目录惯例当成现有事实。
- 前端 API 类型与后端公开 Schema 需保持同步；API 与 Worker 的执行权边界遵循 `AGENTS.md`。
- Do not write request-time scan results, change targets, diff impact, or validation results into `AGENTS.md` or `repo-profile.md`.
- Keep request-time findings out of this file.
