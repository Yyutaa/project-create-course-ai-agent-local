# AGENTS.md

## 项目定位

本仓库是 AI Course Studio 的本地优先独立副本。当前代码具备 React/Vite、
FastAPI、SQLite 持久事实、LangGraph 七步控制流与本地 Worker 执行协议。
本副本不包含原项目的 `courses/`、`docs/` 和 `implementation-guide-20-lessons/`；
本文件、代码和测试是本副本的可用契约，不得依赖缺失目录才能启动。

## 目录职责

- `apps/web/`：React + TypeScript 前端。通过 REST API 读取事实并提交人工命令，
  不持有执行权。
- `apps/api/`：FastAPI 后端与独立本地 Worker。API 暴露健康检查、可选静态课程列表、
  持久七步 V0 事实及 Command 接口。
- `.course-agent/v0-facts.sqlite3`：V0 的 SQLite 事实库，不与旧 Demo 数据库混用。
- `.course-agent/workspaces/<course_id>/runs/<run_id>/`：Course 归属的版本课程文件。
- `courses/`：本副本不附带。若本地另行放入示例，`catalog.json` 才成为静态列表事实源；
  缺失时静态列表为空且不挂载示例页面，不影响 Run 与 Worker。
- `.agents/skills/`：版本化的领域与工程规则，必须整体保留。
- `assets/aiagent/`：存放当前项目的 PRD 和 FE-TD 和 BE-TD，根据任务类型按需读取。

## 分阶段约束

- 当前已进入本地 Worker/lease/checkpoint 阶段；仍不得加入云队列、分布式部署、
  自动发布或新的质量语义。
- 七阶段产品契约固定为：`intake`、`mission`、`blueprint`、`batch_plan`、
  `generation`、`quality`、`release`。
- 七阶段必须按上述顺序由受控 Workflow 推进；`research` 是 `blueprint` 的
  内部活动，不得提升为独立阶段。
- `release` 必须保留人工决策权；质量状态 `ready` 不等于发布，模型和代码
  不得自动或静默替代人工决定。
- 静态示例课程是可选观察材料，不参与生成流程。

## 产品与技术契约

- `teach-generator` 是课程生产规则来源，负责课程任务定义、规划、生成和质量
  闭环的领域规则。
- `humanizer-zh` 是 `quality` 阶段中的中文表达质量 Gate，只判断和修订语言
  表达；它不核验事实、不判断课程整体质量，也不决定发布。
- 前端技术选型为 React + TypeScript，用于展示七步状态、失败证据和人工
  release 决定。
- 后端技术选型为 FastAPI + Pydantic，用于定义和校验明确的请求、响应与错误
  Schema。
- 运行时采用受控 Workflow 固定阶段顺序、进入条件、停止条件和返工路径；
  模型输出不能直接修改阶段状态。
- 正常流程使用真实 LLM Provider，并通过统一 Provider 接口调用，以便替换和
  测试。Fake Provider 只作为验收和回归测试的确定性兜底，不进入正常流程。
- 后续设计和代码必须遵守本文件冻结的七步名称、顺序、Skill 边界、Provider
  边界和人工 release 控制权；如需变更，须同步更新本文件，不得静默偏离。

## 七步 Graph 运行约定

- LangGraph `StateGraph` 以显式 Node、Edge 和条件路由推进固定七步并记录
  `StageRecord`；`V0Runner` 负责节点执行适配与持久事实提交，不拥有隐藏顺序。
  前一步失败即停止，未执行阶段保持 `pending`；`research` 不成为第八步。
- 后端 Schema 名称固定为 `CourseInput`、`V0Run`、`StageRecord`、`MissionDraft`、
  `BlueprintDraft`、`BatchPlanDraft`、`LessonDraft`、`QualitySummary`、
  `ReleaseDecision`。前端类型与公开响应同步更新。
- Provider 统一接口接收阶段、上下文和目标 Pydantic Schema，返回经校验的候选结果。
  正常 API 只注入真实 LLM Provider；Fake Provider 只由验收和回归测试注入，缺失
  真实配置时不得自动回退 Fake。
- V0 真实配置使用 `COURSE_LLM_BASE_URL`、`COURSE_LLM_MODEL`、
  `COURSE_LLM_API_KEY`；为兼容仓库既有 `.env`，缺失时依次读取 `LLM_BASE_URL`、
  `LLM_MODEL`、`DEEPSEEK_API_KEY`。密钥只留在后端环境，不进入前端、响应或仓库。
- `quality=ready` 后 Graph 必须停在 `release=waiting_for_human`。人工选择
  `prepare` 只得到 `ready_for_release`，不实际发布；选择 `stop` 得到 `stopped`。
