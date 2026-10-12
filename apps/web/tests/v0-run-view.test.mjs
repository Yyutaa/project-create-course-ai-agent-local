import test from "node:test";
import assert from "node:assert/strict";

import {
  artifactHandoffLabel,
  batchProgressLabel,
  canStartRun,
  canDecideRelease,
  canReviewMission,
  canResumeRun,
  continuityLedgerLabels,
  budgetTokenLabel,
  generationConstraintLabels,
  preferNewerRun,
  reviewFindingLabel,
  qualityGateLabels,
  shouldPoll,
} from "../src/run-view.ts";
import { api } from "../src/api.ts";
import * as runView from "../src/run-view.ts";
import * as idempotency from "../src/idempotency.ts";


test("course progress names the current step and its state", () => {
  assert.equal(runView.courseProgressLabel?.({
    current_stage: "mission", stage_status: "waiting_for_human",
  }), "第 2/7 步 · mission · 等待人工");
  assert.equal(runView.courseProgressLabel?.({
    current_stage: "quality", stage_status: "failed",
  }), "第 6/7 步 · quality · 失败");
});


test("run content reader uses the run-specific endpoint", async () => {
  const originalFetch = globalThis.fetch;
  let path;
  globalThis.fetch = async (requested) => {
    path = requested;
    return new Response(JSON.stringify({
      run_id: "run-1", title: "第一门课", chapters: [],
    }), { status: 200 });
  };
  try {
    const content = await api.runContent?.("run-1");
    assert.equal(path, "/api/v0/runs/run-1/content");
    assert.equal(content.title, "第一门课");
  } finally {
    globalThis.fetch = originalFetch;
  }
});


test("a Run has its own URL rather than a new-course query", () => {
  assert.equal(runView.runPath?.("run/1"), "/run/run%2F1");
});


test("local DeepSeek config API returns status and never stores the key", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (path, init) => {
    calls.push({ path, init });
    return new Response(JSON.stringify({
      provider: "deepseek", model: "deepseek-flash", configured: true, error: null,
    }), { status: 200 });
  };
  try {
    await api.getLlmConfig();
    await api.saveLlmConfig("deepseek-flash", "KEY_904");
    await api.saveLlmConfig("deepseek-v4-pro");
    await api.clearLlmConfig();
    assert.deepEqual(calls.map((call) => [call.path, call.init?.method]), [
      ["/api/v0/llm-config", undefined], ["/api/v0/llm-config", "PUT"],
      ["/api/v0/llm-config", "PUT"], ["/api/v0/llm-config", "DELETE"],
    ]);
    assert.deepEqual(JSON.parse(calls[1].init.body), {
      model: "deepseek-flash", api_key: "KEY_904",
    });
    assert.deepEqual(JSON.parse(calls[2].init.body), { model: "deepseek-v4-pro" });
    assert.equal(calls[1].init.headers["Content-Type"], "application/json");
  } finally {
    globalThis.fetch = originalFetch;
  }
});


