"""Checks for the exploratory sequence-analysis fixture corpus."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from slogger.schema import validate_log_record
from slogger.tools.validate import validate as validate_sources

REPO = Path(__file__).resolve().parent.parent
SEQ = REPO / "tests" / "fixtures" / "logs" / "sequence"
BUILD = SEQ / "build_corpus.py"
SOURCE_JSONL = SEQ / "source_derived" / "pick_basket_issue_cluster.jsonl"
PROVENANCE = SEQ / "source_derived" / "provenance.json"
FORCE_EXIT_JSONL = SEQ / "source_derived" / "force_exit_retry_abort.jsonl"
FORCE_EXIT_PROVENANCE = SEQ / "source_derived" / "provenance_force_exit.json"
FULL_CYCLE_A = SEQ / "source_derived" / "full_slide_cycle_a.jsonl"
FULL_CYCLE_B = SEQ / "source_derived" / "full_slide_cycle_b.jsonl"
ENRICHED = SEQ / "enriched"
EXPECTATIONS = SEQ / "expectations.json"
SYNTHETIC = SEQ / "synthetic"

_CORE_CYCLE_APIS = (
    "/robotic-arm/pick/basket",
    "/robotic-arm/place/scanner",
    "/robotic-arm/pick/scanner",
    "/robotic-arm/drop-slide",
)


def _jsonl_paths() -> list[Path]:
    return sorted(SEQ.rglob("*.jsonl"))


def test_all_jsonl_records_validate() -> None:
    paths = _jsonl_paths()
    assert paths, "expected committed sequence fixtures"
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            validate_log_record(json.loads(line))


def test_validate_tool_reports_clean() -> None:
    paths = [str(p.relative_to(REPO)) for p in _jsonl_paths()]
    result = validate_sources(paths)
    assert result["invalid"] == 0
    assert result["valid"] > 0


def test_provenance_maps_fixture_lines() -> None:
    manifest = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    records = [
        json.loads(line)
        for line in SOURCE_JSONL.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert manifest["records"] == len(records)
    assert manifest["no_span_events"] is True
    mapped = [p for p in manifest["provenance"] if p.get("fixture_line") is not None]
    assert len(mapped) == len(records)
    for entry, rec in zip(mapped, records, strict=True):
        assert entry["source_line"] == rec["source_line"]
        assert entry["fixture_line"] == rec["fixture_seq"]


def test_source_derived_preserves_failure_codes() -> None:
    records = [
        json.loads(line)
        for line in SOURCE_JSONL.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    codes = {r.get("error_code") or r.get("slide_error_code") for r in records}
    assert "CLDJ_SLIDE_NOT_FOUND" in codes
    assert "ROBOT_NOT_IN_CORRECT_POSITION" in codes
    # No fabricated span events in source-derived corpus.
    assert not any(r.get("event") in ("span.start", "span.end") for r in records)


def test_force_exit_provenance_maps_fixture_lines() -> None:
    manifest = json.loads(FORCE_EXIT_PROVENANCE.read_text(encoding="utf-8"))
    records = [
        json.loads(line)
        for line in FORCE_EXIT_JSONL.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert manifest["records"] == len(records)
    assert manifest["has_error_level_lines"] is True
    mapped = [p for p in manifest["provenance"] if p.get("fixture_line") is not None]
    assert len(mapped) == len(records)
    for entry, rec in zip(mapped, records, strict=True):
        assert entry["source_line"] == rec["source_line"]
        assert entry["fixture_line"] == rec["fixture_seq"]


def test_force_exit_source_preserves_codes_and_abort() -> None:
    records = [
        json.loads(line)
        for line in FORCE_EXIT_JSONL.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    codes = {r.get("error_code") or r.get("slide_error_code") for r in records}
    assert "E-200" in codes
    assert "RA_CANNOT_PICK_FROM_BASKET_MULTIPLE_ATTEMPTS" in codes
    assert any(r.get("message") == "pick.retry_loop_abort" for r in records)
    assert any(r.get("message") == "force.stop_playing" for r in records)
    # Failed episode then next-slot success remain distinct.
    episodes = {r.get("episode_id") for r in records if r.get("episode_id")}
    assert "CS001-1-1-1790200023515:r2-c9" in episodes
    assert "CS001-1-1-1790200023515:r2-c10" in episodes
    assert not any(r.get("event") in ("span.start", "span.end") for r in records)
    assert not any("recovery_of" in r for r in records)


@pytest.mark.parametrize(
    ("path", "episode_id"),
    [
        (FULL_CYCLE_A, "CS001-1-1-1790200023515:r1-c2"),
        (FULL_CYCLE_B, "CS001-1-1-1790200023515:r1-c20"),
    ],
)
def test_full_slide_cycle_core_api_order(path: Path, episode_id: str) -> None:
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert records
    assert all(r.get("episode_id") == episode_id for r in records)
    completed = [
        r["api"]
        for r in records
        if r.get("message") == "activity.completed" and r.get("api") in _CORE_CYCLE_APIS
    ]
    assert completed == list(_CORE_CYCLE_APIS)
    assert any(r.get("place_status") is True for r in records)
    assert any(r.get("pick_status") is True for r in records)
    assert not any(r.get("event") in ("span.start", "span.end") for r in records)


def test_parallel_gripper_does_not_close_arm_motion() -> None:
    records = [
        json.loads(line)
        for line in FULL_CYCLE_A.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    home = [
        r
        for r in records
        if r.get("motion") == "move_trajectory" and r.get("goal") == "z1_home"
    ]
    assert home
    assert all(r.get("motion_ok") is True for r in home)
    overlapped = next(r for r in home if r.get("source_line") == 5993)
    assert overlapped["path"] == ["s1_1", "z1_c_conv_a", "z1_home_a"]
    assert all("cmd_str" not in r for r in records)


def test_tool_contact_and_move_to_node_arguments() -> None:
    cycle = [
        json.loads(line)
        for line in FULL_CYCLE_A.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    contact = next(r for r in cycle if r.get("motion") == "tool_contact")
    assert contact["direction"] == [0, -1, 0]
    assert contact["force_threshold"] == 4.0
    assert contact["distance_threshold"] == 0.0046
    assert contact["contact_status"] is True
    assert contact["motion_ok"] is True

    cluster = [
        json.loads(line)
        for line in SOURCE_JSONL.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    node = next(r for r in cluster if r.get("motion") == "move_to_node")
    assert node["pose_node"] == "z2_home_a"
    assert node["motion_ok"] is True
    assert node["episode_id"].endswith(":r1-c5")


def test_synthetic_full_slide_cycle_shares_episode() -> None:
    path = SYNTHETIC / "full_slide_cycle.jsonl"
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {r.get("episode_id") for r in records} == {"syn:CS001-loadJ:r1-c2"}
    ends = [r for r in records if r.get("message") == "workflow.end"]
    assert len(ends) == 5
    assert all(r.get("workflow_outcome") == "ok" for r in ends)
    apis = {r.get("workflow") for r in ends}
    assert apis >= set(_CORE_CYCLE_APIS)


def test_expectations_file_well_formed() -> None:
    data = json.loads(EXPECTATIONS.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["sequence_examples"]
    polarities = {ex["polarity"] for ex in data["sequence_examples"]}
    assert "positive" in polarities and "negative" in polarities
    for ex in data["sequence_examples"]:
        for rel in ex.get("files", []):
            assert (SEQ / rel).is_file(), rel


def test_synthetic_scenarios_present() -> None:
    index = json.loads((SYNTHETIC / "index.json").read_text(encoding="utf-8"))
    for name, count in index["files"].items():
        path = SYNTHETIC / name
        assert path.is_file()
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(lines) == count


def test_synthetic_regeneration_is_byte_identical() -> None:
    before = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in SYNTHETIC.glob("*.jsonl")
    }
    assert before
    enriched_before = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in ENRICHED.glob("*.spans.jsonl")
    }
    proc = subprocess.run(
        [sys.executable, str(BUILD), "--skip-source"],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    after = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in SYNTHETIC.glob("*.jsonl")
    }
    assert before == after
    enriched_after = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in ENRICHED.glob("*.spans.jsonl")
    }
    assert enriched_before
    assert enriched_before == enriched_after


def test_source_derived_remain_span_free() -> None:
    for path in (SOURCE_JSONL, FORCE_EXIT_JSONL, FULL_CYCLE_A, FULL_CYCLE_B):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            assert rec.get("event") not in ("span.start", "span.end"), path.name


def test_enriched_spans_preserve_originals_and_mark_provenance() -> None:
    index = json.loads((ENRICHED / "index.json").read_text(encoding="utf-8"))
    assert index["files"]
    for out_name, meta in index["files"].items():
        enriched = [
            json.loads(line)
            for line in (ENRICHED / out_name).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        original = [
            json.loads(line)
            for line in (SEQ / meta["source"]).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert meta["original_records"] == len(original)
        # Every original source_line still present.
        orig_lines = {r["source_line"] for r in original if "source_line" in r}
        kept = {
            r["source_line"]
            for r in enriched
            if r.get("span_enrichment") != "proposed" and "source_line" in r
        }
        assert orig_lines <= kept
        span_ends = [r for r in enriched if r.get("event") == "span.end"]
        assert span_ends
        for rec in span_ends:
            assert rec.get("span_enrichment") == "proposed"
            assert rec.get("duration_ms_provenance") == "derived_from_timestamps"
            assert rec.get("span_boundary_end") in ("observed", "inferred")
            assert "source_line_end" in rec or rec.get("span") == "episode"


def test_enriched_force_exit_retry_loop_under_api() -> None:
    path = ENRICHED / "force_exit_retry_abort.spans.jsonl"
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    retry_ends = [
        r
        for r in records
        if r.get("event") == "span.end" and r.get("span") == "retry_loop"
    ]
    assert len(retry_ends) == 1
    assert retry_ends[0]["status"] == "error"
    assert retry_ends[0]["workflow_outcome"] == "aborted"
    assert retry_ends[0]["span_boundary_end"] == "observed"
    # Parent chain: retry → api → episode via parent_span_id
    retry_start = next(
        r
        for r in records
        if r.get("event") == "span.start" and r.get("span") == "retry_loop"
    )
    assert retry_start["span_boundary_start"] == "inferred"
    api_start = next(
        r
        for r in records
        if r.get("event") == "span.start"
        and r.get("span") == "api./robotic-arm/pick/basket"
        and r.get("episode_id") == "CS001-1-1-1790200023515:r2-c9"
    )
    assert retry_start["parent_span_id"] == api_start["span_id"]
    episode_start = next(
        r
        for r in records
        if r.get("event") == "span.start"
        and r.get("span") == "episode"
        and r.get("episode_id") == "CS001-1-1-1790200023515:r2-c9"
    )
    assert api_start["parent_span_id"] == episode_start["span_id"]


def test_enriched_readable_by_tree() -> None:
    from slogger.tools.tree import tree

    rows = tree(str((ENRICHED / "force_exit_retry_abort.spans.jsonl").relative_to(REPO)))
    assert rows


def test_equal_timestamps_in_repeated_steps_fixture() -> None:
    path = SYNTHETIC / "repeated_steps_equal_ts.jsonl"
    stamps = [
        json.loads(line)["timestamp"]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(stamps) != len(set(stamps))


def test_failure_then_recovery_keeps_both_outcomes() -> None:
    path = SYNTHETIC / "failure_then_recovery.jsonl"
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    ends = [r for r in records if r.get("message") == "workflow.end"]
    outcomes = {r["workflow_id"]: r["workflow_outcome"] for r in ends}
    assert outcomes["syn:pick_basket:loadB:slide=2:b2-z1-r1-c3"] == "error"
    assert (
        outcomes["syn:recovery:from=syn:pick_basket:loadB:slide=2:b2-z1-r1-c3"] == "ok"
    )


def test_incomplete_workflow_lacks_workflow_end() -> None:
    path = SYNTHETIC / "incomplete_workflow.jsonl"
    messages = [
        json.loads(line)["message"]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert "workflow.start" in messages
    assert "workflow.end" not in messages


@pytest.mark.parametrize(
    "rel",
    [
        "synthetic/success_pick_place.jsonl",
        "synthetic/near_match_wrong_order.jsonl",
        "synthetic/force_exit_retry_abort.jsonl",
        "synthetic/full_slide_cycle.jsonl",
        "source_derived/pick_basket_issue_cluster.jsonl",
        "source_derived/force_exit_retry_abort.jsonl",
        "source_derived/full_slide_cycle_a.jsonl",
        "source_derived/full_slide_cycle_b.jsonl",
    ],
)
def test_fixture_readable_by_query(rel: str) -> None:
    from slogger.tools.query import query

    page = query(str((SEQ / rel).relative_to(REPO)), limit=5)
    assert page.records


def test_synthetic_force_exit_aborts() -> None:
    path = SYNTHETIC / "force_exit_retry_abort.jsonl"
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    ends = [r for r in records if r.get("message") == "workflow.end"]
    assert ends
    assert ends[-1]["workflow_outcome"] == "aborted"
    codes = {r.get("error_code") for r in records if r.get("error_code")}
    assert "E-200" in codes
    assert "RA_CANNOT_PICK_FROM_BASKET_MULTIPLE_ATTEMPTS" in codes