- 发布是 `prepare` 之后独立的显式人工动作：只有人工提交
  `POST /api/v0/runs/{run_id}/publish`，系统才把课程物化到
  `courses/published/<slug>/`（`course.json`、`lessons/*.md`、`index.html`）、把条目写入
  `courses/catalog.json`，Run 进入 `published` 并从「我的课程」草稿列表移出；不满足
  `ready_for_release` 或存在未生成章节时拒绝，且沿用 `Idempotency-Key` 幂等。
- V0 用 SQLite 保留 Course、Run、Intake、Artifact、Event、Snapshot 和执行协议事实；
  页面刷新、API 重启后凭 Run ID 重新读取，Worker 以有效 lease 接管未完成执行。

## 持久事实约定

- Course 是长期归属，Run 是单次执行，Intake 是不可变的原始输入；三者均由后端生成
  稳定 ID 和所有权，不从课程标题拼路径。当前新 Run 创建新 Course。
- Artifact 是 Run 的不可覆盖版本化产物，kind 固定为 `mission`、`blueprint`、
  `batch_plan`、`lesson`、`quality`。Event 是只追加的阶段和人工决定历史。
- Snapshot 是按 Course/Run/Intake、Event 和 Artifact 重建的读取投影，不是唯一事实源；
  事务中与事实同步更新，缺失时重建。读取响应与数据库行模型分离。
- SQLite 以 `PRAGMA user_version` 做可重复迁移；迁移 DDL 与版本更新同事务。
  V0 使用独立数据库，不迁移或改动旧 `.course-agent/agent.db` 和
  `.course-agent/checkpoints.db`。
- Workspace 只归属 Course，路径由后端 ID 派生并限制在
  `.course-agent/workspaces/`。Lesson Markdown 为版本文件副本；SQLite Artifact 内容仍为
  事实。文件与数据库不能跨介质原子提交，失败时回滚数据库并清理本次新文件。
- 创建 Run 和提交 release 决定要求 `Idempotency-Key`：同 key 同请求只受理一次；
  同 key 异请求返回 409。release 仍只由人工操作，`ready_for_release` 不执行发布。
- 前端使用 React Query 管理 Run 远端读取的加载、错误、失效与轮询；Course、Artifact、
  Snapshot 另有只读 API。Query 缓存不是事实源，Run ID 保留在 URL；运行中快速
  轮询、等待人工及可 RESUME 的停止态低频轮询，不可推进的终态停止。
- LangGraph 不使用内置 checkpointer；采用项目自己的 SQLite checkpoint 和 Worker。
  本阶段只实现局部 Finding/Repair/Verification 质量闭环，不声称完整课程量规。后续代码
  必须遵循本节对象语义；若变更须同步修订本文件，不可静默偏离。

## 五角色 Agent 契约

- 模型角色固定为 Mission、Blueprint、Writer、Reviewer、Repair。Mission 负责任务定义，
  Blueprint 负责蓝图，Writer 负责候选 Lesson，Reviewer 负责结构化质量证据，Repair
  只按明确 Finding 生成新的 Lesson 候选版本。
- 每个 Agent Definition 必须声明目标、输入 Artifact kind、输出 Artifact kind、输出
  Pydantic Schema、Skill 切片和 Tool 白名单。只加载当前角色需要的 Skill 规则摘要及
  来源章节，不复制完整 Skill。
- Humanizer 写作指导投影可进入新版 Writer；评分门槛和语言 Gate 仅由 Reviewer
  使用，Repair 只接收当前 Finding 对应规则。它不能核验事实、改变任务范围、
  更新 Run 状态或决定 release。旧 Run 维持原角色切片。
- Provider 统一使用结构化 `AgentRequest → AgentResponse`：请求携带角色、目标、短规则、
  精确输入 Artifact 与目标 JSON Schema；响应只携带角色和 JSON 对象。真实 Provider 与
  Fake Provider 使用同一接口，Fake 仍只用于测试。
- 角色之间通过精确 `ArtifactRef` 交接，引用包含 Run ID、Artifact ID、版本、kind 和内容
  hash。新 Artifact 记录 `producer_role` 与 `source_refs`；旧记录不得伪造来源。
- Artifact Tool 只能执行 Definition 授权的精确读和候选写。角色、Tool、kind、Run 归属、
  版本、hash、输入完整性和输出 Schema 必须在持久化副作用前检查；越权调用不得写入
  Artifact、Event 或 Snapshot。
- Agent、Provider 和 Tool 都不能直接更新阶段或 Run 状态。Graph Node 独占前六步状态
  写入，Edge 只做纯路由，release 继续由人独占。Repair 只能在 quality 的明确 Finding、
  双预算和独立 Verification 约束下触发。
