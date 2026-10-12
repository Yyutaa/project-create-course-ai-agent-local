
# 课程生成约束前置实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 subagent-driven-development（推荐）或 executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在新建课程时持久化章节数、单章有效字符下限和 Token 阈值，并在 Blueprint、Quality 与 Worker 节点边界执行已批准的约束语义。

**架构：** 扩展现有 `CourseInput → SQLite Intake → Context Pack` 链路，不新增 Graph 阶段、Agent 角色或通用规则引擎。章节偏差在 `batch_plan` 入口复用人工等待与 `RESUME`，字符下限进入 deterministic quality gate，Token 阈值复用 `provider_calls` 并在下一节点 `STARTED` 前终止 Run。

**技术栈：** Python 3.12、FastAPI、Pydantic、SQLite、LangGraph、pytest、React、TypeScript、React Query、Node test runner、Vite

**规格：** `assets/aiagent/course-generation-constraints-design.md`

## 全局约束

- 七阶段顺序保持 `intake → mission → blueprint → batch_plan → generation → quality → release`。
- 新 Run 默认 `expected_chapters=12`、`min_effective_chars=12000`、`token_limit=null`。
- 章节数固定允许 ±1，不增加可配置容差。
- 有效字符去除 Markdown 标记、HTML 标签和空白，代码块内容保留计数。
- Token 只累计 Provider 返回的真实 `input_tokens + output_tokens`；unknown 不估算。
- Token 达线允许当前节点提交，在下一节点前不可恢复地停止；`RESUME` 不得绕过。
- 历史 Run 使用 `constraints_version=0`；新 Run 使用版本 1。
- SQLite schema 升级到 8；迁移 DDL 与版本更新保持同一事务。
- 不新增依赖，不扩大 Repair 的单行修复权限，不改变人工 release 决策权。
- Python 单行不超过 92 字符；前后端公开类型必须同步。

## 文件职责

- `apps/api/app/v0/schemas.py`：CourseInput 约束字段与 Run 约束版本。
- `apps/api/app/v0/storage.py`：schema v8 迁移及 Intake 创建、重建。
- `apps/api/app/v0/context.py`：按角色裁剪约束摘要。
- `apps/api/app/v0/graph.py`：章节偏差门和字符不足人工升级。
- `apps/api/app/v0/quality_loop.py`：有效字符纯函数与 deterministic Finding。
- `apps/api/app/v0/budget.py`：真实 Token 汇总。
- `apps/api/app/v0/execution.py`：节点前 Token 检查、偏差接受和 RESUME 限制。
- `apps/api/app/v0/worker.py`：提交 Token 终止事实。
- `apps/api/app/v0/delivery.py`：脱敏证据索引。
- `apps/web/src/api.ts`、`run-view.ts`、`pages.tsx`、`styles.css`：类型、展示与界面。
- `AGENTS.md`：冻结 schema v8 和生成约束契约。

---

### 任务 1：持久化 CourseInput 与 schema v8

**文件：**
- 修改：`apps/api/app/v0/schemas.py:75-82,321-342`
- 修改：`apps/api/app/v0/storage.py:68-240,251-370`
- 测试：`apps/api/tests/test_v0_schemas.py`
- 测试：`apps/api/tests/test_v0_storage.py`

- [ ] **步骤 1：编写失败的 Schema 测试**

```python
def test_course_input_has_generation_constraint_defaults():
    value = CourseInput(topic="Python", audience="初学者", goal="练习", language="zh")
    assert value.expected_chapters == 12
    assert value.min_effective_chars == 12_000
    assert value.token_limit is None


@pytest.mark.parametrize("field,value", [
    ("expected_chapters", 0), ("expected_chapters", 101),
    ("min_effective_chars", 0), ("token_limit", 0),
])
def test_course_input_rejects_invalid_constraints(field, value):
    payload = {"topic": "Python", "audience": "初学者", "goal": "练习",
               "language": "zh", field: value}
    with pytest.raises(ValidationError):
        CourseInput.model_validate(payload)
```

- [ ] **步骤 2：编写 v7 迁移与历史隔离测试**

构造含历史 Run/Intake 的 v7 数据库。迁移两次后断言版本为 8，新增四列存在，历史
`constraints_version=0`。再创建新 Run、删除 Snapshot 并重建：

