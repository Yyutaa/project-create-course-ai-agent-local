import pytest

from app.v0.skill_rules import (
    HUMANIZER_PATTERNS,
    SKILL_RULE_SETS,
    repair_rules_for,
    rule_ids_for,
    rules_for,
)


def test_humanizer_catalog_covers_every_numbered_pattern_without_role_leakage():
    assert len(HUMANIZER_PATTERNS) == 46
    assert len({rule.id for rule in HUMANIZER_PATTERNS}) == 46
    assert all(rule.source_section and rule.text for rule in HUMANIZER_PATTERNS)
    assert set(SKILL_RULE_SETS) >= {"writer", "reviewer", "repair"}
    writer = "\n".join(rule.text for rule in rules_for("writer"))
    reviewer = "\n".join(rule.text for rule in rules_for("reviewer"))
    assert "humanizer.score_threshold" not in rule_ids_for("writer")
    assert "humanizer.score_threshold" in rule_ids_for("reviewer")
    assert "分才算过" not in writer
    assert "重写正文" not in reviewer
    assert "humanizer.core.trust_reader" in rule_ids_for("writer")
    assert "humanizer.format.machine_boundaries" in rule_ids_for("writer")
    assert "humanizer.score.directness" in rule_ids_for("reviewer")
    assert "humanizer.score.directness" not in rule_ids_for("writer")


def test_repair_projection_is_specific_to_current_finding_rule():
    selected = repair_rules_for("humanizer.language.filler")
    assert [rule.id for rule in selected] == ["humanizer.language.filler"]
    with pytest.raises(ValueError, match="未知规则"):
        repair_rules_for("humanizer.unknown")


def test_located_teaching_finding_keeps_a_narrow_repair_path():
    selected = repair_rules_for("teaching.practice")
    assert len(selected) == 1
    assert selected[0].id == "teaching.practice"
    assert "当前" in selected[0].text
    with pytest.raises(ValueError, match="未知规则"):
        repair_rules_for("source.claim_support")
