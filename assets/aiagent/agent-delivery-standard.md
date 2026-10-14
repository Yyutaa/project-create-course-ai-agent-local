# 课程生产 Agent 交付标准梳理（结构化分析）

> 分析对象：`/Users/yuta/Documents/project-create-course-ai-agent-local`（只读）
> 结论摘要：项目已落地 **七阶段课程生产闭环**，核心能力集中在 `apps/api/app/v0/`。任务描述中提到的 `agents/definitions.py`、`course_runtime.py`、`ModelTransport`、`AGENT.md` 均**不是本仓库的实际文件/命名**，它们来自设计文档 `assets/aiagent/BE-TD.md` 的**目标架构**。真实实现见下文映射表。

---

## 0. 关键命名校正（先对齐，避免后续判断错位）

| 任务描述里的名字 | 仓库实际 | 说明 |
| --- | --- | --- |
| `agents/definitions.py` | `apps/api/app/v0/agents.py` | `AGENT_DEFINITIONS` + `AgentExecutor` 都在此文件 |
| `course_runtime.py` | 无此文件；运行时拆为 `graph.py`（图/节点）+ `runner.py`（提交/加载）+ `worker.py`（进程/租约） | 目标设计叫 `agents/course_runtime.py`，实际被扁平化 |
| `ModelTransport` 协议 | `Provider` 协议（`provider.py:60`） | 只有一个方法 `invoke(request) -> AgentResponse` |
| 七个 Agent Definition | **五个** 角色：`mission / blueprint / writer / reviewer / repair`（`schemas.py:22`） | “7” 是**阶段**数（`STAGES`），不是角色数 |
| `AGENT.md` | `AGENTS.md`（24 KB 契约总纲） | 文件名为复数 |
| `tests/` | `apps/api/tests/`（20 个测试文件）+ `apps/web/tests/`（2 个） | — |

补充：目标架构（BE-TD.md，第 43–58 行）规划了 `agents/ /providers/ /courses/ /workflow/ /observability/` 等目录，实际实现**未采用该目录结构**，而是把领域内核收拢到单一 `app/v0/` 包。评估交付标准时应以实际代码为准，BE-TD 仅作领域契约参照。

---

## 第一步：项目交付物清单

### 1.1 可运行代码模块

**前端（1 个应用：`apps/web`）—— 8 个源文件**

| 文件 | 职责 |
| --- | --- |
| `src/main.tsx` | 入口，挂载 React + Router + QueryClient |
| `src/App.tsx` | 路由表：`/`（课程列表）、`/workflow`、`/new`、`/run/:id` |
| `src/components/layout.tsx` | 侧边导航 + 顶栏外壳 |
| `src/pages.tsx` | 4 个页面组件：`CoursesPage`、`WorkflowPage`、`CourseWorkflowPage`（新建+运行工作台）、`LlmConfigDialog` |
| `src/api.ts` | 全部 REST 契约类型 + `api.*` 客户端（含幂等 POST） |
| `src/run-view.ts` | 纯函数视图逻辑：进度、轮询、`canDecideRelease`、`canReviewMission`、`canReviewQuality` 等 |
| `src/idempotency.ts` | 浏览器 `sessionStorage` 幂等 Key 管理 |
| `src/styles.css` | 样式 |

前端测试：`tests/v0-run-view.test.mjs`（node:test）、`tests/run-polling.test.ts`。

**后端（1 个应用：`apps/api`）—— 约 22 个功能模块**

