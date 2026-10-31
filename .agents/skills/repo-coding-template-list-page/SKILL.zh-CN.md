---
name: repo-coding-template-list-page
description: 先选择同应用列表页参考，再考虑兜底结构示意。
---

# 仓库编码：列表页模板

## 用途

先选择同应用列表页参考，再考虑兜底结构示意。

## 上下文读取

- 先读 `AGENTS.md` 确认 Repo Guide 入口。
- 按需读取 `repo-profile.md` 的稳定事实和边界；编码判断以当前同应用源码为主。
- 需要证据时检查当前仓库源码。

## 证据入口

- React: `apps/web/src/courses-page.tsx`
- React: `apps/web/src/components/layout.tsx`
- 这些采样路径只是证据入口，不是全局强制实现规则。当同应用、同框架、同模块的当前示例与这些入口不一致时，优先使用当前示例。
- 这些路径仅作查找锚点；除非用户明确确认稳定仓库约束，否则不作为全局规则。

## 按框架查找

- React: 从 `apps/web/src/courses-page.tsx` 开始，并核对目标模块的邻近文件。
- Vue: No evidence found in lightweight sampling
- H5: No evidence found in lightweight sampling

## 需要检查的内容

- 检查当前列表页、加载和空状态、导航及有证据的 UI 依赖。

## 需要避免的内容

- 不要把内联示意直接复制为实现，也不要默认手写列表控件。

## 需要确认

- 实现前确认目标页面和组件库可用性。

## 验证提示

- 核对最邻近的变更文件；React/TypeScript 变更运行 `npm --prefix apps/web run typecheck`，API 契约变更再运行对应后端测试。
- 通过 `repo-workflow-validation-guidance` 选择任务对应的最窄验证命令。

## 响应建议

使用自然语言，说明相关当前源码证据、收窄后的实现规则、未明确的归属和匹配的验证建议。

## 约束

- 不要把运行时扫描结果写入 `AGENTS.md` 或 `repo-profile.md`。
- 优先使用当前同应用、同框架、同模块源码，而非采样锚点或过时假设。
- 除非用户明确要求实现变更，否则不要修改源码。

## React 结构示意

仅作结构示意与兜底参考，不是可直接复制的代码。优先使用同应用示例和目标仓库确有证据的组件库。

```text
apps/web/src/<page>.tsx
  [evidenced component-library list/table] -> loading/empty/error -> item action
  [evidenced component-library filter/pagination] when needed
apps/web/src/App.tsx -> route entry
```

## H5 结构示意

仅作结构示意；确认 H5 目标及其移动组件库后才可使用。轻量采样未发现 H5 源码。

```text
[confirmed H5 page root]/<page>
  [evidenced mobile component-library control] -> loading/error/action
  [same-app route and API entries] -> navigation and request
```

## 模板应用规则

- 从 `repo-profile.md` 与当前源码确认目标应用、根目录和框架。
- 按顺序优先使用：用户给出的参考模块；同应用同框架示例；有证据的组件库模式；最后才是内联示意。
- 当前包清单未显示专门的 UI 组件库；选用控件前重新核对。
- 不要默认手写表格、表单、模态框、抽屉、列表或底部弹层。
- 只在确认 React 或 H5 目标且缺少更高优先级参考时使用示意。Vue 目标应检查同应用 Vue 源码并请求确认。
- 实现前关联适用的路由、API、组件与状态规则技能。
