---
name: repo-workflow-coding-guidance
description: 结合相关 coding skill、仓库稳定事实和当前源码证据，输出请求级编码指导。
---

# 仓库工作流：编码指导

## 用途

结合相关 coding rule skill、仓库稳定事实和当前源码证据，返回请求级编码指导。

这个 workflow 的职责不是只列出涉及哪些 coding skill，而是把这些 skill 消化成当前请求范围内可直接执行的实现建议和生码规则要求。

## 输入

接受自然语言请求，但要区分为两类输入。

第一类：定向编码指导输入

- 已经包含明确的 target context，例如页面、模块、路由、共享包、变更文件，或上游 workflow 已确认的改动目标
- 也可以直接提供 `root_path`、`file_path`、目标文件路径或已确认的变更范围
- 这类输入下，应直接输出面向该目标的编码指导

第二类：信息不足输入

- 只有需求描述、模式询问、泛化问题，或“这种场景一般怎么做”这类问题
- 没有明确页面、模块、路由、共享包、文件路径或已确认的改动目标
- 这类输入下，这个 workflow 不负责反推出最终改动落点；它应返回未解析 guidance，并指出下一步优先确认哪些 coding categories

如果 target context 同时映射到多个 app、portal、shared package 或多个同级候选目标，也不应直接给出定向实现建议；此时同样返回未解析 guidance，并请求确认。

## 相关 skill 选择依据

相关 coding skill 的选择应基于当前请求中的以下三类信号，而不是任意罗列可能相关的 skill：

- 输入类别，如菜单、路由、API、i18n、permission、store、shared module、template 类型
- 目标路径信号，如 `router/routes`、`api/service`、`locale/i18n`、`store/model`、`packages/**`
- change intent，如 add page、change route、change API payload、translate UI copy、add permission、modify shared package

## 步骤

1. 先读取 `AGENTS.md`。
2. 先判断当前输入属于“定向编码指导输入”还是“信息不足输入”，以及是否已经具备足够的 target context，例如明确页面、模块、路由、共享包、变更文件，或上游 workflow 已确认的 `root_path` / `file_path`。
3. 如果当前属于“信息不足输入”，或 target context 同时映射到多个 app、portal、shared package 或多个同级候选目标，则返回未解析 guidance。先明确说明当前缺少或存在冲突的 target context，并优先要求确认目标上下文，例如所属 app / portal、目标页面或模块、`root_path`、是否位于 `packages/**`、以及直接 consumer 或直接入口文件；只有当当前输入已经提供了部分目标线索时，才再从当前案例里真正可能阻塞实现判断的已登记 coding-rule 类别中收窄出需要确认的项，例如 `menu`、`route`、`api`、`shared-module`、`permission`、`i18n`、`store`、`hooks`、`enum`、`time`、`file-operation` 或 template 类别。
4. 如果 target context 已明确，再只加载与当前请求真正相关的 coding skill。
5. 按“相关 skill 选择依据”筛选当前请求真正相关的 coding skill。
6. 读取匹配的 `repo-profile.md` 边界和模板章节。
7. 在给出实现方向前，优先检查同应用、同框架、同模块的源码证据。
8. 输出带有具体文件锚点的实现建议和生码规则要求，而不是停留在 coding skill 名称列表。

## 输出重点

- 仅固定 `Status` 和 `Summary` 作为最小输出头
- 当前真正相关的规则类别
- 应优先覆盖泛化样例的同应用源码锚点
- 共享包或跨框架风险
- 有针对性的实现建议和生码规则要求

## 默认输出

始终先输出：

- `Status`
- `Summary`

只有当当前输入已经具备清晰且足够收窄的 target context，并且 workflow 能把相关 coding skill 收敛成面向该目标的定向实现指导时，才使用 `Status: resolved`。

当出现以下情况时，使用 `Status: unresolved`：

- 当前输入仍然属于信息不足输入
- target context 同时映射到多个 app、portal、shared package 或同级候选目标
- 当前输入仍缺少所属 app / portal、目标页面或模块、`root_path`、是否位于 `packages/**`、或直接 consumer / 直接入口文件等实现判断所必需的上下文

`Summary` 控制在 2 到 4 条短 bullet，只说明当前编码指导结论，不要把完整源码锚点或实现建议重复一遍。

当 `Status: resolved` 时，默认按以下顺序输出：

1. `Status`
2. `Summary`
3. 当前请求真正相关的 coding categories
4. 同应用、同框架、同模块应优先遵循的源码锚点
5. 直接可执行的实现建议和生码规则要求
6. 仅在有证据且确有必要时补充共享包或跨框架风险

