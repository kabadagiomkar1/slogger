"""Qualification exercises observe installed Investigation contracts."""

import asyncio

import pytest
from benchmarks.investigation_qualification import (
    Evidence,
    Sampler,
    native_phase,
    qualify_admission_case,
    qualify_disk_refusal,
)

from slogger.tools import Investigation, parse_filter


def test_encoded_admission_refusal_keeps_prefix_and_gates_complete_operations(tmp_path):
    report = qualify_admission_case(
        tmp_path, name="encoded-over", target_line_bytes=1025, max_record_bytes=1024
    )
    assert report["capture_status"]["phase"] == "failed"
    assert report["diagnostic"]["code"] == "record_too_large"
    assert report["retained_messages"] == ["admitted prefix"]
    assert report["global_operation_error"] == "dataset_incomplete"
    assert report["closed_allocated_bytes"] == 0


@pytest.mark.parametrize("durable", [False, True])
def test_combined_refresh_refusal_preserves_old_owner_and_successful_view(tmp_path, durable):
    report = qualify_disk_refusal(tmp_path, durable=durable)
    assert report["refresh_status"]["phase"] == "failed"
    assert report["refresh_status"]["diagnostic"]["code"] == "resource_limit"
    assert report["old_owner_complete"]
    assert report["old_view_count"] == 2
    assert report["old_first_message"] == "admitted prefix"
    assert report["old_identity_unchanged"]
    assert report["reserved_after_close"] == 0


def test_native_measurement_cleanup_preserves_owner_and_kept_view_for_refresh(tmp_path):
    source = tmp_path / "native.jsonl"
    source.write_text('{"message":"first","service":"checkout","cost_units":1}\n' * 8)
    session = Investigation.open([source], storage_dir=tmp_path / "native-managed")
    view = session.filter(parse_filter("exists(message)")).wait()
    assert view is not None
    before = view.page(0, 1).identities
    evidence = Evidence(tmp_path / "native-evidence")
    sampler = Sampler(evidence, tmp_path / "native-managed")
    sampler.session = session
    try:
        asyncio.run(
            native_phase(session, evidence, sampler, idle_seconds=0, navigation_keys=("down",))
        )
        assert session.status.complete
        assert view.record_count == 8 and view.page(0, 1).identities == before
        refresh = session.refresh(background=True)
        try:
            replacement = refresh.wait()
            assert replacement is not None and replacement.status.complete
            assert replacement.restore_record(session, before[0]).identity is not None
        finally:
            refresh.close()
        assert session.status.complete and view.page(0, 1).identities == before
    finally:
        view.close()
        session.close()
        evidence.close()


@pytest.mark.parametrize("line_bytes", [1023, 1024])
def test_admitted_record_envelope_runs_complete_operations(tmp_path, line_bytes):
    report = qualify_admission_case(
        tmp_path, name=f"encoded-{line_bytes}", target_line_bytes=line_bytes, max_record_bytes=1024
    )
    assert report["capture_status"]["phase"] == "complete"
    assert report["record_count"] == 3
    assert report["operations_verified"] == ["filter", "search", "numeric", "discovery", "tree"]
    assert report["closed_allocated_bytes"] == 0


def test_operation_refusal_reports_stricter_decoded_envelope_without_losing_owner(tmp_path):
    report = qualify_admission_case(
        tmp_path, name="decoded-tree-refusal", decoded_items=3000, working_memory_bytes=1024 * 1024
    )
    assert report["capture_status"]["phase"] == "complete"
    assert report["record_count"] == report["old_record_count_after_refusal"] == 3
    assert report["operation_refusals"][0]["name"] == "tree"
    assert report["operation_refusals"][0]["status"]["diagnostic"]["code"] == "resource_limit"
    assert report["closed_allocated_bytes"] == 0


@pytest.mark.parametrize("shape", ["encoded", "decoded", "refused"])
def test_native_envelope_verifies_whole_candidate_or_explicit_retained_prefix(tmp_path, shape):
    from benchmarks.investigation_oracles import write_decoded_probe, write_encoded_probe
    from benchmarks.investigation_qualification import native_envelope_phase

    from slogger.tools import ResourceLimits

    source = tmp_path / "candidate.jsonl"
    if shape == "decoded":
        write_decoded_probe(source, 1000)
    else:
        write_encoded_probe(source, 1024 if shape == "encoded" else 1025)
    source.write_bytes(
        b'{"message":"admitted prefix"}\n'
        + source.read_bytes()
        + b'{"message":"after candidate"}\n'
    )
    session = Investigation.open(
        [source],
        storage_dir=tmp_path / "managed",
        limits=ResourceLimits(max_record_bytes=1024 * (10 if shape == "decoded" else 1)),
    )
    evidence = Evidence(tmp_path / "evidence")
    sampler = Sampler(evidence, tmp_path / "managed")
    try:
        report = asyncio.run(native_envelope_phase(session, evidence, sampler))
        assert report["owner_usable"]
        if shape == "refused":
            assert report["capture_refusal"] == "record_too_large"
        else:
            assert report["full_json_verified"] and report["navigation_after_candidate"]
            assert report["candidate_items"] == (1000 if shape == "decoded" else 0)
        assert session.page(0, 1).records == [{"message": "admitted prefix"}]
    finally:
        session.close()
        evidence.close()


def test_browsing_candidate_checks_complete_forward_and_reverse_populations(tmp_path):
    from benchmarks.investigation_fixtures import smoke_fixture
    from benchmarks.investigation_qualification import browsing_pass

    manifest = smoke_fixture(tmp_path / "fixtures")
    files = manifest["files"]
    assert isinstance(files, list)
    paths = [item["path"] for item in files]
    with Investigation.open(paths, storage_dir=tmp_path / "managed") as owner:
        for reverse in (False, True):
            report = browsing_pass(owner, files, paths, reverse=reverse)
            assert report["records_verified"] == 624
            assert report["page_calls"] == sum(report["latency_bucket_counts"]) == 3
            assert owner.resources.reserved_disk_bytes == 0