- Mission、Blueprint、Lesson、Review 模型输出禁止额外字段。解析失败必须以角色、字段
  路径和错误类型写入当前阶段失败原因，但不得回显密钥、完整 Prompt 或原始敏感输出。
- Artifact 的生产角色和来源引用属于事实，Snapshot 仍只是可重建读取投影。
  当前 schema 版本以“课程生成约束”节为准。

## LangGraph 控制流契约

- 用户可见 Node 名固定为 `intake`、`mission`、`blueprint`、`batch_plan`、
  `generation`、`quality`、`release`；内部 Node 为 `repair`、`verification`、
  安全失败汇聚点 `route_error`。
- Graph State 只保存 `run_id`、`current_node`、`artifact_refs`、`batch_cursor`、
  `quality_cursor`、`active_finding_id`、`approval_status`、`loop_counts`、`last_outcome`
  和 `exit_reason`。正文、Prompt、
  Provider 原始响应和 Context Pack 不得复制进 State。
- 每个条件 Edge 必须穷尽 `succeeded`、`failed`、`waiting_for_human`、`stopped`、
  `unknown`；未知节点、未知结果和不可能状态必须进入 `route_error`，不得默认继续。
- Context Pack 按角色裁剪：Mission 仅 Intake；Blueprint 仅 Mission 与已批准来源摘要；
  Writer 仅当前章节 brief、紧邻前章摘要和必要 continuity ledger；Reviewer 仅当前
  brief、候选内容与最小质量规则。预算分别为 4,000、8,000、12,000、24,000
  Unicode 字符；Repair 只接收定位片段、规则和目标，预算 4,000 字符。
- `lesson_id` 由规范化章节语义的 SHA-256 前 16 位生成；`batch_id` 由有序
  `lesson_id` 列表的 SHA-256 前 16 位生成。索引不是身份，相同逻辑内容必须得到相同
  ID。每批完整结束后才追加 continuity ledger 并推进 `batch_cursor`。
- 批次循环上限固定为 20；Repair 每个 Finding 最多 2 次、每个 Run 最多 3 次。超限必须停在
  `waiting_for_human` 并给出稳定原因码，不能继续执行或自动发布。
- SQLite Event、Artifact 和 Snapshot 仍是持久事实；Graph 使用独立执行协议 checkpoint，
  进程重启后可由 Worker 接管。

## 分层质量闭环契约

- `quality` 内按 deterministic → rubric/reviewer → humanizer-zh 顺序运行；前一层未通过
  不运行后一层。确定性层检查可重复的 Markdown 结构与适用的构建问题；Reviewer 只评估
  最小教学目标、解释和练习；Humanizer 只评估中文表达，绝不替代事实、教学、构建或
  release 判断。未配置构建目标时不得声称完成构建检查。
- 每次 Gate 产生绑定精确 `ArtifactRef` 的结构化结果。Finding 包含稳定 ID、Run、Gate、
  规则、Lesson Artifact 版本与 hash、lesson_id、行区间、片段 hash、类别、严重度、
  证据和预期结果。Humanizer 只能生成 `language` Finding；事实或无法定位的问题交人工。
- RepairTask 只包含 Finding ID、原 Artifact 引用、单行问题片段与 hash、规则及目标；
  不传整章或历史。只允许精确单行替换，片段不匹配或越界时停止。Repair 产生新版
  Lesson Candidate；`candidate.created` 不改变有效 Lesson，独立 Verification 全部通过后
  才记录 `candidate.accepted` 并切换投影，失败记录 `candidate.rejected`，旧版始终可读。
  若 Verification 已明确失败，只有绑定精确 Candidate、Quality Artifact 与 checkpoint
  的 `QUALITY_REVIEW accept` 才能以 `candidate.human_accepted` 切换投影；该事件是人工
  风险覆盖，不得表述为独立验证通过。
- Verification 由确定性检查器和 Reviewer/Humanizer 重新读取 Candidate，不能采信
  Repair 的自述。每个 Candidate 从 deterministic 起重跑三层；验证记录和 Finding、
  RepairTask 留在不可覆盖的 Quality Artifact/Event 链中。
- 每个 Finding 最多 2 次 Repair，每个 Run 最多 3 次；达到任一上限、事实来源不足、
  缺定位证据、未知 Gate 状态或修复无法局部化时停在 `quality=waiting_for_human`。
  `release` 保持人工决定，质量 ready 绝不自动发布。
- 本节覆盖此前“Repair 未触发”与 Graph State 八字段的阶段性约定。

## 本地 Worker 执行协议契约

