# AI Course Studio：前端技术设计

| 属性 | 内容 |
| --- | --- |
| 目录 | `apps/web/` |
| 技术栈 | React 19、TypeScript 5.9、Vite 7、React Router 7、TanStack Query 5 |
| 辅助库 | React Markdown、remark-gfm、Mermaid、`@xyflow/react`、Framer Motion、Lucide、语法高亮 |
| 定位 | 本地课程 Agent 的生产控制台，不是聊天 UI |
| 关联 | [PRD](PRD.md) · [后端与 Agent 设计](BE-TD.md) |

## 1. 设计目标与边界

前端将后端的课程、Run、Command、节点执行、Artifact、质量门和人工审批转化为可读、可操作的工作台。它不实现 LangGraph 路由、不自行判断课程是否发布，也不根据事件文案猜测当前阶段；这些都以 API 返回的当前事实为准。

核心原则：

- **请求快速返回**：创建、审批、继续和停止只提交 Command，收到 `202` 或成功 JSON 不表示长任务已经完成。
- **过程与产物分开**：Run 工作台展示过程（阶段、事件、Trace、Command），课程/章节页面展示产物（Workspace、Markdown、HTML、质量快照）。
- **新建与历史分开**：未完成的新课程优先回到原 Run；已有课程 Review 不把磁盘中的历史正文显示为当前模型输出。
- **后端是真实状态源**：本地组件状态仅保存表单、Tab、筛选与暂存编辑内容；课程和 Run 数据进入 Query Cache。
- **本地优先**：浏览器只连接本机 API，Provider 凭据由后端持久化到本地 `.course-agent/`，不会回传到前端读模型。

## 2. 工程结构

```text
apps/web/src/
├── App.tsx                         # 六条页面路由
├── main.tsx                        # React 根节点与全局样式入口
├── api.ts                          # API 类型、request 包装与资源方法
├── constants.ts                    # UI 常量
├── components/
│   ├── layout.tsx                  # 全局导航、Provider 状态
│   ├── common.tsx                  # Markdown、状态标签、共享小组件
│   └── workspace.tsx               # Workspace 文件树与编辑器
├── pages/
│   ├── course-pages.tsx            # Dashboard、创建、课程、章节页面
│   └── workflow-overview.tsx       # Workflow 只读说明
├── features/run/
│   ├── run-workspace.tsx           # Run 工作台组合入口
│   ├── run-polling.ts              # snapshot / SSE 刷新策略
│   ├── activity.tsx                # 事件轨迹
│   ├── artifacts.tsx               # 模型与工具产物
│   ├── execution-panel.tsx         # Command 与 NodeExecution
│   ├── batch-panels.tsx            # 批次与质量矩阵
│   ├── course-output.tsx           # 课程正文与质量概览
│   ├── observability-panels.tsx    # Token、预算与 Trace
│   └── visuals.tsx                 # Workflow/Agent 拓扑图
└── styles/                          # 基础、工作台、质量与响应式样式
```

`App.tsx` 只负责路由装配，具体页面和 Run 功能按领域拆分。新增页面优先进入 `pages/`；只服务 Run 的组件进入 `features/run/`，不要重新把业务逻辑堆回路由入口。

## 3. 路由与页面设计

| 路由 | 组件 | 数据读取 | 主要操作 |
| --- | --- | --- | --- |
| `/` | `Dashboard` | `GET /api/courses` | 打开课程、继续可恢复 Run、进入新建页 |
| `/new` | `NewCourse` | `GET /api/health` | 提交课程需求与 Provider/Model |
| `/courses/:slug` | `CourseWorkspace` | 课程详情、Workspace 列表 | Review、重生成、构建、校验、编辑 Workspace |
| `/courses/:slug/chapters/:key` | `ChapterWorkspace` | 章节正文 | 保存 Markdown、选择性重新构建 |
| `/runs/:runId` | `RunWorkspace` | Run、预算、Trace、事件流、Workflow | 审批、继续、停止、查看 Artifact 与质量 |
| `/workflow` | `WorkflowOverview` | `GET /api/workflow` | 阅读主图与 Review 图 |

### 3.1 Dashboard 与创建向导

Dashboard 读取课程列表，并根据 `resumable_run_id` 将未完成的新课程引导至 `/runs/:runId`。课程卡片显示标题、章节数、发布状态、质量信息及可继续入口。

创建向导提交 `POST /api/courses`，字段包括 `title`、`slug`、`audience`、`goals`、`scope`、`source_policy`、`delivery`、章节数、单章有效字符下限、Token 预算、Provider 和 Model。后端成功后返回 `{ course, run_id, command_id, duplicate }`；页面立即跳转 Run 工作台，并通过轮询显示从 `QUEUED` 到 `RUNNING` 的变化。

### 3.2 Course Workspace 与章节编辑

课程页负责“已有课程”视角：读取 Workspace 文件列表、课程章节和当前质量快照；可发起 `review_course` 或 `regenerate_course` Run，也可执行 `build`、`validate`。复杂的审批和修复过程始终跳转到 Run 工作台。

Workspace 与章节编辑都使用乐观并发控制：读取时获得 `content_hash`，保存时将其作为 `expected_hash` 传回。若后端发现文件已被其他操作改写，返回 `409`，UI 必须提示刷新并比较，而不是静默覆盖。章节保存可携带 `rebuild: true`，在写入 Markdown 后触发静态构建。

