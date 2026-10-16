import { CourseInput, StageRecord } from "./api";

export function IntakeStageDetail({ intake, status, loading, error }: {
  intake?: CourseInput;
  status: StageRecord["status"];
  loading: boolean;
  error: boolean;
}) {
  const submitted = status !== "pending";
  return (
    <section className="stage-detail intake-detail" id="stage-detail"
      aria-label="课程需求输入与提交记录">
      <div className="stage-detail-grid">
        <div className="intake-input">
          <p className="eyebrow">USER INPUT</p>
          <h2>课程需求</h2>
          <p>课程名称、目标受众、学习目标、来源政策和生成约束</p>
          <p className="intake-input-status">
            {submitted ? "✓ 本节点输入已处理" : "等待课程需求受理"}
          </p>
        </div>
        <div className="intake-history">
          <p className="eyebrow">SUBMISSION · HISTORY</p>
          <div className="intake-timeline">
            <span className="intake-timeline-dot" aria-hidden="true" />
            <article className="intake-record">
              <span className="intake-record-badge">本次创建输入</span>
              <h2>{submitted ? "课程需求已提交" : "课程需求待提交"}</h2>
              <p>以下信息来自本次新建课程表单，保存在本地课程工作区。</p>
              {loading && <p>正在读取课程需求…</p>}
              {error && <p role="alert">课程需求读取失败，请刷新后重试。</p>}
              {intake && <>
                <div className="intake-metrics">
                  <span><small>期望章节数</small><strong>{intake.expected_chapters}</strong></span>
                  <span><small>单章有效字符下限</small><strong>{intake.min_effective_chars}</strong></span>
                  <span><small>Token 阈值</small><strong>{intake.token_limit ?? "不限制"}</strong></span>
                </div>
                <dl className="intake-facts">
                  <div><dt>课程</dt><dd>{intake.topic}</dd></div>
                  <div><dt>目标受众</dt><dd>{intake.audience}</dd></div>
                  <div><dt>学习目标</dt><dd>{intake.goal}</dd></div>
                  <div><dt>来源政策</dt><dd>{intake.source_policy}</dd></div>
                </dl>
                <details className="intake-raw">
                  <summary>查看完整创建输入</summary>
                  <pre>{JSON.stringify(intake, null, 2)}</pre>
                </details>
              </>}
            </article>
          </div>
        </div>
      </div>
    </section>
  );
}