- 入口与目录：`app/main.py`（FastAPI + 来源守卫 + 静态挂载）、`app/catalog.py`（`courses/catalog.json` 只读）。
- API 路由（5 个）：`api/system_routes.py`（health）、`api/course_routes.py`（`/api/courses`）、`api/fact_routes.py`（`/api/v0/courses`）、`api/config_routes.py`（DeepSeek 配置）、`api/run_routes.py`（Run/Command/Artifact/Evidence，最重）。
- 领域内核 `app/v0/`（17 个模块）：
  - 编排：`graph.py`（LangGraph 图 + 节点 + 路由，1228 行，核心）、`runner.py`（提交/回放/加载）、`worker.py`（Command 轮询/租约/心跳）。
  - 执行协议：`execution.py`（Command 队列、lease、checkpoint、node_execution）。
  - 角色与上下文：`agents.py`（定义+执行器）、`artifact_tools.py`（权限校验读写）、`context.py`（角色化 Context Pack + 预算）。
  - 质量：`quality_loop.py`（确定性检查、Reviewer/ Humanizer Gate、Repair patch）。
  - 数据：`storage.py`（SQLite 事实库，884 行）、`schemas.py`（全部 Pydantic 契约）。
  - 其它：`provider.py`（Provider 协议 + Real/Fake）、`budget.py`（调用/Token 预算）、`batching.py`（稳定 ID + 批次）、`delivery.py`（交付证据投影）、`local_config.py`（系统凭据库）、`sensitive.py`（错误白名单）、`workspace.py`（课程文件写入）。

### 1.2 测试覆盖了哪些路径 / 哪些没覆盖

**已覆盖（20 个测试文件，约 160+ 用例）**

| 维度 | 覆盖内容 | 代表文件 |
| --- | --- | --- |
| 阶段全链 | 七步成功、质量 ready、release 等待人工、不自动发布 | `test_v0_runner.py`、`test_v0_api.py` |
| 持久事实 | 迁移、外键、事务回滚、重启重建、幂等、Snapshot | `test_v0_storage.py` |
| 执行协议 | 崩溃接管、lease 过期、STOP 竞争、token 上限、两 Worker 互斥 | `test_v0_execution_protocol.py`（最全，34 用例） |
| 质量闭环 | 三 Gate 顺序、Finding 定位、Repair patch、返工预算、人工风险接受 | `test_v0_quality_loop.py` |
| 控制流路由 | 各 router 穷举、批次 20 次上限、章节偏差、恢复分支 | `test_v0_graph.py` |
| 人工门禁 | Mission 审批/修订/停用、版本绑定、幂等 | `test_v0_mission_review.py` |
| 交付证据 | 三条路径（normal/recovery/human）索引、脱敏、预算投影 | `test_v0_delivery_evidence.py` |
| 角色/上下文 | 定义边界、Context Pack 预算与裁剪 | `test_v0_agents.py`、`test_v0_context.py` |
| Provider | 真实 Provider 结构化请求、Fake 行为 | `test_v0_provider.py` |
| 本地配置 | keyring 保存/清除/并发/修复态 | `test_v0_local_config.py` |
| 其它 | schemas 校验、batching 稳定性、artifact_tools 权限、本地写入守卫、可选示例目录 | 其余文件 |

**未覆盖 / 薄弱**

- 前端只有 `run-view.ts` / 轮询逻辑的纯函数测试；**页面组件（`pages.tsx`）无组件测试**，无端到端（Playwright/浏览器）测试。
- **无真实 LLM 端到端测试**（文档亦声明：真实模型冒烟依赖使用者本机配置，见 `docs/seven-stage-v0-technical-plan.md:91`）。
- `delivery.py` 的只读投影有测试，但 `main.py` 的 `local_write_guard`（来源守卫）仅在 `test_v0_local_api.py` 覆盖，**CORS 之外的 Host/Origin 组合未穷举**。
- `workspace.py` 的课程文件写入路径仅被 `test_v0_runner.py` 间接覆盖（文件事务回滚），**未直接测试多版本/并发写**。

### 1.3 架构说明需要包含什么

- **组件图（静态结构）**：`React 前端 → FastAPI API → SQLite 事实库（.course-agent/v0-facts.sqlite3）`；`API 只受理 Command（POST 返回 202）`；`独立 Worker 进程 → 拉取 Command → LangGraph 图 → AgentExecutor → Provider（DeepSeek/Fake）`；`图事件/Artifact → SQLite`；`课程 Markdown → .course-agent/workspaces/<course>/runs/<run>/lesson-vN.md`；`courses/catalog.json` 只读示例。参见 `README.md` 与 `BE-TD.md:15-28` 的 mermaid 图（注意目标与实际的差异）。
- **时序图（一次 Run 的动态流程）**：`POST /api/v0/runs`（校验 + 幂等）→ `create_run` 写 Course/Run/Intake/事件 → 入队 `START` Command → Worker `claim`+`acquire lease` → `route_start` → `intake`（同步）→ `mission`（模型）→ 视配置 `waiting_for_human`（Mission 审批）→ `blueprint` → `batch_plan` → `generation`（按批次循环）→ `quality`（三 Gate，可 `repair`+`verification`）→ `release`（`waiting_for_human`）→ 人工 `prepare/stop`。每一节点写 `stage.started/succeeded/failed` 事件 + Artifact + checkpoint。

