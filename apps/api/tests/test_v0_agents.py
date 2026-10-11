from app.v0.agents import AGENT_DEFINITIONS, AgentExecutor
from app.v0.artifact_tools import ArtifactTools
from app.v0.provider import AgentInput, FakeProvider
from app.v0.schemas import ArtifactRecord, ArtifactRef


def test_five_agent_definitions_have_frozen_artifact_boundaries():
    assert set(AGENT_DEFINITIONS) == {
        "mission",
        "blueprint",
        "writer",
        "reviewer",
        "repair",
    }
    assert {
        role: (definition.input_kinds, definition.output_kind)
        for role, definition in AGENT_DEFINITIONS.items()
    } == {
        "mission": ((), "mission"),
        "blueprint": (("mission",), "blueprint"),
        "writer": (("mission", "blueprint", "batch_plan"), "lesson"),
        "reviewer": (("mission", "blueprint", "lesson"), "quality"),
        "repair": (("blueprint", "lesson", "quality"), "lesson"),
    }


def test_definitions_slice_skills_and_never_grant_state_or_release_tools():
    for definition in AGENT_DEFINITIONS.values():
        assert definition.goal.strip()
        assert definition.skill_slices
        assert definition.refusal_conditions
        assert definition.allowed_tools <= {
            "read_artifact",
            "write_candidate_artifact",
        }

    assert all(
        "humanizer-zh" not in slice_name
        for role in ("mission", "blueprint", "writer")
        for slice_name in AGENT_DEFINITIONS[role].skill_slices
    )
    assert all(
        any(
            "humanizer-zh" in slice_name
            for slice_name in AGENT_DEFINITIONS[role].skill_slices
        )
        for role in ("reviewer", "repair")
    )

    assert any("事实" in item for item in AGENT_DEFINITIONS["reviewer"].refusal_conditions)
    assert any("Finding" in item for item in AGENT_DEFINITIONS["repair"].refusal_conditions)


def test_executor_keeps_prebuilt_context_slice_instead_of_reloading_full_content():
    mission = ArtifactRecord(
        artifact_id="mission-1",
        version=1,
        run_id="run-1",
        kind="mission",
        content={
            "audience": "初学者",
            "learning_goal": "完成练习",
            "scope": "Python 基础",
            "stop_conditions": ["冲突时停止"],
            "private": "不得进入 Provider",
        },
        content_hash="mission-hash",
    )
    mission_ref = ArtifactRef(
        run_id="run-1",
        artifact_id="mission-1",
        version=1,
        kind="mission",
        content_hash="mission-hash",
    )

    class RecordingProvider(FakeProvider):
        request = None

        def invoke(self, request):
            self.request = request
            return super().invoke(request)

    provider = RecordingProvider()
    executor = AgentExecutor(
        provider,
        ArtifactTools(AGENT_DEFINITIONS, lambda artifact_id, version: mission),
    )
    result = executor.invoke(
        "blueprint",
        "run-1",
        inputs=[
            AgentInput(
                kind="mission",
                content={"mission": {"learning_goal": "完成练习"}},
                reference=mission_ref,
            )
        ],
    )

    assert result.lessons
    assert provider.request.inputs[0].content == {
        "mission": {"learning_goal": "完成练习"}
    }
    assert "private" not in provider.request.model_dump_json()