```python
assert store.schema_version() == 8
assert rebuilt.constraints_version == 1
assert rebuilt.course_input.expected_chapters == 12
```

- [ ] **步骤 3：运行测试确认字段和迁移缺失**

运行：`apps/api/.venv/bin/python -m pytest apps/api/tests/test_v0_schemas.py apps/api/tests/test_v0_storage.py -q`

预期：CourseInput 属性不存在或 schema 仍为 7。

- [ ] **步骤 4：实现最小 Schema 和迁移**

```python
class CourseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: NonEmptyText
    audience: NonEmptyText
    goal: NonEmptyText
    language: Literal["zh"]
    expected_chapters: int = Field(default=12, ge=1, le=100)
    min_effective_chars: int = Field(default=12_000, gt=0)
    token_limit: int | None = Field(default=None, gt=0)
```

给 `V0Run` 增加 `constraints_version: int = Field(default=0, ge=0, le=1)`。实现
`_migrate_v8()`：Intake 增加三个约束列，Run 增加默认 0 的版本列，最后设置版本 8。
新 Run INSERT 明确写版本 1；`_rebuild()` 同步读取四项事实。

- [ ] **步骤 5：补充幂等测试**

同键同约束返回同一 Run；同键只改变 `expected_chapters` 返回冲突。

- [ ] **步骤 6：验证通过并提交**

运行：`apps/api/.venv/bin/python -m pytest apps/api/tests/test_v0_schemas.py apps/api/tests/test_v0_storage.py -q`

```bash
git add apps/api/app/v0/schemas.py apps/api/app/v0/storage.py apps/api/tests/test_v0_schemas.py apps/api/tests/test_v0_storage.py
git commit -m "feat: persist course generation constraints"
```

### 任务 2：按角色传递最小约束上下文

**文件：**
- 修改：`apps/api/app/v0/context.py:39-135,147-225`
- 修改：`apps/api/app/v0/graph.py:295-465`
- 测试：`apps/api/tests/test_v0_context.py`
- 测试：`apps/api/tests/test_v0_graph.py`

- [ ] **步骤 1：编写失败的 Context Pack 测试**

```python
blueprint = builder.for_blueprint("run-1", mission_ref, expected_chapters=12)
assert blueprint.inputs[0].content["generation_constraints"] == {
    "expected_chapters": 12,
}
writer = builder.for_writer(
    "run-1", mission_ref, blueprint_ref, batch_ref,
    lesson_index=0, min_effective_chars=12_000,
)
assert writer.inputs[0].content == {
    "generation_constraints": {"min_effective_chars": 12_000},
}
```

同时断言 Blueprint/Writer 看不到 topic、audience、goal、token_limit。

- [ ] **步骤 2：运行测试确认新参数尚不存在**

运行：`apps/api/.venv/bin/python -m pytest apps/api/tests/test_v0_context.py -q`

- [ ] **步骤 3：实现显式关键字参数**

扩展 `for_blueprint()`、`for_writer()` 与 `_writer_inputs()`。Graph 仅在版本 1 时传值；
历史 Run 传 `None` 且不生成约束键。不新增 input kind。

- [ ] **步骤 4：验证通过并提交**

运行：`apps/api/.venv/bin/python -m pytest apps/api/tests/test_v0_context.py apps/api/tests/test_v0_graph.py -q`

```bash
git add apps/api/app/v0/context.py apps/api/app/v0/graph.py apps/api/tests/test_v0_context.py apps/api/tests/test_v0_graph.py
git commit -m "feat: pass generation constraints to course agents"
```

### 任务 3：实现 Blueprint 章节偏差人工门

**文件：**
- 修改：`apps/api/app/v0/graph.py:296-355`
- 修改：`apps/api/app/v0/execution.py:504-534`
- 修改：`apps/api/app/v0/storage.py`（精确 Artifact 接受事实查询）
- 测试：`apps/api/tests/test_v0_graph.py`
- 测试：`apps/api/tests/test_v0_execution_protocol.py`

- [ ] **步骤 1：编写偏差边界失败测试**

复用 `MultiLessonProvider`，期望为 12。实际 11、12、13 应继续；实际 14 应保存 Blueprint、
不生成 BatchPlan，并等待人工：

```python
assert run.status == "waiting_for_human"
assert commands.read_model(run.id).waiting_reason == "blueprint_chapter_deviation"
assert not [item for item in run.artifacts if item.kind == "batch_plan"]
```

