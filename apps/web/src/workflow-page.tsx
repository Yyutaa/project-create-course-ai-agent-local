import { workflowSteps } from "./workflow-steps";

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
