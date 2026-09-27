from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from slogger.tools import (
    FINGERPRINT_VERSION,
    extract_episodes,
    load_profile,
)
from slogger.tools.seq.paths import collapse, fingerprint, path_tokens, paths

REPO_ROOT = Path(__file__).resolve().parents[1]
SEQ = REPO_ROOT / "tests/fixtures/logs/sequence"
ROBOT_PATH = SEQ / "profiles/robotic_arm_observed.json"
SYNTH_PATH = SEQ / "profiles/synthetic_workflow.json"
CA = SEQ / "source_derived/full_slide_cycle_a.jsonl"
CB = SEQ / "source_derived/full_slide_cycle_b.jsonl"
CL = SEQ / "source_derived/pick_basket_issue_cluster.jsonl"
CA_ENR = SEQ / "enriched/full_slide_cycle_a.spans.jsonl"
CB_ENR = SEQ / "enriched/full_slide_cycle_b.spans.jsonl"

CYCLE_A_TOKENS = (
    "/robotic-arm/pick/basket, OPEN_AT_PICK_BASKET, CLOSE_AT_PICK_BASKET, "
    "observation.slide_present=true, /robotic-arm/move/scanner/imaging, "
    "/robotic-arm/scanner/adjust-position, /robotic-arm/place/scanner, "
    "PARTIAL_OPEN_AT_SCANNER_PLACE, /robotic-arm/move/scanner/open-pose, "
    "OPEN_AT_SCANNER_PLACE, /robotic-arm/move/scanner/open-pose/home, "
    "CLOSE_AT_HOME, observation.slide_present=false, OPEN_AT_HOME, "
    "/robotic-arm/move/pick-basket/home, /robotic-arm/move/scanner/open-pose, "
    "EXTREME_OPEN_AT_HOME_FOR_SCANNER_PICK, /robotic-arm/move/scanner/pick, "
    "CLOSE_AT_SCANNER_PICK, observation.slide_present=true, "
    "/robotic-arm/pick/scanner, /robotic-arm/move/scanner/open-pose, "
    "/robotic-arm/drop-slide, OPEN_AT_PICK_BASKET"
).split(", ")


@pytest.fixture(autouse=True)
def _chdir_repo(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)


@pytest.fixture(scope="module")
def robot():
    return load_profile(ROBOT_PATH)


@pytest.fixture(scope="module")
def synth():
    return load_profile(SYNTH_PATH)


def test_cycle_tokens_and_fingerprint(robot):
    ca = extract_episodes(CA, profile=robot, top=None).episodes[0]
    cb = extract_episodes(CB, profile=robot, top=None).episodes[0]
    assert path_tokens(ca, "app") == CYCLE_A_TOKENS
    assert path_tokens(cb, "app") == CYCLE_A_TOKENS
    fp_a = fingerprint(robot, "app", path_tokens(ca, "app"))
    fp_b = fingerprint(robot, "app", path_tokens(cb, "app"))
    assert fp_a == fp_b
    assert path_tokens(ca, "invocation") == [inv.name for inv in ca.invocations]

    ca_e = extract_episodes(CA_ENR, profile=robot, top=None).episodes[0]
    cb_e = extract_episodes(CB_ENR, profile=robot, top=None).episodes[0]
    assert fingerprint(robot, "app", path_tokens(ca_e, "app")) == fp_a
    assert fingerprint(robot, "app", path_tokens(cb_e, "app")) == fp_a


def test_fingerprint_inputs(robot, monkeypatch):
    tokens = ["a", "b"]
    base = fingerprint(robot, "app", tokens)
    assert fingerprint(replace(robot, profile_version="2"), "app", tokens) != base
    assert fingerprint(robot, "invocation", tokens) != base
    monkeypatch.setitem(fingerprint.__globals__, "FINGERPRINT_VERSION", 99)
    assert fingerprint(robot, "app", tokens) != base
    assert FINGERPRINT_VERSION == 1  # package export unchanged