### 1.4 运行说明需要覆盖什么

- 前置：Node.js 20+、Python 3.12（`README.md:19-22`）。
- 启动：macOS `bash scripts/start-agent.sh`；Windows `.\scripts\start-agent.ps1`（自动建 `.venv`、装依赖、分别起 Uvicorn/Worker/Vite）。
- 端口固定：前端 `5176`、API `8002`（占用即启动失败，见 `docs/teaching-scaffold-implementation.md:225`）；Worker 无 HTTP 端口。
- 配置：首次进「新建课程 → 配置 DeepSeek」填模型+Key（存系统凭据库，SQLite 只存非敏感状态）。
- 验证命令（`README.md:67-74`、`AGENTS.md` 验证节）：
  ```bash
  apps/api/.venv/bin/python -m pytest apps/api/tests
  npm --prefix apps/web run test:v0
  npm --prefix apps/web run typecheck
  npm --prefix apps/web run build
  ```
- 健康检查：`curl http://127.0.0.1:8002/api/health`、`/api/courses`。

---

## 第二步：纵向切片策略（最小闭环）

### 2.1 从「创建课程」到「拿到任务定义」经过的代码

```
NewCoursePage/CourseWorkflowPage.start()           apps/web/src/pages.tsx:422-430
  └ api.startRun(input, key)                        apps/web/src/api.ts:295
     └ POST /api/v0/runs                            apps/api/app/api/run_routes.py:102-122
        ├ start_run 校验: require_credentials       run_routes.py:108-115
        └ runner.create_once(... enqueue_start=True) runner.py:56-71
           └ store.create_run → 写 Course/Run/Intake/Event + 入队 START   storage.py
Worker.run_once → execution.claim → _apply           worker.py:227-262, 120-225
  └ runner.execute → build_graph().invoke            runner.py:262-289
     ├ route_start → "intake"                         graph.py:42-47
     │   └ _intake 同步标记成功（不调模型）           graph.py:241-252
     ├ route_after_intake → "mission"                 graph.py:50-51
     └ _mission                                       graph.py:254-316
        └ executor.invoke("mission", inputs=pack)     agents.py:136-188
           └ provider.invoke(request)                 provider.py (Real:78 / Fake:160)
        → 写出 mission Artifact（任务定义）           graph.py:292-316
```

**“任务定义”产物 = `MissionDraft{audience, learning_goal, scope, stop_conditions}`**（`schemas.py:96-102`），落库为 mission Artifact 与 `Run.mission`。

### 2.2 最小闭环涉及的组件

前端（React）+ API（FastAPI）+ Command/ExecutionStore（SQLite 队列）+ Worker（独立进程）+ LangGraph 图 + AgentExecutor + Provider（模型）+ FactStore（事实库）。**共 7 类。**

### 2.3 去掉 Blueprint 与 Chapter 生成，最小闭环还能跑吗？

**结论：能用 Fake/真实模型跑到 mission，但当前 Graph 不会在 mission 后停下——会继续硬编码前往 blueprint。**

- `graph.py:1218-1226` 把 `intake→mission→blueprint→batch_plan→generation→quality→repair→verification→release` 无条件串起来，**没有“截断到 mission”的路由**。
- 若要一个真正“到任务定义为止”的纵向切片，必须二选一：
  1. 新增一个终止路由（例如 mission 成功后 `END`）——属于改代码；
  2. 依赖失败自然中止：例如不给 Writer/后续角色提供有效输出。测试里正是用 `FakeProvider(fail_at="writer")` 制造“生成阶段失败、后续不推进”（`test_v0_runner.py:62`、`test_v0_runner.py:178`），以及未配置模型时 `mission` 报配置失败、后续保持 pending（`docs/seven-stage-v0-technical-plan.md:72`）。
