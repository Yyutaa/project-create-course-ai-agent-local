---
name: repo-workflow-scan-structure
description: 识别前端仓库形态，并按框架差异扫描当前仓库结构。
---

# 仓库工作流：扫描结构

## 用途

先识别仓库形态，再按当前请求扫描真正相关的目录，并用接近 `tree` 的方式输出仓库结构，帮助后续定位页面入口、路由入口、API、i18n、store 和共享模块边界。

## 输入

接受自然语言请求，不要求额外拆分结构化输入字段。

常见输入场景包括：

- 扫描仓库结构
- 输出某个应用的结构树
- 梳理 `apps/` 和 `packages/` 的职责边界
- 查看某个页面或模块线索会命中哪些 app / 模块结构
- 梳理某个 app 下 `views/` 或 `pages/` 的模块层级
- 查找 route / moduleEntries / api / i18n / store 入口
- 比较 Vue、React、H5 各自所在目录和页面层结构

如果用户只给了页面名、模块名、app 名、目录片段或一句目标描述，也应先按自然语言理解，再映射到对应的结构扫描范围。

## 仓库结构说明

以下语义是扫描时的解释提示，不是死规则；必须结合附近文件、入口文件、路由注册、package 脚本和 import 关系确认：

- `apps/`
  - 一般表示可运行应用或 portal 根目录。
  - 一个 app 通常对应一个独立的业务入口、启动脚本、路由层和页面层。
- `packages/`
  - 一般表示共享模块、共享页面承载区、共享组件库、公共工具或跨应用复用逻辑。
  - 不要因为存在 `packages/` 就把整个仓库误判成纯组件库；如果同时有 `apps/`，优先按业务前端仓库理解。
- `apps/*/src` 或 `packages/*/src`
  - 一般表示该应用或共享包的主源码根目录。
  - 如果 `packages/*/src` 下继续存在业务模块目录，也应按共享模块层级展开，而不是只停留在包根目录。
- `src/views/`、`src/pages/`
  - 一般表示页面级或业务模块级目录。
  - 扫描时至少细化到其下一层模块目录；必要时继续看二级模块。
  - 当用户输入包含页面名、菜单名或模块内页面线索时，可继续展开到模块下的页面级目录或关键页面入口文件。
- `src/router/`、`src/routes/`、`src/moduleEntries/`
  - 一般表示路由注册、模块注册或 portal 暴露入口。
  - 对 portal 形态的 Vue app，`moduleEntries/` 可能是一级暴露边界，而不是次级注册细节。
- `src/api/`、`src/apis/`、`src/services/`、`src/request/`
  - 一般表示接口定义、请求封装或服务调用入口。
- `src/lang/`、`src/i18n/`
  - 一般表示多语言入口。
- `src/store/`、`src/stores/`、`src/models/`、`src/state/`
  - 一般表示状态管理入口。
- `src/components/`
  - 一般表示共享组件或模块内公共组件；要区分 app 内组件和跨 app 共享组件。
- `src/utils/`、`src/hooks/`、`src/types/`、`src/constants/`
  - 一般表示支撑代码，不默认视为页面入口。

## 结构参考例子

以下示例只用于解释本仓库目录语义：

```text
repo-root/
├── apps/
│   ├── web/
│   │   └── src/
│   │       ├── App.tsx                    # 路由注册
│   │       ├── courses-page.tsx           # 课程页面
│   │       ├── course-workflow-page.tsx   # Run 与创建页面
│   │       ├── api.ts                     # REST 客户端与类型
│   │       └── components/                # 应用内组件
│   └── api/
│       └── app/                           # FastAPI 与 Worker 代码
└── scripts/                               # 本地启动脚本
```

## 步骤

