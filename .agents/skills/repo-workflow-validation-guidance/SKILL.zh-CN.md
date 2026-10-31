---
name: repo-workflow-validation-guidance
description: 为当前目标选择最小且有意义的验证命令；当目标或命令范围仍不清晰时，返回未决验证指导而不是强行下结论。
---

# 仓库工作流：验证指导

## 用途

为当前变更范围返回任务级验证指导。

这个 workflow 只在当前目标已经足够明确时，负责选择最小且有意义的验证命令。如果目标归属、受影响应用、consumer 范围，或命令范围仍不清晰，就不能强行给出验证命令，而是应该返回未决指导，并说明还缺少哪些确认信息。

这个 workflow 的主要职责不是加载仓库基础信息，不负责大范围结构扫描，不负责从零定位最终改动目标，也不执行验证命令。

## 输入模式

接受自然语言请求，但需要先把当前输入归类到以下模式之一。

模式 1：上游已收敛的验证模式

- 输入里已经包含上游收敛过的目标范围，例如已确认的 `root_path` / `file_path`、changed files，或已明确的应用 / 包目标
- 当目标落在 `packages/**` 下时，输入里最好还包含直接的 consumer 线索，例如 consumer entry 文件、消费该包的应用名，或面向 consumer 的变更文件
- 当当前上下文已经包含上游 workflow 收敛过的目标范围时，使用这个模式，典型来源是 `repo-workflow-scope-change-targets`
- 只有当当前目标范围已经足够确认、可以进入命令选择时，这个模式才成立
- 如果上游结果本身仍未收敛，存在多个候选目标、归属未定，或 shared package 的 consumer 范围未定，则不能把它当成已确认验证目标
- 如果上游结果虽然带有 `requires confirmation: yes`，但已经收敛到单一具体目标和单一可用验证范围，则可以返回带简短确认说明的 provisional 验证指导，而不是默认中止

模式 2：直接目标验证模式

- 输入来自用户直接请求，且已经明确指出一个单一精确目标
- 当 `root_path` / `file_path` 还没有显式给出时，workflow 可以做最小化确认
- 当目标落在 `packages/**` 下时，direct consumer 线索仍然是更理想的输入；没有这些线索时，共享包验证可能仍需返回未决指导
- 当用户直接指出一个精确的应用、模块、页面或 shared package 目标时，使用这个模式
- 这个模式只允许做把单一精确目标映射到验证范围所需的最小化确认
- 这个模式不能扩展成大范围结构扫描，也不能替代 `repo-workflow-scope-change-targets`

模式 3：上下文不足的验证模式

- 输入只是泛化请求，例如“这个改动怎么验证”“应该跑什么命令”或“这个模块最小安全检查是什么”
- 输入没有明确指出归属应用、shared package、框架面、变更文件、上游已确认的目标范围，或在需要时没有给出共享包对应的 consumer 范围
- 在这个模式下，workflow 不能猜测最终验证命令，而应返回未决指导，并说明还需要确认哪些目标上下文

如果当前输入命中多个应用、多个 shared package、多个同层候选目标、应用与共享包之间的归属边界仍不清晰，或 shared package 尚未确认 consumer 范围，都应视为命令选择所需上下文不足。

## 前置条件

- 优先建立在当前上下文已经加载过 `repo-workflow-load-basics` 的前提上。
- 优先建立在当前目标范围已经通过 `repo-workflow-scope-change-targets` 收窄过的前提上，尤其是已确认的 `root_path` / `file_path`、当前 changed files，或用户直接提供的文件路径。
- 如果当前上下文仍缺少足够的目标信息，只允许最小化补读 `AGENTS.md`、`repo-profile.md` 和直接相关的目标线索；不要在这里用大范围源码探索替代目标定位 workflow。

## 步骤