def test_synthetic_span_paths(synth):
    success = extract_episodes(
        SEQ / "synthetic/success_pick_place.jsonl", profile=synth, top=None
    ).episodes[0]
    home = extract_episodes(
        SEQ / "synthetic/success_with_home_correction.jsonl", profile=synth, top=None
    ).episodes[0]
    assert success.outcome.value == "ok"
    assert home.outcome.value == "ok"
    t_s = path_tokens(success, "span")
    t_h = path_tokens(home, "span")
    assert t_s[-1] == "workflow"
    assert t_h[-1] == "workflow"
    assert fingerprint(synth, "span", t_s) != fingerprint(synth, "span", t_h)
    assert set(t_s) == {
        "move_to_pick",
        "OPEN_AT_PICK_BASKET",
        "CLOSE_AT_PICK_BASKET",
        "PARTIAL_OPEN_AT_PICK_BASKET",
        "move_scanner_imaging",
        "place_scanner",
        "workflow",
    }
    assert set(t_h) == {
        "home_mismatch",
        "move_z2_home",
        "OPEN_AT_PICK_BASKET",
        "CLOSE_AT_PICK_BASKET",
        "place_scanner",
        "workflow",
    }


def test_collapse_adjacent_only(synth):
    repeated = extract_episodes(
        SEQ / "synthetic/repeated_steps_equal_ts.jsonl", profile=synth, top=None
    ).episodes[0]
    tokens = path_tokens(repeated, "app")
    assert tokens == [
        "observation.slide_present=false",
        "CLOSE_AT_PICK_BASKET",
        "observation.slide_present=false",
        "CLOSE_AT_PICK_BASKET",
        "observation.slide_present=false",
        "CLOSE_AT_PICK_BASKET",
    ]
    from slogger.tools.seq.paths import _token_refs

    refs = _token_refs(repeated, "app")
    collapsed = collapse(tokens, refs)
    assert len(collapsed) == 6
    assert all(row["count"] == 1 for row in collapsed)

    retry = extract_episodes(
        SEQ / "synthetic/retry_exhaustion.jsonl", profile=synth, top=None
    ).episodes[0]
    span_tokens = path_tokens(retry, "span")
    refs = _token_refs(retry, "span")
    collapsed = collapse(span_tokens, refs)
    assert collapsed[0]["token"] == "CLOSE_AT_PICK_BASKET"
    assert collapsed[0]["count"] == 3
    assert len(collapsed[0]["refs"]) == 3
    assert [row["token"] for row in collapsed[1:]] == ["abort", "workflow"]


def test_paths_cluster_groups(robot):
    payload = paths(CL, profile=robot, top=None)
    assert "anomaly" not in str(payload)
    assert payload["fingerprint_version"] == 1
    assert payload["profile"]["name"] == "robotic-arm-observed"
    assert payload["granularity"] == "app"
    assert len(payload["paths"]) == 2
    # one singleton r1-c1, one group of three empty-slot episodes
    sizes = sorted(len(g["episodes"]) for g in payload["paths"])
    assert sizes == [1, 3]
    triple = next(g for g in payload["paths"] if len(g["episodes"]) == 3)
    assert triple["outcomes"] == {"error": 3}


def test_show_background(synth):
    payload = paths(
        SEQ / "synthetic/success_pick_place.jsonl",
        profile=synth,
        show_background=True,
        top=None,
    )
    refs = payload["paths"][0].get("background_refs", [])
    assert refs  # is_alive.tick inherited workflow_id
    tokens = payload["paths"][0]["tokens"]
    assert "is_alive.tick" not in tokens


def test_paths_cli(capsys):
    from slogger.cli import main

    code = main(
        [
            "paths",
            str(CL),
            "--profile",
            str(ROBOT_PATH),
            "--format",
            "table",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    header = out.splitlines()[0]
    for col in ("fingerprint", "episodes", "outcomes", "completion", "tokens"):
        assert col in header
