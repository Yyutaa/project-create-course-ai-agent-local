---
name: repo-workflow-load-basics
description: 加载 AGENTS.md 和 repo-profile.md 中的稳定仓库事实与边界，作为后续分析前置。
---

# 仓库工作流：加载基础信息

## 用途

本 Skill 是 Repo Guide workflow 的第一阶段，只负责加载仓库级稳定事实、Repo Guide 入口状态和已确认边界，作为后续结构扫描、目标定位、影响分析和验证指导的前置基础。

本 Skill 不做请求期结构扫描、不定位改动目标、不分析 diff、不选择验证命令，也不执行验证。

## 输入

接受自然语言请求，不要求额外拆分结构化输入字段。

先把当前请求理解为以下两种模式之一：

- `entry-status mode`
  - 用户是在检查 Repo Guide 入口文件和入口登记是否存在、是否完整
  - 常见请求包括查看 Repo Guide 入口状态、bootstrap 是否补齐、仓库稳定事实是否已登记
- `stable-facts mode`
  - 用户是在询问依赖 `repo-profile.md` 的仓库级稳定事实，例如 repo kind、framework map、app/package map、业务范围、运行时模型、共享包边界或仓库级命令覆盖范围

常见输入场景包括：

- 加载仓库基础信息
- 查看这个仓库有哪些应用
- 查看这个仓库应用怎么启动
- 查看 Repo Guide 入口状态
- 查看稳定事实记录位置
- 查看仓库类型、框架映射、应用/包映射
- 查看业务范围、运行时模型和共享包边界
- 查看仓库级命令覆盖范围
- 确认后续 workflow skill 应建立在哪些已确认边界之上

如果用户只给了“仓库概览”“基础信息”“先加载一下 repo 信息”之类的简短描述，也应按自然语言理解并返回仓库级稳定事实。

## 路由边界

这个 workflow 只负责仓库级稳定事实、Repo Guide 入口状态、已确认边界，以及仓库级命令覆盖范围。

如果当前请求已经在问具体页面、模块、路由、文件路径、改动落点、受影响页面，或任务级验证命令选择，就不要继续按 `repo-workflow-load-basics` 执行。此时只需简短说明当前 workflow 只返回仓库级稳定事实，并指向下一步更合适的 workflow：

- repo 级 app map、framework map、业务范围、运行时模型、已记录命令覆盖范围 -> 继续由 `repo-workflow-load-basics` 处理
- tree 风格结构、目录层级、模块布局、页面层结构或 package 布局扫描 -> `repo-workflow-scan-structure`
- 改动落点或文件范围问题 -> `repo-workflow-scope-change-targets`
- 任务级验证命令选择 -> `repo-workflow-validation-guidance`

## 步骤

1. 如果 `AGENTS.md` 存在，先读取它，并检查 Repo Guide 标记块、`repo-profile.md`、skills root、workflow skills 和 coding rule skills。
2. 先判断当前请求属于 `entry-status mode` 还是 `stable-facts mode`。
3. 在 `entry-status mode` 下，优先返回 `AGENTS.md`、`repo-profile.md` 和 skills root 的存在/缺失状态，再基于当前已存在文件检查 workflow skills 登记和 coding rule skills 登记。
4. 在 `stable-facts mode` 下，再按当前请求读取 `repo-profile.md` 中相关的稳定事实章节。
5. 默认只基于 `AGENTS.md` 和 `repo-profile.md` 返回结果，不做请求期结构扫描。
6. 只有当 `repo-profile.md` 已存在、但明显过期，或与当前代码存在明确矛盾时，才做最小必要的源码核验；不要广泛扫描整棵源码树。
7. 只返回仓库级稳定事实、已确认边界、仓库级命令覆盖范围摘要、请求要求时的入口状态结果，以及需要确认的低置信度事实。

## 允许的补充核验

当 `repo-profile.md` 已存在但看起来过期，或与当前代码存在明确矛盾时，补充核验必须保持最小范围。只允许用于确认：

- app 根目录或 shared package 根目录是否仍然存在
- framework 归类是否可以从 package manifest 或应用入口文件直接确认
- `repo-profile.md` 中记录的命令是否仍然存在于当前源码

不要把这类补充核验扩展成：

- 页面级结构扫描
- route 级归属判断
- 改动目标定位
- 影响分析
- 任务级验证命令选择

## 默认输出

- 默认输出自然语言文本，不输出 JSON。
- 始终先输出：
  - `Status`：`resolved` | `partial` | `blocked`
  - `Summary`：用 2 到 4 条简短 bullet，只回答当前请求最相关的仓库级结论
- 输出只覆盖仓库级稳定事实，不混入请求期结构扫描、变更目标、影响分析或验证决策。
- 输出应尽量按当前请求裁剪：
  - 用户只问启动方式时，优先返回仓库级命令覆盖范围摘要和命令记录位置。
  - 用户只问应用/包映射时，优先返回仓库类型、框架映射和应用/包映射。
  - 用户只问 Repo Guide 入口状态时，优先返回 `AGENTS.md`、`repo-profile.md`、skills root 和已登记的 skills 信息。
