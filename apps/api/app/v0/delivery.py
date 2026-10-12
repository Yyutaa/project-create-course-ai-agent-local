"""Redacted, rebuildable delivery evidence over existing SQLite facts."""

import json
from hashlib import sha256
from pathlib import Path

from pydantic import BaseModel

from app.v0.quality_loop import effective_character_count
from app.v0.storage import FactStore


def safe_rule_id(value: str) -> str:
    return "rule-" + sha256(value.encode("utf-8")).hexdigest()[:16]


class TraceCommand(BaseModel):
    id: str
    kind: str
    status: str


class TraceNode(BaseModel):
    id: str
    command_id: str | None
    node: str
    attempt: int
    lease_epoch: int
    status: str
    before_checkpoint_id: str | None
    after_checkpoint_id: str | None


class TraceArtifact(BaseModel):
    id: str
    version: int
    kind: str
    content_hash: str


class TraceProviderCall(BaseModel):
    id: str
    command_id: str | None
    node_execution_id: str | None
    role: str
    status: str
    duration_ms: int | None
    input_tokens: int | None
    output_tokens: int | None


class TraceFinding(BaseModel):
    id: str
    gate: str
    rule_id: str
    artifact_id: str
    artifact_version: int
    lesson_id: str
    line_start: int
    excerpt_hash: str
    expected_value: int | None = None
    actual_value: int | None = None


class TraceVerification(BaseModel):
    id: str
    gate: str
    status: str
    rule_id: str
    candidate_id: str
    candidate_version: int
    finding_id: str | None


class TraceDecision(BaseModel):
    event_id: int
    kind: str
    action: str | None


class TraceConstraintEvent(BaseModel):
    event_id: int
    kind: str
    status: str | None
    artifact_id: str | None
    artifact_version: int | None
    expected_value: int | None = None
    actual_value: int | None = None


class PathEvidence(BaseModel):
    scenario: str
    status: str
    evidence_ids: list[str]


class DeliveryEvidence(BaseModel):
    trace_id: str
    run_status: str
    commands: list[TraceCommand]
    nodes: list[TraceNode]
    artifacts: list[TraceArtifact]
    provider_calls: list[TraceProviderCall]
    findings: list[TraceFinding]
    verifications: list[TraceVerification]
    decisions: list[TraceDecision]
    constraint_events: list[TraceConstraintEvent]
    paths: list[PathEvidence]
    integrity_issues: list[str]


