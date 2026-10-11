# AI Course Studio（本地版）

AI Course Studio 是本地优先的 AI 课程生成工具。当前代码包含 React + Vite 前端、
FastAPI、SQLite 事实库、七阶段 Graph、独立 Worker 和人工审批；它不是公网多用户服务，
也不会自动发布课程。

本仓库不附带课程示例和历史实施资料；代码、测试、领域 Skill 与产品技术资料
保留在本仓库。

## 项目内容

- `apps/web/`：React + TypeScript + Vite，展示七步 Run、质量证据和只读执行工作台。
- `apps/api/`：FastAPI + 独立本地 Worker，提供 Command、Run、Artifact 与执行状态接口。
- `.agents/skills/`：课程生成与 API 开发使用的 `teach-generator`、`humanizer-zh` 和 `fastapi` 规则。
- `assets/aiagent/`：产品与前后端技术资料。

## 启动

前置条件：

- Node.js 20+
- Python 3.12

macOS 运行：

```bash
bash scripts/start-agent.sh
```

Windows PowerShell 运行：

```powershell
.\scripts\start-agent.ps1
```

首次启动会创建 `apps/api/.venv` 并安装缺失依赖；前端依赖缺失时会自动安装。
打开「新建课程」页面，点击「配置 DeepSeek」，选择模型并填写自己的 API Key。
Key 保存在当前操作系统账号的凭据库，SQLite 只保存模型等非敏感状态；刷新页面或
重启服务后无需重新填写。已有 `.env` 的 `COURSE_LLM_*` 不会自动导入，首次需要重填。
系统凭据库不可用时不会回退到明文文件。Fake Provider 只用于自动测试。

启动后访问：

- 前端：`http://127.0.0.1:5176`（固定端口；被占用时启动失败）
- API 文档：`http://127.0.0.1:8002/docs`（固定端口；被占用时启动失败）
- Worker：同一脚本启动的独立本地进程，没有 HTTP 端口。

API 的 Run 启动 POST 只持久受理 Command 并返回 202；Worker 在后台执行。
关闭浏览器或重启 API 不会转移执行权。`release` 仍由人决定，不自动发布。
保存或清除配置后无需重启 Worker，改动影响下一次模型调用；同一 Run 可能跨配置。
「保存成功」只表示本机安全存储完成，不证明 Key 有效、余额足够或 DeepSeek 可用。
启动脚本只监听本机回环地址，不要把本项目直接暴露到局域网或公网。

如果新 Run 提示「请配置 DeepSeek」，先查看页面配置状态；模型调用报 HTTP 失败时，
再检查 Key、模型、账户余额和网络。不要把 Key 或完整请求体贴进日志或工单。

## API 验证

```bash
curl http://127.0.0.1:8002/api/health
curl http://127.0.0.1:8002/api/courses
```

预期健康检查返回 `status: "ok"`，未附带示例课程时课程列表返回 `{"items": []}`。
新建 Run 后，「我的课程」会读取本机 SQLite 中的课程事实。

## 开发验证

```bash
apps/api/.venv/bin/python -m pytest apps/api/tests
npm --prefix apps/web run test:v0
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
```

## 当前边界

本阶段使用单机 SQLite Worker/lease/checkpoint，不包含云队列、分布式部署、
业务失败阶段的一键重试或自动发布。执行约束见 [AGENTS.md](AGENTS.md)。
