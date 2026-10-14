# 课程发布链路缺口分析与实现计划

> 目标工程：`/Users/yuta/Documents/project-create-course-ai-agent-local`
> 计划文档位置：Open Design 项目根（本文）
> 结论一句话：**不是 release 流程出错，而是「发布」这一步在 V0 里从未实现**。`准备发布` 只记录人工意向，课程永远不会进入「已发布」列表。
> **状态：已实现并验证（见第 9 节实现记录）。** 方案 A 已落地：新增独立显式 `publish` 动作。

---

## 1. 意图摘要

用户现象：七阶段全部成功后，人工选择「准备发布」，操作成功，但「课程列表」里新课程没有出现在「已发布」分组，仍停留在「我的课程 / 草稿」分组。

需要回答：这是 bug 还是功能未实现？下一步该做什么？

---

## 2. 诊断结论（附真源码行号）

**结论：功能未实现，且是当前契约的既定设计，不是运行时故障。**

### 2.1 `准备发布` 只写意向，不发布

- `apps/api/app/v0/runner.py:391-399`：人工决定 `prepare` 时，
  `output_summary = "人工选择准备发布；V0 未执行发布"`，`run.status = "ready_for_release"`。
  没有任何「写课程文件 / 写目录 / 写目录索引」的动作。
- `apps/api/app/v0/graph.py:153-185`：`release` 节点在 `prepare` 分支只调用
  `_record_release_decision`，返回 `exit_reason="release_prepare"` 后流程直接结束。
- 前端文案本身就是证据：`apps/web/src/pages.tsx:688`
  `“准备发布”只记录人工意向，不会自动发布课程。`；`pages.tsx:698`
  `人工已选择准备发布；V0 尚未发布任何文件。`
- 契约文档确认这是刻意为之：`docs/seven-stage-v0-technical-plan.md:28,83`、
  `docs/seven-stage-course-agent-contract.md:64-65`、`docs/quality-loop-technical-plan.md:55`。
- 测试也在固化该行为：`apps/api/tests/test_v0_api.py:250-256`
  （`test_api_human_prepare_does_not_publish`，断言 `"published" not in status`）。

### 2.2 「已发布」列表与 Run 管线完全不连通

- 列表来源：`apps/web/src/pages.tsx:46-49` → `api.courses()` → `GET /api/courses`
  → `apps/api/app/api/course_routes.py:9-13` → `apps/api/app/catalog.py:29-40`：
  读取静态文件 `courses/catalog.json`。
- `courses/catalog.json` 目前只有 1 条硬编码条目
  （`advanced-learning-of-obsidian`，`status: "published"`）。
- **全仓库没有任何代码写入 `catalog.json`**：grep 仅命中 `catalog.py:12` 的读取处。
- 因此无论怎么 release，已发布分组都不会变化。

### 2.3 「我的课程 / 草稿」列表显示的是全部 Run

- 来源：`apps/web/src/pages.tsx:54-55` → `api.courseFacts()` → `GET /api/v0/courses`
  → `apps/api/app/api/fact_routes.py:17-19` → `storage.list_courses()`
  （`apps/api/app/v0/storage.py:752-771`）。
- 该查询把 `courses` 表里**所有**课程（不论 status）都列出来，标题写死「{n} 门草稿」。
  所以新课程永远先出现在这里，且 `ready_for_release` 也照样留在这里。

### 2.4 一句话根因

Run 的最终状态是 `ready_for_release`（意向），系统里不存在
「把 Run 的内容物化为可访问课程 + 写入目录索引」这一环；「已发布」列表读的是另一个静态文件。

---

## 3. 当前数据流（现状）

```
创建课程 → Run(7阶段) → 质量 ready → release 节点 waiting_for_human
       → 人工 POST /release {action:"prepare"} → status = ready_for_release（结束）

「我的课程/草稿」 ← storage.list_courses()  ← SQLite（全部课程，不分状态）
「已发布」       ← catalog.list_courses()  ← courses/catalog.json（静态，无人写入）
                                   ↑
                          没有任何写入者
```

---

## 4. 需要先决定的产品问题（开放问题）

- [ ] **`prepare` 之后是否要立即发布？** 现行契约「人工独占发布权」下，`prepare` 语义就是意向。
      若希望一键发布，应新增独立的 `publish` 动作，而不是改写 `prepare` 语义。可以
