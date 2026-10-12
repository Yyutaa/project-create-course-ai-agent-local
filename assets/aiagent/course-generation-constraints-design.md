# 课程生成约束前置设计

日期：2026-10-13

## 1. 背景与目标

当前新建课程只收集主题、目标受众、学习目标和语言。章节规模、单章内容下限与
Token 成本没有成为结构化 Intake 事实，模型只能从自然语言中自行推断。

本设计在创建 Run 时前置三项不可修改的生成约束：

- 期望章节数：规划参考，允许实际结果偏差一章；
- 单章有效字符数下限：质量硬门槛；
- Token 阈值：整次 Run 的终止阈值，可选择不限制。

约束必须贯穿前端、公开 Schema、SQLite Intake、角色 Context Pack、质量 Gate、
执行预算和读取模型。它们不得改变七阶段顺序、Agent 权限边界或人工 release 决策权。

## 2. 已确认的产品语义

新 Run 的默认值为：

- `expected_chapters = 12`；
- `min_effective_chars = 12000`；
- `token_limit = null`，表示不限制。

三项约束进入不可变 Intake，创建后没有编辑接口。章节数不是硬性平均分配目标；
Blueprint 实际章节数与期望值相差不超过一章时继续执行，超过一章时等待人工接受。

有效字符的统计口径为：去除 Markdown 标记、HTML 标签和空白后统计正文字符，
代码块内容保留计数。低于下限的 Lesson 不能通过 deterministic quality gate。

Token 使用量只采用 Provider 返回的真实 `input_tokens + output_tokens`。达到或超过阈值
时，当前 Graph 节点允许完成并提交；系统在下一节点开始前终止 Run。该终止不可恢复，
普通 `RESUME` 必须被拒绝。Provider 未返回用量时记录 `unknown`，不得推算缺失值。

## 3. 方案选择

采用直接扩展 Intake 并复用现有执行协议的方案：

```text
CourseInput
  → SQLite Intake
  → Mission / Blueprint / Writer Context Pack
  → Blueprint 偏差检查 / Quality 字符 Gate / Provider Token 账本
  → Event、Snapshot、执行读取模型
```

不采用以下方案：

- 单个 JSON 约束字段：数据库迁移仍不可避免，且字段校验、查询与兼容更模糊；
- 独立 Policy 表或规则引擎：当前只有三个创建后不可变字段，没有足够需求支撑新子系统。

## 4. 数据与接口契约

`CourseInput` 增加三个字段：

| 字段 | 类型 | 校验 | 默认值 | 含义 |
| --- | --- | --- | --- | --- |
| `expected_chapters` | `int` | `1..100` | `12` | Blueprint 规划参考 |
| `min_effective_chars` | `int` | `> 0` | `12000` | 每章质量硬门槛 |
| `token_limit` | `int \| null` | 非空时 `> 0` | `null` | Run 累计 Token 终止阈值 |

创建请求的幂等哈希包含三项约束。同一 `Idempotency-Key` 携带不同约束时返回 409。
公开 Run 响应可以显示这些非敏感数值；主题、受众和目标继续按现有规则隐藏。

SQLite schema 从 7 迁移到 8：

- `intakes` 增加 `expected_chapters`、`min_effective_chars`、`token_limit`；
- `runs` 增加内部 `constraints_version`；
- 迁移前 Run 的 `constraints_version` 为 0，不执行新约束；
- 新 Run 的 `constraints_version` 为 1，三个字段都进入持久事实；
- Snapshot 缺失或过期时，从 Run 与 Intake 事实重建完整读取模型。

版本标记避免历史 Run 在恢复时被新的默认值追溯约束，同时允许新请求省略字段并使用默认值。

## 5. 角色上下文与控制流

### 5.1 Mission

Mission 继续接收完整 Intake。约束作为精确输入存在，模型无权修改。Mission 人工确认
仍只批准任务定义，不改变约束值。

### 5.2 Blueprint 与章节偏差

Blueprint Context Pack 在已批准 Mission 和允许的来源摘要之外，附加最小结构化约束摘要，
不重新暴露完整 Intake。Blueprint Artifact 提交后计算章节偏差并写入
`blueprint.chapter_count_observed` 事件。

- `abs(actual - expected) <= 1`：进入 `batch_plan`；
- `abs(actual - expected) > 1`：保留 Blueprint Artifact，在 `batch_plan` 入口进入
  `waiting_for_human`，原因码为 `blueprint_chapter_deviation`；
- 用户执行现有 `RESUME` 表示接受当前精确 Blueprint 的偏差，系统写入幂等的
  `blueprint.chapter_deviation_accepted` 事件，然后继续构建 Batch Plan。

接受事件必须绑定 Run、Blueprint Artifact ID、版本和内容 hash。恢复或 Command 重放不得
重复写入。重新生成的 Blueprint 不能复用旧版本的接受事实。

### 5.3 Writer

Writer 的最小 Context Pack 增加当前 Run 的 `min_effective_chars`，使模型在生成阶段就按
下限写作。它仍只获得当前章节 brief、必要的相邻章节摘要和 continuity ledger，不能读取
完整课程正文或修改约束。