- **注意**：`intake` 不调模型，是纯确定性节点，因此“输入 → intake 成功”本身不构成任务定义；任务定义必须经过 `mission` 的模型调用。

---

## 第三步：Agent Definition 接入验证

### 3.1 “七个 Definition 是否都有对应方法”

- 实际是 **5 个 Agent Definition**（`agents.py:38-128`）：`mission / blueprint / writer / reviewer / repair`。
- 对应执行方法分布在 **`graph.py` 的 `WorkflowNodes`**，而非 definitions 内部：
  | 角色 | 定义 | 执行入口 |
  | --- | --- | --- |
  | mission | `agents.py:39-55` | `WorkflowNodes._mission`（`graph.py:254`） |
  | blueprint | `agents.py:56-72` | `WorkflowNodes._blueprint`（`graph.py:318`） |
  | writer | `agents.py:73-89` | `WorkflowNodes._generation`（`graph.py:407`） |
  | reviewer | `agents.py:90-106` | **不经 executor**：`quality_loop.review_gate`（`quality_loop.py:166-283`） |
  | repair | `agents.py:107-127` | `WorkflowNodes._repair`（`graph.py:850`） |
- 因此结论：**5 个角色均有执行路径；不存在“声明了但完全没实现”的角色**。

### 3.2 input_schema / output_schema 是否与方法匹配

- 定义侧：`input_kinds`（tuple of ArtifactKind）+ `output_kind` + `output_model`（Pydantic 类）。
- 匹配校验发生在 **`AgentExecutor.invoke`**（`agents.py:145-160`）与 **`ArtifactTools`**（`artifact_tools.py:42-95`）：
  - 输入顺序/种类必须与 `input_kinds` 完全一致（mission 特例：只接受 intake，或引用自身 mission 做修订）。
  - 输出用 `definition.output_model.model_validate` 强校验（`agents.py:184`）。
  - `output_schema` 由 `output_model.model_json_schema()` 动态生成并传给 Provider（`agents.py:178`）。
- **发现的真实缺口（重要）**：`reviewer` 走的是 `quality_loop.review_gate`，它**直接调用 `runner.provider.invoke` 并自行校验**（`quality_loop.py:199-218`），**绕过了 `AgentExecutor` 的输入/输出一致性校验**。这带来两个后果：
  1. Reviewer 的 `input_kinds`（`mission, blueprint, lesson`）在 executor 层不被强制；
  2. Reviewer 的“角色越权”是**手工特判**（humanizer 只能 `language`、rubric 只能 `teaching/fact`，`quality_loop.py:222-225`），而非基于定义。
  → 这是“定义声明与实际调用不完全一致”的唯一点，可作为加固项。

### 3.3 是否存在声明了但未实现的方法

- `AgentExecutor.invoke` 对 5 个 role 均在 `AGENT_DEFINITIONS[role]` 中可查（`agents.py:145`），无 KeyError 风险。
- 但 **`AgentExecutor.invoke` 的 writer/reviewer/repair 分支在正常图中并不都经由它**：writer/repair 经 executor；reviewer 被 `review_gate` 旁路。所以**不存在未实现的角色，但存在“实现路径不统一”**。

---

## 第四步：Fake Provider 可用性

### 4.1 FakeProvider 实现的是哪个协议 / 哪些方法

- 协议名是 **`Provider`**（`provider.py:60-61`），**不是 `ModelTransport`**，且**只有一个方法**：`invoke(request: AgentRequest) -> AgentResponse`。
- `FakeProvider`（`provider.py:156-200`）实现该方法：按 `request.role` 返回固定 fixtures（mission/blueprint/writer/reviewer/repair 五套），并支持 `fail_at` 指定角色固定抛 `ProviderError`。
- 另有 `RealProvider`（OpenAI 兼容 `/chat/completions`）、`LocalConfiguredProvider`（每次调用现解析本地配置）、`BudgetedProvider`（包装计费，`budget.py:205`）。

### 4.2 哪些测试用了 FakeProvider / 覆盖了什么

