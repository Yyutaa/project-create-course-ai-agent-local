# V0 课程生产可观测性

## 调用指标

每次真实 Provider 尝试先由 `BudgetStore.reserve()` 写入 `provider_calls`，状态为
`RESERVED`。调用结束后，`BudgetStore.finish()` 在有效 lease 下记录状态、耗时、
已知的输入/输出 Token、Provider 名称、模型、HTTP 状态、安全错误码、失败分类和
错误摘要。模型响应已返回但后续 JSON 解析失败时，异常携带响应中的已知 Token
用量；没有 usage 的失败或崩溃保持 `NULL`。`total_tokens` 只在输入和输出均已知时
计算，不作为独立事实列。

HTTP 429 与超时记为临时失败；解析错误记为确定性失败；其他无法可靠分类的
Provider 错误记为未知。调用次数预算按预留次数计，未知用量不按零 Token 推断。
模型名只投影当前本地允许的 DeepSeek 模型，旧调用缺失的元数据保持 `null`。

## Trace 与 Span

`GET /api/v0/runs/{run_id}/evidence` 的 `trace_id` 等于 Run ID。`spans` 在读取时
从持久事实重建，顺序为 Run → Command → NodeExecution → ProviderCall/ToolCall。
每个 Span 的 ID 由对象类别和稳定对象 ID 组成；缺失上级引用时回退到 Run 根节点，
并保留已有的开始/结束时间；同时保留现有的 `integrity_issues`。
这是一份可重建的业务追踪投影，不是另一个
执行权威或 OpenTelemetry Span 存储。

排查一次失败时，先按 Provider Span 的 `status` / `error_code` 找到调用，再沿
`parent_span_id` 回到 Node 与 Command；Node 的 `failure_class` 和安全错误摘要
可帮助区分模型调用失败与模型返回后发生的阶段失败。

## Token 边界与敏感信息

`TOKEN_BUDGETS` 是五角色输入消息的离线预检上限；`MAX_OUTPUT_TOKENS` 是发往
DeepSeek 的输出上限：Writer 为 32768，其余四个角色为 8192。Run 的总量限制
仍取不可变 Intake 的 `token_limit`，调用次数预算保持原规则。项目没有
`token_budget_mtokens`、planning 或 presentation 角色。

证据不包含 Key、Authorization、Prompt、模型原始响应、课程正文和工具结果正文。
未知异常只输出类型与受控诊断，已落库的历史原始错误在读取时再次经过安全过滤。
没有响应正文截断和 `[redacted]` 原文替换：原始失败响应根本不进入证据。
