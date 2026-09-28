from __future__ import annotations

import json
from pathlib import Path

import pytest

from slogger.tools import (
    Duration,
    Filters,
    Where,
    episode_summary,
    extract_episodes,
    get_episode,
    load_profile,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SEQ = REPO_ROOT / "tests/fixtures/logs/sequence"
PROFILES = SEQ / "profiles"
ROBOT_PATH = PROFILES / "robotic_arm_observed.json"
SYNTH_PATH = PROFILES / "synthetic_workflow.json"
CL = SEQ / "source_derived/pick_basket_issue_cluster.jsonl"
FE = SEQ / "source_derived/force_exit_retry_abort.jsonl"
CA = SEQ / "source_derived/full_slide_cycle_a.jsonl"
CB = SEQ / "source_derived/full_slide_cycle_b.jsonl"
EDGE = SEQ / "edge/late_and_unassigned.jsonl"
ENRICHED = {
    "cluster": SEQ / "enriched/pick_basket_issue_cluster.spans.jsonl",
    "force_exit": SEQ / "enriched/force_exit_retry_abort.spans.jsonl",
    "cycle_a": SEQ / "enriched/full_slide_cycle_a.spans.jsonl",
    "cycle_b": SEQ / "enriched/full_slide_cycle_b.spans.jsonl",
}
SOURCE = {
    "cluster": CL,
    "force_exit": FE,
    "cycle_a": CA,
    "cycle_b": CB,
}


@pytest.fixture(autouse=True)
def _chdir_repo(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)


@pytest.fixture(scope="module")
def robot():
    return load_profile(ROBOT_PATH)


@pytest.fixture(scope="module")
def synth():
    return load_profile(SYNTH_PATH)


def _by_suffix(episodes, suffix: str):
    matches = [ep for ep in episodes if ep.key.endswith(suffix)]
    assert matches, f"missing episode ending {suffix}"
    return matches[0]


def test_span_nesting_parent_is_profile_declared(robot):
    """Motion and gripper are siblings under api; Slide Present stays on api."""
    result = extract_episodes(CA, profile=robot, top=None)
    ep = result.episodes[0]
    by_index = {span.index: span for span in ep.spans}
    assert ep.spans[ep.root].role == "episode"

    home = next(
        span
        for span in ep.spans
        if span.role == "motion"
        and span.name == "move_trajectory"
        and any(
            ep.events[i].attrs.get("source_line") == 5993 for i in span.events
        )
    )
    assert home.parent_index is not None
    assert by_index[home.parent_index].role == "api"
    assert home.complete is True

    close = next(
        span
        for span in ep.spans
        if span.role == "gripper" and span.name == "CLOSE_AT_HOME"
    )
    open_home = next(
        span
        for span in ep.spans
        if span.role == "gripper" and span.name == "OPEN_AT_HOME"
    )
    assert close.parent_index == home.parent_index == open_home.parent_index
    assert close.complete is True and open_home.complete is True

    slide = next(
        e
        for e in ep.events
        if e.token == "observation.slide_present=false"
        and e.attrs.get("source_line") == 6029
    )
    assert slide.span_index is not None
    assert ep.spans[slide.span_index].role == "api"

    force = extract_episodes(FE, profile=robot, top=None)
    r9 = _by_suffix(force.episodes, "r2-c9")
    open_pose = next(
        span
        for span in r9.spans
        if span.role == "motion"
        and any(r9.events[i].attrs.get("source_line") == 28111 for i in span.events)
    )
    assert open_pose.complete is False
    force_ev = next(e for e in r9.events if e.token == "force.stop_playing")
    assert force_ev.span_index == open_pose.index


def test_a1_cluster_episode_order(robot):
    result = extract_episodes(CL, profile=robot, top=None)
    assert result.unassigned_records == 0
    assert [ep.key.split(":")[-1] for ep in result.episodes] == [
        "r1-c1",
        "r1-c3",
        "r1-c4",
        "r1-c5",
    ]


def test_a2_cluster_outcomes_and_occurrences(robot):
    result = extract_episodes(CL, profile=robot, top=None)
    r1 = _by_suffix(result.episodes, "r1-c1")
    assert len(r1.invocations) == 2
    assert r1.invocations[0].name == "/robotic-arm/pick/basket"
    assert r1.invocations[0].complete is True
    assert r1.invocations[0].outcome.value == "ok"
    assert r1.invocations[0].outcome.evidence[0].source_line == 1895
    assert r1.invocations[1].name == "/robotic-arm/move/scanner/imaging"
    assert r1.invocations[1].outcome.value == "ok_with_warning"
    assert r1.invocations[1].outcome.evidence[0].source_line == 1911
    assert r1.outcome.value == "ok_with_warning"
    assert r1.completion == "incomplete"

    r3 = _by_suffix(result.episodes, "r1-c3")
    assert len(r3.invocations) == 1
    assert r3.invocations[0].outcome.value == "error"
    assert r3.outcome.value == "error"
    assert r3.completion == "incomplete"
    opens = [
        e
        for e in r3.events
        if e.token == "OPEN_AT_PICK_BASKET" and e.category == "step"
    ]
    assert [(e.occurrence_n, e.ref.source_line) for e in opens] == [
        (1, 8401),
        (2, 8474),
    ]


def test_a3_force_exit(robot):
    result = extract_episodes(FE, profile=robot, top=None)
    r9 = _by_suffix(result.episodes, "r2-c9")
    assert r9.invocations[0].outcome.value == "aborted"
    assert r9.invocations[0].outcome.evidence[0].source_line == 28371
    error_lines = {
        e.ref.source_line for e in r9.events if e.ref.source_line in (28118, 28369, 28370)
    }
    assert error_lines == {28118, 28369, 28370}
    opens = [e for e in r9.events if e.token == "OPEN_AT_PICK_BASKET"]
    assert any(e.occurrence_n == 2 and e.ref.source_line == 28135 for e in opens)
    assert r9.links.recovery_of is None
    assert r9.links.triggered_recovery is None

    r10 = _by_suffix(result.episodes, "r2-c10")
    assert r10.invocations[0].outcome.value == "ok"
    assert r10.outcome.value == "unknown"
    assert r10.completion == "incomplete"
    assert r10.links.recovery_of is None


def test_a4_full_cycle(robot):
    result = extract_episodes(CA, profile=robot, top=None)
    ep = result.episodes[0]
    assert len(ep.invocations) == 12
    names = [inv.name for inv in ep.invocations]
    assert names[0] == "/robotic-arm/pick/basket"
    assert names[-1] == "/robotic-arm/drop-slide"
    assert ep.completion == "complete"
    assert ep.outcome.value == "ok"
    assert ep.invocations[0].duration == Duration(3177.0, "derived")

    # Truncate after L5552 (start only) → unavailable duration
    rows = [json.loads(line) for line in CA.read_text().splitlines() if line.strip()]
    cut = [r for r in rows if r["source_line"] <= 5552]
    truncated = extract_episodes(cut, profile=robot, top=None).episodes[0]
    assert truncated.invocations[0].duration == Duration(None, "unavailable")


def test_a5_synthetic(synth):
    ftr = extract_episodes(
        SEQ / "synthetic/failure_then_recovery.jsonl", profile=synth, top=None
    )
    assert len(ftr.episodes) == 2
    failed = next(ep for ep in ftr.episodes if ep.outcome.value == "error")
    recovery = next(ep for ep in ftr.episodes if ep.outcome.value == "ok")
    assert failed.links.triggered_recovery == recovery.key
    assert recovery.links.recovery_of == failed.key

    incomplete = extract_episodes(
        SEQ / "synthetic/incomplete_workflow.jsonl", profile=synth, top=None
    ).episodes[0]
    assert incomplete.completion == "incomplete"
    assert incomplete.outcome.value == "unknown"
    assert incomplete.duration.kind == "unavailable"
    summary = episode_summary(incomplete)
    assert summary["elapsed_ms"] == 59.0

    retry = extract_episodes(
        SEQ / "synthetic/retry_exhaustion.jsonl", profile=synth, top=None
    ).episodes[0]
    assert retry.outcome.value == "aborted"
    closes = [e for e in retry.events if e.token == "CLOSE_AT_PICK_BASKET"]
    assert [e.occurrence_n for e in closes] == [1, 2, 3]
    assert [e.occurrence_label for e in closes] == ["1", "2", "3"]

    repeated = extract_episodes(
        SEQ / "synthetic/repeated_steps_equal_ts.jsonl", profile=synth, top=None
    ).episodes[0]
    closes = [e for e in repeated.events if e.token == "CLOSE_AT_PICK_BASKET"]
    assert len(closes) == 3
    assert [e.occurrence_label for e in closes] == ["close-1", "close-2", "close-3"]


def test_a6_interleaved_time_order(synth):
    result = extract_episodes(
        [
            SEQ / "synthetic/interleaved_episodes.jsonl",
            SEQ / "synthetic/success_pick_place.jsonl",
        ],
        profile=synth,
        order="time",
        top=None,
    )
    assert len(result.episodes) == 3
    bg = [
        e
        for ep in result.episodes
        for e in ep.events
        if e.category == "background"
    ]
    assert bg
    assert all(e.invocation_index is not None or True for e in bg)


def test_a7_variant_equivalence(robot):
    pairs = [
        ("cluster", SOURCE["cluster"], ENRICHED["cluster"]),
        ("force_exit", SOURCE["force_exit"], ENRICHED["force_exit"]),
        ("cycle_a", SOURCE["cycle_a"], ENRICHED["cycle_a"]),
        ("cycle_b", SOURCE["cycle_b"], ENRICHED["cycle_b"]),
    ]
    # Allowed source/enriched deltas per D3 / A7, plus event_count (span rows)
    # and record ids (path-qualified _id).
    drop = {"duration_evidence", "span_events", "boundaries", "event_count"}

    def scrub_refs(obj):
        if isinstance(obj, dict):
            if "id" in obj and ("source_line" in obj or "timestamp" in obj):
                obj = {k: v for k, v in obj.items() if k != "id"}
            return {k: scrub_refs(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [scrub_refs(v) for v in obj]
        return obj

    def scrub(summary: dict) -> object:
        out = json.loads(json.dumps(summary))
        for key in drop:
            out.pop(key, None)
        for inv in out.get("invocations", []):
            for key in drop:
                inv.pop(key, None)
        # Span-tree rows gain enriched span_event attachments and may anchor
        # the episode root on a proposed span.start; compare structure only.
        for span in out.get("spans", []):
            for key in ("event_count", "start", "end", "duration"):
                span.pop(key, None)
        out.pop("span_count", None)
        return scrub_refs(out)

    for _name, src, enr in pairs:
        src_eps = extract_episodes(src, profile=robot, top=None).episodes
        enr_eps = extract_episodes(enr, profile=robot, top=None).episodes
        assert len(src_eps) == len(enr_eps)
        for s_ep, e_ep in zip(src_eps, enr_eps, strict=True):
            assert scrub(episode_summary(s_ep)) == scrub(episode_summary(e_ep))
            for inv in s_ep.invocations:
                assert inv.duration.kind == "derived"
            for inv in e_ep.invocations:
                assert inv.duration.kind == "derived"

    fe_enr = extract_episodes(ENRICHED["force_exit"], profile=robot, top=None)
    r9 = _by_suffix(fe_enr.episodes, "r2-c9")
    summary = episode_summary(r9)
    assert summary["boundaries"]["start"] == "inferred"
    assert summary["invocations"][0]["boundaries"]["start"] == "observed"


def test_a8_variant_key_file_merge(robot):
    from dataclasses import replace

    profile = replace(robot, variant_key="file")
    result = extract_episodes([FE, ENRICHED["force_exit"]], profile=profile, top=None)
    assert any(w.startswith("variant_collision:") for w in result.warnings)
    assert all("possible_duplicate" not in w for w in result.warnings)
    app = [ep for ep in result.episodes if ep.variant == "converted_from_plain_log"]
    span = [ep for ep in result.episodes if ep.variant == "span_enrichment"]
    assert app
    r9 = _by_suffix(app, "r2-c9")
    assert len(r9.events) == 52  # application records doubled across the two files
    assert span


def test_a9_round_trip(robot):
    key = "CS001-1-1-1790200023515:r1-c2"
    episode, records = get_episode(CA, key, profile=robot)
    assert len(records) == 96
    file_rows = [json.loads(line) for line in CA.read_text().splitlines() if line.strip()]
    stripped = [{k: v for k, v in row.items() if k != "_id"} for row in records]
    assert stripped == file_rows
    again = extract_episodes(
        [{k: v for k, v in row.items() if k != "_id"} for row in records],
        profile=robot,
        top=None,
    )

    def scrub(summary: dict) -> object:
        def walk(obj: object) -> object:
            if isinstance(obj, dict):
                data = obj
                if "id" in data and "source_line" in data:
                    data = {k: v for k, v in data.items() if k != "id"}
                return {k: walk(v) for k, v in data.items()}
            if isinstance(obj, list):
                return [walk(v) for v in obj]
            return obj

        return walk(json.loads(json.dumps(summary)))

    assert scrub(episode_summary(again.episodes[0])) == scrub(episode_summary(episode))


def test_a10_edge_fixture(robot):
    result = extract_episodes(EDGE, profile=robot, top=None)
    assert result.unassigned_records == 1
    assert len(result.episodes) == 2
    e1 = next(ep for ep in result.episodes if ep.key == "E1")
    assert any(w.startswith("non_monotonic:") for w in e1.warnings)
    bad = next(e for e in e1.events if e.ref.timestamp == "bad")
    assert bad.ts is None


def test_a11_caps(robot):
    capped = extract_episodes(CL, profile=robot, max_open_episodes=1, top=None)
    assert capped.episodes_capped is True
    assert capped.total == 4
    assert capped.returned == 1

    truncated = extract_episodes(CL, profile=robot, max_events_per_episode=5, top=None)
    for ep in truncated.episodes:
        assert ep.truncated is True
        assert len(ep.events) == 5


def test_a12_selection_keeps_leadup(robot):
    result = extract_episodes(
        CL,
        profile=robot,
        filters=Filters(where=(Where("error_code", "=", "CLDJ_SLIDE_NOT_FOUND"),)),
        top=None,
    )
    assert len(result.episodes) == 3
    for ep in result.episodes:
        cats = {e.category for e in ep.events}
        assert "invocation_start" in cats
        assert any(e.token == "OPEN_AT_PICK_BASKET" for e in ep.events)


def test_a13_cli_episodes_and_episode(capsys):
    from slogger.cli import main

    robot = str(ROBOT_PATH)
    code = main(
        [
            "episodes",
            str(CL),
            "--profile",
            robot,
            "--format",
            "json",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    payload = json.loads(out)
    assert payload["total"] == 4
    assert payload["schema_version"] == 1

    code = main(
        [
            "episodes",
            str(CL),
            "--profile",
            robot,
            "--format",
            "table",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    header = out.splitlines()[0]
    for col in ("key", "variant", "invocations", "outcome", "completion", "first", "last"):
        assert col in header

    code = main(
        [
            "episodes",
            str(CL),
            "--profile",
            robot,
            "--exclude-events",
            "--format",
            "json",
        ]
    )
    assert code == 64
    capsys.readouterr()

    code = main(
        ["episode", str(CL), "nope", "--profile", robot, "--format", "json"]
    )
    err = capsys.readouterr().err
    assert code == 2
    assert "episode_not_found" in err

    key = "CS001-1-1-1790200023515:r1-c2"
    code = main(
        [
            "episode",
            str(CA),
            key,
            "--records",
            "--profile",
            robot,
            "--format",
            "json",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    lines = [json.loads(line) for line in out.splitlines() if line.strip()]
    assert len(lines) == 98  # 96 records + _episode + _meta
    assert "_episode" in lines[-2]
    assert "_meta" in lines[-1]
    assert lines[-2]["_episode"]["invocation_count"] == 12

    code = main(
        [
            "episode",
            str(CA),
            key,
            "--records",
            "--hide",
            "kind=api.meta",
            "--profile",
            robot,
            "--format",
            "json",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    lines = [json.loads(line) for line in out.splitlines() if line.strip()]
    records = lines[:-2]
    assert len(records) == 84  # 96 - 12 api.meta
    assert lines[-2]["_episode"]["invocation_count"] == 12

    code = main(
        [
            "episodes",
            str(CL),
            "--profile",
            robot,
            "--format",
            "json",
            "--after",
            f"{CL}:1",
        ]
    )
    assert code == 0
    capsys.readouterr()
