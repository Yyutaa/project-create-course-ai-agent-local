---
name: repo-workflow-scope-change-targets
description: 为用户需求圈定最可能的主改动落点与首轮相关文件范围。
---

# 仓库工作流：圈定改动目标

## 用途

把自然语言请求映射到最可能的主改动落点，并返回首轮应优先检查的相关文件范围。

## 输入

接受自然语言输入，不要求额外拆分结构化输入字段。

常见输入来源包括：

- 用户需求描述
- PRD / Jira / bug log
- 页面名、菜单名、模块名、路由名、共享模块名
- 可选的结构扫描结果或上游 workflow 输出

常见输入场景包括：

- 圈定需求改动目标
- 查找某个功能在哪
- 确定某个 bug 的主改动落点
- 把业务术语映射到源码文件
- 确认某个需求应该落在哪个已有页面、模块或共享模块
- 判断某个新增模块在当前仓库中是否已存在对应入口

如果用户只给了页面名、模块名、菜单名、路由名、共享模块名或一句目标描述，也应先按自然语言理解，再映射到最可能的改动范围。

## 前置依赖

- 优先建立在 `repo-workflow-scan-structure` 已经加载的仓库结构认知之上。
- 如果当前上下文里还没有足够的结构结果，只补充读取 `AGENTS.md`、`repo-profile.md`，并按最小范围检查相关 app / package / route / 直接目标层入口。
- 不要在这个 workflow 中重新展开广泛结构扫描；结构索引的建立主要由 `repo-workflow-scan-structure` 负责。

## 步骤

1. 优先复用当前上下文中已经加载的 `repo-workflow-scan-structure` 结构结果，先用直接目标层索引缩小到相关 app / package / 直接目标层。
2. 如果当前上下文还没有足够的结构结果，先读取 `repo-profile.md` 中与当前请求相关的应用映射、运行时模型、修改边界和仓库分类章节；只有在需要确认 Repo Guide 入口登记或 workflow 可用性时，才读取 `AGENTS.md`，然后再做最小补充检查。
3. 基于已知结构判断相关 app、shared package、framework 和直接目标层级；不要把结果扩展成广泛结构分析。
4. 对请求中的页面名、菜单名、模块名、路由名、共享模块名或其它显式路径线索，先与当前源码做精确核对。
5. 在相关应用/共享包中按搜索优先级规则检查必要类目，并在已经足够圈定主改动落点和首轮改动范围时停止继续扩查。
6. 按判定优先级决定返回精确命中、现有单候选、可 proposed 的单目标、多候选或未解析结果。
7. 如果输入涉及多个模块、页面、菜单、共享模块或 PRD 小节，为每个模块分别输出独立目标块，不要合并成共享父目录。
8. 即使最强证据来自 route 文件、页面入口文件、共享模块入口文件、导出入口或消费入口，也要先把现有命中结果归一到目录级 `root_path`。
9. 返回最可能的 `root_path`、首轮改动范围 `file_path`、证据、置信度和需要确认的项。

## 搜索优先级规则

按输入类型，至少优先检查以下类目：

- 页面名 / 模块名输入
  - 如果名称明显对应 app 内页面，必须先看：页面/模块目录、关键入口文件、route 注册文件
  - 如果名称明显对应 shared package / shared module，必须先看：共享模块目录、共享模块入口、导出入口、消费入口
  - 已命中 app 内现有页面或模块后，只有当 direct import、consumer entry 或其他直接依赖线索表明 shared package / shared module 属于首轮联动面时，才继续检查；如存在这类直接依赖，再把对应共享模块纳入 `file_path`
  - 已命中主改动落点后，再补充检查与该落点直接相关、且通常需要联动检查的 API / store / hook / permission / i18n 文件
- 菜单名 / 路由名输入
  - 必须先看：route / menu 注册文件、route 指向的直接目标入口、对应模块目录
  - 已命中 app 内现有页面或模块后，只有当 direct import、consumer entry 或其他直接依赖线索表明 shared package / shared module 属于首轮联动面时，才继续检查；如存在这类直接依赖，再把对应共享模块纳入 `file_path`
  - 已命中主改动落点后，再补充检查与该落点直接相关、且通常需要联动检查的 moduleEntries、API / store / permission / i18n 文件
