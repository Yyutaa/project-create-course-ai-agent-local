---
name: repo-coding-api
description: 修改 API 使用前查找当前 REST 客户端与请求响应边界。
---

# 仓库编码：API

## 用途

修改 API 使用前查找当前 REST 客户端与请求响应边界。

## 上下文读取

- 先读 `AGENTS.md` 确认 Repo Guide 入口。
- 按需读取 `repo-profile.md` 的稳定事实和边界；编码判断以当前同应用源码为主。
- 需要证据时检查当前仓库源码。

## 证据入口

- React: `apps/web/src/api.ts`
- React: `apps/web/src/course-workflow-page.tsx`
- React: `apps/api/app/api/run_routes.py`
- 这些采样路径只是证据入口，不是全局强制实现规则。当同应用、同框架、同模块的当前示例与这些入口不一致时，优先使用当前示例。
- 这些路径仅作查找锚点；除非用户明确确认稳定仓库约束，否则不作为全局规则。

## 按框架查找

- React: 从 `apps/web/src/api.ts` 开始，并核对目标模块的邻近文件。
- Vue: No evidence found in lightweight sampling
- H5: No evidence found in lightweight sampling

## 需要检查的内容

- 检查类型化请求、请求封装、响应处理及对应 FastAPI Schema。

## 需要避免的内容

- 不要仅凭前端类型认定后端行为。

## 需要确认

- 变更跨越前后端 API 契约时确认归属。

## 验证提示

- 核对最邻近的变更文件；React/TypeScript 变更运行 `npm --prefix apps/web run typecheck`，API 契约变更再运行对应后端测试。
- 通过 `repo-workflow-validation-guidance` 选择任务对应的最窄验证命令。

## 响应建议

使用自然语言，说明相关当前源码证据、收窄后的实现规则、未明确的归属和匹配的验证建议。

## 约束

- 不要把运行时扫描结果写入 `AGENTS.md` 或 `repo-profile.md`。
- 优先使用当前同应用、同框架、同模块源码，而非采样锚点或过时假设。
- 除非用户明确要求实现变更，否则不要修改源码。