1. 先读取 `AGENTS.md`。
2. 读取 `repo-profile.md` 中的命令和边界章节。
3. 判断当前输入属于“上游已收敛的验证模式”“直接目标验证模式”还是“上下文不足的验证模式”。
4. 如果输入属于“上游已收敛的验证模式”，先检查上游目标是否真的已经确认到可以进入验证命令选择；如果上游结果仍存在多个候选、归属未定，或 shared package 的 consumer 范围未定，则返回未决指导。如果它已经收敛到单一具体目标和单一可用验证范围，则可以返回带简短确认说明的 provisional 验证指导。
5. 如果输入属于“直接目标验证模式”，且 `root_path` / `file_path` 还没有显式给出，则只做最小化确认，把这个单一精确目标映射到一个验证范围；不要把这一步扩展成结构扫描。
6. 如果经过上游结果检查或最小化确认之后，目标仍不清晰、命中多个应用或 shared package，或证据仍不足以收敛到一个验证范围，先返回未决指导，而不是强行给命令。
7. 如果目标已经明确到可以映射为单一验证范围，则结合当前目标应用/模块/shared package，以及直接相关的 changed files 或上游给出的 `root_path` / `file_path`，选择最小但有意义的验证范围。
8. 这里优先把“检查类命令”视为验证命令；除非用户明确要求运行时验证指导，或当前已确认目标属于仅靠已登记静态检查无法可信覆盖风险的运行时集成面，否则不要把 install、dev、serve 作为默认验证结论返回。
9. 当确认目标下存在 `repo-profile.md` 已登记的较小范围检查命令且已经足够时，优先选择它。
10. 如果 `repo-profile.md` 没有登记足够窄的命令，但当前源码证据可以清楚核实某条窄范围检查命令，也可以返回它；但必须明确标注其属于 source-verified，而不是稳定仓库事实。
11. 除非它们已经为该确认目标运行面被 `repo-profile.md` 明确记录，或已被当前源码证据窄范围核实适用于该确认目标，否则不要把 test/build 当成默认验证结论推荐出去。
12. 当目标是 `packages/**` 下的 shared package 时，不要默认包内命令本身就足够。
13. shared package 验证默认需要已确认的 consumer 范围；只有当 `repo-profile.md` 明确记录了该共享包自身足够使用的检查命令时，才可以不先依赖 consumer 范围。
14. 如果 shared package 目标已经有明确的 consumer 线索，先检查 `repo-profile.md` 是否真的记录了该共享包自身可执行的检查命令。
15. 如果没有记录共享包自身的检查命令，不要靠猜测臆造它；只有当当前源码文件能直接核实该包存在窄范围检查命令时，才可以返回，例如包级 `package.json` script、带明确 package filter 的 workspace script，或其它直接面向该目标的脚本定义，并标注为 source-verified，而不是 repo-profile 已登记命令。否则只返回 `repo-profile.md` 已支持的、直接受影响 consumer 范围的最小检查命令集。
16. 只有当共享包自身检查命令已经被 `repo-profile.md` 明确记录，或已由当前源码文件直接核实时，才可以把它放在 consumer 范围检查之前一起返回。
17. 如果 shared package 目标还没有确认 consumer 范围，则返回未决指导，而不是只给一句泛化提醒。
18. 在这个仓库里，如果已确认目标跨越 React 前端、API 或 Worker，并依赖 `repo-profile.md` 已记录的启动联动链路，而静态检查不足以覆盖集成风险，则可以把最小运行时联调命令集作为 fallback 返回；但必须明确标注它属于 runtime verification guidance，而不是静态检查。
19. 当命令范围明确时，直接返回应执行的 Validation commands；只有在确实影响执行时，才补充最短的说明或注意事项。

## 决策规则

按以下优先级选择输出。

1. 单一明确命令
   - 归属应用或 shared package 已明确
   - 验证范围可以收敛到一条有意义的命令
   - 直接返回该命令
2. 目标明确，但需要多项检查
   - 归属目标明确，且 shared-package consumer 范围或跨端验证范围也已经明确
   - 因为至少要覆盖直接受影响的 consumer 范围，或必须验证跨运行面的联动链路；只有在共享包自身检查命令已被 `repo-profile.md` 明确记录，或已由当前源码文件直接核实时，才会额外纳入该检查，所以一条命令不足以完成验证
   - 返回最小必要命令集，并按执行顺序给出，同时说明为什么需要不止一项检查
3. provisional 单目标指导
   - 上游结果虽然仍带有 `requires confirmation: yes`，但已经收敛到单一具体目标和单一可用验证范围
   - 返回最小可执行命令，并用一句短说明指出仍待确认的点
4. 未决验证指导
   - 归属应用、shared package、框架面、changed-file 范围，或 shared-package consumer 范围仍不清晰
   - 或者上游输入仍无法收敛到单一具体验证范围
   - 或者一个精确的自然语言目标仍然无法通过最小化确认收敛到单一验证范围
   - 返回未决指导，并明确指出缺少哪些确认点，而不是猜测命令

## 输出重点