- [ ] **步骤 2：编写接受绑定和重放失败测试**

RESUME 后只允许一条 `blueprint.chapter_deviation_accepted`；事件绑定最新 Blueprint 的
artifact ID、version、hash。旧版本接受事实不能放行新 Blueprint。

- [ ] **步骤 3：运行测试确认当前流程直接继续**

运行：`apps/api/.venv/bin/python -m pytest apps/api/tests/test_v0_graph.py apps/api/tests/test_v0_execution_protocol.py -q`

- [ ] **步骤 4：实现 batch_plan 入口门**

Blueprint 提交后幂等记录 `blueprint.chapter_count_observed`。`_batch_plan()` 在创建 Artifact
前比较偏差；超出 ±1 且无当前精确引用接受事实时调用
`self.runner._mark_waiting(state.run_id, index, "blueprint_chapter_deviation")`。

`prepare_resume()` 仅对此等待原因写入精确绑定的
`blueprint.chapter_deviation_accepted`，随后按现有路径恢复。保留租约和 Command 重放检查。

- [ ] **步骤 5：验证通过并提交**

运行：`apps/api/.venv/bin/python -m pytest apps/api/tests/test_v0_graph.py apps/api/tests/test_v0_execution_protocol.py -q`

```bash
git add apps/api/app/v0/graph.py apps/api/app/v0/execution.py apps/api/app/v0/storage.py apps/api/tests/test_v0_graph.py apps/api/tests/test_v0_execution_protocol.py
git commit -m "feat: gate large blueprint chapter deviations"
```

### 任务 4：实现单章有效字符质量门

**文件：**
- 修改：`apps/api/app/v0/quality_loop.py:1-90`
- 修改：`apps/api/app/v0/graph.py:496-644`
- 测试：`apps/api/tests/test_v0_quality_loop.py`
- 测试：`apps/api/tests/test_v0_graph.py`

- [ ] **步骤 1：编写计数口径失败测试**

```python
def test_effective_count_strips_markup_and_whitespace_but_keeps_code():
    text = "# 标题\n\n<strong>正文</strong>\n```py\nprint(1)\n```"
    assert effective_character_count(text) == len("标题正文print(1)")
```

补充链接、强调、列表标记和 CRLF，保证结果稳定。

- [ ] **步骤 2：编写不足下限 Finding 失败测试**

```python
report = check_markdown("# 标题\n\n正文", ref, "lesson-1", min_effective_chars=20)
finding = next(x for x in report.findings
               if x.rule_id == "lesson.effective_chars.minimum")
assert finding.category == "structure"
assert finding.severity == "blocker"
```

Graph 测试断言进入 `quality=waiting_for_human`，原因为
`lesson_effective_chars_below_minimum`，且没有 RepairTask 或 Candidate。

- [ ] **步骤 3：运行测试确认函数和参数缺失**

运行：`apps/api/.venv/bin/python -m pytest apps/api/tests/test_v0_quality_loop.py -q`

- [ ] **步骤 4：实现纯函数与人工升级**

使用标准库 `re`：保留 fenced code 内容，去掉 fence、HTML 标签、Markdown 标记和全部空白。
给 `check_markdown()` 增加可选下限；历史 Run 传 `None`。`_quality()` 识别该 rule ID 后先
持久化 QualitySummary，再等待人工，不走 `repair_needed`。

- [ ] **步骤 5：验证通过并提交**

运行：`apps/api/.venv/bin/python -m pytest apps/api/tests/test_v0_quality_loop.py apps/api/tests/test_v0_graph.py -q`

```bash
git add apps/api/app/v0/quality_loop.py apps/api/app/v0/graph.py apps/api/tests/test_v0_quality_loop.py apps/api/tests/test_v0_graph.py
git commit -m "feat: enforce lesson effective character minimum"
```

### 任务 5：实现 Token 汇总与不可恢复停止

**文件：**
- 修改：`apps/api/app/v0/budget.py:1-199`
- 修改：`apps/api/app/v0/execution.py:61-71,370-425,504-594`
- 修改：`apps/api/app/v0/worker.py:35-210`
- 测试：`apps/api/tests/test_v0_delivery_evidence.py`
- 测试：`apps/api/tests/test_v0_execution_protocol.py`