1. 先读取 `AGENTS.md`。
2. 读取 `repo-profile.md` 中与当前请求相关的仓库类型、应用映射、运行模型、边界和依赖拓扑章节。
3. 如果 `repo-profile.md` 缺失、信息明显不足，或与当前目录结构不一致，再做轻量补扫并明确哪些结论来自当前源码。
4. 先判断当前仓库属于哪一类：`business-monorepo`、`single-app`、`micro-frontend`、`h5` 或 `unknown`。
5. 按仓库类型决定扫描范围：
   - `business-monorepo`：优先看 `apps/**`、`packages/**`、各 app 的 `src` 根、路由根、页面根、共享包根。
   - `single-app`：优先看 `src/**`、页面根、路由根、配置根和内嵌框架子树。
   - `micro-frontend`：优先看 host app、remote app、loader、联邦配置和独立启动入口。
   - `h5`：优先看 H5 app 根、`pages`、`routes`、`core`、环境配置。
6. 结合实际目录和入口文件，识别各 app 或共享包下的：
   - 源码根目录
   - 页面根目录，如 `views` 或 `pages`
   - 路由/模块注册入口
   - API/i18n/store/components/utils 等关键入口
7. 如果存在 `views/` 或 `pages/`，继续细化到其下一层模块目录；必要时展示二级模块目录。
8. 当用户输入包含页面名、菜单名，或需要更细的页面层结构索引时，可继续展开模块下的页面级目录、典型子页面目录，或关键页面入口文件，例如 `index.vue`、`index.tsx`、`detail/`、`log/`、`create-edit/`。
9. 如果 `packages/*/src` 下存在共享模块、共享页面或业务子目录，也继续细化到其下一层模块目录；必要时展示二级模块目录。
10. 用接近 `tree` 的文本输出当前仓库结构，并固定附上精简的关键证据路径。
11. 如果当前请求需要最终归属或最终改动落点结论，只停留在目录索引与证据层，并明确说明本 workflow 不负责目标收敛。

## 默认输出

- 默认输出自然语言 + `tree` 风格结构，不输出原始命令结果堆砌。
- 始终先输出：
  - `Status`：`resolved` | `partial`
  - `Summary`：2 到 4 条简短 bullet，只回答当前请求最相关的结构结论
- 结构输出要优先覆盖：
  - 相关 app 根目录和共享包根目录
  - 每个相关 app 的 `src` 主入口
  - 每个相关 shared package 的 `src` 主入口
  - `views` / `pages` 下的模块层级
  - 模块下的页面级目录、典型子页面目录或关键页面入口文件
  - `packages/*/src` 下的共享模块或共享页面层级
  - route / moduleEntries / api / i18n / store 等关键入口
- 如果用户问“这个页面或模块线索在仓库里出现在哪里”，结果中要明确：
  - 哪些 app 或 shared package 结构包含这个线索
  - 匹配到的页面根目录在哪里
  - 对应模块在 `views` 或 `pages` 下的哪一层
  - 该模块下实际存在哪些页面级目录或关键页面入口文件
- 如果是混合框架仓库，要把 Vue、React、H5 分开说明，不要揉成一个平面目录列表。
- 当当前请求可以清楚收敛到一个仓库类型判断和一个结构范围时，使用 `Status: resolved`。
- 当当前请求同时命中多个 app/package 结构、repo kind 置信度不足，或部分结构结论依赖轻量补扫时，使用 `Status: partial`。
- 不要仅因为用户请求的是一个较窄的 app 级或模块级扫描范围，就使用 `partial`；如果该局部范围内的结构结论本身清晰，仍应使用 `resolved`。
- 输出里应包含：
  - `Repository kind`
  - `Matched structures`
  - `Structure tree`
  - `Key entry points`
  - `Key evidence`
- `关键证据` 固定输出，但控制在 1 到 3 条关键路径即可。
- `Matched structures` 用于先简短列出与当前请求直接命中的 app / package / module 结构，再展开 tree。
- 如果 `Matched structures` 只有一个显而易见的目标，就保持成一行短列表，不要展开成长段说明。
- `Matched structures` 只用于列命中的 app / package / module scope，不要在这里混入证据解释、置信度讨论或 ownership 结论。