- 仅固定 `Status` 和 `Summary` 作为最小输出头
- 返回用户应直接执行的 Validation commands
- 当 shared package 或跨端目标明确且需要多于一项检查时，返回最小必要命令集
- 当目标或命令范围仍不清晰时，返回未决验证指导
- 只有在确实影响执行时才补充前置条件或注意事项

## 默认输出

始终先输出：

- `Status`
- `Summary`

当目标与命令范围已经足够明确，可以返回一条具体验证命令或一组最小必要命令集时，使用 `Status: resolved`。

当上游结果仍带有 `requires confirmation: yes`，但已经收敛到单一具体目标和单一可用验证范围时，使用 `Status: provisional`。

当目标归属、受影响应用、shared-package consumer 范围、框架面，或命令范围仍不足以收敛到单一验证范围时，使用 `Status: unresolved`。

`Summary` 控制在 2 到 4 条短 bullet，只说明当前验证结论，不要把每条命令或所有待确认项重复一遍。

当 `Status: resolved` 或 `Status: provisional` 时，优先使用如下结构：

```text
Status
- resolved

Summary
- `...`

Validation commands
- `...`
```

当目标明确但需要多于一项检查时，也尽量保持简洁：

```text
Status
- resolved

Summary
- `...`

Validation commands
- `...`
- `...`

Why these checks
- `...`
```

对于 provisional 单目标指导，也可以使用：

```text
Status
- provisional

Summary
- `...`

Validation commands
- `...`

Needs confirmation
- `...`
```

当目标仍不清晰时，优先返回未决指导：

```text
Status
- unresolved

Summary
- `...`

Needs confirmation
- 已确认的 `root_path`
- 首轮 `file_path`
- 上游 scope 是否已经确认
- 目标是应用内目标还是位于 `packages/**` 下
- 如果 `root_path` 位于 `packages/**` 下，还需要确认 consumer app 或 consumer entry
```

## 约束

- 不要执行命令。
- 仅固定 `Status` 和 `Summary` 作为最小输出头，其他块按当前请求实际需要出现。
- 除非会改变验证选择，不要重复宽泛的仓库概览信息。
- 不要把这个 workflow 当成 `repo-workflow-load-basics` 的替代；repository-level command coverage summary 属于后者。
- 不要把这个 workflow 当成 `repo-workflow-scope-change-targets` 的替代；如果目标仍有歧义，应先返回未决指导。
- 不要把上游候选目标、多候选上游结果，或 shared package consumer 范围未定的上游结果，当成已确认的验证范围。
- 但如果上游结果虽然带有 `requires confirmation: yes`，却已经收敛到单一具体目标和单一可用验证范围，也不要默认卡住；此时应返回带简短说明的 provisional 验证指导。
- 当 `Status: unresolved` 时，不要像命令范围已经确定一样继续输出 `Validation commands`、`Why these checks` 或 `Note`。
- 当 `Status: resolved` 或 `Status: provisional` 时，只返回最小且有意义的命令范围，不要膨胀成仓库级命令菜单。
- 当多个应用、shared package 或框架面仍同时成立时，不要强行选一条命令。
- 不要默认把 install、dev、serve 当成验证结论返回。只有当用户明确要求运行时验证指导，或已确认目标属于仅靠已登记静态检查无法可信覆盖的运行时联动集成面时，才允许返回这类命令。
- 不要在 shared package 的边界和 consumer 影响尚未明确时，声称一条命令就足以完成验证。
- 当 `repo-profile.md` 没有为该确认目标运行面明确记录 test/build 命令时，不要默认推荐它们作为验证结论；除非这条命令已经被当前源码文件直接、窄范围核实适用于该确认目标。
- 命令来源优先级固定为：1）`repo-profile.md` 为确认目标运行面明确记录的命令；2）当前源码文件可直接核实的窄范围命令；3）仅当以上两类仍不足以可信覆盖已确认集成风险时，才返回 runtime verification guidance。
- 如果某条命令既没有在 `repo-profile.md` 中被明确记录，也无法由当前源码文件直接核实，就不要推荐它。
- 当命令来自当前源码证据而不是 `repo-profile.md` 时，不要展开成长篇过程说明；只有在这个差异确实影响用户对命令可信度或执行方式的判断时，才补一句短说明。
- 如果 `repo-profile.md` 已经记录了确认目标所在运行面的启动联动链路，而静态检查本身又不足以覆盖风险，可以把这条已记录联动链路作为 runtime verification guidance 返回；但命令集仍应尽量最小。
- 输出自然语言文本。