- bug / 功能点输入
  - 必须先看：直接目标入口、route、对应模块目录；若明显落在 shared package，则改看共享模块目录、导出入口和消费入口
  - 已命中 app 内现有页面或模块后，只有当 direct import、consumer entry 或其他直接依赖线索表明 shared package / shared module 属于首轮联动面时，才继续检查；如存在这类直接依赖，再把对应共享模块纳入 `file_path`
  - 已命中主改动落点后，再补充检查与该落点直接相关、且通常需要联动检查的 API / store / hook / permission / i18n 文件
- create / migrate / implement 新模块输入
  - 必须先看：`repo-profile.md` 是否定义新增模块默认落点
  - 如果 `repo-profile.md` 已有明确约定，优先按该约定检查对应 app / package 的目标层级
  - 如果 `repo-profile.md` 没有说明，不要默认偏向任何 framework；除非当前请求或源码证据已经明确 app / framework，否则保持未收敛
  - 即使用户没有显式写出 `create`、`新模块`、`implement`，只要自然语言里出现“新菜单分支”“新的父菜单层级”“菜单路径里包含 `New` / `new` / `新增` / `新`”，或在现有父层级下明显是在新增同级菜单，也要把它当成新模块信号处理
  - 当这些新模块信号已经成立，且请求叶子目标在当前直接目标层中不存在时，应优先基于已确认的 app / framework / 直接目标层构造唯一 proposed `root_path`，而不是继续扩散成多个语义相关候选
  - 只有当请求明确要求 shared package，或现有证据表明该能力应作为共享模块复用时，才检查或 proposed 到 shared package
  - 再检查：现有直接目标层目录、同级模块目录、route / moduleEntries、是否已有同名叶子模块
  - 不要为了 proposed `root_path` 反向搜索大量 API / store / hook / component 来填充 `file_path`

如果多个类目同时可用，优先顺序为：

1. 直接目标层目录
2. 直接目标层入口文件
3. route / menu / moduleEntries / 共享导出入口 / 消费入口
4. API / store / hook / permission / i18n
5. component

当直接目标层目录、直接目标层入口文件或 route / 导出入口证据已经足以圈定 `root_path` 时，应停止继续扩大搜索范围；但如果已经命中该主改动落点，仍可继续补充与该落点直接相关、且通常需要联动检查的 API、store、hook、permission、i18n 文件进入 `file_path`。当 `file_path` 已经覆盖入口和主要联动面后，就应停止；不要为了补齐类目而把仅因目录相邻、但与该落点没有直接关联的文件回填进 `file_path`。

## 默认输出

- 默认输出自然语言文本，不输出 JSON。
- 始终先输出：
  - `Status`：`resolved` | `partial` | `unresolved`
  - `Summary`：2 到 4 条简短 bullet，只回答当前请求最相关的改动目标圈定结论
- 输出以 `root_path` 和 `file_path` 为中心，不扩展成广泛结构分析或影响分析。
- 如果输入涉及多个模块、页面、菜单或共享模块，必须按模块分别输出，不要合并。
- 一个目标块只对应一个 `root_path`；如果一个输入明确对应多个直接目标入口，就输出多个目标块，不要在同一目标块里放多个 `root_path`。只有当连 proposed path 都无法可靠构造时，才允许返回不带目标块的未解析结果。
- 当当前请求已经收敛到一个具体目标块时，无论是精确命中还是单一现有/可 proposed 目标，使用 `Status: resolved`。
- 当当前请求仍存在多个候选目标块，或一个请求本身覆盖多个独立模块、需要分别输出多个目标块时，使用 `Status: partial`。
- 只有当连一个可靠的 proposed `root_path` 都无法构造时，才使用 `Status: unresolved`。
- `root_path` 表示主改动落点目录。命中现有目标时应返回真实目录；proposed 场景下可返回建议目录。
- `root_path` 必须始终是目录路径。如果最强证据是文件级命中，应先回落到该文件所属的目标目录，再把文件证据保留在 `file_path` 或 `evidence` 中。
- `file_path` 表示围绕主改动落点的首轮检查文件列表，不是同模块全量文件清单，也不要求所有文件都位于 `root_path` 目录内。
- 当没有首轮联动文件可列时，明确写 `file_path: none`，不要把该字段留空。
- 当 `root_path` 已命中现有目标时，`file_path` 可以纳入与该落点直接相关、且通常需要联动检查的 route、API、store、hook、permission、i18n、导出入口、消费入口或直接依赖的 shared module 等关联文件；这些文件可以位于 `root_path` 内，也可以位于直接 consumer 或直接依赖侧。仅因目录相邻但无直接关联的文件不应纳入。
- 当存在未解析项、名称冲突或低置信度判断时，要明确标注 `requires confirmation`。
- `confidence` 必须与判定结果绑定：
  - 精确命中 -> `high`
  - 单一现有候选 -> `medium`
  - 单一 proposed target -> `low`
  - 多候选 -> 每个候选块都使用 `low`
  - `unresolved` -> 不输出 `confidence`
