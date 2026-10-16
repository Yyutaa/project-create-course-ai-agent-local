import { CourseInput, ExecutionReadModel, RunContent, StageRecord, V0Run } from "./api";
import { artifactHandoffLabel, batchProgressLabel, qualityGateLabels, stageDisplayName } from "./run-view";
import { workflowSteps } from "./workflow-steps";
import { IntakeStageDetail } from "./intake-stage-detail";

export function activeStage(run: V0Run): StageRecord {
  return run.stages.find((stage) =>
    ["running", "waiting_for_human", "failed", "stopped"].includes(stage.status))
    ?? run.stages.find((stage) => stage.status === "pending")
    ?? [...run.stages].reverse().find((stage) => stage.status === "succeeded")
    ?? run.stages[0];
}

export function StageStepper({ run, selectedStage, onSelect, streamConnected }: {
  run: V0Run;
  selectedStage: StageRecord["name"] | null;
  onSelect: (stage: StageRecord["name"]) => void;
  streamConnected: boolean;
}) {
  const current = activeStage(run);
  const displayed = run.stages.find((stage) => stage.name === selectedStage) ?? current;
  return (
    <section className="stage-workbench" aria-label="七步运行状态">
      <div className="stage-heading">
        <div>
          <h2>每一步都能看见输入、输出和暂停原因</h2>
          <p>工作流结构由系统确定；模型负责课程判断与写作，用户保留方向和发布决定。</p>
        </div>
        <span aria-live="polite">{streamConnected ? "实时连接中" : "定时刷新中"}</span>
      </div>
      <ol className="stage-strip">
        {run.stages.map((stage, index) => (
          <li key={stage.name}>
            <button type="button"
              className={`stage-step ${stage.status} ${current.name === stage.name ? "current" : ""} ${displayed.name === stage.name ? "selected" : ""}`}
              aria-current={current.name === stage.name ? "step" : undefined}
              aria-pressed={displayed.name === stage.name}
              onClick={() => onSelect(stage.name)}>
              <span className="stage-number">{stage.status === "succeeded" ? "✓" : index + 1}</span>
              <span><strong>{stageDisplayName(stage.name)}</strong><small>{
                stage.status === "pending" && current.name === stage.name
                  ? "当前节点" : statusLabels[stage.status]
              }</small></span>
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}

const stageKinds: Record<StageRecord["name"], { input: string | null; output: string | null }> = {
  intake: { input: null, output: null },
  mission: { input: null, output: "mission" },
  blueprint: { input: "mission", output: "blueprint" },
  batch_plan: { input: "blueprint", output: "batch_plan" },
  generation: { input: "batch_plan", output: "lesson" },
  quality: { input: "lesson", output: "quality" },
  release: { input: "quality", output: null },
};

const statusLabels: Record<StageRecord["status"], string> = {
  pending: "未开始", running: "进行中", succeeded: "已完成",
  waiting_for_human: "等待人工", failed: "失败", stopped: "已停止",
};

export function StageDetail({ run, selectedStage, content, execution,
  intake, intakeLoading, intakeError }: {
  run: V0Run;
  selectedStage: StageRecord["name"] | null;
  content?: RunContent;
  execution?: ExecutionReadModel;
  intake?: CourseInput;
  intakeLoading: boolean;
  intakeError: boolean;
}) {
  const stage = run.stages.find((item) => item.name === selectedStage) ?? activeStage(run);
  if (stage.name === "intake") {
    return <IntakeStageDetail intake={intake} status={stage.status}
      loading={intakeLoading} error={intakeError} />;
  }
  const kinds = stageKinds[stage.name];
  const outputArtifacts = run.artifacts.filter((item) => item.kind === kinds.output);
  const inputRefs = outputArtifacts.at(-1)?.source_refs.filter(
    (item) => item.kind === kinds.input,
  ) ?? [];
  const notStarted = stage.status === "pending" && outputArtifacts.length === 0;
  return (
    <section className="stage-detail intake-detail" id="stage-detail" aria-label="阶段输入与输出">
      <div className="stage-detail-grid">
        <div className="intake-input">
          <p className="eyebrow">USER INPUT</p>
          <h2>{stageDisplayName(stage.name)}</h2>
          <p>{workflowSteps[run.stages.findIndex((item) => item.name === stage.name)][1]}</p>
          <p className={`stage-input-status ${stage.status}`}>
            {statusLabels[stage.status]}
          </p>
          {!notStarted && stage.name === "mission" && intake && <dl className="intake-facts">
            <div><dt>课程</dt><dd>{intake.topic}</dd></div>
            <div><dt>目标受众</dt><dd>{intake.audience}</dd></div>
            <div><dt>学习目标</dt><dd>{intake.goal}</dd></div>
            <div><dt>来源政策</dt><dd>{intake.source_policy}</dd></div>
          </dl>}
          {!notStarted && stage.name === "mission" && !intake && <p>{intakeError
            ? "课程需求读取失败" : "正在读取课程需求…"}</p>}
          {!notStarted && stage.name === "blueprint" && run.mission && <dl className="intake-facts">
            <div><dt>目标受众</dt><dd>{run.mission.audience}</dd></div>
            <div><dt>学习目标</dt><dd>{run.mission.learning_goal}</dd></div>
            <div><dt>范围</dt><dd>{run.mission.scope}</dd></div>
          </dl>}
          {!notStarted && stage.name === "batch_plan" && run.blueprint && <ol className="stage-list">
            {run.blueprint.lessons.map((lesson, index) =>
              <li key={lesson.lesson_id ?? index}>{lesson.title}</li>)}
          </ol>}
          {!notStarted && stage.name === "generation" && run.batch_plan && <p>{batchProgressLabel(run.batch_plan)}</p>}
          {!notStarted && stage.name === "quality" && content && <ol className="stage-list">
            {content.chapters.filter((chapter) => chapter.status === "generated")
              .map((chapter, index) => <li key={chapter.lesson_id ?? index}>
                {chapter.title} · v{chapter.version ?? 1}
              </li>)}
          </ol>}
          {!notStarted && stage.name === "release" && run.quality && <p>
            质量状态：{run.quality.status}；限制：{run.quality.limitations.join("；") || "无"}
          </p>}
          {!notStarted && stage.name !== "mission" && stage.name !== "release" && kinds.input &&
            <p className="stage-lineage">来源：{(inputRefs.length ? inputRefs
              : run.artifacts.filter((item) => item.kind === kinds.input))
              .map((item) => `${item.kind} v${item.version}`).join("、") || "等待前一步产物"}</p>}
          {stage.status === "waiting_for_human" && <p className="stage-pause" role="status">
            暂停原因：{stage.failure_reason || execution?.waiting_reason || "等待人工处理"}
          </p>}
        </div>
        <div className="intake-history">
          <p className="eyebrow">{stage.name === "release"
            ? "HUMAN DECISION · HISTORY" : "MODEL OUTPUT · HISTORY"}</p>
          <div className="intake-timeline">
            <span className="intake-timeline-dot" aria-hidden="true" />
            <article className="intake-record">
              <span className="intake-record-badge">{statusLabels[stage.status]}</span>
              <h2>{notStarted ? "该阶段尚未开始" : `${stageDisplayName(stage.name)}阶段记录`}</h2>
              {notStarted && <p>等待前序阶段完成。</p>}
          {!notStarted && stage.name === "mission" && run.mission && <dl className="intake-facts">
            <div><dt>目标受众</dt><dd>{run.mission.audience}</dd></div>
            <div><dt>学习目标</dt><dd>{run.mission.learning_goal}</dd></div>
            <div><dt>范围</dt><dd>{run.mission.scope}</dd></div>
            <div><dt>停止条件</dt><dd>{run.mission.stop_conditions.join("；")}</dd></div>
          </dl>}
          {!notStarted && stage.name === "mission" && execution?.mission_review && <p>
            Mission v{execution.mission_review.mission_ref.version} · {
              execution.mission_review.status === "pending" ? "待人工确认" : "已人工确认"}
          </p>}
          {!notStarted && stage.name === "blueprint" && run.blueprint && <ol className="stage-list">
            {run.blueprint.lessons.map((lesson, index) => <li key={lesson.lesson_id ?? index}>
              <strong>{lesson.title}</strong><p>学习目标：{lesson.learning_goal}</p>
              <p>验收证据：{lesson.evidence}</p>
            </li>)}
          </ol>}
          {!notStarted && stage.name === "batch_plan" && run.batch_plan && <ol className="stage-list">
            {run.batch_plan.batches.map((batch, index) => <li key={index}>
              批次 {index + 1}：第 {batch.map((chapter) => chapter + 1).join("、")} 章
            </li>)}
          </ol>}
          {!notStarted && stage.name === "generation" && content && <ol className="stage-list">
            {content.chapters.map((chapter, index) => <li key={chapter.lesson_id ?? index}>
              {chapter.title} · {chapter.status === "generated" ? `已生成 v${chapter.version ?? 1}` : "待生成"}
            </li>)}
          </ol>}
          {!notStarted && stage.name === "quality" && run.quality && <>
            <p>质量状态：{run.quality.status}；语言风险：{run.quality.language_risk}</p>
            <ul className="stage-list">{qualityGateLabels(run.quality).map((label, index) =>
              <li key={index}>{label}</li>)}</ul>
            {run.quality.findings.length > 0 && <ul className="stage-list">
              {run.quality.findings.map((finding, index) => <li key={`${finding.code}-${index}`}>
                {finding.severity}/{finding.category}：{finding.evidence}
              </li>)}
            </ul>}
          </>}
          {!notStarted && stage.name === "release" && <p>{run.status === "published"
            ? "已由人工发布" : run.status === "ready_for_release"
              ? "已准备，等待人工发布" : run.release_decision?.action === "stop"
                ? "人工决定停止" : "等待人工决定"}</p>}
          {outputArtifacts.length > 0 && <details className="stage-versions">
            <summary>产物版本（{outputArtifacts.length}）</summary>
            <ul>{outputArtifacts.map((item) => <li key={`${item.artifact_id}:${item.version}`}>
              {artifactHandoffLabel(item)} · hash {item.content_hash.slice(0, 12)}
            </li>)}</ul>
          </details>}
          {stage.failure_reason && stage.status !== "waiting_for_human" &&
            <p className="stage-pause">阶段原因：{stage.failure_reason}</p>}
            </article>
          </div>
        </div>
      </div>
    </section>
  );
}