- [ ] **步骤 1：编写 Token 汇总失败测试**

插入 `(100,20)`、`(None,None)`、`(50,10)` 三次调用，阈值为 180：

```python
summary = BudgetStore(facts.path).summary(run.id)
assert summary.tokens_used == 180
assert summary.token_limit == 180
assert summary.token_usage_unknown == 1
assert summary.token_exhausted is True
```

另测 `token_limit=None` 和版本 0 不触发阈值。

- [ ] **步骤 2：编写节点边界与 RESUME 失败测试**

让 Mission 调用刚好达到阈值。断言 Mission Artifact 和 after-node checkpoint 已提交，
Blueprint 没有 `STARTED`，Run 为 stopped，原因 `token_limit_reached`，终止事件只有一条。
提交 RESUME 后 Command 为 REJECTED，且仍无 Blueprint 节点。

- [ ] **步骤 3：运行测试确认当前只统计调用次数**

运行：`apps/api/.venv/bin/python -m pytest apps/api/tests/test_v0_delivery_evidence.py apps/api/tests/test_v0_execution_protocol.py -q`

- [ ] **步骤 4：扩展 BudgetSummary**

```python
class BudgetSummary(BaseModel):
    used: int
    limit: int
    warning_at: int
    warning: bool
    requires_human: bool
    unknown: int
    repair_used: int
    repair_limit: int
    repair_exhausted: bool
    tokens_used: int
    token_limit: int | None
    token_usage_unknown: int
    token_exhausted: bool
```

SQL 累计已知输入与输出 Token；任一 Token 字段缺失的已完成调用计入 unknown。只有版本 1
且阈值非空时设置 exhausted，不改变现有 48/60 次调用预算。

- [ ] **步骤 5：在下一节点前提交不可恢复停止**

定义携带 used、limit、next_node 的 `TokenLimitReached`。`start_node()` 在写 before-node
checkpoint 和 NodeExecution 前检查并抛出。Worker 捕获后持 lease 把 Run 和即将进入阶段
标记 stopped，原因 `token_limit_reached`，追加一次 `budget.token_exhausted`。不得设置人工
STOP 标志。`prepare_resume()` 在修改 Run 前查询终止事件并拒绝。

- [ ] **步骤 6：验证通过并提交**

运行：`apps/api/.venv/bin/python -m pytest apps/api/tests/test_v0_delivery_evidence.py apps/api/tests/test_v0_execution_protocol.py -q`

```bash
git add apps/api/app/v0/budget.py apps/api/app/v0/execution.py apps/api/app/v0/worker.py apps/api/tests/test_v0_delivery_evidence.py apps/api/tests/test_v0_execution_protocol.py
git commit -m "feat: stop runs at immutable token limits"
```

### 任务 6：同步安全 API 与交付证据

**文件：**
- 修改：`apps/api/app/api/run_routes.py:68-83`
- 修改：`apps/api/app/v0/sensitive.py`
- 修改：`apps/api/app/v0/delivery.py`
- 测试：`apps/api/tests/test_v0_api.py`
- 测试：`apps/api/tests/test_v0_delivery_evidence.py`

- [ ] **步骤 1：编写公开响应失败测试**

POST 后断言 topic 仍隐藏，三项约束保持真实值。非法约束返回 422 且响应不含 Pydantic 原始
`input`。Token 停止只暴露稳定原因码，不包含 Provider 原始文本。

- [ ] **步骤 2：编写证据索引失败测试**

构造偏差接受、字符 Finding 和 Token 终止，断言 evidence 只含事件 ID、Artifact 版本、
rule ID、状态和计数，不含 Intake、Lesson 正文或 Prompt。

- [ ] **步骤 3：实现最小读取变更**

`_public_run()` 继续只隐藏 topic、audience、goal。把以下稳定原因加入安全白名单：

```text
blueprint_chapter_deviation
lesson_effective_chars_below_minimum
token_limit_reached
```

`delivery.py` 索引新增事件及引用，不复制正文。

- [ ] **步骤 4：验证通过并提交**

运行：`apps/api/.venv/bin/python -m pytest apps/api/tests/test_v0_api.py apps/api/tests/test_v0_delivery_evidence.py -q`