不要只输出 coding skill 名称列表；如果目标上下文已经足够，必须把相关 skill 收敛成面向当前请求的直接指导。

当 `Status: unresolved` 时，默认按以下顺序输出：

1. `Status`
2. `Summary`
3. `Target context to confirm first`
4. 仅在当前输入已经提供足够线索、可以缩小阻塞项时再输出 `Rule categories to confirm next`

对于未解析 guidance：

- 明确说明当前缺少目标上下文，或当前存在多个候选目标，尚不能定向给出编码指导
- 先要求确认 target context，例如所属 app / portal、目标页面或模块、`root_path`、是否位于 `packages/**`、以及直接 consumer 或直接入口文件
- 只有当当前输入已经提供了部分目标线索时，再从当前案例里真正可能阻塞实现判断的已登记 coding-rule 类别出发，例如 `menu`、`route`、`api`、`shared-module`、`permission`、`i18n`、`store`、`hooks`、`enum`、`time`、`file-operation` 或 template 类别
- 如果当前输入已经提供了足够线索，优先收窄到当前案例里真正阻塞实现判断的 2 到 4 类
- 只有当当前输入几乎没有线索、无法继续缩小阻塞项时，才退回到较宽的未决类别列表
- 请求补充确认，而不是把这些类别写成默认实现结论

## 推荐输出模板

输出自然语言即可，必要时可按以下顺序组织：

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

如果当前属于“信息不足输入”，或 target context 同时映射到多个候选目标，可改为：

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

## 最小样例

样例 1：resolved

```text
Status
- resolved

Summary
- 当前 target context 已足够收窄，可以直接沿用目标 app 内现有的 route、API 与 components 组织方式。
- 同应用源码锚点应优先于仓库级泛化样例。

Relevant rule categories
- `route`
- `api`
- `components`

Source anchors
- `apps/web/src/App.tsx`
- `apps/web/src/course-workflow-page.tsx`
- `apps/web/src/components/layout.tsx`

Implementation guidance
- 先沿用当前目标页面所在 app 的路由注册方式，不要改成其他 app 的入口模式。
- 接口入参与响应处理优先复用当前模块已有 request/response 写法，不要单独发明新的封装层。

Code-generation rules
- 路由、页面实现、组件组织应保持同应用现有方式一致。
- 如果同模块已有同名能力示例，优先复制其组织模式，再做最小改动。
```

样例 2：unresolved

```text
Status
- unresolved

Summary
- 当前无法给出定向编码指导，因为缺少明确的 target context。
- 需要先确认目标归属和范围，再决定 route 或 API 的实现模式。

Target context to confirm first
- 所属 app / portal
- 目标页面或模块
- 是否位于 `packages/**`

Rule categories to confirm next
- `route`
- `api`
```

## 约束

- 将 coding skill 当作指导型工作流，而不是固定法条。
- 仅固定 `Status` 和 `Summary` 作为最小输出头，其他块按当前请求实际需要出现。
- 当同应用示例与仓库通用锚点不一致时，优先当前同应用示例。
- 当 `Status: resolved` 时，`Relevant rule categories` 只保留当前请求真正相关的类别，不要膨胀成仓库级 checklist。
- 当 `Status: resolved` 时，若存在足够证据，优先给出 2 到 5 个同应用、同框架、同模块的具体 `Source anchors`。
- 当 target context 已明确时，不要停在 coding skill 名称列表；必须收敛成实现建议和生码规则要求。
- 当当前属于“信息不足输入”，或 target context 同时映射到多个候选目标时，不要假装已经得出了实现结论；先返回未解析 guidance，并优先要求确认 target context。在当前输入已经提供了部分目标线索时，才从当前案例里真正可能阻塞实现判断的已登记 coding-rule 类别出发，优先收窄到 2 到 4 类。
- 当 `Status: unresolved` 时，不要像目标已确认一样继续输出 `Implementation guidance` 或 `Code-generation rules`。
- 不要把未登记的类别当作已有 coding-rule skill 来引用。如果当前源码线索指向模块注册或暴露文件，应把这类确认需求折回到最接近的已登记类别，例如 `menu`、`route` 或 `shared-module`，并直接指出具体源码锚点。
- 不要脱离输入类别、路径信号和 change intent，泛泛罗列 coding categories。
- 不要推荐与目标应用框架冲突的 UI 库或架构。
- 不要把验证命令选择混入这个 workflow；验证命令属于 `repo-workflow-validation-guidance`。
- 输出自然语言文本。
