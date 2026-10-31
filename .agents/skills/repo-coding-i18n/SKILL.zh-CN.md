---
name: repo-coding-i18n
description: 修改用户可见文案前查找本地化归属。
---

# 仓库编码：国际化

## 用途

修改用户可见文案前查找本地化归属。

## 上下文读取

- 先读 `AGENTS.md` 确认 Repo Guide 入口。
- 按需读取 `repo-profile.md` 的稳定事实和边界；编码判断以当前同应用源码为主。
- 需要证据时检查当前仓库源码。

## 证据入口

- No evidence found in lightweight sampling
- 这些采样路径只是证据入口，不是全局强制实现规则。当同应用、同框架、同模块的当前示例与这些入口不一致时，优先使用当前示例。
- 这些路径仅作查找锚点；除非用户明确确认稳定仓库约束，否则不作为全局规则。

## 按框架查找

- React: No evidence found in lightweight sampling
- Vue: No evidence found in lightweight sampling
- H5: No evidence found in lightweight sampling

## 需要检查的内容

- 搜索目标应用的语言资源与文本渲染；当前采样只发现内联中文。

## 需要避免的内容

- 不要发明国际化框架或翻译键约定。

## 需要确认

- 新增语言时确认本地化要求。

## 验证提示

- 核对最邻近的变更文件；React/TypeScript 变更运行 `npm --prefix apps/web run typecheck`，API 契约变更再运行对应后端测试。
- 通过 `repo-workflow-validation-guidance` 选择任务对应的最窄验证命令。

## 响应建议

使用自然语言，说明相关当前源码证据、收窄后的实现规则、未明确的归属和匹配的验证建议。

## 约束

- 不要把运行时扫描结果写入 `AGENTS.md` 或 `repo-profile.md`。
- 优先使用当前同应用、同框架、同模块源码，而非采样锚点或过时假设。
- 除非用户明确要求实现变更，否则不要修改源码。
