import { useState } from "react";
import { CourseInput } from "./api";

const DEFAULT_SOURCE_POLICY = "允许使用用户资料与公开官方资料";

const sourcePolicies = [
  {
    value: "允许使用用户资料与公开官方资料",
    label: "用户资料 + 官方资料",
    description: "优先使用你提供的材料，并允许官方文档、标准和论文补足事实。",
  },
  {
    value: "仅限使用内部提供材料",
    label: "仅内部资料",
    description: "不从公开网络补充知识；证据不足时缩小断言或暂停确认。",
  },
  {
    value: "仅允许使用公开官方资料",
    label: "仅公开官方资料",
    description: "只使用官方文档、标准、论文及权威机构的一手材料。",
  },
  {
    value: "允许使用用户资料、公开官方资料与经交叉核验的高质量社区资料",
    label: "扩展资料并交叉核验",
    description: "社区材料可用于案例和经验，关键事实仍需官方或一手来源确认。",
  },
];

export function NewCourseForm({ onStart, creationAction }: {
  onStart: (input: CourseInput) => void;
  creationAction: { disabled: boolean; label: string };
}) {
  const [input, setInput] = useState<CourseInput>({
    topic: "",
    audience: "",
    goal: "",
    language: "zh",
    source_policy: DEFAULT_SOURCE_POLICY,
    expected_chapters: 12,
    min_effective_chars: 12000,
    token_limit: null,
  });
  const [tokenLimitDraft, setTokenLimitDraft] = useState(100000);

  return (
<form className="course-form" onSubmit={(event) => { event.preventDefault(); onStart(input); }}>
          <section className="form-section">
            <div className="form-section-copy">
              <span>01</span>
              <h2>课程意图</h2>
              <p>告诉 Agent 要为谁解决什么学习问题。</p>
            </div>
            <div className="form-section-fields">
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
            </div>
          </section>
          <section className="form-section">
            <div className="form-section-copy">
              <span>02</span>
              <h2>生成约束</h2>
              <p>章节数用于规划参考，不会硬性平均分配；有效字符会去除 Markdown、HTML 和空白。</p>
            </div>
            <div className="form-section-fields">
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
                <div className="source-policy-field">
                  <span>来源政策</span>
                  <div className="source-policy-grid" role="radiogroup" aria-label="来源政策">
                    {sourcePolicies.map((policy) => (
                      <label className={`source-policy ${input.source_policy === policy.value ? "selected" : ""}`} key={policy.value}>
                        <input type="radio" name="source-policy" value={policy.value}
                          checked={input.source_policy === policy.value}
                          onChange={() => setInput({ ...input, source_policy: policy.value })} />
                        <span><strong>{policy.label}</strong><small>{policy.description}</small></span>
                      </label>
                    ))}
                  </div>
                  <small>当前为约束口径，V0 不执行联网检索；政策决定模型可用的事实来源边界。</small>
                </div>
              </fieldset>
            </div>
          </section>
          <div className="form-submit">
            <p><strong>输出语言</strong><br />中文 · 课程创建后立即进入七阶段工作流</p>
            <button className="primary-action" type="submit" disabled={creationAction.disabled}>
              <span aria-hidden="true">✦</span>{creationAction.label}
            </button>
          </div>
        </form>
  );
}