test("missing local config keeps a stable API error code", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({
    detail: { code: "llm_config_required", message: "请配置 DeepSeek" },
  }), { status: 409 });
  try {
    await assert.rejects(api.startRun({
      topic: "变量", audience: "初学者", goal: "学习", language: "zh",
    }, "start-1"), (error) => {
      assert.equal(error.code, "llm_config_required");
      assert.equal(error.message, "请配置 DeepSeek");
      return true;
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});


test("new Run stays gated until local config is ready", () => {
  assert.equal(canStartRun(undefined), false);
  assert.equal(canStartRun({ configured: false, error: "keyring_unavailable" }), false);
  assert.equal(canStartRun({ configured: true, error: null }), true);
});

test("generation constraints and token usage have stable readable labels", () => {
  assert.deepEqual(generationConstraintLabels({
    expected_chapters: 12,
    min_effective_chars: 12000,
    token_limit: null,
  }), [
    "期望章节：12（允许 ±1 章偏差）",
    "单章下限：12,000 有效字符",
    "Token 阈值：不限制",
  ]);
  assert.equal(budgetTokenLabel({
    tokens_used: 180,
    token_limit: 180,
    token_usage_unknown: 1,
    token_exhausted: true,
  }), "Token：180/180；1 次用量未知；已达阈值");
});

test("chapter deviation can resume but token termination cannot", () => {
  const waiting = {
    status: "waiting_for_human",
    stages: [{ failure_reason: "blueprint_chapter_deviation" }],
  };
  assert.equal(canResumeRun(waiting, { budget: { token_exhausted: false } }), true);
  assert.equal(canResumeRun({
    status: "stopped",
    stages: [{ failure_reason: "token_limit_reached" }],
  }, { budget: { token_exhausted: true } }), false);
});

test("new course payload includes explicit generation constraint defaults", async () => {
  const originalFetch = globalThis.fetch;
  let body;
  globalThis.fetch = async (_path, init) => {
    body = JSON.parse(init.body);
    return new Response(JSON.stringify({ id: "run-1" }), { status: 202 });
  };
  try {
    await api.startRun({
      topic: "变量",
      audience: "初学者",
      goal: "学习变量",
      language: "zh",
      expected_chapters: 12,
      min_effective_chars: 12000,
      token_limit: null,
    }, "start-constraints");
    assert.deepEqual(body, {
      topic: "变量",
      audience: "初学者",
      goal: "学习变量",
      language: "zh",
      expected_chapters: 12,
      min_effective_chars: 12000,
      token_limit: null,
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});


test("resumable and human-gated Runs keep low-frequency polling", () => {
  assert.equal(shouldPoll("running"), true);
  assert.equal(shouldPoll("waiting_for_human"), true);
  assert.equal(shouldPoll("failed"), false);
  assert.equal(shouldPoll("ready_for_release"), false);
  assert.equal(shouldPoll("stopped"), true);
});

test("mission review action requires a matching pending execution checkpoint", () => {
  const run = {
    status: "waiting_for_human",
    stages: [{ name: "mission", status: "waiting_for_human" }],
  };
  const execution = {
    checkpoint: { id: "cp-1" }, commands: [],
    mission_review: {
      status: "pending", checkpoint_id: "cp-1",
      mission_ref: { run_id: "r1", artifact_id: "a1", version: 1,
        kind: "mission", content_hash: "hash" },
    },
  };
  assert.equal(canReviewMission(run, execution), true);
  assert.equal(canReviewMission({ ...run, status: "running" }, execution), false);
  assert.equal(canReviewMission(run, {
    ...execution, commands: [{ kind: "MISSION_REVIEW", status: "ACCEPTED" }],
  }), false);
});

test("mission review request carries exact reference, checkpoint and key", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (path, init) => {
    calls.push({ path, init });
    return new Response(JSON.stringify({
      id: "cmd", run_id: "r1", kind: "MISSION_REVIEW", status: "ACCEPTED", error: null,
    }), { status: 202 });
  };
  try {
    const ref = { run_id: "r1", artifact_id: "a1", version: 1,
      kind: "mission", content_hash: "hash" };
    await api.reviewMission("r1", "revise", ref, "cp-1", "修改目标", "review-key");
    assert.equal(calls[0].path, "/api/v0/runs/r1/mission-review");
    assert.equal(calls[0].init.headers["Idempotency-Key"], "review-key");
    assert.deepEqual(JSON.parse(calls[0].init.body), {
      action: "revise", mission_ref: ref,
      expected_checkpoint_id: "cp-1", feedback: "修改目标",
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("quality evidence identifies gate, artifact version and location", () => {
  const labels = qualityGateLabels({
    gate_results: [{
      gate: "deterministic", status: "fail", rule_id: "markdown.h1",
      evidence: "首行缺少标题",
      artifact_ref: { version: 2, kind: "lesson" },
    }],
    evidence_findings: [{
      finding_id: "f1", gate: "deterministic", rule_id: "markdown.h1",
      severity: "major", category: "structure", evidence: "首行缺少标题",
      artifact_ref: { version: 2, kind: "lesson" },
      location: { lesson_id: "lesson-1", line_start: 1, line_end: 1 },
    }],
  });
  assert.match(labels[0], /deterministic.*lesson v2.*markdown.h1/);
  assert.match(labels[1], /lesson-1.*第 1 行/);
});

test("an older polling snapshot cannot hide the human decision state", () => {
  const running = {
    id: "r1",
    status: "running",
    stages: [
      { status: "succeeded" },
      { status: "running" },
      ...Array.from({ length: 5 }, () => ({ status: "pending" })),
    ],
  };
  const waiting = {
    id: "r1",
    status: "waiting_for_human",
    stages: [
      ...Array.from({ length: 6 }, () => ({ status: "succeeded" })),
      { status: "waiting_for_human" },
    ],
  };
  const stopped = {
    id: "r1",
    status: "stopped",
    stages: [...waiting.stages.slice(0, 6), { status: "stopped" }],
  };

  assert.equal(preferNewerRun(running, waiting), waiting);
  assert.equal(preferNewerRun(waiting, running), waiting);
  assert.equal(preferNewerRun(stopped, waiting), stopped);
});

test("input validation errors identify the invalid field", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({
    detail: [{ loc: ["body", "topic"], msg: "String should have at least 1 character" }],
  }), { status: 422, headers: { "Content-Type": "application/json" } });
  try {
    await assert.rejects(
      api.startRun({ topic: " ", audience: "学员", goal: "了解变量", language: "zh" }),
      /topic.*String should have at least 1 character/,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("running query polls fast and human wait polls slowly", () => {
  assert.equal(runView.pollInterval({ status: "running" }), 1000);
  assert.equal(runView.pollInterval({ status: "waiting_for_human" }), 5000);
  assert.equal(runView.pollInterval({ status: "stopped" }), 5000);
});

test("write APIs send the stable idempotency key", async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (_path, init) => {
    requests.push(init);
    return new Response(JSON.stringify({ id: "r1" }), { status: 200 });
  };
  try {
    await api.startRun({ topic: "课", audience: "学员", goal: "学习", language: "zh" }, "start-key");
    await api.decideRelease("r1", "stop", "人工停止", "release-key");
    assert.equal(requests[0].headers["Idempotency-Key"], "start-key");
    assert.equal(requests[1].headers["Idempotency-Key"], "release-key");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("control requests only submit commands and execution view reads persisted state", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (path, init) => {
    calls.push({ path, init });
    return new Response(JSON.stringify({
      id: "command-1", run_id: "run-1", kind: "STOP", status: "ACCEPTED", error: null,
      commands: [], current_node: "mission", node_status: "STARTED", checkpoint: null,
      stop_requested: true, human_input_revision: 1, waiting_reason: null,
    }), { status: 200 });
  };
  try {
    await api.stopRun("run-1", "stop-key");
    await api.resumeRun("run-1", "resume-key");
    await api.reviseRun("run-1", "补充示例", "checkpoint-1", "revise-key");
    const view = await api.execution("run-1");
    assert.equal(view.current_node, "mission");
    assert.deepEqual(calls.map((call) => call.path), [
      "/api/v0/runs/run-1/stop", "/api/v0/runs/run-1/resume",
      "/api/v0/runs/run-1/revise", "/api/v0/runs/run-1/execution",
    ]);
    assert.equal(calls[2].init.headers["Idempotency-Key"], "revise-key");
    assert.equal(JSON.parse(calls[2].init.body).expected_checkpoint_id, "checkpoint-1");
    assert.equal(calls[3].init, undefined);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("evidence reader uses the redacted trace endpoint", async () => {
  const originalFetch = globalThis.fetch;
  const paths = [];
  globalThis.fetch = async (path) => {
    paths.push(path);
    return new Response(JSON.stringify({ trace_id: "r1", paths: [] }), { status: 200 });
  };
  try {
    const evidence = await api.evidence("r1");
    assert.equal(evidence.trace_id, "r1");
    assert.deepEqual(paths, ["/api/v0/runs/r1/evidence"]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("a pending request reuses its key until accepted or input changes", () => {
  const values = new Map();
  const storage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
  const first = idempotency.pendingKey(storage, "start", "same-body");
  assert.equal(idempotency.pendingKey(storage, "start", "same-body"), first);
  assert.notEqual(idempotency.pendingKey(storage, "start", "changed-body"), first);
  idempotency.clearPendingKey(storage, "start");
  assert.equal(storage.getItem("course-agent:pending:start"), null);
});

test("artifact and review labels expose role, version, sources and evidence", () => {
  assert.equal(
    artifactHandoffLabel({
      artifact_id: "lesson-1",
      version: 2,
      kind: "lesson",
      content_hash: "hash",
      producer_role: "writer",
      source_refs: [
        {
          run_id: "r1",
          artifact_id: "blueprint-1",
          version: 1,
          kind: "blueprint",
          content_hash: "blueprint-hash",
        },
      ],
    }),
    "writer · lesson v2 · 来源 blueprint v1",
  );
  assert.equal(
    reviewFindingLabel({
      code: "language-1",
      category: "language",
      severity: "minor",
      evidence: "连续三句长度相同",
      recommendation: "调整其中一句的节奏",
    }),
    "[minor/language] 连续三句长度相同；建议：调整其中一句的节奏",
  );
});

test("batch progress exposes stable ids and completed continuity entries", () => {
  assert.equal(
    batchProgressLabel({
      batches: [[0, 1], [2]],
      batch_ids: ["batch-first", "batch-second"],
      lesson_ids: [["lesson-a", "lesson-b"], ["lesson-c"]],
      continuity_ledger: [
        {
          batch_id: "batch-first",
          lesson_id: "lesson-a",
          lesson_ref: {
            run_id: "run-1",
            artifact_id: "lesson-artifact-a",
            version: 1,
            kind: "lesson",
            content_hash: "hash-a",
          },
          summary: "A 摘要",
          terminology: [],
          next_promises: [],
        },
        {
          batch_id: "batch-first",
          lesson_id: "lesson-b",
          lesson_ref: {
            run_id: "run-1",
            artifact_id: "lesson-artifact-b",
            version: 1,
            kind: "lesson",
            content_hash: "hash-b",
          },
          summary: "B 摘要",
          terminology: [],
          next_promises: [],
        },
      ],
    }),
    "2 个批次，已完成 1 个 · batch-first、batch-second",
  );
});

test("release controls appear only at the release human gate", () => {
  const names = ["intake", "mission", "blueprint", "batch_plan", "generation", "quality", "release"];
  const stages = names.map((name, index) => ({
    name,
    status: index < 6 ? "succeeded" : "waiting_for_human",
  }));
  assert.equal(canDecideRelease({ status: "waiting_for_human", stages }), true);
  assert.equal(
    canDecideRelease({
      status: "waiting_for_human",
      stages: stages.map((stage, index) => (
        index === 4 ? { status: "waiting_for_human" } : { ...stage, status: "pending" }
      )),
    }),
    false,
  );
  assert.equal(canDecideRelease({ status: "ready_for_release", stages }), false);
});

test("continuity ledger labels expose lesson identity and summary", () => {
  assert.deepEqual(
    continuityLedgerLabels({
      batches: [[0]],
      batch_ids: ["batch-first"],
      lesson_ids: [["lesson-a"]],
      continuity_ledger: [{
        batch_id: "batch-first",
        lesson_id: "lesson-a",
        lesson_ref: {
          run_id: "run-1",
          artifact_id: "artifact-a",
          version: 1,
          kind: "lesson",
          content_hash: "hash-a",
        },
        summary: "已经解释变量赋值。",
        terminology: [],
        next_promises: [],
      }],
    }),
    ["lesson-a：已经解释变量赋值。"],
  );
});

test("legacy batch plans without graph metadata remain readable", () => {
  const legacy = { batches: [[0]] };

  assert.equal(batchProgressLabel(legacy), "1 个批次，已完成 0 个");
  assert.deepEqual(continuityLedgerLabels(legacy), []);
});