| 测试文件 | 用法 | 覆盖场景 |
| --- | --- | --- |
| `test_v0_provider.py` | 直接用 | Fake 结构化请求/响应、只在指定角色失败 |
| `test_v0_runner.py` | `FakeProvider()` / `fail_at="writer"` / 子类 | 七步成功、失败停链、重启重建、冲突校验 |
| `test_v0_api.py` | 注入 Worker/ runner | API 全链、幂等、脱敏、不自动发布、重启读同 Run |
| `test_v0_graph.py` | `MultiLessonProvider(FakeProvider)` | 两批次、连续性、章节偏差、质量逐章 |
| `test_v0_quality_loop.py` | `GateProvider/RepairingProvider/... (FakeProvider)` | Gate 顺序、Finding、Repair、预算耗尽 |
| `test_v0_agents.py` | `RecordingProvider(FakeProvider)` | 输入切片不被重复加载 |
| `test_v0_execution_protocol.py` | 通过 Worker(provider=...) | 崩溃接管、lease、STOP、token 上限 |

### 4.3 去掉真实 API Key，项目能否通过所有测试？

**能。** 依据：
- 所有后端测试均注入 `FakeProvider` 或其子类；真实 Provider 分支只在 `test_v0_provider.py` 中用 **monkeypatch 的本地 HTTP 替身**验证请求格式，不发真实网络。
- API 层需要凭据的 `start_run`（`run_routes.py:108-115`）在测试中走 Fake runner，`test_v0_local_api.py:134` 用 `LocalConfiguredProvider` 配合假配置。
- `README.md:40` 明确：`Fake Provider 只用于自动测试`；`AGENTS.md:48` 同：Fake 只作确定性兜底。
- 唯一依赖“真实配置”的是**手工端到端**，不属于自动化测试范围。

**注意点**：`FakeProvider` 返回的是**固定片段**，因此它无法验证真实模型的语义质量；测试证明的是**控制流、持久化与契约**，不是内容质量。

---

## 第五步：里程碑完成度评估

> 说明：仓库未显式定义 `M1/M2/M3`；按实现指引（`implementation-guide-20-lessons/README.md:42-51`）的阶段划分，对应为：M1=阶段01 七步 Happy Path、M2=阶段03+04 角色/Graph、M3=阶段05 质量闭环（并已延伸到阶段06/07）。

### M1 · 最小闭环 —— ✅ 已完成（含加固）

- 七阶段 `STAGES` 齐备且顺序被 `V0Run.validate_stages` 强约束（`schemas.py:348-352`）。
- `intake` 同步、`mission→blueprint→batch_plan→generation→quality→release` 全链可跑通；Fake 下 6 阶段 succeeded + release `waiting_for_human`（`test_v0_runner.py:37`、`test_v0_api.py:65`）。
- 持久事实（阶段02）也已完成：SQLite、Snapshot、重启重建。
- **缺口**：无“发布”终态（见 M3）；`intake` 无独立校验节点，直接信任 API 入参。

### M2 · 多角色 —— ✅ 基本完整，⚠️ 一处不统一

- Writer（`_generation`）、Reviewer（`review_gate`）、Repair（`_repair`）均实现。
- **Artifact 交接完整且强校验**：
  - 每个 Artifact 带 `producer_role` + `source_refs`，写入前 `ArtifactTools` 校验输入顺序/种类/哈希（`artifact_tools.py:64-95`）。
  - 版本链：`_source_refs` 取最新版本，`_write_role_success` 记录产物+来源（`runner.py:246-260,331-356`）。
  - Writer 逐章组装：mission+blueprint(brief)+batch_plan(ledger)（`context.py:115-177`）。
  - Repair candidate **不自动生效**，须经 `verification` 独立验收（`runner.py:169-204`、`graph.py:958-1070`）。
- **缺口**：Reviewer 旁路 `AgentExecutor`（见第三步 3.2），导致其输入契约不由定义强制；此外 mission 修订时 `AgentExecutor` 用 intake 类型承载 `revision_request`（`context.py:55-76`），语义上略绕。

### M3 · 质量闭环 —— ✅ 主体完成，⚠️ 有明确缺口