### 5.4 Quality

deterministic quality gate 在现有 Markdown 结构检查中增加有效字符统计。统计器必须是纯函数，
相同 Markdown 始终得到相同结果。低于下限时产生阻断型 `content_length` Finding，绑定精确
Lesson ArtifactRef、实际值、下限和证据 hash。

现有 Repair 只允许精确单行替换，无法安全承担整章扩写。字符不足因此不进入自动 Repair，
而是以 `lesson_effective_chars_below_minimum` 停在 `quality=waiting_for_human`。

## 6. Token 阈值与终止语义

继续复用 `provider_calls` 中的真实 `input_tokens` 和 `output_tokens`，不建立第二套 Token 账本。
预算读取模型增加已知累计 Token、阈值、未知用量调用数和终止状态。

Provider 调用完成后照常记录用量；当前节点的 Artifact、Event 与 after-node checkpoint 按现有
lease/epoch 围栏提交。下一节点写入 `NodeExecution.STARTED` 前执行阈值检查：

- `token_limit = null`：跳过；
- 已知累计 Token 小于阈值：继续；
- 已知累计 Token 达到或超过阈值：只追加一次 `budget.token_exhausted`，Run 进入
  `stopped`，原因码为 `token_limit_reached`，不得创建下一节点的 `STARTED`；
- 存在 unknown 调用：显示 unknown，但不估算其 Token，也不据此触发终止。

Token 阈值停止与人工 STOP 不同。它是不可恢复的终止原因，`RESUME` 必须返回明确拒绝，
也不得通过现有“追加 Provider 调用次数”机制绕过。Provider 调用次数的 48 次预警、60 次硬
上限仍独立生效。

## 7. 前端设计

保留现有单页创建表单，不改造成多步向导。在学习目标下增加 `生成约束` fieldset：

- `期望章节数` 数字输入，默认 12，提示“用于规划，允许 ±1 章偏差”；
- `单章有效字符数下限` 数字输入，默认 12000，并解释统计口径；
- `Token 阈值` 使用“不限制 / 设置阈值”单选；默认不限制，选择设置后才显示正整数输入。

前端提供即时校验，后端保留最终校验权。创建按钮提交明确值，Token 不限制序列化为 `null`，
不增加额外布尔字段。

Run 工作台显示只读约束摘要，例如：

```text
期望章节：12（允许 11–13）
单章下限：12,000 有效字符
Token：已用 18,420 / 50,000
```

状态提示：

- `blueprint_chapter_deviation`：显示期望数、实际数及“接受偏差并继续”按钮；
- `lesson_effective_chars_below_minimum`：显示章节、实际字符数和下限；
- `token_limit_reached`：显示累计用量与阈值，并明确此 Run 已终止、不能继续。

本阶段不增加动态图表、单独预算设置页或创建后的约束编辑入口。

## 8. 错误、安全与证据

校验错误返回稳定字段路径和原因，不回显 Prompt、模型原始响应、密钥或 Intake 正文。
Event、Snapshot 和证据包只记录约束值、实际计数、ArtifactRef、原因码与时间。

新增事件和原因码必须支持正常执行、Worker 接管和 Command 重放：

- `blueprint.chapter_count_observed`；
- `blueprint.chapter_deviation_accepted`；
- `budget.token_exhausted`；
- `blueprint_chapter_deviation`；
- `lesson_effective_chars_below_minimum`；
- `token_limit_reached`。

所有持久化副作用继续验证有效 lease 的 owner、epoch 和过期时间。

## 9. 验证策略

后端测试覆盖：

- CourseInput 默认值、边界和 nullable Token；
- schema 7 到 8 的可重复迁移以及历史 Run 的版本 0 行为；
- 带约束的创建幂等与冲突；
- Snapshot 重建和公开响应；
- 各角色 Context Pack 的最小约束暴露；
- Blueprint 偏差边界、等待、接受绑定和重放；
- 有效字符统计及阻断 Finding；
- 字符不足不进入单行 Repair；
- Token 达线时当前节点已提交、下一节点未启动；
- unknown Token 不估算；
- Token 停止拒绝 RESUME；
- 崩溃接管不重复写事件。

前端测试覆盖默认值、Token 开关、提交 payload、只读摘要、原因提示和继续按钮。

交付前运行：

```bash
apps/api/.venv/bin/python -m pytest apps/api/tests
npm --prefix apps/web test
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
```

同时更新 `AGENTS.md`：将 SQLite schema 版本改为 8，并冻结本设计中的生成约束、偏差、
质量门和 Token 终止语义。

## 10. 非目标

- 不新增 Graph 阶段或 Agent 角色；
- 不自动发布；
- 不提供创建后编辑约束；
- 不按章节平均拆分字符或 Token；
- 不对 unknown Token 做成本推算；
- 不把字符不足交给单行 Repair；
- 不建立通用规则引擎或可版本化 Policy 子系统。
