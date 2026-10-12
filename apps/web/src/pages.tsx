import { FormEvent, useEffect, useRef, useState } from "react";
import { Link, Navigate, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError, Course, CourseInput, CourseProgress, Health, LlmConfigStatus } from "./api";
import { clearPendingKey, pendingKey } from "./idempotency";
import {
  artifactHandoffLabel,
  batchProgressLabel,
  budgetTokenLabel,
  canResumeRun,
  canStartRun,
  canDecideRelease,
  canReviewMission,
  courseCreationAction,
  courseProgressLabel,
  continuityLedgerLabels,
  generationConstraintLabels,
  pollInterval,
  qualityGateLabels,
  reviewFindingLabel,
  runPath,
} from "./run-view";


const workflowSteps = [
  ["intake", "接收并校验课程意图"],
  ["mission", "形成可审阅的任务定义"],
  ["blueprint", "规划课程结构与学习路径"],
  ["batch_plan", "安排可控的生成批次"],
  ["generation", "生成候选课程内容"],
  ["quality", "形成质量证据与修复结论"],
  ["release", "由人做出发布决定"],
];


export function CoursesPage() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [drafts, setDrafts] = useState<CourseProgress[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draftsError, setDraftsError] = useState<string | null>(null);

  useEffect(() => {
    void Promise.all([api.health(), api.courses()])
      .then(([healthResponse, coursesResponse]) => {
        setHealth(healthResponse);
        setCourses(coursesResponse.items);
      })
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "无法读取课程信息");
      });
    void api.courseFacts()
      .then((response) => setDrafts(response.items))
      .catch((reason: unknown) => {
        setDraftsError(reason instanceof Error ? reason.message : "无法读取我的课程");
      });
  }, []);

  return (
    <>
      <section className="dashboard-heading">
        <div>
          <h1>课程不是一次生成，而是一条可以恢复的生产线</h1>
          <p>每门课程都会进入独立工作台，可审阅章节、查看质量证据，或启动新的课程 Agent Run。</p>
        </div>
        <Link className="primary-button" to="/new"><span aria-hidden="true">✦</span>创建课程</Link>
      </section>

      {error && <p className="notice error">{error}</p>}
      {!error && !health && <p className="notice">正在连接本地课程服务。</p>}
      {health && <p className="connection-note"><span />本地服务已连接</p>}

      <section aria-label="我的课程" className="course-section">
        <div className="section-heading">
          <div><p className="eyebrow">Workspace</p><h2>我的课程</h2></div>
          <span>{drafts.length} 门草稿</span>
        </div>
        {draftsError && <p className="notice error">无法读取我的课程：{draftsError}</p>}
        <div className="course-grid">
          {drafts.map((course) => (
            <Link className="course-card" key={course.id} to={runPath(course.run_id)}>
              <div className="card-meta"><span className="status-pill">工作区</span><span>7 阶段</span></div>
              <h2>{course.title}</h2>
              <p>课程正在本地生成，可随时回到工作台继续处理。</p>
              <div className="course-metrics">
                <span>▱ {courseProgressLabel(course)}</span>
                <span>♢ 持久化运行记录</span>
              </div>
              <span className="course-link">打开课程工作台 <b aria-hidden="true">›</b></span>
            </Link>
          ))}
          {!draftsError && drafts.length === 0 && <div className="empty-card">
            <p className="eyebrow">No courses yet</p>
            <h2>从第一门课程开始</h2>
            <p>定义主题、受众和生成约束，创建后会自动进入 Run 工作台。</p>
            <Link className="text-link" to="/new">创建课程 →</Link>
          </div>}
        </div>
      </section>

      {courses.length > 0 && <section className="course-section" aria-label="示例课程">
        <div className="section-heading">
          <div><p className="eyebrow">Library</p><h2>已发布示例</h2></div>
          <span>{courses.length} 门课程</span>
        </div>
        <div className="course-grid">
          {courses.map((course) => <CourseCard key={course.slug} course={course} />)}
        </div>
      </section>}
    </>
  );
}


function CourseCard({ course }: { course: Course }) {
  return (
    <article className="course-card">
      <div className="card-meta">
        <span className="status-pill published">{course.status}</span>
        <span>{course.chapters} 章</span>
      </div>
      <h2>{course.title}</h2>
      <p>{course.description}</p>
      <div className="course-metrics">
        <span>▱ {course.chapters} 个 Markdown 章节</span>
        <span>♢ {course.duration}</span>
      </div>
      <a className="course-link" href={course.href}>
        打开课程工作台 <b aria-hidden="true">›</b>
      </a>
    </article>
  );
}


