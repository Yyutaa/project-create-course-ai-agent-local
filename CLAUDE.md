# Claude Code 入口

本项目使用 Repo Guide。不要仅凭通用经验猜测仓库事实。

## 开始任何仓库任务前

1. 先读 `repo-profile.md`：稳定事实、命令、端口、运行拓扑、修改边界。
2. 再读 `AGENTS.md`：仓库规则、执行协议、安全边界、验收要求。
3. 工作流任务按需读取 `.agents/skills/repo-workflow-*/SKILL.md`。
4. 编码任务只读取与当前改动相关的 `.agents/skills/repo-coding-*/SKILL.md`。
5. 验证命令优先从 `repo-profile.md` 和 `AGENTS.md` 获取，不要猜。

## 重要边界

- `AGENTS.md` 与 `repo-profile.md` 是单一事实来源；不要在本文件复制或改写它们。
- `.agents/skills/` 是 Repo Guide 生成的技能文件；Claude Code 不会自动把它们注册为 Skill，需按路径读取。
- 修改代码前先确认当前分支、工作区状态和测试基线。
- 不把运行期扫描结果、diff 影响或验证结果写回 `AGENTS.md` / `repo-profile.md`。

## 快速入口

- 稳定事实：`repo-profile.md`
- 仓库规则：`AGENTS.md`
- 工作流 skills：`.agents/skills/repo-workflow-*`
- 编码规则 skills：`.agents/skills/repo-coding-*`