- `START`、`STOP`、`RESUME`、`REVISE`、`QUALITY_REVIEW` 是关联 Run 的持久 Command；状态为
  `ACCEPTED → CLAIMED → APPLIED/FAILED/REJECTED`。同 Run 的 Idempotency-Key
  与规范化 payload 绑定，同 key 异请求冲突。创建 Run 与 START Command 同一事务。
- API 的 Run 启动和控制 POST 只返回 202 accepted，不执行 Graph；Worker 独立于 API 和
  浏览器进程。前端只读执行工作台的状态事实，按钮只提交 Command，不持有 lease。
- 单机 SQLite `BEGIN IMMEDIATE` 原子领取 Command、获得每 Run 的 lease。lease 包含
  `owner`、单调递增 `epoch` 和过期时间；TTL 60 秒，活跃 Worker 每 15 秒 heartbeat。
  任何 Artifact/Event/Snapshot、checkpoint 和 Command 结果提交必须验证 owner、epoch
  与未过期时间；失权 Worker 即使模型返回也不得提交。
- 每个 Graph Node 记录 `NodeExecution` 的 `STARTED`、`COMMITTED` 或 `FAILED`。
  副作用前写 `before_node` checkpoint；Artifact/Event 与 `after_artifact` 同事务；
  节点结束写 `after_node`。Graph State/checkpoint 仅存 ArtifactRef 和游标，不复制正文。
  接管时从最后合法 checkpoint 恢复，已提交 Artifact 必须按引用/hash 复用，不再生成
  同一版本；质量链按已提交 Event/Candidate 决定恢复，接管后复核若得出相反结果必须
  升级人工，不能静默翻转。恢复中的 `before_node` 保留上次提交的 Event ID；
  未提交的派生 workspace 文件可以从 SQLite 事实修复。
- 新 Run 的 NodeExecution 记录规范化 `input_hash`。相同输入且已有成功结果时直接
  复用并写 `node.reused` 事件，不新建 NodeExecution；活着的同输入执行返回 `busy`；
  旧 Run 和 `input_hash=NULL` 的历史行不参与复用。失败按 `transient` /
  `deterministic` / `business` / `unknown` 分类，仅 transient 自动重试；同一
  input_hash 累计 3 次 FAILED 后转人工。只有显式 `QUALITY_REVIEW retry` 可以对
  当前节点绕过该拒绝。SQLite schema 为 15。
- STOP 受理即持久设置停止请求；若节点已开始，可完成当前有效提交，但下一节点的
  `STARTED` 必须被阻止。不得用强杀代替协作停止。RESUME 仅从合法停止/人工等待
  checkpoint 继续，不代表业务失败阶段自动重试。REVISE 持久保存有长度上限的人工
  输入并校验期望 checkpoint；release 决定仍由独立人工接口提交。
- `QUALITY_REVIEW` 仅作用于 `quality=waiting_for_human` 且当前内部节点为 `quality` 或
  `verification` 的精确 checkpoint。`retry` 重新检查同一 Lesson 或 Candidate Artifact；
  `accept` 必须携带人工说明，绑定当前 Lesson/Candidate 与 Quality Artifact 的精确版本
  和 hash。`quality` 等待态记录 `quality.risk_accepted`；`verification` 等待态还须记录
  `candidate.human_accepted`，明确区分于独立验证通过的 `candidate.accepted`。决定提交后
  生成新的 Quality Artifact，并继续下一章或进入人工 release。它不等同于模型 Gate
  通过，也不得自动发布。通用 `REVISE` 文本不能替代该决定。
- 唯一的技术失败恢复例外是 `quality=failed`、当前节点为 `quality`、最新
  `after_node` checkpoint 为失败、该节点 Reviewer 调用已成功返回但结构化结果校验失败。
  此时仅展示并受理精确 checkpoint 与当前 Lesson 引用的 `QUALITY_REVIEW retry`，
  不要求尚未产生的当前 Quality Artifact，也不允许 `accept`；历史仅有泛化错误文本的
  Run 还须由同节点成功的 Reviewer 调用事实佐证。重检是显式人工命令，保留此前
  Quality Artifact、风险接受 Event 与返工预算，不扩展为一般业务失败自动重试。
- 读取模型组合 Command、当前 NodeExecution、最后 checkpoint、停止请求和等待人工原因；
  Snapshot 与前端缓存都不持有执行权。正常模型调用可能在崩溃后重复，保证的是
  已提交事实的幂等与旧租约围栏，不声称 Provider 调用 exactly-once。
- 启动端口固定为 API 8002、Vite 5176；Worker 无 HTTP 端口。冻结契约与限制见
  本节约定。

### 执行协议检查项与待办（2026-10-25）