- 输出格式以自然语言可读性优先。单目标且结论清晰时，可直接用简短条目说明 `root_path`、`file_path`、`evidence`、`confidence` 和 `requires confirmation`；多目标或歧义场景下，再展开成多个目标块。

## 输出重点

- `Status`
- `Summary`
- `root_path`：主改动落点目录；若不是现有精确命中，其推导依据需在 `evidence` 中说明
- `file_path`：围绕主改动落点的首轮检查文件列表，通常覆盖入口及主要联动面；允许包含直接 consumer 或直接依赖侧的关联文件
- `evidence`：1 到 3 条最直接支撑定位结论的路径或线索
- `confidence`：仅使用 `high` / `medium` / `low`
- `requires confirmation` 和未解析项

## 判定优先级

按以下顺序收敛结果，不要混用：

1. 精确命中
   - 请求中的页面名、模块名、菜单名、路由名、共享模块名或显式路径线索，能与当前直接目标层目录、直接目标层入口文件、共享模块目录、共享模块入口或 route 直接精确对上。
   - 如果最强精确命中是文件级证据，返回前也必须先回落到所属目标目录作为 `root_path`。
   - `confidence: high`
   - 直接返回单个目标块，`requires confirmation: no`。
2. 非精确但只有一个现有候选
   - 输入名称与当前代码定义存在偏差，但直接目标层证据只收敛到唯一一个合理的现有候选，且没有其他同级近似模块竞争。
   - 只有当叶子名称差异仍足够接近，当前页面/模块仍可被合理视为用户目标时，才使用这一档。
   - `confidence: medium`
   - 返回这个现有候选目标块，并标注 `requires confirmation: yes`。
3. 不存在现有叶子目标，但可构造唯一 proposed target
   - 输入名称与当前代码定义存在偏差，且当前页面/模块不应被回填为 target。
   - 这也包括：用户通过自然语言表达了一个新菜单分支或新的父层级，当前请求叶子目标不存在，但 app / framework / 直接目标层已经足够清楚。
   - `confidence: low`
   - 如果父菜单、app、framework 和直接目标层已经足够明确，可以构造出唯一一个合理的 proposed path，则返回该 proposed `root_path` 的单目标块，`file_path` 为空，并标注 `requires confirmation: yes`。
4. 非精确且多候选
   - 输入名称与当前代码定义存在偏差，且当前同时存在多个 app、多个模块或多个直接目标层候选。
   - 每个候选块都使用 `confidence: low`
   - 返回多个候选目标块，并标注 `requires confirmation: yes`。
5. 无法收敛
   - 连候选层都收不拢，或 app / framework / 直接目标层仍不清楚，以至于连一个可靠的 proposed `root_path` 都无法构造。
   - 此时返回未解析结果，不要硬猜 `root_path`。

## 约束