## 推荐输出模板

默认按以下结构输出，必要时可省略空项，但不要改变整体顺序：

1. Status
   - `resolved` 或 `partial`
2. Summary
   - 仅保留 2 到 4 条简短 bullet
   - 不要复述完整 tree
   - 不要把 `Key evidence` 再重复写进来
3. Repository kind
   - 例如：`business-monorepo`
   - 如有混合框架，紧跟说明 Vue / React / H5 的分布
4. Matched structures
   - 先列出最直接命中的 app / package / module 结构
   - 保持简短，不要变成完整证据列表
   - 不要混入应属于 `Key evidence` 或补充说明的解释
5. Structure tree
   - 使用接近 `tree` 的层级化文本
   - 只展开与当前请求相关的 app / package
   - 至少展开到 `views/`、`pages/` 或 `packages/*/src` 下一级模块目录
   - 当请求涉及页面名时，可继续展开到模块下的页面级目录或关键页面入口文件
6. Key entry points
   - 列出与当前请求直接相关的 `router/routes`、`moduleEntries`、`api`、`i18n`、`store`、`components` 等入口
   - 控制在最直接相关的 2 到 5 条
   - 如条件允许，优先顺序固定为：page root、route entry、module entry、再到 API / store / i18n entry
7. Key evidence
   - 固定输出
   - 控制在 1 到 3 条关键路径即可，不展开成长列表
8. 必要时补充说明
   - 只有当用户实际在问最终归属或改动落点时才使用
   - 此时可明确说明本 workflow 只提供结构索引与证据，最终收敛属于后续的变更目标收敛步骤

样例 1：resolved

```text
Status
- resolved

Summary
- 仓库是 `single-app` 前端，另有本机 API。
- 当前请求映射到 `apps/web` 下的 React 结构。

Repository kind
- single-app
- React 前端与 FastAPI 配套服务

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

样例 2：partial

```text
Status
- partial

Summary
- 仓库类型可识别为 `single-app`。
- 页面线索对应多个 React 文件，因此只做结构索引。

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

## 约束

- 忽略 `skills/bootstrap/**`、`node_modules`、`dist`、`build`、`coverage`、`report`、构建产物和生成文件。
- 只把 `Status` 和 `Summary` 作为固定头部。
- `Summary` 保持简短，不要扩展成仓库讲解长段落。
- 不要让 `Summary`、`Matched structures`、`Structure tree`、`Key evidence` 重复表达同一层信息；每个块只承担自己的角色。
- 扫描范围要收敛到用户请求，但在输出结构时，允许为当前目标 app 补齐必要的上层目录语义。
- 不要把整个仓库所有目录完整倾倒出来；重点展示与请求相关的 app / package，以及其 `views` / `pages` / `packages/*/src` 模块层级。
- 页面层展开只用于补充结构理解和目录索引，不用于给候选排序，也不直接给出最终页面目标结论。
- 页面层展开可以到页面级目录和关键入口文件，但仍应停留在结构索引与证据层，不要收敛成最终归属或最终 `root_path`。
- 不要为了页面层展开而继续摊开 hooks、utils、const、types、普通 components 等非页面支撑文件。
- 不要仅输出扁平文件夹列表；需要解释目录语义，并整理成可读的 tree 风格结果。
- 不要把扫描结果写回 Repo Guide 文件。
- 不要在缺少证据时臆断某目录的业务归属；低置信度时应明确说明待确认。
- 最终归属收敛和改动落点判断不属于本 workflow。
- 不要输出 `root_path`、`file_path`、候选排序或最终 owner 结论；这些属于后续的改动目标收敛 workflow。
- 不要默认附带 target convergence 免责声明；只有当用户实际在问最终归属或最终改动范围时，才补这类说明。
- 如果页面名、模块名或目录片段同时命中多个 app / package，或 repo kind 无法确认，只输出命中的结构与证据，不要排序，也不要给出最终归属结论。