| 检查项 | 状态 | 说明 |
|---|---|---|
| Command | 部分通过 | 大部分写操作是持久化 Command；release/publish 仍由 API 同步执行 |
| 输入哈希 | 已实现 | 仅 NodeExecution 级 input_hash + 分类重试，见 `docs/superpowers/specs/2026-10-25-node-execution-input-hash-design.md` |
| 租约/心跳 | 通过 | 实现完整；心跳续租缺少直接测试 |
| thread_id | 未按字面实现 | 全仓库无 `thread_id`，用 SQLite `checkpoints(run_id, node_execution_id)` 替代 |
| 恢复 | 通过 | 从最近 checkpoint 继续，已完成节点不重跑 |

待执行 TODO：

- [ ] 决定 release / publish 是否命令化；当前仍由 API 同步执行
- [ ] 补心跳续租测试：断言 Worker 每 15 秒延长 Run lease 与 Command `claimed_until`
- [ ] 决定 `thread_id`：保持 `run_id` 作为 checkpoint 隔离键，或接入 LangGraph checkpointer
- [ ] 补 Graph 层 `TokenPreflightError → waiting_for_human` 的原因码测试
- [ ] 补 tokenizer 缺失/损坏时 fail-closed 的 Provider 调用计数测试
- [ ] 评估 Provider 单次调用结果缓存（input_hash 的更细粒度复用）
- [ ] 明确不支持 Lesson 行/段/Token 级断点续传，仅支持节点与 Artifact 级恢复

## 交付证据与风险迁移契约

- 一次 Run 的 `trace_id` 固定等于其 `run_id`。Command、NodeExecution、Artifact、
  Finding、Verification 和人工决定必须能沿 Run ID 与稳定对象 ID、精确 Artifact
  版本追溯；NodeExecution 记录所属 Command ID。证据索引是可重建的读取投影，
  不复制正文，不取代 SQLite Artifact/Event 事实。交付证据能力引入时的 SQLite
  schema 版本为 4；现行版本以后续约束为准。
- Provider 调用先持久预留，按实际尝试计数；崩溃后结果未知仍占预算。每 Run 默认
  48 次预警、60 次硬上限；到线写 `budget.warning` / `budget.exhausted` Event，
  后者阻止下一次模型调用并使 Graph 等待人工。REVISE 仅在耗尽等待态、匹配最新
  checkpoint 时可明确批准追加 20 次，随后仍需单独 RESUME。不得用普通 RESUME
  绕过上限。Provider 未返回 token 用量时记录 `unknown`，不臆测成本。
- 质量返工仍按每 Finding 2 次、每 Run 3 次限制；耗尽写
  `budget.repair_exhausted` Event 并等待人工。返工用量由 Candidate 提交事件及
  checkpoint 推导，不从前端缓存决定。
- Intake 原文、人工修订原文、密钥、Authorization、完整 Prompt、模型原始响应和
  Skill 内部规则不得进入 Trace、证据摘要或普通日志。证据只显示对象 ID、规则 ID 摘要、
  ArtifactRef、版本、位置 hash、状态、计数及时间；异常详情使用安全白名单或泛化
  错误。原 Artifact 内容仍留在受信本地事实库，现有原文 API 属于本地作者查看面，
  不应被误认为具备公网鉴权或多租户隔离。
- 交付证据包从 `/api/v0/runs/{run_id}/evidence` 读取，包含关联对象与 normal、
  recovery、human 三条路径的可观测事实索引；`not_observed` 不得写成已通过。
  自动测试、手工验收和未验证分别标记，一次成功演示不代表生产保证。
- 仅当并发积压、存储故障、恢复目标或权限隔离等风险有可复现观测证据，才评估
  队列、对象存储、更强运行时或鉴权隔离。不得把先进架构当作默认升级。
- 本阶段不自动发布、不扩展云组件；仅新 Run 允许本文件约束的 Blueprint 有限再规划
  和 Mission/Blueprint Provider 临时故障窄范围重试，不引入通用业务失败节点重试。
  完整证据与已知限制见本节约定。

## Mission 人工确认门禁

- 本功能上线后创建的 Run 固定 `mission_review_required=1`；该门禁引入时的 SQLite
  schema 版本为 5。
  迁移前 Run 默认 0，继续按旧流程执行，不能对其追溯插入 Mission 门禁。
- 每个新 Run 的每一版 Mission Artifact 提交后，`mission` 与 Run 必须停在
  `waiting_for_human`；未经人工确认的当前精确版本不得进入 Blueprint。
  Graph 路由与 Blueprint 入口均验证决定事实；普通 RESUME 不等于批准。