- 当请求属于 `entry-status mode` 时，入口文件缺失默认应作为当前状态返回，而不是直接视为失败。
- 当请求属于 `stable-facts mode` 时，只有在所需稳定事实依赖某个缺失入口文件、且无法由其余入口文件支撑时，才应停止。
- 当当前 Repo Guide 入口足以回答请求时，使用 `Status: resolved`。
- 当当前只能回答一部分，且存在过期、缺失、低置信度或不一致事实时，使用 `Status: partial`。
- 只有在所需稳定事实依赖关键入口文件、且无法由其余 Repo Guide 入口支撑时，才使用 `Status: blocked`。
- 如果答案仍然可以部分成立，不要使用 `blocked`；当缺失信息只是辅助信息而不是关键前提时，应优先使用 `partial`。
- 命令相关内容只输出仓库级命令覆盖范围摘要，不输出“这次该跑哪个命令”的结论。
- 如果已记录的稳定事实过期、记录不完整，或与当前代码矛盾，要明确标注 warning，并指出需要回查的文件。
- 如果某个稳定事实置信度不足，要明确标注需要确认，而不是用当前猜测补齐。
- 在 `entry-status mode` 下，检查范围应固定收敛在：
  - `AGENTS.md`
  - `repo-profile.md`
  - skills root
  - workflow skills 登记
  - coding rule skills 登记
- 当返回 workflow skills 登记或 coding rule skills 登记结果时，优先使用简短状态，如 `complete` | `incomplete` | `inconsistent`，不要展开成长段叙述。
- `Warnings` 是条件输出块，只在以下情况输出：
  - `repo-profile.md` 已存在，但已过期，或与当前代码存在明确矛盾
  - 仓库入口文件存在，但稳定事实记录明显不完整
- `Requires Confirmation` 是条件输出块，只在以下情况输出：
  - 某个稳定事实置信度较低
  - app / framework / shared package 归类存在多个合理候选
  - `AGENTS.md` 与 `repo-profile.md` 的稳定事实记录不一致
- 如果 `Warnings` 或 `Requires Confirmation` 没有内容，就完全省略该块。

## 输出重点

- Status
- Summary
- Repo Guide entry status when requested
- Repository kind and mapping when requested
- Business scope when requested
- Runtime model when requested
- repository-level command coverage summary when requested
- shared-package boundaries when requested
- Warnings when needed
- Requires Confirmation when needed

## 推荐输出模板

默认可按以下风格输出。固定保留最小头部，再按当前请求展开相关段落；不要扩展成结构扫描或验证建议。

样例 1：resolved

```text
Status
- resolved

Summary
- 仓库级稳定事实记录在 `repo-profile.md` 中。
- 当前仓库是单个 React 前端应用，配有本机 API。
- 任务级验证命令选择应交给 `repo-workflow-validation-guidance`。

Repo Guide entry status
- `AGENTS.md` 已存在
- `repo-profile.md` 已存在
- workflow skill registration: complete
- coding skill registration: complete

Repo profile summary
- 仓库名称：`AI Course Studio`
- 仓库类型：single-app（单个 React 前端应用）
```

样例 2：partial

```text
Status
- partial

Summary
- 仓库级稳定事实记录在 `repo-profile.md` 中，但部分当前事实可能需要回查。
- 当前仓库仍可识别为单个 React 前端应用。

Repo Guide entry status
- `AGENTS.md` 已存在
- `repo-profile.md` 已存在
- workflow skill registration: complete
- coding skill registration: inconsistent

Warnings
- `repo-profile.md` 中 `apps/web/` 的 framework mapping 可能已过期，需要回查。

Requires Confirmation
- `apps/web/` 的 framework 归类置信度较低，需要复核入口文件
```

## 约束

- 输出保持轻量，不要为了协议完整性而强行展开所有段落。
- 只把 `Status` 和 `Summary` 作为固定头部，其余都按请求或按条件输出。
- `Summary` 保持简短，不要扩展成仓库概览长段落。
- 如果请求属于 `entry-status mode`，应直接把缺失的 `AGENTS.md`、`repo-profile.md` 或 skills root 作为状态返回，默认不要把入口缺失视为硬失败。
- 如果请求属于 `stable-facts mode`，只有在所需稳定事实依赖某个缺失入口文件、且无法由其余入口文件支撑时，才停止。
- 不要因为入口文件缺失，就回退到源码扫描并把结果包装成“稳定事实”输出。
- 不要把请求期的结构扫描、变更目标、影响分析或验证决策当作稳定事实返回。
- 不要选择任务级验证命令，也不要给出最终 validation 结论；这属于 `repo-workflow-validation-guidance`。
- 不要把当前请求的页面、模块、diff、报错或验证问题回写成仓库稳定事实。
- 除非用户明确要求，不要改写 `AGENTS.md` 或 `repo-profile.md`。
- 如果某个事实依赖当前代码且 repo profile 看起来过期，要说明这一点并指出需要回查的文件。
