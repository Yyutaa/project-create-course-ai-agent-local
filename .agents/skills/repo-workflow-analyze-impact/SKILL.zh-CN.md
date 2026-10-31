---
name: repo-workflow-analyze-impact
description: 根据变更文件返回受影响页面菜单路径，并补充有证据的跨应用或共享风险提示。
---

# 仓库工作流：分析影响

## 用途

优先返回当前证据下最窄且可信的用户侧影响，概括变更文件可能带来的影响范围。

这个 workflow 只负责“基于已有变更分析影响面”，不负责在没有变更输入时反推需求应该改哪里。

## 前置依赖

- 优先建立在 `repo-workflow-scan-structure` 已经加载的仓库结构认知之上。
- 如果当前上下文里还没有足够的结构结果，再补充读取 `AGENTS.md`、`repo-profile.md`，并按最小范围检查相关 route / menu / shared package / 生成产物路径。
- 不要在这个 workflow 中重新展开广泛结构扫描；结构索引的建立主要由 `repo-workflow-scan-structure` 负责。

## 输入

接受以变更为中心的输入，例如变更文件列表、diff 摘要、PR 描述中的变更信息，或粘贴的 git 输出。

可以接受自然语言说明，但前提是其中已经包含明确的变更输入；如果只有需求描述、页面名、菜单名或 bug 现象，而没有 changed files / diff / 变更摘要，就不应在这里继续做影响分析。

常见输入场景包括：

- 分析一组变更文件会影响哪些页面
- 根据 diff 摘要判断受影响菜单路径
- 判断共享包改动会波及哪些应用
- 判断生成产物、工具链或配置改动是否需要额外警告

## 步骤

1. 先读取 `AGENTS.md`。
2. 先确认当前输入里是否存在明确的 changed files、diff 摘要、PR 变更信息或等价的变更证据。
3. 如果没有变更输入，则停止影响分析，并明确说明当前无法判断受影响页面。
4. 优先复用当前上下文中已经加载的 `repo-workflow-scan-structure` 结构结果；如果还没有足够结构结果，再读取 `repo-profile.md` 中的应用映射、业务入口、运行时模型、边界和依赖拓扑。
5. 先把变更文件映射到当前证据下最窄且可信的用户侧影响面。只有当当前 change evidence 已经直接支持页面或菜单路径时，才输出这类路径；只有当这层主结论仍不足以判断共享包、跨应用、生成产物或工具链风险时，才补充检查相关入口。
6. 按默认输出顺序返回：如果页面或菜单路径已被直接证据支撑，就返回这类路径；否则返回受影响 surface 或已确认的 consumer app。只有在确有必要时才补充简短风险提示，且仅在主结论本身不足以支撑判断时才补充极少量路径证据。

## 输出重点

- 仅固定 `Status` 和 `Summary` 作为最小输出头
- 按应用归类、且已被直接证据支撑的页面或菜单路径
- 当页面或菜单路径不是可信输出时，返回受影响的 surfaces 或已确认的 consumer apps
- 只有在证据表明存在跨应用、跨框架或生成产物风险时才给出警告

## 默认输出

始终先输出：

- `Status`
- `Summary`

当当前输入已经包含可用的 change evidence，且 workflow 可以基于这些证据给出最窄且可信的影响结论时，使用 `Status: resolved`。

当当前输入缺少 changed files、diff 摘要、PR 变更详情或等价 change evidence 时，使用 `Status: unresolved`。

`Summary` 控制在 2 到 4 条短 bullet，只说明当前影响分析结论，不要把完整证据或每一条受影响页面重复一遍。

当 `Status: resolved` 时，默认按以下顺序输出：

1. `Status`
2. `Summary`
3. 被直接证据支撑的页面或菜单路径
4. 如果页面或菜单路径不是可信输出，则返回受影响的 surfaces 或已确认的 consumer apps
5. 仅在有证据且确有必要时补充简短风险提示，例如跨应用、共享包、工具链或生成产物风险
6. 只有当主要影响输出本身不足以支撑判断时，才补充极少量路径证据

如果变更文件已经可以清楚映射到具体页面或菜单路径，默认只输出这些路径；不要额外展开证据、app / package / tooling / validation 小节。

如果变更文件本身并不能可信地映射到页面或菜单路径，就不要硬凑这类路径；改为返回最窄的受影响 surfaces 或已确认的 consumer apps。

当 `Status: unresolved` 时，默认按以下顺序输出：

1. `Status`
2. `Summary`

如果当前没有任何可用于分析的变更输入，默认不要推测受影响页面，直接说明当前无法分析及原因。

## 推荐输出模板

输出自然语言即可，必要时可按以下顺序组织：

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

如果页面菜单路径已经足够清晰，默认只保留 `Impacted pages` 段落。

如果菜单路径不是可信输出，可改为：

```text
Status
- resolved

Summary
- `...`

Impacted surfaces
- `apps/web/src`，当证据只能定位前端应用层时
```

只有在页面菜单路径不足以支撑判断时，才补充极少量证据，例如：

```text
Evidence
- `...`
```

如果当前没有可用的 change evidence，则使用：

```text
Status
- unresolved

Summary
- `...`
```

## 最小样例

样例 1：resolved

```text
Status
- resolved

Summary
- 当前 changed files 直接映射到 `AI Course Studio` 内的页面本地流程。
- 页面级菜单路径已经是当前最窄且可信的影响输出。

Impacted pages
- `AI Course Studio` / `课程`
- `AI Course Studio` / `新建课程`
```

样例 2：unresolved

```text
Status
- unresolved

Summary
- 当前无法分析受影响页面，因为没有提供 changed files、diff 摘要或等价的变更信息。
```

## 约束

- 默认返回当前证据下最窄且可信的用户侧影响，不写成架构长文。
- 仅固定 `Status` 和 `Summary` 作为最小输出头，其他块按当前请求实际需要出现。
- 如果没有 changed files、diff 摘要、PR 变更信息或等价变更证据，直接停止并说明当前无法分析影响面；不要把需求定位、页面定位或模块猜测混进来。
- 当 `Status: resolved` 时，只有在当前 change evidence 能可信支撑页面或菜单级映射时，才输出 `Impacted pages`。
- 当 `Status: resolved` 时，如果证据只能支撑模块级、应用级、shared-package 级或已确认 consumer 级影响，则输出 `Impacted surfaces`。
- 当 `Status: unresolved` 时，不要像影响已经成立一样继续输出 `Impacted pages`、`Impacted surfaces`、`Warnings` 或 `Evidence`。
- 当页面或菜单路径已经足够清晰时，不要默认补证据。
- 当页面或菜单路径对当前改动并不是可信输出时，不要强行输出它；改用受影响的 surfaces 或已确认的 consumer apps。
- 当当前 change evidence 只能支撑模块级、应用级、shared-package 级或 consumer 级影响时，不要反向硬推页面或菜单路径。
- 当变更文件只是普通页面文件、路由文件或明确的页面本地实现时，不要额外展开 app/package/tooling 分类说明。
- 不要扩展成影响分类总表、架构说明或验证建议。
- 不要默认推荐验证命令；验证命令属于 `repo-workflow-validation-guidance`。
- 只有当变更文件明确触达共享包、生成产物、工具链文件、locale/permission/error-code/enum 基础设施、构建配置或跨应用消费链路时，才补充简短风险提示。
- 除非 diff 直接触达，否则忽略 bootstrap skill 文件和生成产物。
- 不要把“应该改哪里”的目标圈定职责混入这个 workflow；那不是 impact 分析本身。
- 输出自然语言文本。