- 人工仅通过带 `Idempotency-Key` 的 `MISSION_REVIEW` Command 提交 `approve` 或
  `revise`。命令携带 Run、Mission Artifact ID/版本/hash 与最新 checkpoint；HTTP
  返回 202 accepted，Worker 持有效 lease 原子提交决定、Event、Run 和 Snapshot。
  同一版本至多一条决定，同一 Command 接管重放不得重复提交。
- `approve` 使当前 Mission 成功并继续 Blueprint；`revise` 必须有 1–2000 字意见，
  使用原 Intake、上一版 Mission 精确引用与意见构建有界 Context Pack，产出新版本
  后再次等待确认。旧 Mission 不覆盖，新版 `source_refs` 指向前版。
- 审批意见只保存在受控 SQLite 业务事实中，不进入 Graph State、Trace、日志、
  普通执行读模型或浏览器幂等键缓存；证据包仅输出决定动作和事件 ID。
  STOP 在受理后阻止下一节点；崩溃接管复用已提交 Artifact。release 仍独立由人决定，
  本门禁不增加自动发布或业务失败重试能力，遵循本节契约。

## 本地 DeepSeek 配置存储

- 本地配置存储引入时的 SQLite schema 版本为 7；从 v6 可重复迁移，单行元数据仅保存固定 provider、
  模型、修复状态和非敏感操作 token。Key 只存在当前 OS 用户的凭据库。
- 默认凭据库后端只接受 macOS Keychain 或 Windows Credential Locker；其他后端
  一律视为不可用，不得回退到可能的明文后端。
- 写入前持久设置修复状态和随机操作 token；持有 SQLite 写锁时先核对 token，
  过期操作不得触碰凭据库。Keyring 读写、元数据提交和失败恢复在同一锁内；
  读取模型与 Key 也须取得同一锁，避免混合版本。
- 任一侧失败不得返回成功或误报已配置。清除时无凭据条目不调用删除。
- 当前正常 API/Worker 路径固定使用 `https://api.deepseek.com` 和
  `deepseek-flash` / `deepseek-v4-pro`；旧 `COURSE_LLM_*` 仅保留直接构造兼容能力，
  不作为清除配置后的隐藏兜底。本节覆盖早期 V0 的环境变量配置约定。
- `GET/PUT/DELETE /api/v0/llm-config` 只提供单个本机配置。GET/写入响应不得回传 Key；
  配置字段校验错误也须删去 Pydantic 的原始 `input`。前端 Key 输入仅在弹窗内存中，
  每次打开为空，不进浏览器持久存储。Fake Provider 仍只用于测试。
- 正常新 Run 在创建 Course/Run/Command 前检查完整配置；缺失或凭据库不可读时拒绝。
  Worker 每次模型调用前重新读取当前配置，不需重启；正在进行的调用不被中断，
  同一 Run 可能跨 Key/模型。Provider 失败沿既有安全错误链记录，不自动切换 Fake。
- 配置及所有 `/api/v0` 写请求必须验证精确本机 Host 与页面 Origin，拒绝跨站、
  `Origin: null` 和无来源写入；配置 PUT 只接受 JSON。CORS 不是写入授权。
  API 固定监听 `127.0.0.1:8002`，Vite 固定 5176，Worker 与 API 由同一 OS 用户启动。
- macOS 用 `scripts/start-agent.sh`，Windows 用 `scripts/start-agent.ps1`；不提供安装包、
  云端密钥管理、多用户服务或自动发布。真实系统凭据库和 DeepSeek 调用须单独手工验收。

## 课程生成约束

- 现行 SQLite schema 版本为 15，可从 v7 起重复迁移。`intakes` 持久保存
  `source_policy`、`expected_chapters`、`min_effective_chars`、`token_limit`，`runs` 保存
  `constraints_version`，`publications` 保存已发布课程。迁移前 Run 固定为版本 0，不追溯
  执行新约束；新 Run 固定为版本 1。
- 新 Run 默认期望 12 章、单章至少 12000 个有效字符，Token 默认不限制，来源政策固定
  `仅允许使用公开官方资料`。四项约束属于不可变 Intake，创建后无编辑入口；
  创建幂等哈希必须包含四项约束。
- 旧 Run 保留原来的四类来源政策与 `source_evidence_version=0`，不得追溯改写；
  新 Run 固定 `source_evidence_version=1`，仅开放公开官方一手资料。来源政策随 Intake
  进入 Mission、Blueprint、Writer 的 Context Pack；Blueprint 的 research 及 Writer
  可经 Worker 内受控 ToolRuntime 请求 DeepSeek Search/Fetch。搜索结果仅是候选，
  已准入页面的内容与身份凭据持久登记后才可用作课程证据。
