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
EXPECTATIONS = SEQ / "expectations.json"
SYNTHETIC = SEQ / "synthetic"


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
    assert "pick_basket:CS001-1-1-1790200023515:slide=259969:b1-z1-r2-c9" in episodes
    assert "pick_basket:CS001-1-1-1790200023515:slide=259970:b1-z1-r2-c10" in episodes
    assert not any(r.get("event") in ("span.start", "span.end") for r in records)
    assert not any("recovery_of" in r for r in records)


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
        "source_derived/pick_basket_issue_cluster.jsonl",
        "source_derived/force_exit_retry_abort.jsonl",
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