- [ ] **发布物是什么形态？** 参照现有示例课程 `courses/advanced-learning-of-obsidian/`
      （`index.html` + `lessons/*.md` + `assets/` + `course.json`），
      还是仅写目录索引 + 挂载？前置
- [ ] **发布目标在哪？** 就地生成到 `courses/<slug>/`，还是单独 `published/` 目录？单独 `published/` 目录
- [ ] **谁有权发布、如何记录？** 当前 `ReleaseDecision` 只允许 `prepare | stop`
      （`apps/api/app/v0/schemas.py:254`），没有操作者身份。当前操作者可以发布
- [ ] **发布后草稿列表如何处理？** 从「我的课程」移除、标记为已发布，还是保留并改徽标？从「我的课程」移除、标记为已发布
- [ ] **是否要落库记录发布状态？** 建议在 SQLite 增 `published` 状态与 `catalog` 写回，而非只改静态文件。是

---

## 5. 建议实现方案（供选择，尚未执行）

> 只做前端替身 / 真实落盘两种档位，按用户最终选择推进。

**方案 A（最小闭环，推荐先做）**
1. `schemas.py`：`ReleaseDecision.action` 增加 `"publish"`；或新增独立端点
   `POST /api/v0/runs/{id}/publish`。
2. `runner.py`：新增 `publish()`，在 `ready_for_release` 基础上把 Run 内容物化为课程产物，
   并在 SQLite 记录 `published_at` / `published_slug`。
3. `catalog.py`：新增 `append_course()`，把发布结果写入 `courses/catalog.json`
   （幂等：按 slug 去重），或改为读 SQLite 已发布表。
4. `storage.list_courses()`：区分草稿与已发布；已发布的从「草稿」分组移出。
5. 前端 `pages.tsx`：`release-panel` 增加「发布」主按钮（保持一次一个主 CTA），
   「我的课程」卡片按状态分组/打徽标。
6. 幂等：沿用现有 `Idempotency-Key` 机制（`run_routes.py:214-226`、`storage.release_replay`）。

**方案 B（纯前端演示替身）**
- 仅在 `/release` prepare 成功后，前端把该 Run 追加进本地「已发布」视图（不落盘），用于演示，不改变后端契约。

**建议**：若目标是真实可用 → 方案 A；若只是走查交互 → 方案 B。

---

## 6. 验收清单（实现后逐项核对）

- [ ] release 之前不出现任何发布按钮（保持人工独占）。
- [ ] `prepare` 行为不变：仍只到 `ready_for_release`，文案与新按钮不冲突。
- [ ] 执行发布后：新课程出现在「已发布」列表，且从「草稿」列表移出（或明确标记）。
- [ ] 发布幂等：重复提交同一 Idempotency-Key 返回同一结果，不产生重复目录。
- [ ] 发布失败有明确错误（allowlisted，不泄露原始异常文本，沿用 `sensitive.py` 口径）。
- [ ] `courses/catalog.json` 或 SQLite 的写入有测试覆盖（对齐 `test_v0_api.py` 风格）。
- [ ] 前端任务：`npm run build` / 类型检查通过；后端：`ruff` + `pytest` 通过。
- [ ] 更新受影响的契约文档（`docs/seven-stage-v0-technical-plan.md` 等），
      把「V0 未执行发布」改为新语义。

---

## 7. 风险与边界

- **契约冲突**：多个技术文档明确写「不自动发布」「release 只记意向」。改行为必须同步改文档与测试，
  否则 `test_api_human_prepare_does_not_publish` 会红。
- **权限空缺**：当前无身份认证，所谓「人工发布」不校验操作者（见 `docs/...v0-technical-plan.md:92`）。
- **不要削弱人工闸门**：即使新增发布，也应保持「先 prepare 再 publish」或同等显式人工确认。
- **示例课程为只读**：`courses/advanced-learning-of-obsidian/` 是保留示例，不要作为发布写入目标。

---

## 8. 下一步（Next step）

1. 请先回答第 4 节的开放问题（尤其是：**`prepare` 后是否要真实发布、发布物形态与目标目录**）。
2. 确认后我将按方案 A / B 之一更新本计划，并产出可执行的改造清单（含文件级修改点与测试）。
3. 若确认走实现，请在 Design 模式中指示「按 `course-publish-plan.md` 执行」，我再落地代码改动。

> 本文件为计划文档，尚未改动任何工程代码。可直接在本 Markdown 上批注/编辑。