- **条件路由**：`route_after_quality`（`all_lessons_ready | more_lessons | repair_needed`）、`route_after_verification`、`route_after_repair` 全部实现且被测试穷举（`graph.py:78-103`、`test_v0_graph.py`）。
- **有限循环**：三处预算——批次 `batch_iterations<20`（`graph.py:417`）、整轮返工 `repair_attempts<3`（`graph.py:801`）、单 Finding `finding_attempts<2`（`graph.py:804`）；Provider 调用上限默认 60（`budget.py:14`）+ Token 上限（约束版本 1）。
- **人工 Gate**：Mission 审批（`route`+`MISSION_REVIEW`）、Quality 人工接受/重试（`QUALITY_REVIEW`）、Release `prepare/stop`（`run_routes.py:214-226`）。均幂等、有版本绑定、有脱敏证据。
- **缺口清单**：
  1. ~~**`release` 不是“发布”**~~ **（已补齐）**：新增独立显式 `publish` 动作——
     `runner.publish()` + `POST /api/v0/runs/{run_id}/publish`，把 Run 物化到
     `courses/published/<slug>/`（`course.json` + `lessons/*.md` + `index.html`），
     写入 `courses/catalog.json`，落库 `publications` 表（迁移 v9），Run 进入 `published`
     并从草稿列表移除。`prepare` 语义不变（仍只到 `ready_for_release`）。
  2. **Humanizer / 课程量规未走确定性脚本**：`review_gate` 用**模型**判 language/rubric，未接入 `teach-generator/scripts/validate-course.mjs` 的确定性硬检查，也不强制 SKILL 规定的 `45/50` 阈值。V0 也在 `V0_QUALITY_LIMITATIONS` 显式声明未执行完整量规（`runner.py:26-30`）。
  3. **无富样式 HTML 构建与产物体验检查**（阶段3 体验审校缺失）：发布生成的是目录页
     `index.html`（链接到 `lessons/*.md`），而非示例课程那种渲染后的章节 HTML；仓库内无
     Markdown→HTML 渲染器。
  4. **`delivery.py` 只是只读证据投影**，不构成发布产物；其 `paths` 仍只覆盖
     normal/recovery/human 三条路径的“观察”，未新增“已发布”路径。
  5. **无身份认证**：人工决定与发布均不校验操作者（`docs/seven-stage-v0-technical-plan.md`）。

### 里程碑完成度量化（建议口径）

| 里程碑 | 完成度 | 判定依据 |
| --- | --- | --- |
| M1 最小闭环 | ~95% | 七步+持久化全绿；仅缺 intake 校验节点 |
| M2 多角色 | ~90% | 五角色+Artifact 交接+独立验收齐备；Reviewer 路径不统一 |
| M3 质量闭环 | ~85% | 路由/循环/Gate 齐备；发布已补齐，确定性量规与富样式 HTML 构建仍缺 |

---

## 6. 交付物清单（可核查文件）

- 交付标准/证据文档：`NOTES.md`（**当前缺失，建议补**）、`AGENTS.md`（契约总纲）、`README.md`、`docs/*.md`（11 篇技术方案）、`assets/aiagent/{PRD,FE-TD,BE-TD}.md`。
- 架构说明：建议产出 `ARCHITECTURE.md`，含**组件图**（前端/API/Worker/DB/Provider/文件）+ **时序图**（一次 Run 的 Command→Graph→Artifact 流），并**明确标注目标架构（BE-TD）与实际实现（app/v0）的差异**。
- 运行说明：建议产出 `RUNBOOK.md`，覆盖前置版本、双平台启动、固定端口、DeepSeek 配置、验证命令、健康检查、常见启动失败（端口占用）。

---

## 7. 建议的下一步（Next step）

1. 若目标是**补全交付标准**：请确认是否要我在本 Design Files 中生成 `ARCHITECTURE.md`（组件图+时序图，Mermaid）与 `RUNBOOK.md`（启动/验证/排障）两份文档。
2. 若目标是**补齐功能缺口**：优先处理 `release` 真正发布（见 `course-publish-plan.md`）与 Reviewer 统一走 `AgentExecutor`。
3. 若目标是**核对里程碑验收**：请确认 M1/M2/M3 的官方定义（本仓库未显式命名），我据此逐条给出可执行验收脚本与证据清单。

> 本文件仅为分析结果，未修改任何工程代码。