- 这是一个窄范围改动圈定工作流。
- 只把 `Status` 和 `Summary` 作为固定头部。
- `Summary` 保持简短，不要扩展成完整推理过程。
- 不要把 `AGENTS.md` 当成应用映射、运行时模型、修改边界或依赖拓扑这类稳定仓库事实的来源；这些事实应以 `repo-profile.md` 为准。
- `root_path` 必须表示主改动落点目录，不能只给 route 模块目录。
- 当一个 route 指向页面组件时，`root_path` 应返回该页面组件所在目录；route 注册文件保留在 `file_path`。
- 当页面入口文件、共享模块入口文件、导出入口或消费入口才是最强命中时，`root_path` 也应返回其所属目标目录；命中的文件本身保留在 `file_path` 或 `evidence`。
- 当需求主落点位于 shared package、共享模块目录或其它非页面目录时，`root_path` 应返回对应的实际主改动目录，而不是强行回退到页面目录。
- 对已有模块/页面场景，只有当直接依赖线索表明 shared package / shared module 属于首轮联动面时，才把它纳入联动范围；也只有在证据表明其是真实主改动落点时，才能把 `root_path` 直接落到 shared package。
- 不要因为名字出现在请求里、只是名称相似，或被描述为参考/旧版/类似/现有行为，就把某模块当作 target。
- 如果请求中的显式路径线索不能精确对上，不要直接拍板；先按“判定优先级”继续判断是唯一候选、多候选还是未解析。
- 如果请求中的显式路径线索同时命中多个 app / package / 直接目标层目录，也不要强行选一个；要返回候选并标注 `requires confirmation`。
- 如果直接目标层索引或共享模块目录中已经出现同名直接目标层目录、典型子目录、关键入口文件或共享模块入口，优先基于这些直接目标层证据判定真实 `root_path`。
- 当输入名称与当前代码定义存在偏差时，先按以下顺序收敛候选范围：
  1. 直接目标层目录、关键入口文件、共享模块目录或共享模块入口同名 / 近名
  2. route / menu / moduleEntries / 导出入口 / 消费入口直接指向
  3. 所属 app / framework / 直接目标层已明确
  4. 父模块 / 父菜单命中
  5. API / store / permission / i18n 等辅助线索
- 如果名称有偏差，但直接目标层证据只收敛到唯一一个现有候选，且没有其他同级近似模块竞争，只有在叶子名称差异仍足够接近、当前页面/模块仍可被合理视为用户目标时，才可以返回单个候选目标块；`requires confirmation` 必须为 `yes`。
- 如果名称有偏差，且当前叶子页面/模块名与请求叶子名差异明显，不要因为父菜单、route 层级或功能语义收敛，就把现有页面/模块当作 target；此时应基于已确认的 app / framework / 父层级返回 proposed `root_path`，并保持 `file_path` 为空。
- 如果请求本身表达了新菜单分支、新的父层级，或其它明显的新增菜单路径信号，且请求叶子目标并不存在，不要仅因业务语义相近就把现有能力升级成多个候选 target；当 app / framework / 直接目标层已明确时，应优先返回唯一 proposed `root_path`。
- 如果名称有偏差，且同时存在多个 app、多个模块或多个直接目标层候选，不得直接拍板；必须返回多个候选目标块，并要求确认。
- 如果只能命中父模块、父菜单或业务语义近似线索，而没有直接目标层精确证据，不得把最相近名称直接当作最终目标。
- 如果叶子目标页不存在，或请求叶子名与现有所有叶子目标差异明显，但父菜单、应用或框架已经足够明确，可以给出 proposed `root_path`，此时 `file_path` 必须为空。
- proposed `root_path` 主要适用于“明确是 create / migrate / implement 新模块，且当前源码中还不存在叶子目标”的场景；同时也适用于“叶子名称差异明显、父层已收敛清楚，但不应把现有叶子页回填为 target”的场景。
- 对于通过菜单路径表达出来的新模块信号，即使用户没有显式说 `create`，语义相近的现有模块也只能作为 `evidence` 中的 reference-only 上下文，不能默认升级成 candidate target；除非用户明确表示新需求就要落在这些现有叶子模块之一。
- 对新增模块场景，先以 `repo-profile.md` 的约定为准；如果 `repo-profile.md` 没有说明，不要默认 proposed 到某个 framework 的直接目标层级；除非当前请求或源码证据已经明确 app / framework，否则保持未收敛。
- 只有当请求明确要求 shared package，或现有证据表明目标应设计为共享模块时，才允许 proposed 到 shared package。
- 只有在直接目标层索引、直接目标层入口目录、共享模块目录和显式路径线索都无法命中现有叶子目标时，才允许从父模块或父菜单推 proposed `root_path`。
- 当 `root_path` 不是现有精确命中，而是按当前直接目标层约定或共享模块约定推导时，需在 `evidence` 中明确说明其为 proposed 路径依据。
- 当 app / framework 已清楚时，proposed `root_path` 应按当前仓库的直接目标层约定构造，例如：
  - React 应用页面：检查 `apps/web/src/App.tsx` 与邻近页面文件；当前页面文件直接位于 `apps/web/src/`。