class DeliveryStore:
    def __init__(self, path: Path):
        self.facts = FactStore(path)
        self.facts.migrate()

    def read(self, trace_id: str) -> DeliveryEvidence:
        with self.facts.connect() as connection:
            run = connection.execute(
                "SELECT runs.status, intakes.expected_chapters, "
                "intakes.min_effective_chars, intakes.token_limit FROM runs "
                "JOIN intakes ON intakes.run_id=runs.id WHERE runs.id=?",
                (trace_id,),
            ).fetchone()
            if run is None:
                raise KeyError(trace_id)
            commands = connection.execute(
                "SELECT id, kind, status FROM commands WHERE run_id=? ORDER BY rowid",
                (trace_id,),
            ).fetchall()
            nodes = connection.execute(
                "SELECT id, command_id, node, attempt, lease_epoch, status, before_checkpoint_id, "
                "after_checkpoint_id FROM node_executions WHERE run_id=? ORDER BY rowid",
                (trace_id,),
            ).fetchall()
            artifacts = connection.execute(
                "SELECT artifact_id, version, kind, content_hash, content_json "
                "FROM artifacts WHERE run_id=? ORDER BY rowid", (trace_id,),
            ).fetchall()
            provider_calls = connection.execute(
                "SELECT id, command_id, node_execution_id, role, status, "
                "duration_ms, input_tokens, output_tokens FROM provider_calls "
                "WHERE run_id=? ORDER BY rowid", (trace_id,),
            ).fetchall()
            decisions = connection.execute(
                "SELECT id, type, CASE type "
                "WHEN 'mission.approved' THEN 'approve' "
                "WHEN 'mission.revision_requested' THEN 'revise' "
                "ELSE release_action END AS action FROM events WHERE run_id=? AND "
                "type IN ('mission.approved','mission.revision_requested',"
                "'release.decided') ORDER BY id", (trace_id,),
            ).fetchall()
            budget_events = connection.execute(
                "SELECT id FROM events WHERE run_id=? AND "
                "type IN ('budget.exhausted','budget.repair_exhausted')",
                (trace_id,),
            ).fetchall()
            constraint_events = connection.execute(
                "SELECT id, type, status, artifact_id, artifact_version FROM events "
                "WHERE run_id=? AND type IN ("
                "'blueprint.chapter_count_observed',"
                "'blueprint.chapter_deviation_accepted',"
                "'budget.token_exhausted') ORDER BY id",
                (trace_id,),
            ).fetchall()
        findings: dict[str, TraceFinding] = {}
        verifications: list[TraceVerification] = []
        artifact_contents = {}
        artifact_issues = []
        for row in artifacts:
            key = (row["artifact_id"], row["version"])
            try:
                content = json.loads(row["content_json"])
            except (json.JSONDecodeError, TypeError):
                artifact_issues.append(
                    f"artifact:{row['artifact_id']}:{row['version']}:invalid_json"
                )
                continue
            if not isinstance(content, dict):
                artifact_issues.append(
                    f"artifact:{row['artifact_id']}:{row['version']}:invalid_content"
                )
                continue
            artifact_contents[key] = content
        quality_artifacts = [row for row in artifacts if row["kind"] == "quality"]
        for artifact in quality_artifacts[-1:]:
            content = artifact_contents.get(
                (artifact["artifact_id"], artifact["version"])
            )
            if content is None:
                continue
            for finding in content.get("evidence_findings", []):
                ref = finding["artifact_ref"]
                location = finding["location"]
                expected_value = None
                actual_value = None
                if finding["rule_id"] == "lesson.effective_chars.minimum":
                    expected_value = run["min_effective_chars"]
                    lesson = artifact_contents.get(
                        (ref["artifact_id"], ref["version"])
                    )
                    if lesson is not None:
                        markdown = lesson.get("markdown")
                        if isinstance(markdown, str):
                            actual_value = effective_character_count(markdown)
                        else:
                            artifact_issues.append(
                                f"artifact:{ref['artifact_id']}:{ref['version']}:"
                                "invalid_lesson_content"
                            )
                findings[finding["finding_id"]] = TraceFinding(
                    id=finding["finding_id"], gate=finding["gate"],
                    rule_id=safe_rule_id(finding["rule_id"]),
                    artifact_id=ref["artifact_id"],
                    artifact_version=ref["version"], lesson_id=location["lesson_id"],
                    line_start=location["line_start"],
                    excerpt_hash=location["excerpt_hash"],
                    expected_value=expected_value,
                    actual_value=actual_value,
                )
            links = content.get("verification_links", [])
            for index, result in enumerate(content.get("verification_results", [])):
                ref = result["artifact_ref"]
                link = next((item for item in links if
                             item["result_start"] <= index <
                             item["result_start"] + item["result_count"]), None)
                verifications.append(TraceVerification(
                    id=f"{artifact['artifact_id']}:{artifact['version']}:{index}",
                    gate=result["gate"], status=result["status"],
                    rule_id=safe_rule_id(result["rule_id"]),
                    candidate_id=ref["artifact_id"],
                    candidate_version=ref["version"],
                    finding_id=link["finding_id"] if link else None,
                ))
        command_ids = {row["id"] for row in commands}
        node_commands = {row["id"]: row["command_id"] for row in nodes}
        artifact_versions = {
            (row["artifact_id"], row["version"]) for row in artifacts
        }
        issues = list(dict.fromkeys(artifact_issues))
        issues.extend(
            f"node:{row['id']}:missing_command"
            for row in nodes
            if row["command_id"] and row["command_id"] not in command_ids
        )
        issues.extend(
            f"provider_call:{row['id']}:missing_node"
            for row in provider_calls
            if row["node_execution_id"] and row["node_execution_id"] not in node_commands
        )
        issues.extend(
            f"provider_call:{row['id']}:missing_command"
            for row in provider_calls
            if row["command_id"] and row["command_id"] not in command_ids
        )
        issues.extend(
            f"provider_call:{row['id']}:command_mismatch"
            for row in provider_calls
            if row["node_execution_id"] in node_commands
            and node_commands[row["node_execution_id"]] != row["command_id"]
        )
        issues.extend(
            f"finding:{item.id}:missing_artifact"
            for item in findings.values()
            if (item.artifact_id, item.artifact_version) not in artifact_versions
        )
        issues.extend(
            f"verification:{item.id}:missing_candidate"
            for item in verifications
            if (item.candidate_id, item.candidate_version) not in artifact_versions
        )
        issues.extend(
            f"verification:{item.id}:missing_finding"
            for item in verifications
            if item.finding_id and item.finding_id not in findings
        )
        epochs_by_command_node: dict[tuple[str, str], set[int]] = {}
        recovery_ids: list[str] = []
        for row in nodes:
            if not row["command_id"]:
                continue
            key = (row["command_id"], row["node"])
            epochs = epochs_by_command_node.setdefault(key, set())
            if epochs and row["lease_epoch"] not in epochs:
                recovery_ids.append(row["id"])
            epochs.add(row["lease_epoch"])
        tokens_used = sum(
            (row["input_tokens"] or 0) + (row["output_tokens"] or 0)
            for row in provider_calls
            if row["status"] != "RESERVED"
        )
        constraint_trace = []
        for row in constraint_events:
            expected_value = None
            actual_value = None
            if row["type"].startswith("blueprint.chapter_"):
                expected_value = run["expected_chapters"]
                blueprint = artifact_contents.get(
                    (row["artifact_id"], row["artifact_version"])
                )
                if blueprint is not None:
                    lessons = blueprint.get("lessons")
                    if isinstance(lessons, list):
                        actual_value = len(lessons)
                    else:
                        issue = (
                            f"artifact:{row['artifact_id']}:"
                            f"{row['artifact_version']}:invalid_blueprint_content"
                        )
                        if issue not in issues:
                            issues.append(issue)
            elif row["type"] == "budget.token_exhausted":
                expected_value = run["token_limit"]
                actual_value = tokens_used
            constraint_trace.append(TraceConstraintEvent(
                event_id=row["id"],
                kind=row["type"],
                status=row["status"],
                artifact_id=row["artifact_id"],
                artifact_version=row["artifact_version"],
                expected_value=expected_value,
                actual_value=actual_value,
            ))
        return DeliveryEvidence(
            trace_id=trace_id, run_status=run["status"],
            commands=[TraceCommand(**dict(row)) for row in commands],
            nodes=[TraceNode(**dict(row)) for row in nodes],
            artifacts=[TraceArtifact(
                id=row["artifact_id"], version=row["version"],
                kind=row["kind"], content_hash=row["content_hash"],
            ) for row in artifacts],
            provider_calls=[TraceProviderCall(**dict(row)) for row in provider_calls],
            findings=list(findings.values()), verifications=verifications,
            decisions=[TraceDecision(
                event_id=row["id"], kind=row["type"], action=row["action"],
            ) for row in decisions],
            constraint_events=constraint_trace,
            paths=[
                PathEvidence(
                    scenario="normal",
                    status="observed" if any(
                        row["type"] == "release.decided" for row in decisions
                    ) and all(
                        row["status"] == "COMMITTED" for row in nodes
                    ) else "not_observed",
                    evidence_ids=[str(row["id"]) for row in decisions],
                ),
                PathEvidence(
                    scenario="recovery",
                    status="observed" if recovery_ids else "not_observed",
                    evidence_ids=recovery_ids,
                ),
                PathEvidence(
                    scenario="human",
                    status="observed" if decisions or budget_events or any(
                        row["kind"] in ("STOP", "REVISE") for row in commands
                    ) else "not_observed",
                    evidence_ids=[
                        *[row["id"] for row in commands if row["kind"] in ("STOP", "REVISE")],
                        *[str(row["id"]) for row in decisions],
                        *[str(row["id"]) for row in budget_events],
                    ],
                ),
            ],
            integrity_issues=issues,
        )