- v13 迁移为既有 Run 设置 `planning_loop_version=0`，其 Blueprint 章数仍沿用 ±1
  容差并在超出时等待人工。新 Run 固定 `planning_loop_version=1`：期望 1–2 章
  必须严格相等，期望至少 3 章允许 ±1。首次超出范围在 Batch Plan 前记录绑定
  当前 Blueprint 的 `blueprint.replan_requested`，最多回到 Blueprint 再规划一次；
  新版 Artifact 同时引用获批 Mission 与前版 Blueprint，旧版不可覆盖。再次超出记录
  `blueprint.replan_exhausted` 并以 `blueprint_chapter_deviation` 等待人工。Graph State
  计数与 Event 交叉核对，接管时复用已提交事实；再规划 Context Pack 仅携带有界
  前版章节摘要，完整前版仍由精确 ArtifactRef 保留。新 Run 的偏差接受 `RESUME` 必须
  绑定当前 checkpoint 与 Blueprint ArtifactRef，写入幂等
  `blueprint.chapter_deviation_accepted`；旧 Run 的接受行为不变。
- 仅新 Run 的 Mission/Blueprint Provider 调用边界可对明确超时、HTTP 429 自动
  增加至多一次技术尝试，同一 NodeExecution 共用上限，每次真实调用都先预留预算；
  客户端内置重试为零。重试预留与 STOP 检查在同一事务中完成；两次仍失败以稳定原因
  等待人工。解析/Schema 错误、来源不足
  与教学方案不合格不属于临时故障；Worker 恢复不计为业务返工。不得在整个 Graph
  节点上套用 RetryPolicy，且不得绕过 lease、STOP、预算或 Mission 人工确认。
- 有效字符统计去除 Markdown 标记、HTML 标签和空白，保留代码内容。低于下限时产生绑定
  精确 Lesson ArtifactRef 的 `lesson.effective_chars.minimum` 阻断 Finding，并以
  `lesson_effective_chars_below_minimum` 等待人工；不得交给单行 Repair 自动扩写。
- Token 只累计 Provider 返回的 `input_tokens + output_tokens`；缺失用量记为 `unknown`，
  不估算。达到或超过阈值时允许当前 Graph 节点完成提交，在下一节点写入
  `NodeExecution.STARTED` 前追加一次 `budget.token_exhausted`，以
  `token_limit_reached` 不可恢复地停止 Run。普通 `RESUME` 和调用次数追加预算都不得绕过。
- Token 阈值不改变既有 48/60 次 Provider 调用预算、质量返工预算、七步顺序或人工
  release 权限。约束状态进入安全读取模型和证据索引，但不得复制 Intake、正文、Prompt、
  模型原始响应或密钥。

## 角色上下文契约 v14

- SQLite v14 给既有 Run 的 `context_contract_version` 默认 0，不追溯改写产物；
  新 Run 固定为 1。旧 Run 保留原 Context Pack 和字符预算。
- 新 Run 的 Writer、Reviewer、Repair 先以 Pydantic 校验本轮 Pack，拒绝空必需字段、
  越界章号、过量来源摘要和额外字段。角色规则从版本化 `SKILL_RULE_SETS` 投影，
  不在运行时解析完整 Skill 文档；Writer 不接收评分门槛，Reviewer 不写正文，
  Repair 只见当前 Finding 的规则与单行摘录。未知规则转人工，不推断修复方式。
- 新 Run 的 Writer 输出 `key_facts/next_goals`；完整批次结束后追加仅含这两类
  要点及 `lesson_id` 的 `continuity_ledger_v1`，不把全文放进台账。旧
  `continuity_ledger` 保持可读；Lesson 和 Quality 版本仍以 Artifact/Event 为事实。
- 新 Run 的真实 DeepSeek Provider 对最终发送消息和每轮来源工具消息使用固定 V4
  tokenizer 离线预估，含规则、JSON Schema、工具声明与结果，预留 20% 加 128 Token。
  不支持的模型、tokenizer 缺失或超预算时不发送，也不占用 Provider 调用次数；
  离线数字仅为 `preflight_estimate`，实际用量仍只取 API `usage`。旧 Run 不启用此
  Token 预检。Prompt、完整 Skill 和人工反馈原文不得进入 Graph State 或普通日志。

## 官方来源核验与受控 ToolRuntime

- ToolManifest 为不可变静态注册项，仅含 `id`、`callers`、`idempotent`；本期白名单
  只有 `course.source.search` 和 `course.source.fetch`，只允许 blueprint/generation
  调用。模型提出函数请求，Worker 校验参数、有效 lease、来源边界及预算后执行；
  Provider 不执行工具。每 Run 上限为 Search 20 次、Fetch 40 次，每次网络请求 20 秒、
  页面 64 KiB、模型工具循环 6 轮。构建、任意 Shell、工作区补丁不开放。