export function WorkflowPage() {
  return (
    <section className="workflow-page">
      <p className="eyebrow">Product contract</p>
      <h1>七阶段课程生产工作流</h1>
      <p>七步 V0 已可运行；Run 事实存入 SQLite，release 仍需人工决定。</p>
      <ol className="workflow-list">
        {workflowSteps.map(([id, description], index) => (
          <li key={id}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            <div>
              <strong>{id}</strong>
              <p>{description}</p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}


function LlmConfigDialog({ status, onClose, onUpdated }: {
  status?: LlmConfigStatus;
  onClose: () => void;
  onUpdated: (next: LlmConfigStatus) => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [model, setModel] = useState<LlmConfigStatus["model"]>(status?.model ?? "deepseek-flash");
  const [apiKey, setApiKey] = useState("");
  const saveMutation = useMutation({
    mutationFn: () => api.saveLlmConfig(model, apiKey.trim() || undefined),
    onSuccess: (next) => { onUpdated(next); onClose(); },
  });
  const clearMutation = useMutation({
    mutationFn: api.clearLlmConfig,
    onSuccess: (next) => { onUpdated(next); onClose(); },
  });
  useEffect(() => {
    dialogRef.current?.showModal();
  }, []);
  const busy = saveMutation.isPending || clearMutation.isPending;
  const error = saveMutation.error || clearMutation.error;

  return (
    <dialog ref={dialogRef} className="config-dialog" onClose={onClose} aria-labelledby="config-title">
      <form onSubmit={(event) => { event.preventDefault(); saveMutation.mutate(); }}>
        <h2 id="config-title">配置 DeepSeek</h2>
        <p>API Key 仅保存在当前电脑的系统凭据库。保存不验证额度或网络连接。</p>
        <label>模型
          <select value={model} onChange={(event) => setModel(event.target.value as LlmConfigStatus["model"])}>
            <option value="deepseek-flash">deepseek-flash</option>
            <option value="deepseek-v4-pro">deepseek-v4-pro</option>
          </select>
        </label>
        <label>API Key {status?.configured ? "（留空则保留原 Key）" : ""}
          <input type="password" autoComplete="new-password" value={apiKey}
            required={!status?.configured} maxLength={4096}
            onChange={(event) => setApiKey(event.target.value)} />
        </label>
        <p className="config-hint">修改或清除配置只影响后续模型调用；正在运行的 Run 可能跨配置。</p>
        {error && <p className="notice error" role="alert">{error.message}</p>}
        <div className="config-actions">
          <button type="submit" disabled={busy}>保存配置</button>
          {(status?.configured || status?.error) && <button type="button" disabled={busy}
            className="secondary" onClick={() => clearMutation.mutate()}>清除配置</button>}
          <button type="button" className="secondary" disabled={busy}
            onClick={() => dialogRef.current?.close()}>取消</button>
        </div>
      </form>
    </dialog>
  );
}


export function NewCoursePage() {
  const [searchParams] = useSearchParams();
  const legacyRunId = searchParams.get("run");
  return legacyRunId ? <Navigate to={runPath(legacyRunId)} replace />
    : <CourseWorkflowPage openConfig={searchParams.get("config") === "open"} />;
}


export function RunPage() {
  const { id } = useParams();
  return <CourseWorkflowPage runId={id} />;
}


function CourseWorkflowPage({ runId, openConfig = false }: { runId?: string; openConfig?: boolean }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [configOpen, setConfigOpen] = useState(openConfig);
  const configQuery = useQuery({ queryKey: ["llm-config"], queryFn: api.getLlmConfig });
  useEffect(() => {
    if (openConfig) setConfigOpen(true);
  }, [openConfig]);
  const [input, setInput] = useState<CourseInput>({
    topic: "",
    audience: "",
    goal: "",
    language: "zh",
    expected_chapters: 12,
    min_effective_chars: 12000,
    token_limit: null,
  });
  const [tokenLimitDraft, setTokenLimitDraft] = useState(100000);
  const [reason, setReason] = useState("");
  const [revisionText, setRevisionText] = useState("");
  const [missionFeedback, setMissionFeedback] = useState("");
  const runQuery = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.run(runId!),
    enabled: Boolean(runId),
    refetchInterval: (query) => pollInterval(query.state.data),
  });
  const run = runQuery.data;
  const contentQuery = useQuery({
    queryKey: ["run-content", runId],
    queryFn: () => api.runContent(runId!),
    enabled: Boolean(runId),
    refetchInterval: run?.status === "running" ? 1000 : false,
  });
  const executionQuery = useQuery({
    queryKey: ["execution", runId],
    queryFn: () => api.execution(runId!),
    enabled: Boolean(runId),
    refetchInterval: (query) => {
      if (query.state.data?.commands.some((command) =>
        command.status === "ACCEPTED" || command.status === "CLAIMED"
      )) return 1000;
      return pollInterval(run);
    },
  });
  const evidenceQuery = useQuery({
    queryKey: ["evidence", runId],
    queryFn: () => api.evidence(runId!),
    enabled: Boolean(runId),
    refetchInterval: run?.status === "running" ? 5000 : false,
  });
  const executionSignature = executionQuery.data
    ? `${executionQuery.data.checkpoint?.id ?? ""}:${executionQuery.data.commands.map((command) => `${command.id}:${command.status}`).join(",")}`
    : "";
  useEffect(() => {
    if (runId && executionSignature) {
      void queryClient.invalidateQueries({ queryKey: ["run", runId] });
    }
  }, [runId, executionSignature, queryClient]);
  const startMutation = useMutation({
    mutationFn: ({ course, key }: { course: CourseInput; key: string }) => api.startRun(course, key),
    onSuccess: (created) => {
      clearPendingKey(sessionStorage, "start");
      queryClient.setQueryData(["run", created.id], created);
      navigate(runPath(created.id));
      void queryClient.invalidateQueries({ queryKey: ["courses"] });
    },
    onError: (failure) => {
      if (failure instanceof ApiError && failure.code === "llm_config_required") {
        queryClient.setQueryData<LlmConfigStatus>(["llm-config"], (previous) => ({
          provider: "deepseek", model: previous?.model ?? "deepseek-flash",
          configured: false, error: "key_missing",
        }));
        setConfigOpen(true);
        void queryClient.invalidateQueries({ queryKey: ["llm-config"] });
      }
    },
  });
  const releaseMutation = useMutation({
    mutationFn: ({ id, action, reason, key }: {
      id: string; action: "prepare" | "stop"; reason: string; key: string;
    }) => api.decideRelease(id, action, reason, key),
    onSuccess: (decided) => {
      clearPendingKey(sessionStorage, `release:${decided.id}`);
      queryClient.setQueryData(["run", decided.id], decided);
      void queryClient.invalidateQueries({ queryKey: ["snapshot", decided.id] });
    },
  });
  const controlMutation = useMutation({
    mutationFn: async (kind: "STOP" | "RESUME" | "REVISE") => {
      if (!runId) throw new Error("Run 不存在");
      const body = kind === "REVISE" ? `${revisionText}:${executionQuery.data?.checkpoint?.id}` : kind;
      const key = pendingKey(sessionStorage, `${kind}:${runId}`, body);
      if (kind === "STOP") return api.stopRun(runId, key);
      if (kind === "RESUME") return api.resumeRun(runId, key);
      const checkpoint = executionQuery.data?.checkpoint?.id;
      if (!checkpoint) throw new Error("缺少可修订的 checkpoint");
      return api.reviseRun(runId, revisionText.trim(), checkpoint, key);
    },
    onSuccess: (command) => {
      clearPendingKey(sessionStorage, `${command.kind}:${command.run_id}`);
      void queryClient.invalidateQueries({ queryKey: ["execution", command.run_id] });
    },
  });
  const budgetMutation = useMutation({
    mutationFn: async () => {
      if (!runId || !executionQuery.data?.checkpoint) throw new Error("缺少预算审批 checkpoint");
      const nextLimit = executionQuery.data.budget.limit + 20;
      const checkpoint = executionQuery.data.checkpoint.id;
      const key = pendingKey(sessionStorage, `budget:${runId}`, `${checkpoint}:${nextLimit}`);
      return api.reviseRun(runId, "人工批准追加 20 次模型调用", checkpoint, key, nextLimit);
    },
    onSuccess: (command) => {
      clearPendingKey(sessionStorage, `budget:${command.run_id}`);
      void queryClient.invalidateQueries({ queryKey: ["execution", command.run_id] });
    },
  });
  const missionReviewMutation = useMutation({
    mutationFn: async (action: "approve" | "revise") => {
      const review = executionQuery.data?.mission_review;
      const checkpoint = executionQuery.data?.checkpoint?.id;
      if (!runId || !run || !canReviewMission(run, executionQuery.data) || !review || !checkpoint) {
        throw new Error("Mission 审批状态已变化，请刷新后重试");
      }
      const feedback = action === "revise" ? missionFeedback.trim() : undefined;
      if (action === "revise" && !feedback) throw new Error("请填写修改意见");
      const digest = feedback
        ? await crypto.subtle.digest("SHA-256", new TextEncoder().encode(feedback))
        : null;
      const fingerprint = digest
        ? Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("")
        : "";
      const slot = `mission-review:${runId}`;
      const key = pendingKey(sessionStorage, slot,
        JSON.stringify({ action, ref: review.mission_ref, checkpoint, fingerprint }));
      return api.reviewMission(runId, action, review.mission_ref, checkpoint, feedback, key);
    },
    onSuccess: (command) => {
      clearPendingKey(sessionStorage, `mission-review:${command.run_id}`);
      void queryClient.invalidateQueries({ queryKey: ["execution", command.run_id] });
      void queryClient.invalidateQueries({ queryKey: ["run", command.run_id] });
      void queryClient.invalidateQueries({ queryKey: ["snapshot", command.run_id] });
      void queryClient.invalidateQueries({ queryKey: ["evidence", command.run_id] });
    },
  });
  const busy = startMutation.isPending || releaseMutation.isPending || controlMutation.isPending || budgetMutation.isPending || missionReviewMutation.isPending;
  const error = startMutation.error || releaseMutation.error || controlMutation.error || budgetMutation.error || missionReviewMutation.error || runQuery.error || contentQuery.error || executionQuery.error || evidenceQuery.error;
  const chapterDeviation = run?.stages.some(
    (stage) => stage.failure_reason === "blueprint_chapter_deviation",
  ) ?? false;
  const tokenTerminated = run?.stages.some(
    (stage) => stage.failure_reason === "token_limit_reached",
  ) || executionQuery.data?.budget.token_exhausted;
  const lengthFinding = run?.quality?.evidence_findings?.find(
    (finding) => finding.rule_id === "lesson.effective_chars.minimum",
  );
  const creationAction = courseCreationAction(configQuery.data, busy);

  function start(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canStartRun(configQuery.data)) {
      setConfigOpen(true);
      return;
    }
    const key = pendingKey(sessionStorage, "start", JSON.stringify(input));
    startMutation.mutate({ course: input, key });
  }

  function decide(action: "prepare" | "stop") {
    if (!run || !reason.trim()) return;
    const key = pendingKey(
      sessionStorage, `release:${run.id}`, JSON.stringify({ action, reason: reason.trim() }),
    );
    releaseMutation.mutate({ id: run.id, action, reason: reason.trim(), key });
  }

  return (
    <div className="run-page">
      <section className="page-intro">
        <p className="eyebrow">{runId ? "Course workspace" : "New course"}</p>
        <h1>{runId ? contentQuery.data?.title ?? "课程详情" : "新建课程"}</h1>
        <p>{runId ? "在同一个工作台中审阅课程草稿、执行状态和人工决策。" : "先定义课程意图与生成边界，再启动可暂停、可恢复的七阶段 Run。"}</p>
        <button className="config-inline" type="button" disabled={configQuery.isPending}
          onClick={() => setConfigOpen(true)}>
          <span className={`status-dot ${configQuery.data?.configured ? "ready" : ""}`} />
          DeepSeek · {configQuery.isPending ? "读取中" : configQuery.data?.configured
            ? `${configQuery.data.model} 已配置` : "需要配置"}
        </button>
        {configQuery.data?.error && <p className="notice error">配置不可用，请重新保存或清除配置。</p>}
        {configQuery.isError && <p className="notice error">无法读取本机配置：{configQuery.error.message}</p>}
      </section>

      {configOpen && <LlmConfigDialog
        status={configQuery.data}
        onClose={() => setConfigOpen(false)}
        onUpdated={(next) => queryClient.setQueryData(["llm-config"], next)}
      />}

      {!runId && (
        <form className="course-form" onSubmit={start}>
          <div className="form-section-heading"><span>01</span><div><h2>课程意图</h2><p>告诉 Agent 要为谁解决什么学习问题。</p></div></div>
          <div className="form-grid">
            <label>课程主题
              <input required placeholder="例如：用 FastAPI 构建生产级 API"
                value={input.topic} onChange={(event) => setInput({ ...input, topic: event.target.value })} />
            </label>
            <label>目标受众
              <input required placeholder="例如：具备 Python 基础的后端开发者"
                value={input.audience} onChange={(event) => setInput({ ...input, audience: event.target.value })} />
            </label>
          </div>
          <label>学习目标
            <textarea required placeholder="描述完成课程后，学习者能够独立完成什么。"
              value={input.goal} onChange={(event) => setInput({ ...input, goal: event.target.value })} />
          </label>
          <div className="form-section-heading">
            <span>02</span>
            <div>
              <h2>生成约束</h2>
              <p>章节数用于规划参考，不会硬性平均分配；有效字符会去除 Markdown、HTML 和空白。</p>
            </div>
          </div>
          <fieldset className="generation-constraints">
            <legend className="visually-hidden">生成约束</legend>
            <div className="constraint-grid">
              <label>期望章节数
                <input type="number" required min={1} max={100}
                  value={input.expected_chapters}
                  onChange={(event) => setInput({
                    ...input, expected_chapters: event.target.valueAsNumber,
                  })} />
                <small>允许 ±1 章偏差；超出后等待人工确认。</small>
              </label>
              <label>单章有效字符数下限
                <input type="number" required min={1}
                  value={input.min_effective_chars}
                  onChange={(event) => setInput({
                    ...input, min_effective_chars: event.target.valueAsNumber,
                  })} />
              </label>
            </div>
            <div className="token-choice">
              <span>Token 阈值</span>
              <label><input type="radio" name="token-limit" checked={input.token_limit === null}
                onChange={() => setInput({ ...input, token_limit: null })} /> 不限制</label>
              <label><input type="radio" name="token-limit" checked={input.token_limit !== null}
                onChange={() => setInput({ ...input, token_limit: tokenLimitDraft })} /> 设置阈值</label>
            </div>
            {input.token_limit !== null && <label>Token 阈值
              <input type="number" required min={1} value={tokenLimitDraft}
                onChange={(event) => {
                  const value = event.target.valueAsNumber;
                  setTokenLimitDraft(value);
                  setInput({ ...input, token_limit: value });
                }} />
              <small>达到阈值后允许当前节点提交，并在下一节点前终止。</small>
            </label>}
          </fieldset>
          <div className="form-submit">
            <p><strong>输出语言</strong><br />中文 · 课程创建后立即进入七阶段工作流</p>
            <button className="primary-action" type="submit" disabled={creationAction.disabled}>
              <span aria-hidden="true">✦</span>{creationAction.label}
            </button>
          </div>
        </form>
      )}

      {error && <p className="notice error" role="alert">{error.message}</p>}
      {runId && runQuery.isError && <button onClick={() => void runQuery.refetch()}>重试读取</button>}
      {runId && runQuery.isPending && <p className="notice">正在读取 Run。</p>}

      {runId && contentQuery.data && <section aria-label="课程内容" className="course-content">
        <h2>章节内容（草稿）</h2>
        {contentQuery.data.chapters.length === 0 && <p>蓝图尚未生成，章节内容待补充。</p>}
        {contentQuery.data.chapters.map((chapter, index) => (
          <article key={chapter.lesson_id ?? `${index}-${chapter.title}`} className="result-card">
            <h3>{index + 1}. {chapter.title}</h3>
            {chapter.markdown ? <pre className="lesson-markdown">{chapter.markdown}</pre> : <p>待生成</p>}
          </article>
        ))}
      </section>}

      {run && (
        <>
          <section aria-live="polite" className="run-summary">
            <h2>运行摘要</h2>
            <p>Run ID：<code>{run.id}</code></p>
            <p>Course ID：<code>{run.course_id}</code>；事实修订：{run.revision}</p>
            <p>当前状态：{run.status}</p>
            {run.constraints_version === 1 ? <ul className="constraint-summary">
              {generationConstraintLabels(run.course_input).map((label) => (
                <li key={label}>{label}</li>
              ))}
            </ul> : <p>历史 Run：未启用生成约束。</p>}
          </section>
          <section className="result-card" aria-label="执行工作台">
            <h2>执行工作台</h2>
            <p>当前节点：{executionQuery.data?.current_node ?? "待领取"}；节点尝试：{executionQuery.data?.node_status ?? "未开始"}</p>
            <p>最后 checkpoint：{executionQuery.data?.checkpoint?.position ?? "无"}（{executionQuery.data?.checkpoint?.id ?? "无"}）</p>
            {executionQuery.data?.waiting_reason && <p>等待人工：{executionQuery.data.waiting_reason}</p>}
            {executionQuery.data?.budget && <p role={executionQuery.data.budget.warning ? "alert" : undefined}>
              模型调用：{executionQuery.data.budget.used}/{executionQuery.data.budget.limit}
              {executionQuery.data.budget.unknown > 0 ? `；${executionQuery.data.budget.unknown} 次结果未知` : ""}
              {executionQuery.data.budget.requires_human ? "；预算耗尽，需人工决定" : executionQuery.data.budget.warning ? "；接近上限" : ""}
            </p>}
            {executionQuery.data?.budget && <p role={executionQuery.data.budget.repair_exhausted ? "alert" : undefined}>
              质量返工：{executionQuery.data.budget.repair_used}/{executionQuery.data.budget.repair_limit}
              {executionQuery.data.budget.repair_exhausted ? "；已升级人工" : ""}
            </p>}
            {executionQuery.data?.budget && <p role={executionQuery.data.budget.token_exhausted ? "alert" : undefined}>
              {budgetTokenLabel(executionQuery.data.budget)}
            </p>}
            {lengthFinding && <p role="alert">
              单章有效字符不足：{lengthFinding.evidence}；{lengthFinding.expected}
            </p>}
            {chapterDeviation && run.blueprint && <p role="alert">
              章节数偏差：期望 {run.course_input.expected_chapters} 章，实际 {run.blueprint.lessons.length} 章。
            </p>}
            {tokenTerminated && <p role="alert">Token 阈值已终止本次 Run，不能继续或修订。</p>}
            <ul>
              {(executionQuery.data?.commands ?? []).map((command) => (
                <li key={command.id}>{command.kind} · {command.status}{command.error ? ` · ${command.error}` : ""}</li>
              ))}
            </ul>
            {run.status === "running" && <button disabled={busy} onClick={() => controlMutation.mutate("STOP")}>请求停止</button>}
            {canResumeRun(run, executionQuery.data) && (run.status === "stopped" || (run.status === "waiting_for_human" && !canDecideRelease(run)
              && executionQuery.data?.mission_review?.status !== "pending")) && executionQuery.data?.checkpoint && (
              <div>
                <label>人工修订说明
                  <textarea value={revisionText} onChange={(event) => setRevisionText(event.target.value)} />
                </label>
                <button disabled={busy || !revisionText.trim()} onClick={() => controlMutation.mutate("REVISE")}>提交修订</button>
                <button disabled={busy} onClick={() => controlMutation.mutate("RESUME")}>
                  {chapterDeviation ? "接受偏差并继续" : "继续执行"}
                </button>
              </div>
            )}
            {run.status === "waiting_for_human" && executionQuery.data?.budget.requires_human && executionQuery.data.checkpoint && (
              <button disabled={busy} onClick={() => budgetMutation.mutate()}>人工批准追加 20 次调用</button>
            )}
          </section>
          {evidenceQuery.data && <section className="result-card" aria-label="交付证据摘要">
            <h2>交付证据摘要</h2>
            <p>Trace ID：<code>{evidenceQuery.data.trace_id}</code></p>
            <p>节点尝试 {evidenceQuery.data.nodes.length}；模型调用 {evidenceQuery.data.provider_calls.length}；Artifact 版本 {evidenceQuery.data.artifacts.length}；Finding {evidenceQuery.data.findings.length}；独立验证记录 {evidenceQuery.data.verifications.length}</p>
            <ul>{evidenceQuery.data.paths.map((path) => <li key={path.scenario}>
              {path.scenario}：{path.status === "observed" ? "已有事实证据" : "本 Run 未观察到"}（{path.evidence_ids.length} 个关联）
            </li>)}</ul>
            {evidenceQuery.data.integrity_issues.length > 0 && <p role="alert">证据关联缺失 {evidenceQuery.data.integrity_issues.length} 处，需人工检查。</p>}
            <p>摘要不包含 Intake、Prompt 或正文原文；单次运行不代表生产保证。</p>
          </section>}
          <ol className="workflow-list run-stages" aria-label="七步运行状态">
            {run.stages.map((stage, index) => (
              <li key={stage.name}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <div>
                  <strong>{stage.name}</strong> <span className={`stage-state ${stage.status}`}>{stage.status}</span>
                  <p>{workflowSteps[index][1]}</p>
                  {stage.input_summary && <p>输入：{stage.input_summary}</p>}
                  {stage.output_summary && <p>输出：{stage.output_summary}</p>}
                  {stage.failure_reason && <p className="notice error">失败：{stage.failure_reason}</p>}
                </div>
              </li>
            ))}
          </ol>
          {run.artifacts.length > 0 && (
            <section className="result-card">
              <h2>Artifact 交接</h2>
              <ul>
                {run.artifacts.map((artifact) => (
                  <li key={`${artifact.artifact_id}:${artifact.version}`}>
                    {artifactHandoffLabel(artifact)}
                  </li>
                ))}
              </ul>
            </section>
          )}
          {run.mission && <section className="result-card">
            <h2>Mission</h2>
            <p>受众：{run.mission.audience}</p>
            <p>学习目标：{run.mission.learning_goal}</p>
            <p>范围：{run.mission.scope}</p>
            <p>停止条件：{run.mission.stop_conditions.join("；")}</p>
            {executionQuery.data?.mission_review && <p>
              当前版本：v{executionQuery.data.mission_review.mission_ref.version}；
              {executionQuery.data.mission_review.status === "pending" ? "待人工确认" : "已人工确认"}
            </p>}
            {canReviewMission(run, executionQuery.data) && <div>
              <p>请先确认任务定义，或提出具体修改意见。确认后才会进入 Blueprint。</p>
              <label>修改意见
                <textarea value={missionFeedback} maxLength={2000}
                  onChange={(event) => setMissionFeedback(event.target.value)} />
              </label>
              <div className="release-actions">
                <button disabled={busy} onClick={() => missionReviewMutation.mutate("approve")}>确认任务定义</button>
                <button disabled={busy || !missionFeedback.trim()} onClick={() => missionReviewMutation.mutate("revise")}>要求修改</button>
              </div>
            </div>}
          </section>}
          {run.blueprint && <section className="result-card"><h2>Blueprint</h2><p>{run.blueprint.lessons[0].title}：{run.blueprint.lessons[0].learning_goal}</p></section>}
          {run.batch_plan && <section className="result-card"><h2>Batch plan</h2><p>{batchProgressLabel(run.batch_plan)}</p>{(run.batch_plan.continuity_ledger?.length ?? 0) > 0 && <ul>{continuityLedgerLabels(run.batch_plan).map((label) => <li key={label}>{label}</li>)}</ul>}</section>}
          {run.quality && <section className="result-card"><h2>分层质量证据</h2><p>{run.quality.status}；语言风险：{run.quality.language_risk}</p><p>限制：{run.quality.limitations.join("；")}</p>{qualityGateLabels(run.quality).length > 0 && <ul>{qualityGateLabels(run.quality).map((label, index) => <li key={`${index}-${label}`}>{label}</li>)}</ul>}{run.quality.findings.length > 0 && <ul>{run.quality.findings.map((finding) => <li key={finding.code}>{reviewFindingLabel(finding)}</li>)}</ul>}</section>}
          {canDecideRelease(run) && (
            <section className="release-panel">
              <h2>人工 release 决定</h2>
              <p>“准备发布”只记录人工意向，不会自动发布课程。</p>
              <label>决定理由
                <textarea required value={reason} onChange={(event) => setReason(event.target.value)} />
              </label>
              <div className="release-actions">
                <button disabled={busy || !reason.trim()} onClick={() => decide("prepare")}>准备发布</button>
                <button disabled={busy || !reason.trim()} onClick={() => decide("stop")}>停止</button>
              </div>
            </section>
          )}
          {run.status === "ready_for_release" && <p className="notice">人工已选择准备发布；V0 尚未发布任何文件。</p>}
          {run.status === "stopped" && !tokenTerminated && <p className="notice">人工已停止本次运行。</p>}
        </>
      )}
    </div>
  );
}
