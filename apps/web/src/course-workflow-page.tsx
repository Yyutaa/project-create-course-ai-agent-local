import { useEffect, useRef, useState } from "react";
import { Navigate, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, CourseInput, LlmConfigStatus, StageRecord } from "./api";
import { clearPendingKey, pendingKey } from "./idempotency";
import {
  budgetTokenLabel,
  canResumeRun, canStartRun, canDecideRelease, canPublish,
  canReviewMission, canReviewQuality, courseContentHeading, courseCreationAction,
  continuityLedgerLabels, pollInterval,
  runPath, shouldPoll, sourceReviewSummary, stageDisplayName,
} from "./run-view";
import { subscribeRun } from "./run-stream";
import { LlmConfigDialog } from "./llm-config-dialog";
import { NewCourseForm } from "./new-course-form";
import { activeStage, StageDetail, StageStepper } from "./stage-workbench";
import { RunEvents } from "./run-events";

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
  const [reason, setReason] = useState("");
  const [revisionText, setRevisionText] = useState("");
  const [missionFeedback, setMissionFeedback] = useState("");
  const [qualityReason, setQualityReason] = useState("");
  const [sourceReason, setSourceReason] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [sourceDecision, setSourceDecision] = useState<{
    action: "approve" | "reject"; id: string; metadataHash: string; url: string;
  } | null>(null);
  const sourceDecisionDialog = useRef<HTMLDialogElement>(null);
  const [motionPaused, setMotionPaused] = useState(false);
  const [streamConnected, setStreamConnected] = useState(false);
  const [selectedStage, setSelectedStage] = useState<StageRecord["name"] | null>(null);
  useEffect(() => setSelectedStage(null), [runId]);
  const runQuery = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.run(runId!),
    enabled: Boolean(runId),
    refetchInterval: (query) => pollInterval(query.state.data, streamConnected),
  });
  const run = runQuery.data;
  const displayedStage = run
    ? run.stages.find((stage) => stage.name === selectedStage) ?? activeStage(run)
    : null;
  const contentHeading = run ? courseContentHeading(displayedStage, run.status) : null;
  const contentQuery = useQuery({
    queryKey: ["run-content", runId],
    queryFn: () => api.runContent(runId!),
    enabled: Boolean(runId),
    refetchInterval: run?.status === "running" ? (streamConnected ? 30_000 : 1000) : false,
  });
  const intakeQuery = useQuery({
    queryKey: ["intake", runId],
    queryFn: () => api.intake(runId!),
    enabled: Boolean(runId),
    staleTime: Infinity,
  });
  const executionQuery = useQuery({
    queryKey: ["execution", runId],
    queryFn: () => api.execution(runId!),
    enabled: Boolean(runId),
    refetchInterval: (query) => {
      if (query.state.data?.commands.some((command) =>
        command.status === "ACCEPTED" || command.status === "CLAIMED"
      )) return streamConnected ? 30_000 : 1000;
      return pollInterval(run, streamConnected);
    },
  });
  const activeCommand = executionQuery.data?.commands.filter(
    (command) => command.status === "ACCEPTED" || command.status === "CLAIMED",
  ).at(-1);
  const agentExecuting = run?.status === "running"
    && activeCommand?.status === "CLAIMED"
    && executionQuery.data?.node_status === "STARTED";
  const activityLabel = run?.status !== "running" ? null
    : activeCommand?.status === "ACCEPTED" ? "等待 Worker 接管"
      : agentExecuting ? "Agent 正在执行当前节点"
        : activeCommand?.status === "CLAIMED" ? "Worker 正在处理" : "工作流运行中";
  const evidenceQuery = useQuery({
    queryKey: ["evidence", runId],
    queryFn: () => api.evidence(runId!),
    enabled: Boolean(runId),
    refetchInterval: run?.status === "running" ? (streamConnected ? 30_000 : 5000) : false,
  });
  const eventsQuery = useQuery({
    queryKey: ["events", runId],
    queryFn: () => api.events(runId!),
    enabled: Boolean(runId),
    refetchInterval: pollInterval(run, streamConnected),
  });
  const sourcesQuery = useQuery({
    queryKey: ["sources", runId],
    queryFn: () => api.sources(runId!),
    enabled: Boolean(runId && run?.source_evidence_version),
    refetchInterval: run?.status === "running" ? (streamConnected ? 30_000 : 5000) : false,
  });
  useEffect(() => {
    if (!runId || !run || !shouldPoll(run.status)) {
      setStreamConnected(false);
      return;
    }
    const refresh = () => {
      for (const key of ["run", "execution", "run-content", "evidence", "events", "sources"]) {
        void queryClient.invalidateQueries({ queryKey: [key, runId] });
      }
    };
    const close = subscribeRun(runId, refresh, setStreamConnected);
    return () => {
      close();
      setStreamConnected(false);
    };
  }, [runId, run?.status, queryClient]);
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
      void queryClient.invalidateQueries({ queryKey: ["events", decided.id] });
    },
  });
  const publishMutation = useMutation({
    mutationFn: async () => {
      if (!runId) throw new Error("Run 不存在");
      const key = pendingKey(sessionStorage, `publish:${runId}`, "publish");
      return api.publishRun(runId, key);
    },
    onSuccess: (published) => {
      clearPendingKey(sessionStorage, `publish:${published.id}`);
      queryClient.setQueryData(["run", published.id], published);
      void queryClient.invalidateQueries({ queryKey: ["execution", published.id] });
      void queryClient.invalidateQueries({ queryKey: ["courses"] });
      void queryClient.invalidateQueries({ queryKey: ["snapshot", published.id] });
      void queryClient.invalidateQueries({ queryKey: ["events", published.id] });
    },
  });
  const controlMutation = useMutation({
    mutationFn: async (kind: "STOP" | "RESUME" | "REVISE") => {
      if (!runId) throw new Error("Run 不存在");
      const body = kind === "REVISE" ? `${revisionText}:${executionQuery.data?.checkpoint?.id}` : kind;
      const key = pendingKey(sessionStorage, `${kind}:${runId}`, body);
      if (kind === "STOP") return api.stopRun(runId, key);
      if (kind === "RESUME") {
        const checkpoint = executionQuery.data?.checkpoint?.id;
        const blueprint = run?.artifacts.filter((item) => item.kind === "blueprint").at(-1);
        return api.resumeRun(runId, key, {
          ...(checkpoint ? { expected_checkpoint_id: checkpoint } : {}),
          ...(chapterDeviation && run?.planning_loop_version === 1 && blueprint
            ? { blueprint_ref: {
              run_id: runId, artifact_id: blueprint.artifact_id,
              version: blueprint.version, kind: "blueprint" as const,
              content_hash: blueprint.content_hash,
            } } : {}),
        });
      }
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
  const qualityReviewMutation = useMutation({
    mutationFn: async (action: "retry" | "accept") => {
      const review = executionQuery.data?.quality_review;
      if (!runId || !run || !canReviewQuality(run, executionQuery.data) || !review) {
        throw new Error("Quality 人工处理状态已变化，请刷新后重试");
      }
      if (action === "accept" && review.status === "retry_only") {
        throw new Error("Reviewer 输出格式失败只能重新检查，不能接受为质量通过");
      }
      const acceptedReason = action === "accept" ? qualityReason.trim() : undefined;
      if (action === "accept" && !acceptedReason) throw new Error("请填写风险接受说明");
      const digest = acceptedReason
        ? await crypto.subtle.digest("SHA-256", new TextEncoder().encode(acceptedReason))
        : null;
      const fingerprint = digest
        ? Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("")
        : "";
      const slot = `quality-review:${runId}`;
      const key = pendingKey(sessionStorage, slot, JSON.stringify({
        action,
        qualityRef: review.quality_ref,
        lessonRef: review.lesson_ref,
        checkpoint: review.checkpoint_id,
        fingerprint,
      }));
      return api.reviewQuality(
        runId, action, review.quality_ref, review.lesson_ref,
        review.checkpoint_id, acceptedReason, key,
      );
    },
    onSuccess: (command) => {
      clearPendingKey(sessionStorage, `quality-review:${command.run_id}`);
      setQualityReason("");
      void queryClient.invalidateQueries({ queryKey: ["execution", command.run_id] });
      void queryClient.invalidateQueries({ queryKey: ["run", command.run_id] });
      void queryClient.invalidateQueries({ queryKey: ["snapshot", command.run_id] });
      void queryClient.invalidateQueries({ queryKey: ["evidence", command.run_id] });
    },
  });
  const sourceReviewMutation = useMutation({
    mutationFn: async ({ action, candidateId, metadataHash }: {
      action: "approve" | "reject" | "propose_url" | "retry_search";
      candidateId?: string; metadataHash?: string;
    }) => {
      const review = executionQuery.data?.source_review;
      if (!runId || !review || review.checkpoint_id !== executionQuery.data?.checkpoint?.id) {
        throw new Error("来源复核状态已变化，请刷新后重试");
      }
      const reason = sourceReason.trim();
      if (action === "approve" && !reason) throw new Error("请填写官方归属的判断依据");
      const url = action === "propose_url" ? sourceUrl.trim() : undefined;
      if (action === "propose_url" && !url) throw new Error("请填写公开官方资料地址");
      const payload = {
        action, expected_checkpoint_id: review.checkpoint_id,
        ...(action === "approve" ? { reason } : {}),
        ...(url ? { url } : {}),
        ...(candidateId ? { candidate_id: candidateId, metadata_hash: metadataHash } : {}),
      };
      const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(
        JSON.stringify(payload),
      ));
      const fingerprint = Array.from(new Uint8Array(digest), (byte) =>
        byte.toString(16).padStart(2, "0")).join("");
      const slot = `source-review:${runId}`;
      const key = pendingKey(sessionStorage, slot, fingerprint);
      return api.reviewSource(runId, payload, key);
    },
    onSuccess: (command) => {
      clearPendingKey(sessionStorage, `source-review:${command.run_id}`);
      setSourceReason("");
      setSourceUrl("");
      for (const key of ["execution", "run", "snapshot", "evidence", "sources"]) {
        void queryClient.invalidateQueries({ queryKey: [key, command.run_id] });
      }
    },
  });
  const busy = startMutation.isPending || releaseMutation.isPending || publishMutation.isPending || controlMutation.isPending || budgetMutation.isPending || missionReviewMutation.isPending || qualityReviewMutation.isPending || sourceReviewMutation.isPending;
  const error = startMutation.error || releaseMutation.error || publishMutation.error || controlMutation.error || budgetMutation.error || missionReviewMutation.error || qualityReviewMutation.error || sourceReviewMutation.error || runQuery.error || contentQuery.error || executionQuery.error || evidenceQuery.error || sourcesQuery.error;
  const sourceReviewCompatible = Boolean(executionQuery.data?.source_review
    && Number.isInteger(executionQuery.data.source_review.hidden_candidate_count)
    && Number.isInteger(executionQuery.data.source_review.retry_remaining));
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

  function start(input: CourseInput) {
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

      {!runId && <NewCourseForm onStart={start} creationAction={creationAction} />}

      {error && <p className="notice error" role="alert">{error.message}</p>}
      {runId && runQuery.isError && <button onClick={() => void runQuery.refetch()}>重试读取</button>}
      {runId && runQuery.isPending && <p className="notice">正在读取 Run。</p>}

      {run && (
        <div className="run-layout">
          <div className="run-main">
            <StageStepper run={run} selectedStage={selectedStage}
              onSelect={setSelectedStage} streamConnected={streamConnected}
              agentExecuting={agentExecuting} motionPaused={motionPaused} />
            <div className="run-execution" aria-label="持久执行状态">
              <section aria-live="polite" className="run-summary">
            <h2>运行摘要</h2>
            <p>Run ID：<code>{run.id}</code></p>
            <p>Course ID：<code>{run.course_id}</code>；事实修订：{run.revision}</p>
            <p>当前状态：{run.status}</p>
          </section>
              <section className="result-card execution-card" aria-label="执行工作台">
            <div className="execution-heading">
              <h2>执行工作台</h2>
              <button type="button" className="motion-toggle" aria-pressed={motionPaused}
                onClick={() => setMotionPaused((paused) => !paused)}>
                {motionPaused ? "恢复动效" : "暂停动效"}
              </button>
            </div>
            {activityLabel && <p className={`execution-activity ${agentExecuting && !motionPaused ? "is-animated" : ""}`}
              role="status">
              <strong>{activityLabel}</strong>
              {agentExecuting && <span className="activity-dots" aria-hidden="true"><i /><i /><i /></span>}
            </p>}
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
              && executionQuery.data?.mission_review?.status !== "pending"
              && executionQuery.data?.quality_review?.status !== "pending"
              && !executionQuery.data?.source_review)) && executionQuery.data?.checkpoint && (
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
            </div>
            <section className="workspace-panel" aria-label="阶段工作区">
              <div className="workspace-body">
                <StageDetail run={run} selectedStage={selectedStage}
                  content={contentQuery.data} execution={executionQuery.data}
                  intake={intakeQuery.data} intakeLoading={intakeQuery.isPending}
                  intakeError={intakeQuery.isError} />
                {contentHeading && contentQuery.data &&
                  <details aria-label="课程内容" className="course-content" id="course-content">
                    <summary>{contentHeading}</summary>
                    {contentQuery.data.chapters.length === 0 &&
                      <p>蓝图尚未生成，章节内容待补充。</p>}
                    {contentQuery.data.chapters.map((chapter, index) => (
                      <article key={chapter.lesson_id ?? `${index}-${chapter.title}`}
                        className="result-card">
                        <h3>{index + 1}. {chapter.title}</h3>
                        {chapter.markdown
                          ? <pre className="lesson-markdown">{chapter.markdown}</pre>
                          : <p>待生成</p>}
                      </article>
                    ))}
                  </details>}
          {displayedStage?.name === "mission" && canReviewMission(run, executionQuery.data) &&
            <section className="result-card">
              <p>请先确认任务定义，或提出具体修改意见。确认后才会进入 Blueprint。</p>
              <label>修改意见
                <textarea value={missionFeedback} maxLength={2000}
                  onChange={(event) => setMissionFeedback(event.target.value)} />
              </label>
              <div className="release-actions">
                <button disabled={busy} onClick={() => missionReviewMutation.mutate("approve")}>确认任务定义</button>
                <button disabled={busy || !missionFeedback.trim()} onClick={() => missionReviewMutation.mutate("revise")}>要求修改</button>
              </div>
            </section>}
          {executionQuery.data?.source_review && !sourceReviewCompatible &&
            <section className="result-card" aria-label="来源人工复核">
              <h2>来源复核暂不可用</h2>
              <p role="alert">{sourceReviewSummary(executionQuery.data.source_review)}</p>
            </section>}
          {sourceReviewCompatible && executionQuery.data?.source_review && <section className="result-card source-review-panel" aria-label="来源人工复核">
            <div className="source-review-heading">
              <div>
                <span className="source-review-eyebrow">来源核验暂停</span>
                <h2>先让系统继续查找</h2>
                <p>目前没有足够的官方资料支撑课程。你无需逐条审核搜索结果。</p>
              </div>
              <span className="source-review-state">证据不足</span>
            </div>
            <p className="source-review-summary" role="status">
              {sourceReviewSummary(executionQuery.data.source_review)}
              {(sourcesQuery.data?.documents.length ?? 0) > 0 &&
                `；已有 ${sourcesQuery.data?.documents.length} 份来源文档`}
            </p>
            {sourcesQuery.isError && <p role="alert">来源记录读取失败，请刷新后重试。</p>}
            {executionQuery.data.source_review.retry_remaining > 0 ?
              <div className="source-review-primary">
                <button className="primary-action" disabled={busy}
                  onClick={() => sourceReviewMutation.mutate({ action: "retry_search" })}>
                  继续自动查找官方资料
                </button>
                <span>本 Run 还可重试 {executionQuery.data.source_review.retry_remaining} 次；仍受模型与工具预算约束。</span>
              </div>
              : <p className="source-review-limit">自动查找次数已用尽。若你知道官方文档地址，可在下方补充；否则保持暂停。</p>}
            {executionQuery.data.source_review.candidates.length > 0 && <div className="source-review-candidates">
              <h3>仍需你判断的来源</h3>
              <p>只确认网站的官方归属；课程中的具体事实会另行核验。</p>
              <div className="source-candidate-list">
                {executionQuery.data.source_review.candidates.map((candidate) =>
                  <article className="source-candidate" key={candidate.id}>
                    <div className="source-candidate-copy">
                      <span className="source-candidate-host">{new URL(candidate.url).hostname}</span>
                      <a href={candidate.url} target="_blank" rel="noopener noreferrer">
                        {candidate.title || candidate.url}
                      </a>
                    </div>
                    <div className="source-candidate-actions">
                      <button className="secondary" disabled={busy}
                        onClick={() => {
                          setSourceDecision({ action: "approve", id: candidate.id,
                            metadataHash: candidate.metadata_hash, url: candidate.url });
                          sourceDecisionDialog.current?.showModal();
                        }}>核对并确认</button>
                      <button className="source-reject-button" disabled={busy}
                        onClick={() => {
                          setSourceDecision({ action: "reject", id: candidate.id,
                            metadataHash: candidate.metadata_hash, url: candidate.url });
                          sourceDecisionDialog.current?.showModal();
                        }}>排除</button>
                    </div>
                  </article>) }
              </div>
            </div>}
            <details className="source-review-extra">
              <summary>我有官方文档地址</summary>
              <p>仅作为候选提交，系统不会直接把它当成已核验来源。</p>
              <label>公开官方资料地址
                <input type="url" value={sourceUrl} placeholder="https://官方文档站点/…"
                  onChange={(event) => setSourceUrl(event.target.value)} />
              </label>
              <button className="secondary" disabled={busy || !sourceUrl.trim()}
                onClick={() => sourceReviewMutation.mutate({ action: "propose_url" })}>添加候选地址</button>
            </details>
            {(sourcesQuery.data?.candidates.length ?? 0) > 0 &&
              <details className="source-review-extra source-review-diagnostics">
                <summary>查看全部检索记录（{sourcesQuery.data?.candidates.length}）</summary>
                <ul>{sourcesQuery.data?.candidates.map((candidate) =>
                  <li key={candidate.id}>
                    <a href={candidate.url} target="_blank" rel="noopener noreferrer">
                      {candidate.title || candidate.url}
                    </a>
                    <span>{candidate.status === "candidate" ? "仅为检索结果"
                      : candidate.status === "needs_human" ? "归属待判断"
                        : candidate.status === "rejected" ? "已排除" : "已处理"}</span>
                  </li>)}</ul>
              </details>}
            <dialog ref={sourceDecisionDialog} className="config-dialog"
              aria-labelledby="source-decision-title" onClose={() => setSourceDecision(null)}>
              <h3 id="source-decision-title">
                {sourceDecision?.action === "approve" ? "确认官方来源身份" : "拒绝来源候选"}
              </h3>
              <p>{sourceDecision?.url}</p>
              <p>{sourceDecision?.action === "approve"
                ? "这只确认该地址的官方归属，不会把课程事实自动标为已核验。"
                : "拒绝后，此候选不能再用于当前 Run 的来源核验。"}</p>
              {sourceDecision?.action === "approve" && <label>判断依据
                <textarea value={sourceReason} maxLength={2000} style={{ resize: "none" }}
                  onChange={(event) => setSourceReason(event.target.value)} />
              </label>}
              <div className="release-actions">
                <button onClick={() => sourceDecisionDialog.current?.close()}>取消</button>
                <button disabled={busy || !sourceDecision ||
                  (sourceDecision.action === "approve" && !sourceReason.trim())} onClick={() => {
                  if (!sourceDecision) return;
                  sourceReviewMutation.mutate({
                    action: sourceDecision.action, candidateId: sourceDecision.id,
                    metadataHash: sourceDecision.metadataHash,
                  });
                  sourceDecisionDialog.current?.close();
                }}>{sourceDecision?.action === "approve" ? "确认归属" : "确认拒绝"}</button>
              </div>
            </dialog>
          </section>}
          {displayedStage?.name === "batch_plan" && run.batch_plan &&
            (run.batch_plan.continuity_ledger?.length ?? 0) > 0 && <section className="result-card">
              <h2>批次衔接记录</h2>
              <ul>{continuityLedgerLabels(run.batch_plan).map((label) =>
                <li key={label}>{label}</li>)}</ul>
            </section>}
          {displayedStage?.name === "quality" && canReviewQuality(run, executionQuery.data)
            && executionQuery.data?.quality_review && <section className="result-card quality-review-panel">
              <h2>Quality 人工处理</h2>
              {executionQuery.data.quality_review.status === "retry_only"
                ? <p>Reviewer 输出格式校验失败。可显式重新检查当前章节；此前人工接受的风险不会被撤销。</p>
                : <p>当前证据：quality v{executionQuery.data.quality_review.quality_ref?.version}；
                    Lesson v{executionQuery.data.quality_review.lesson_ref.version}。</p>}
              <button disabled={busy} onClick={() => qualityReviewMutation.mutate("retry")}>
                重新检查
              </button>
              {executionQuery.data.quality_review.status === "pending" && <>
                <label>风险接受说明
                  <textarea value={qualityReason} onChange={(event) => setQualityReason(event.target.value)} />
                </label>
                <button disabled={busy || !qualityReason.trim()}
                  onClick={() => qualityReviewMutation.mutate("accept")}>接受风险并继续</button>
              </>}
            </section>}
          {displayedStage?.name === "release" && canDecideRelease(run) && (
            <section className="release-panel" id="release-actions">
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
          {displayedStage?.name === "release" && canPublish(run) && (
            <section className="release-panel" data-od-id="publish-panel">
              <h2>发布课程</h2>
              <p>课程已通过质量门禁。发布后会在「已发布」列表生成可访问的课程页面，并从「我的课程」移除。</p>
              <div className="release-actions">
                <button disabled={busy || publishMutation.isPending} onClick={() => publishMutation.mutate()}>
                  {publishMutation.isPending ? "正在发布…" : "发布课程"}
                </button>
              </div>
            </section>
          )}
          {displayedStage?.name === "release" && run.status === "published" && run.publication && (
            <p className="notice" data-od-id="published-notice">
              课程已发布：<a className="text-link" href={run.publication.href}>{run.publication.href}</a>
            </p>
          )}
                {displayedStage?.name === "quality" && displayedStage.status !== "pending" && evidenceQuery.data && <section className="result-card" aria-label="交付证据摘要" id="evidence">
            <h2>交付证据摘要</h2>
            <p>Trace ID：<code>{evidenceQuery.data.trace_id}</code></p>
            <p>节点尝试 {evidenceQuery.data.nodes.length}；模型调用 {evidenceQuery.data.provider_calls.length}；Artifact 版本 {evidenceQuery.data.artifacts.length}；Finding {evidenceQuery.data.findings.length}；独立验证记录 {evidenceQuery.data.verifications.length}</p>
            <ul>{evidenceQuery.data.paths.map((path) => <li key={path.scenario}>
              {path.scenario}：{path.status === "observed" ? "已有事实证据" : "本 Run 未观察到"}（{path.evidence_ids.length} 个关联）
            </li>)}</ul>
            {evidenceQuery.data.integrity_issues.length > 0 && <p role="alert">证据关联缺失 {evidenceQuery.data.integrity_issues.length} 处，需人工检查。</p>}
            <p>摘要不包含 Intake、Prompt 或正文原文；单次运行不代表生产保证。</p>
          </section>}
              </div>
            </section>
          </div>
          <RunEvents events={eventsQuery.data?.items ?? []}
            loading={eventsQuery.isPending} error={eventsQuery.isError}
            onSelectStage={setSelectedStage} />
        </div>
      )}
    </div>
  );
}