### 3.3 Run Workbench

Run 工作台围绕四个问题组织：

1. **现在在哪里**：`workflow_steps`、`current_step`、`active_command`、`current_node_execution` 显示阶段、当前节点、Worker 租约与尝试次数。
2. **系统做过什么**：`events` 显示 Agent、工具、路由、重试、审批与系统事件；`artifacts` 提供可读摘要和可展开原始输出。
3. **课程质量如何**：`course_quality_snapshot`、批次结果和 `repair_tasks` 分别呈现章节、批次、整课的门禁与证据。
4. **用户可以做什么**：仅当 `interrupt_payload` 或 Run 状态允许时展示批准、要求修改、重新生成总结、继续失败 Run 或停止按钮。

工作台不把 Artifact 当作当前状态。Artifact 是历史证据；Run snapshot、质量快照和 Command projection 才是当前操作依据。

## 4. 前端数据模型与全局状态

所有 API 类型集中在 `api.ts`。主要读模型如下：

| 类型 | 关键字段 | 使用位置 |
| --- | --- | --- |
| `Course` | `slug`、`lessons`、`course_quality_snapshot`、`resumable_run_id` | Dashboard、课程页 |
| `Chapter` | `content`、`content_hash`、`snapshot_path` | 章节编辑器 |
| `RunDetail` | `status`、`current_step`、`interrupt_payload`、`events`、`artifacts`、`repair_tasks` | Run 工作台 |
| `CommandExecution` | `kind`、`status`、租约、心跳、尝试次数 | 执行面板 |
| `NodeExecution` | `node_id`、`input_hash`、状态、错误 | 节点执行时间线 |
| `CourseQualitySnapshot` | 各章字符数、Humanizer、语义结论、构建/校验结果 | 质量矩阵、课程文章 |
| `BudgetSnapshot` / `TraceProjection` | Token、限制、Span、耗时、错误 | 可观测性面板 |
| `WorkflowSnapshot` | 主图/Review 图的节点、边、Agent、Tool | Workflow 页面与可视化 |

TanStack Query 的 query key 按资源粒度组织，例如 `courses`、`course/:slug`、`run/:id`、`budget/:id`、`trace/:id`。写操作成功后应失效课程或 Run 的相关 key，而不是手工伪造最终状态。局部 UI 状态使用 React state：创建表单、当前 Tab、展开的 Artifact、编辑器草稿和质量筛选。

## 5. API 交互契约

`request<T>()` 统一设置 JSON 头、解析响应，并将 FastAPI 的 `detail` 转为 Error。组件不得直接散落 `fetch`。

| 资源 | 方法 | 用途 | 关键返回 |
| --- | --- | --- | --- |
| `/api/health` | GET | Provider、模型与本地运行状态 | `provider_configured`、Gateway 可用性 |
| `/api/settings/provider` | PUT | 保存本地 Provider 偏好 | provider/model，不回传密钥 |
| `/api/workflow` | GET | 获取可执行图投影 | 拓扑、Agent、Tool manifest |
| `/api/courses` | GET/POST | 列表与创建课程 | Course 或 `run_id`/`command_id` |
| `/api/courses/:slug` | GET | 课程详情和历史 Run | Course + runs |
| `/workspace/*` | GET/PUT/POST | 文件、资源、来源备注 | 文件 hash、保存结果 |
| `/chapters/:key` | GET/PUT | 读取/写入 Markdown | Chapter、可选 build 结果 |
| `/tools/:action` | POST | `build` 或 `validate` | command、stdout/stderr、exit code |
| `/courses/:slug/runs` | POST | 创建 Review/重生成 Run | `run_id`、`command_id` |
| `/api/runs/:id` | GET | Run 主 snapshot | RunDetail |
| `/resolve`、`/continue`、`/stop` | POST | 人工审批、恢复、停止 | 已排队的 Command |
| `/budget`、`/trace` | GET | 可观测性投影 | 用量与 Span |
| `/stream` | GET (SSE) | 增量事件与状态变化 | `run_event`、`snapshot` |

SSE 是体验增强，不是唯一正确性来源：断线、页面重新进入或事件遗漏时，以定期 `GET /api/runs/:id` 的 snapshot 校准。终态 `COMPLETED`、`FAILED`、`STOPPED` 后停止订阅与轮询。

## 6. 可视化、Markdown 与安全呈现

- 课程与 Workspace Markdown 使用 React Markdown + `remark-gfm` 渲染；对课程内图片路径统一转为 `/api/courses/:slug/assets/...`，避免浏览器访问仓库外路径。
- Mermaid 用于工作流和正文图示；执行拓扑来自 `/api/workflow`，前端只做布局与状态样式。
- 原始模型输出、事件 payload 与工具输出默认以可折叠 JSON/文本展示，避免把大对象塞进主视图。
- 不在前端渲染或缓存 DeepSeek API Key；Provider 设置提交后只展示“已配置”状态。

## 7. 前端验证与扩展原则

```bash
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
```

新增 Run 状态、API 字段或审批动作时：先更新 `api.ts` 类型与请求方法，再更新后端契约测试和页面。新增面板时优先复用 Run snapshot；不要通过解析中文事件消息决定业务状态，也不要实现客户端 Workflow 规则。
