from __future__ import annotations

import json
from pathlib import Path

import pytest

from slogger.tools import (
    FINGERPRINT_VERSION,
    GENERIC_PROFILE,
    Profile,
    classify,
    load_profile,
)
from slogger.tools.errors import ToolError
from slogger.tools.seq.profile import (
    CompleteWhenInvocations,
    EpisodeOutcomeAggregate,
    EpisodeOutcomeField,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILES = REPO_ROOT / "tests/fixtures/logs/sequence/profiles"
ROBOT = PROFILES / "robotic_arm_observed.json"
SYNTH = PROFILES / "synthetic_workflow.json"
INVALID = PROFILES / "invalid_unknown_key.json"


@pytest.fixture(autouse=True)
def _chdir_repo(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)


def test_generic_profile_identity():
    assert load_profile(None) is GENERIC_PROFILE
    assert GENERIC_PROFILE.episode_key == ("episode_id",)
    assert GENERIC_PROFILE.name == "generic"
    assert GENERIC_PROFILE.source == "builtin:generic"
    assert GENERIC_PROFILE.spans == "as_steps"
    assert FINGERPRINT_VERSION == 1


def test_load_robot_profile():
    profile = load_profile(ROBOT)
    assert isinstance(profile, Profile)
    assert profile.rules[0].id == "bg"
    assert profile.invocation is not None
    assert profile.invocation.name == "api"
    assert profile.name == "robotic-arm-observed"
    assert profile.episode_key == ("episode_id",)
    assert isinstance(profile.complete_when, CompleteWhenInvocations)
    assert profile.complete_when.invocations[0] == "/robotic-arm/pick/basket"
    assert isinstance(profile.outcome_episode, EpisodeOutcomeAggregate)
    assert profile.outcome_episode.require_outcome_from == (
        "/robotic-arm/pick/basket",
        "/robotic-arm/drop-slide",
    )


def test_load_synthetic_profile():
    profile = load_profile(SYNTH)
    assert profile.spans == "as_steps"
    assert profile.episode_key == ("workflow_id",)
    assert profile.episode_start[0].key == "message"
    assert isinstance(profile.outcome_episode, EpisodeOutcomeField)
    assert profile.outcome_episode.field == "workflow_outcome"


def test_invalid_unknown_key():
    with pytest.raises(ToolError) as exc:
        load_profile(INVALID)
    assert exc.value.code == "profile_invalid"
    assert "bogus" in exc.value.message


def test_invalid_when_token_with_space(tmp_path):
    path = tmp_path / "bad_when.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "bad",
                "episode": {"key": ["id"]},
                "rules": [
                    {"id": "r", "category": "step", "when": ["a b=1"]},
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ToolError) as exc:
        load_profile(path)
    assert exc.value.code == "profile_invalid"


def test_duplicate_rule_ids(tmp_path):
    path = tmp_path / "dup.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "dup",
                "episode": {"key": ["id"]},
                "rules": [
                    {"id": "r", "category": "step", "when": ["k=1"]},
                    {"id": "r", "category": "error", "when": ["k=2"]},
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ToolError) as exc:
        load_profile(path)
    assert exc.value.code == "profile_invalid"
    assert "duplicate" in exc.value.message


def test_unsupported_schema_version(tmp_path):
    path = tmp_path / "v3.json"
    path.write_text(
        json.dumps({"schema_version": 3, "episode": {"key": ["id"]}}),
        encoding="utf-8",
    )
    with pytest.raises(ToolError) as exc:
        load_profile(path)
    assert exc.value.code == "profile_invalid"
    assert "schema_version" in exc.value.message


def test_load_robot_span_roles():
    profile = load_profile(ROBOT)
    roles = {spec.role: spec for spec in profile.span_roles}
    assert set(roles) == {"episode", "api", "motion", "gripper"}
    assert roles["motion"].parent == "api"
    assert roles["gripper"].parent == "api"
    assert roles["api"].parent == "episode"
    assert profile.invocation_role == "api"
    assert profile.profile_version == "2"


def test_profile_not_found():
    with pytest.raises(ToolError) as exc:
        load_profile(PROFILES / "missing.json")
    assert exc.value.code == "profile_not_found"


def test_classify_robot_gripper():
    robot = load_profile(ROBOT)
    assert classify(
        robot, {"kind": "step.entry", "operation_type": "OPEN_AT_PICK_BASKET"}
    ) == ("step", "OPEN_AT_PICK_BASKET", "gripper")


def test_classify_robot_observation_suffix():
    robot = load_profile(ROBOT)
    assert classify(
        robot,
        {
            "kind": "observation",
            "message": "observation.slide_present",
            "slide_present": False,
        },
    ) == ("observation", "observation.slide_present=false", "observe")


def test_classify_first_rule_wins_background():
    robot = load_profile(ROBOT)
    assert classify(
        robot, {"logger": "robotic_arm_service.bg", "kind": "step.entry"}
    ) == ("background", None, "bg")


def test_classify_span_events_robot_vs_synth():
    robot = load_profile(ROBOT)
    synth = load_profile(SYNTH)
    assert classify(robot, {"event": "span.end", "span": "x"}) == (
        "span_event",
        None,
        None,
    )
    assert classify(synth, {"event": "span.end", "span": "x"}) == ("step", "x", "spans")
    assert classify(synth, {"event": "span.start", "span": "x"}) == (
        "span_event",
        None,
        None,
    )


def test_classify_no_rule_is_other():
    robot = load_profile(ROBOT)
    assert classify(robot, {"message": "hello"}) == ("other", None, None)


def test_classify_empty_when_never_matches(tmp_path):
    path = tmp_path / "empty_when.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "empty",
                "episode": {"key": ["id"]},
                "rules": [{"id": "noop", "category": "step", "when": []}],
            }
        ),
        encoding="utf-8",
    )
    profile = load_profile(path)
    assert classify(profile, {"k": 1}) == ("other", None, None)


def test_exports_from_tools_package():
    import slogger.tools as tools

    for name in (
        "RecordRef",
        "Duration",
        "SeqEvent",
        "Span",
        "Invocation",
        "Outcome",
        "Links",
        "Episode",
        "FINGERPRINT_VERSION",
        "Profile",
        "load_profile",
        "GENERIC_PROFILE",
        "classify",
    ):
        assert name in tools.__all__
        assert hasattr(tools, name)