- URL 限 HTTPS 公开主机，不接受凭据、IP 字面量、私网、本地地址或跳转；Fetch
  仅按本 Run 候选 ID 调用。DeepSeek Fetch 不提供最终跳转 URL，故厂商返回正文不直接
  充当证据；已批准原站须通过固定公网 IP、TLS 主机名的禁跳转 GET 再取得证据正文。
  自动归属只接受可核对的维护方身份链及文档型路径；npm 注册信息与维护仓库
  文档主域一致时，可核验该主域下的文档子域，不能用相似域名或搜索标题代替锚点。
  搜索优先限定到锚定的官方主域；旧候选在重试时可由 Worker 重新核验。
  共享托管平台地址不能被人工当成产品官方文档站点批准。歧义由精确
  `SOURCE_REVIEW` Command 提供人工批准、排除或候选 URL，普通 RESUME 不替代批准。
  人工批准只解决来源归属，不代表页面内容或具体断言已核验。
- `tool_invocations`、`source_candidates`、`source_documents`、`source_claim_links`、
  `source_decisions` 为 v12 持久事实。工具请求先登记并计入预算，结果写入时再次核验
  owner/epoch；崩溃后允许重复外部只读调用，但已提交事实按参数复用。不把页面全文、
  Prompt 或密钥复制到 Graph State、普通日志、Snapshot 或证据索引。
- 新 Run 的 quality 在 deterministic 后、rubric 前做独立来源断言审核；旧 Run
  继续原三层。只有当前 Lesson 的来源 Gate 对已准入页面及支持片段通过，
  `QualitySummary` 才能移除对应“未核验事实来源”限制。事实证据不足、冲突、
  清单不完整或学生正文泄漏内部来源状态时等待人工，不能靠删提示词冒充通过。
  Humanizer 和构建检查都不能证明事实，未执行的构建不得标为通过。
- `GET /api/v0/runs/{run_id}/sources` 只读公开候选、文档版本/hash 和断言关联状态，
  不返回页面全文；复核读模型只将已尝试核验且适合人工判断的候选呈现为可操作项，
  其余检索记录默认收起。`SOURCE_REVIEW retry_search` 绑定当前 checkpoint，每 Run
  最多 2 次，仍受 Provider/工具预算约束；拒绝候选不自动重跑。批准须携精确候选、
  元数据 hash 与人工依据，排除和补充 URL 不强制填写长说明。证据不足时继续等待，
  不得靠界面隐藏候选放行。release 与 publish 仍独立由人决定；旧发布课程保持原样。

## Run 状态订阅

- SQLite v11 的 `run_change_seq` 是按 Run 单调递增的读取变化游标，相关事实与投影表的
  写入在同一事务中推进它；事务回滚不得发出变化。它不替代 Event、Artifact 或 Snapshot。
- `GET /api/v0/runs/{run_id}/stream` 只发送 Run ID 和变化序号。前端通过 SSE 通知
  失效 TanStack Query 缓存，再从 REST 读取权威事实；SSE 健康时停止常规轮询，
  连接失败或断开时恢复原有轮询。
- 七阶段 UI 仅改变显示名称与阅读方式，不改变固定阶段顺序、人工门禁或发布权。

## 代码规范

- 前端使用 React + TypeScript。API 契约变更必须同步更新前端类型和测试。
- 后端使用 FastAPI + Pydantic；路由按资源拆分，公开响应使用明确的返回类型或
  `response_model`。
- Python 使用 Python 3.12、Ruff，单行最大 92 字符。
- 使用 `apply_patch` 修改源码与文档；不要覆盖或回滚已有用户改动。
- 输入路径必须规范化并限制在允许的课程目录内；当前 API 不提供任意文件写入接口。
- 优先使用标准库和已有依赖。新依赖必须对应当前阶段的明确需求。
- 不提交 `.venv/`、`node_modules/`、`.course-agent/`、缓存、构建目录或 `.env`。

## Skill 适用范围

- FastAPI 代码遵循 `.agents/skills/fastapi/SKILL.md`。
- 课程生产、课程规划和质量审校遵循
  `.agents/skills/teach-generator/SKILL.md`。
- 中文学生可见正文遵循 `.agents/skills/humanizer-zh/SKILL.md`。

## 验证

涉及前端时运行：

```bash
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
```

涉及后端时运行：

```bash
apps/api/.venv/bin/python -m pytest apps/api/tests
```

变更启动或接口行为后，额外验证：

```bash
curl http://127.0.0.1:8002/api/health
curl http://127.0.0.1:8002/api/courses
```
