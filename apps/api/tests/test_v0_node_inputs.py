from types import SimpleNamespace

from app.v0.node_inputs import build_node_input_hash, provider_fingerprint
from app.v0.schemas import ArtifactRef, CourseInput, GraphState, LoopCounts, V0Run


def fixture():
    run = V0Run(
        id="run-1",
        course_id="course-1",
        course_input=CourseInput(
            topic="Vue", audience="初学者", goal="理解 state", language="zh",
        ),
    )
    state = GraphState(
        run_id="run-1",
        current_node="generation",
        artifact_refs={
            "mission": ArtifactRef(
                run_id="run-1", artifact_id="m1", version=1,
                kind="mission", content_hash="mh",
            ),
        },
        batch_cursor=0,
        quality_cursor=2,
        active_finding_id="finding-1",
        last_outcome="succeeded",
        exit_reason="repair_needed",
    )
    return run, state


def build(run, state, **overrides):
    arguments = {
        "node": "writer",
        "run": run,
        "state": state,
        "mission_review": None,
        "source_summary": [{"document_id": "d1", "content_hash": "dh"}],
        "human_input": None,
        "provider": SimpleNamespace(model="deepseek-flash"),
    }
    arguments.update(overrides)
    return build_node_input_hash(**arguments)


def test_node_input_hash_is_stable_and_ignores_outcome_fields():
    run, state = fixture()
    first = build(run, state)
    changed = state.model_copy(update={
        "last_outcome": "failed", "exit_reason": "boom",
        "loop_counts": LoopCounts(repair_attempts=2),
    })
    assert build(run, changed) == first


def test_node_input_hash_changes_when_artifacts_or_cursors_change():
    run, state = fixture()
    base = build(run, state)
    assert build(run, state.model_copy(update={"batch_cursor": 1})) != base
    assert build(run, state.model_copy(update={"quality_cursor": 3})) != base
    assert build(run, state.model_copy(update={"active_finding_id": "other"})) != base
    refs = dict(state.artifact_refs)
    refs["mission"] = refs["mission"].model_copy(update={"version": 2})
    assert build(run, state.model_copy(update={"artifact_refs": refs})) != base


def test_node_input_hash_changes_for_review_source_provider_and_rules(monkeypatch):
    run, state = fixture()
    base = build(run, state)
    assert build(run, state, mission_review={"action": "revise"}) != base
    assert build(run, state, source_summary=[]) != base
    assert build(run, state, human_input={"text": "重写第一章"}) != base
    assert build(
        run, state, provider=SimpleNamespace(model="deepseek-v4-pro"),
    ) != base
    import app.v0.node_inputs as node_inputs
    monkeypatch.setattr(node_inputs, "RULE_CATALOG_VERSION", "changed")
    assert build(run, state) != base


def test_provider_fingerprint_unwraps_budgeted_provider():
    inner = SimpleNamespace(model="deepseek-flash")
    wrapped = SimpleNamespace(provider=inner)
    assert provider_fingerprint(wrapped) == provider_fingerprint(inner)
    assert "deepseek-flash" in provider_fingerprint(inner)
