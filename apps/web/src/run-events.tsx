import { RunEvent, StageRecord } from "./api";
import { stageDisplayName } from "./run-view";

const eventLabels: Record<string, string> = {
  "stage.started": "阶段开始",
  "stage.succeeded": "阶段完成",
  "stage.failed": "阶段失败",
  "stage.waiting": "等待人工处理",
  "artifact.created": "产物已保存",
  "mission.approved": "任务定义已确认",
  "mission.revision_requested": "任务定义已要求修改",
  "quality.retry_requested": "质量重新检查",
  "quality.risk_accepted": "人工接受质量风险",
  "release.waiting": "等待发布决定",
  "release.decided": "人工提交发布决定",
  "release.published": "课程已发布",
  "run.stopped": "运行已停止",
  "run.resumed": "运行已继续",
  "budget.warning": "模型调用接近上限",
  "budget.exhausted": "模型调用预算耗尽",
  "budget.token_exhausted": "Token 阈值已达到",
};
const knownStages = new Set(["intake", "mission", "blueprint", "batch_plan", "generation", "quality", "release"]);

export function RunEvents({ events, loading, error, onSelectStage }: {
  events: RunEvent[];
  loading: boolean;
  error: boolean;
  onSelectStage: (stage: StageRecord["name"]) => void;
}) {
  return (
    <aside className="run-events" aria-label="运行记录" id="run-events">
      <p className="eyebrow">RUN EVENTS</p>
      <h2>运行记录</h2>
      <p>最近 40 条已保存事件</p>
      {loading && <p>正在读取运行记录…</p>}
      {error && <p role="alert">运行记录读取失败，请刷新重试。</p>}
      {!loading && !error && events.length === 0 && <p>暂无运行事件。</p>}
      <ol>
        {events.map((event) => {
          const stage = event.stage && knownStages.has(event.stage)
            ? event.stage as StageRecord["name"] : null;
          const label = eventLabels[event.type] ?? event.type;
          const time = new Date(event.created_at);
          return <li key={event.id}>
            <time dateTime={event.created_at}>
              {Number.isNaN(time.getTime()) ? "时间未知" : time.toLocaleString("zh-CN")}
            </time>
            <strong>{label}</strong>
            {stage && <button type="button" className="event-stage-link"
              onClick={() => {
                onSelectStage(stage);
                document.getElementById("stage-detail")?.scrollIntoView({ behavior: "smooth" });
              }}>{stageDisplayName(stage)}</button>}
          </li>;
        })}
      </ol>
    </aside>
  );
}