```bash
git add apps/api/app/api/run_routes.py apps/api/app/v0/sensitive.py apps/api/app/v0/delivery.py apps/api/tests/test_v0_api.py apps/api/tests/test_v0_delivery_evidence.py
git commit -m "feat: expose safe generation constraint status"
```

### 任务 7：实现创建表单与 Run 约束界面

**文件：**
- 修改：`apps/web/src/api.ts:32-37,201-220`
- 修改：`apps/web/src/run-view.ts`
- 修改：`apps/web/src/pages.tsx:199-210,381-453,512-530`
- 修改：`apps/web/src/styles.css`
- 测试：`apps/web/tests/v0-run-view.test.mjs`

- [ ] **步骤 1：编写 helper 和 payload 失败测试**

新增并导出 `generationConstraintLabels()`、`budgetTokenLabel()`、`canResumeRun()`。测试默认
摘要、千分位、unknown、偏差可继续、Token 终止不可继续。拦截 `api.startRun()` 并断言：

```javascript
{
  expected_chapters: 12,
  min_effective_chars: 12000,
  token_limit: null,
}
```

- [ ] **步骤 2：运行测试确认 helper 和字段缺失**

运行：`npm --prefix apps/web run test:v0`

- [ ] **步骤 3：同步类型与纯展示逻辑**

CourseInput 增加三个字段，V0Run 增加 constraints_version，Budget 增加四个 Token 字段。
helper 只根据 API 事实显示，不在浏览器计算 Token 或有效字符。

- [ ] **步骤 4：实现最小表单**

```typescript
const [input, setInput] = useState<CourseInput>({
  topic: "", audience: "", goal: "", language: "zh",
  expected_chapters: 12, min_effective_chars: 12000, token_limit: null,
});
```

在现有表单增加 fieldset、两个 number 输入和“不限制/设置阈值”单选。Token 数值只留组件
内存；不写浏览器持久存储。完整 input JSON 继续生成创建幂等键。

- [ ] **步骤 5：实现只读摘要与精确按钮**

偏差原因下把 RESUME 文案显示为“接受偏差并继续”；字符不足显示实际值和下限；Token 终止
隐藏 REVISE/RESUME，显示不可继续提示。其他 stopped/waiting Run 保持现有行为。

- [ ] **步骤 6：验证通过并提交**

```bash
npm --prefix apps/web run test:v0
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
git add apps/web/src/api.ts apps/web/src/run-view.ts apps/web/src/pages.tsx apps/web/src/styles.css apps/web/tests/v0-run-view.test.mjs
git commit -m "feat: add constraints to course creation"
```

### 任务 8：冻结契约并完成全量回归

**文件：**
- 修改：`AGENTS.md`
- 修改：`assets/aiagent/course-generation-constraints-design.md`（只同步实现确认的技术表述）

- [ ] **步骤 1：更新冻结契约**

把现行 schema 版本从 7 改为 8，增加“课程生成约束”小节，固化默认值、版本隔离、章节 ±1、
字符口径、Token 节点边界停止、unknown 和不可恢复 RESUME。不改变七步、调用次数预算或
release 权限。

- [ ] **步骤 2：运行完整后端检查**

```bash
apps/api/.venv/bin/python -m ruff check apps/api/app apps/api/tests
apps/api/.venv/bin/python -m pytest apps/api/tests
```

预期：Ruff 0 errors；pytest 0 failures。

- [ ] **步骤 3：运行完整前端检查**

```bash
npm --prefix apps/web run test:v0
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
```

预期：Node tests 0 failures；TypeScript 0 errors；Vite build 退出 0。

- [ ] **步骤 4：检查变更边界**

```bash
git diff --check
git status --short
git log --oneline -8
```

确认 `.course-agent/`、`courses/`、`docs/`、`implementation-guide-20-lessons/`、构建目录和密钥
未进入提交。仓库开始前已有未提交 `.gitignore` 修改，不得回滚或混入功能提交。

- [ ] **步骤 5：提交契约文档**

```bash
git add AGENTS.md assets/aiagent/course-generation-constraints-design.md
git commit -m "docs: freeze course generation constraint contract"
```

- [ ] **步骤 6：最终证据检查**

逐项对照规格第 4–10 节。只有上述验证命令均为新鲜成功结果时才报告完成。真实 Keychain 或
DeepSeek 若未手工验收，必须明确标记“未验证”，不得写成已通过。