- 如果 app / framework 也不清楚，就保持 `root_path` 未解析，不要 invent proposed path。
- 不要因为父菜单、已有列表页、同级页面、邻近 route、API、store、hook 或组件在结构上相邻，就把这些文件回填进缺失叶子目标的 `file_path`。
- 当现有目标已经命中时，可纳入与该落点直接关联、且通常需要联动检查的 API、store、hook、permission、i18n、route、导出入口或消费入口文件；但不要把仅仅结构相邻、没有直接关联的文件一并回填。
- `file_path` 的目标是覆盖首轮检查范围，而不是列出该模块的所有潜在实现文件。它可以跨出 `root_path` 所在目录，但前提必须是直接联动而不是结构相邻；覆盖主落点入口和主要联动面后就应停止继续扩张。
- 不要把 reference-only、old module、similar module 当作 target；除非用户明确要求它就是本次修改目标。
- 当返回候选目标块时，在 `evidence` 中明确写出输入名称与当前代码定义的偏差点，以及当前为什么收敛到这些候选。
- 当本 workflow 已返回单一具体目标块时，可继续进入后续 target-aware workflow，例如 coding guidance。
- 当本 workflow 返回多个候选目标块或 `unresolved` 结果时，不要把它视为已可以进入任务级 validation choice。

## 推荐输出模板

模板只是推荐组织方式，不是强制 schema。如果只涉及一个目标且结论清晰，可以直接简短输出；如果涉及多个目标或明显歧义，按用户输入顺序输出多个目标块。每个目标块只对应一个 `root_path`。如果当前属于真正的未解析场景，且连 proposed path 都无法可靠构造，则不要强行输出目标块，而应使用未解析模板。

```text
Status
- resolved

Summary
- 当前请求已经收敛到一个具体目标块。
- 首轮文件范围仅覆盖与主落点直接联动的范围。

Target 1
- root_path: `...`
- file_path:
  - `...`
  - `...`
- evidence:
  - `...`
  - `...`
- confidence: high | medium | low
- requires confirmation: yes | no
```

真正未解析时，可改为：

```text
Status
- unresolved

Summary
- 当前请求还无法可靠收敛到一个主改动目标。

Unresolved
- reason: 当前 app / framework / 直接目标层仍不清楚，无法可靠构造 proposed `root_path`
- evidence:
  - `...`
  - `...`
- requires confirmation: yes
```

样例 1：resolved

```text
Status
- resolved

Summary
- 当前请求收敛到现有 React 页面所在目录。
- 首轮范围覆盖直接关联的路由与 API 文件。

Target 1
- root_path: `apps/web/src`
- file_path:
  - `apps/web/src/course-workflow-page.tsx`
  - `apps/web/src/App.tsx`
  - `apps/web/src/api.ts`
- evidence:
  - `apps/web/src/course-workflow-page.tsx`
  - `apps/web/src/App.tsx`
- confidence: high
- requires confirmation: no
```

样例 2：partial

```text
Status
- partial

Summary
- 请求可能指向多个页面文件，需确认目标。

Target 1
- root_path: `apps/web/src`
- file_path:
  - `apps/web/src/courses-page.tsx`
  - `apps/web/src/course-workflow-page.tsx`
- evidence:
  - `apps/web/src/pages.tsx`
- confidence: low
- requires confirmation: yes
```

当 shared package 被判断为主改动落点、但结论仍依赖消费侧入口或消费页证据收敛时，可使用 `confidence: medium` 且 `requires confirmation: yes`。

`file_path` 用于表达首轮检查范围，不固定只有 route / page；如果该需求通常需要联动检查 `api`、`permission`、`i18n`、`store`、`hook`、导出入口、消费入口或直接依赖的 shared module，且这些文件与主改动落点直接相关，可把对应文件纳入 `file_path`。这些文件可以跨出 `root_path` 所在目录，但必须保持“直接联动”而不是“结构相邻”；覆盖主落点入口和主要联动面后就应停止。
