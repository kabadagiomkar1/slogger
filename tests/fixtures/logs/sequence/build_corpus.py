#!/usr/bin/env python3
"""Build the sequence-analysis fixture corpus (source-derived + synthetic).

Run from the repo root after ``pip install -e ".[dev]"``::

    python3 tests/fixtures/logs/sequence/build_corpus.py \\
        --source /path/to/2026-09-23.log

Without ``--source``, only synthetic fixtures are regenerated (source-derived
JSONL must already be present). Generation is deterministic: fixed clocks and
IDs; no sleeps or network.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import secrets
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from slogger import capture_logs, configure, get_logger
from slogger.config import reset
from slogger.schema import validate_log_record

HERE = Path(__file__).resolve().parent
SOURCE_DERIVED = HERE / "source_derived"
SYNTHETIC = HERE / "synthetic"

LINE_RE = re.compile(
    r"^\[(?P<svc>[^\]]+)\] "
    r"\[(?P<ts>\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}\.\d+)\] "
    r"\[(?P<level>\w+)\] : (?P<msg>.*)$"
)
ACTIVITY_RE = re.compile(
    r"^robot_activity_status: (?P<api>[^:]+)::(?P<phase>[^:]+)::(?P<payload>.*)$"
)


def _ts_to_iso(ts: str) -> str:
    """Convert ``DD/MM/YYYY HH:MM:SS.mmm`` bracket times to UTC ISO-8601.

    Bracket times in the attached log align with ``created_at`` UTC fields in
    the same lines (e.g. ``21:44:42`` ↔ ``datetime(..., tzinfo=utc)``). Treated
    as UTC; the DB field ``time_zone: MDT`` is not used for conversion.
    """
    moment = datetime.strptime(ts, "%d/%m/%Y %H:%M:%S.%f").replace(tzinfo=timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def _literal(text: str) -> Any:
    try:
        return ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return None


@dataclass(frozen=True)
class Src:
    line_no: int
    ts: str
    level: str
    msg: str


def _parse_source(path: Path) -> list[Src]:
    out: list[Src] = []
    for i, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        m = LINE_RE.match(raw)
        if not m:
            continue
        out.append(Src(i, m.group("ts"), m.group("level"), m.group("msg")))
    return out


def _base_record(
    src: Src,
    *,
    message: str,
    kind: str,
    fields: dict[str, Any],
) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "timestamp": _ts_to_iso(src.ts),
        "level": src.level,
        "logger": "robotic_arm_service",
        "message": message,
        "file": "converted_from_plain_log",
        "func": "source_derived",
        "line": src.line_no,
        "kind": kind,
        "source_line": src.line_no,
        "service_version": "build-6.0.10",
        "cluster_id": "CS001",
        "entity_id": "R1",
        **fields,
    }
    return rec


def _episode_id_pick(payload: dict[str, Any]) -> str:
    """Deterministic inferred episode key for a pick/basket attempt.

    Derivation (documented uncertainty): API + load_identifier + slide_id +
    basket/zone/row/column. Not present in the source log.
    """
    return (
        f"pick_basket:{payload.get('load_identifier')}:"
        f"slide={payload.get('slide_id')}:"
        f"b{payload.get('basket_number')}-z{payload.get('zone_number')}-"
        f"r{payload.get('row_number')}-c{payload.get('column_number')}"
    )


def _convert_selected(
    lines: list[Src], wanted: set[int]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_no = {s.line_no: s for s in lines}
    records: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    seq = 0

    def emit(src: Src, message: str, kind: str, fields: dict[str, Any], *, note: str) -> None:
        nonlocal seq
        seq += 1
        rec = _base_record(src, message=message, kind=kind, fields=fields)
        rec["fixture_seq"] = seq
        validate_log_record(rec)
        records.append(rec)
        provenance.append(
            {
                "fixture_line": seq,
                "source_line": src.line_no,
                "kind": kind,
                "message": message,
                "classification": note,
            }
        )

    for line_no in sorted(wanted):
        src = by_no[line_no]
        msg = src.msg

        if msg.startswith("API Endpoint: "):
            api = msg.split("API Endpoint: ", 1)[1].strip()
            emit(
                src,
                "api.endpoint",
                "api.request",
                {"api": api, "workflow": api},
                note="observed",
            )
            continue

        if msg.startswith("API Method: "):
            emit(
                src,
                "api.method",
                "api.meta",
                {"http_method": msg.split(": ", 1)[1].strip()},
                note="observed",
            )
            continue

        if msg.startswith("Request Payload: "):
            payload = _literal(msg.split("Request Payload: ", 1)[1])
            fields: dict[str, Any] = {"payload_present": payload is not None}
            if isinstance(payload, dict):
                for key in (
                    "load_identifier",
                    "slide_id",
                    "basket_number",
                    "zone_number",
                    "row_number",
                    "column_number",
                    "scanner_number",
                    "tool_contact",
                    "drop_mode",
                    "pick_from",
                    "action",
                    "move_type",
                ):
                    if key in payload:
                        fields[key] = payload[key]
                if "load_identifier" in payload and "slide_id" in payload:
                    fields["episode_id"] = _episode_id_pick(payload)
                    fields["episode_id_provenance"] = "inferred"
            emit(
                src,
                "api.request_payload",
                "api.payload",
                fields,
                note="observed+inferred_episode_id",
            )
            continue

        am = ACTIVITY_RE.match(msg)
        if am:
            payload = json.loads(am.group("payload")) if am.group("payload") else {}
            fields = {
                "api": am.group("api"),
                "workflow": am.group("api"),
                "activity_phase": am.group("phase"),
            }
            if isinstance(payload, dict):
                for key in (
                    "load_identifier",
                    "slide_id",
                    "basket_number",
                    "zone_number",
                    "row_number",
                    "column_number",
                    "scanner_number",
                    "pick_op_handler",
                    "move_type",
                    "pick_from",
                    "action",
                ):
                    if key in payload:
                        fields[key] = payload[key]
                if "load_identifier" in payload and "slide_id" in payload:
                    fields["episode_id"] = _episode_id_pick(payload)
                    fields["episode_id_provenance"] = "inferred"
            phase = am.group("phase")
            emit(
                src,
                f"activity.{phase}",
                "activity.lifecycle",
                fields,
                note="observed+inferred_episode_id",
            )
            continue

        if msg.startswith("Pick basket handler key: "):
            emit(
                src,
                "pick.handler",
                "step.meta",
                {"pick_op_handler": msg.split(": ", 1)[1].strip()},
                note="observed",
            )
            continue

        if msg.startswith("Robot is not at the correct home"):
            emit(src, "pick.home_mismatch", "step.decision", {}, note="observed")
            continue

        if msg.startswith("Moving to z2_home") or msg.startswith("Moving from pick basket"):
            emit(src, "motion.intent", "command.request", {"detail": msg}, note="observed")
            continue

        if msg.startswith("operation type: "):
            emit(
                src,
                "gripper.operation",
                "step.entry",
                {"operation_type": msg.split(": ", 1)[1].strip()},
                note="observed",
            )
            continue

        if msg.startswith("Slide Present"):
            present = "True" in msg.split(":", 1)[-1]
            emit(
                src,
                "observation.slide_present",
                "observation",
                {"slide_present": present},
                note="observed",
            )
            continue

        if msg.startswith("motion started"):
            emit(src, "motion.started", "command.started", {}, note="observed")
            continue

        if msg.startswith("motion completed successfully"):
            emit(src, "motion.completed", "command.completed", {"motion_ok": True}, note="observed")
            continue

        if msg.startswith("err_msg: Slide not found"):
            emit(
                src,
                "pick.slide_not_found",
                "workflow.error",
                {
                    "error_code": "CLDJ_SLIDE_NOT_FOUND",
                    "err_msg": "Slide not found in the basket",
                    "pick_status": False,
                },
                note="observed",
            )
            continue

        if msg.startswith("Robot not in scanner while moving"):
            emit(
                src,
                "move.position_warning",
                "diagnostic.warning",
                {
                    "error_code": "ROBOT_NOT_IN_CORRECT_POSITION",
                    "err_msg": "Cannot Execute the Path: Robot Arm not in correct Position",
                },
                note="observed",
            )
            continue

        if msg.startswith("API Response: "):
            payload = _literal(msg.split("API Response: ", 1)[1])
            fields = {}
            if isinstance(payload, dict):
                # Application ``status`` must not use the reserved span field name.
                if "status" in payload:
                    fields["api_status"] = payload["status"]
                for key in (
                    "pick_status",
                    "err_msg",
                    "error_code",
                    "slide_error_code",
                    "slide_id",
                    "action",
                    "basket_number",
                    "raw_slide_thickness",
                    "slide_type",
                ):
                    if key in payload and payload[key] != "":
                        fields[key] = payload[key]
                details = payload.get("error_details")
                if isinstance(details, dict):
                    if details.get("api_name"):
                        fields["api"] = details["api_name"]
                        fields["workflow"] = details["api_name"]
                    if details.get("error_root_cause"):
                        fields["error_root_cause"] = details["error_root_cause"]
                    if details.get("service_version"):
                        fields["service_version"] = details["service_version"]
                    if details.get("status"):
                        fields["activity_status"] = details["status"]
                timings = payload.get("module_timings")
                if isinstance(timings, dict) and "total_time" in timings:
                    # Observed wall seconds from the service, not a span duration_ms.
                    fields["total_time_s"] = timings["total_time"]
                    fields["total_time_s_provenance"] = "observed"
            emit(src, "api.response", "api.response", fields, note="observed")
            continue

        if msg.startswith("Total Processing Time for API:"):
            # Skip duplicate of module_timings; keep fixture compact.
            provenance.append(
                {
                    "fixture_line": None,
                    "source_line": src.line_no,
                    "kind": "skipped",
                    "message": "Total Processing Time for API",
                    "classification": "observed_but_omitted_duplicate",
                }
            )
            continue

        # Unclassified wanted line — keep as opaque diagnostic.
        emit(
            src,
            msg[:120],
            "diagnostic.other",
            {"raw_prefix": msg[:80]},
            note="observed_opaque",
        )

    return records, provenance


# Curated source line numbers: successful pick lead-in + imaging warning +
# three consecutive slide-not-found pick attempts. Chosen for sequence design,
# not exhaustive telemetry.
WANTED_LINES = {
    # Successful pick/basket attempt (slide 259811)
    1552,
    1553,
    1556,
    1562,
    1563,
    1573,
    1574,
    1610,
    1651,
    1633,
    1711,
    1744,
    1760,
    1769,
    1843,
    1859,
    1889,
    1895,
    # Imaging after pick: warning then still completes (same load)
    1901,
    1905,
    1906,
    1911,
    1957,
    # Failure cluster: empty slots columns 3,4,5
    8356,
    8357,
    8360,
    8366,
    8367,
    8401,
    8442,
    8464,
    8474,
    8499,
    8512,
    8518,
    8537,
    8538,
    8541,
    8547,
    8548,
    8582,
    8623,
    8645,
    8655,
    8680,
    8693,
    8699,
    8718,
    8719,
    8722,
    8728,
    8729,
    8763,
    8804,
    8826,
    8836,
    8861,
    8874,
    8880,
}


def build_source_derived(source: Path) -> None:
    SOURCE_DERIVED.mkdir(parents=True, exist_ok=True)
    lines = _parse_source(source)
    missing = sorted(WANTED_LINES - {s.line_no for s in lines})
    if missing:
        raise SystemExit(f"source missing expected lines: {missing[:20]}")
    records, provenance = _convert_selected(lines, WANTED_LINES)
    out = SOURCE_DERIVED / "pick_basket_issue_cluster.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, separators=(",", ":"), ensure_ascii=True) + "\n")
    manifest = {
        "schema_version": 1,
        "source_file": source.name,
        "source_sha256_note": "compute locally if needed; upload may be renamed",
        "bracket_time_interpretation": "UTC (aligned with created_at UTC in same log)",
        "episode_id_rule": (
            "pick_basket:{load_identifier}:slide={slide_id}:"
            "b{basket}-z{zone}-r{row}-c{column}"
        ),
        "episode_id_uncertainty": (
            "Inferred for corpus design only; not emitted by the service. "
            "load_identifier alone spans many pick attempts across slots."
        ),
        "no_span_events": True,
        "reason_no_spans": "Source log has no span.start/span.end; activity_phase used instead.",
        "unresolved": [
            "No explicit workflow outcome field distinct from activity completed",
            "No recovery workflow after CLDJ_SLIDE_NOT_FOUND in this slice "
            "(caller moves to next slot)",
            "ROBOT_NOT_IN_CORRECT_POSITION does not abort the imaging activity in this log",
            "No application source in this workspace; interpretations are log-only",
        ],
        "records": len(records),
        "provenance": provenance,
    }
    (SOURCE_DERIVED / "provenance.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


class _DetIds:
    """Process-wide deterministic hex IDs so multi-episode files do not collide."""

    _n = 0

    @classmethod
    def reset(cls, start: int = 0) -> None:
        cls._n = start

    @classmethod
    def token_hex(cls, n: int = 8) -> str:
        cls._n += 1
        return f"{cls._n:0{n * 2}x}"


@contextmanager
def _patched_clock(start: float) -> Iterator[Callable[[float], None]]:
    """Patch clocks and ``secrets.token_hex`` for deterministic emission."""
    state = {"t": start, "p": 0.0}

    def now() -> float:
        return state["t"]

    def perf() -> float:
        return state["p"]

    def advance(dt: float = 0.001) -> None:
        state["t"] += dt
        state["p"] += dt

    import slogger.span as span_mod

    real_time = time.time
    real_perf = time.perf_counter
    real_secrets = secrets.token_hex

    time.time = now  # type: ignore[assignment]
    time.perf_counter = perf  # type: ignore[assignment]
    span_mod.time.perf_counter = perf  # type: ignore[attr-defined]
    secrets.token_hex = _DetIds.token_hex  # type: ignore[assignment]
    try:
        yield advance
    finally:
        time.time = real_time  # type: ignore[assignment]
        time.perf_counter = real_perf  # type: ignore[assignment]
        span_mod.time.perf_counter = real_perf  # type: ignore[attr-defined]
        secrets.token_hex = real_secrets  # type: ignore[assignment]


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            validate_log_record(rec)
            # Stable key order for byte reproducibility.
            fh.write(
                json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
                + "\n"
            )


def _emit_workflow(
    *,
    t0: float,
    workflow: str,
    workflow_id: str,
    steps: list[tuple[str, str, dict[str, Any]]],
    outcome: str,
    background: list[tuple[float, str, dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Emit one workflow via slogger spans + bound fields.

    ``steps`` entries are ``(span_name, status, fields)`` where status is
    ``ok`` or ``error``. Durations are synthetic (fixed advances), not measured.
    """
    reset()
    configure(console=False, level="DEBUG", span_events=True)
    log = get_logger("robotic_arm_service")
    records: list[dict[str, Any]] = []
    bg = list(background or [])
    bg_i = 0

    with _patched_clock(t0) as advance:
        with capture_logs() as captured:
            bound = log.bind(
                workflow=workflow,
                workflow_id=workflow_id,
                service_version="build-6.0.10-synthetic",
                cluster_id="CS001",
                entity_id="R1",
                fixture="synthetic",
            )
            bound.info(
                "workflow.start",
                kind="workflow.lifecycle",
                workflow_outcome="running",
            )
            advance(0.010)
            workflow_error: BaseException | None = None
            try:
                with bound.span("workflow", api=workflow):
                    for name, status, fields in steps:
                        while bg_i < len(bg) and bg[bg_i][0] <= time.time() - t0:
                            _, bmsg, bfields = bg[bg_i]
                            # Background loggers intentionally unbound to workflow.
                            get_logger("robotic_arm_service.bg").info(
                                bmsg, kind="background", fixture="synthetic", **bfields
                            )
                            bg_i += 1
                            advance(0.001)
                        try:
                            with bound.span(name, **fields):
                                bound.info(
                                    "step.body",
                                    kind="step.body",
                                    step=name,
                                )
                                advance(0.050 if status == "ok" else 0.020)
                                if status == "error":
                                    raise RuntimeError(
                                        fields.get("err_msg", "step failed")
                                    )
                        except RuntimeError as exc:
                            workflow_error = exc
                            bound.error(
                                "step.failed",
                                kind="workflow.error",
                                step=name,
                                error_type=type(exc).__name__,
                                err_msg=str(exc),
                                error_code=fields.get("error_code", ""),
                            )
                        advance(0.005)
                    while bg_i < len(bg):
                        _, bmsg, bfields = bg[bg_i]
                        get_logger("robotic_arm_service.bg").info(
                            bmsg, kind="background", fixture="synthetic", **bfields
                        )
                        bg_i += 1
                        advance(0.001)
                    if workflow_error is not None and outcome in ("error", "aborted"):
                        raise workflow_error
            except RuntimeError:
                pass
            bound.info(
                "workflow.end",
                kind="workflow.lifecycle",
                workflow_outcome=outcome,
            )
            records = list(captured)
    reset()
    return records


def build_synthetic() -> None:
    SYNTHETIC.mkdir(parents=True, exist_ok=True)
    # Base epoch: 2026-09-23T22:00:00Z
    t0 = datetime(2026, 9, 23, 22, 0, 0, tzinfo=timezone.utc).timestamp()
    _DetIds.reset(0)

    scenarios: dict[str, list[dict[str, Any]]] = {}

    # 1) Successful pick → place path (one legitimate happy path)
    scenarios["success_pick_place.jsonl"] = _emit_workflow(
        t0=t0,
        workflow="/robotic-arm/pick/basket",
        workflow_id="syn:pick_basket:loadA:slide=1:b2-z1-r1-c1",
        steps=[
            ("move_to_pick", "ok", {"operation_type": "MOVE_TO_PICK"}),
            ("OPEN_AT_PICK_BASKET", "ok", {"operation_type": "OPEN_AT_PICK_BASKET"}),
            (
                "CLOSE_AT_PICK_BASKET",
                "ok",
                {"operation_type": "CLOSE_AT_PICK_BASKET", "slide_present": True},
            ),
            (
                "PARTIAL_OPEN_AT_PICK_BASKET",
                "ok",
                {"operation_type": "PARTIAL_OPEN_AT_PICK_BASKET"},
            ),
            (
                "CLOSE_AT_PICK_BASKET",
                "ok",
                {"operation_type": "CLOSE_AT_PICK_BASKET", "attempt": 2},
            ),
            ("move_scanner_imaging", "ok", {"api": "/robotic-arm/move/scanner/imaging"}),
            ("place_scanner", "ok", {"api": "/robotic-arm/place/scanner"}),
        ],
        outcome="ok",
        background=[(0.030, "is_alive.tick", {"api": "/is_alive"})],
    )

    # 2) Failure then successful recovery (recovery as linked workflow)
    fail_id = "syn:pick_basket:loadB:slide=2:b2-z1-r1-c3"
    recovery_id = "syn:recovery:from=" + fail_id
    part_a = _emit_workflow(
        t0=t0 + 100,
        workflow="/robotic-arm/pick/basket",
        workflow_id=fail_id,
        steps=[
            ("OPEN_AT_PICK_BASKET", "ok", {"operation_type": "OPEN_AT_PICK_BASKET"}),
            (
                "CLOSE_AT_PICK_BASKET",
                "error",
                {
                    "operation_type": "CLOSE_AT_PICK_BASKET",
                    "slide_present": False,
                    "error_code": "CLDJ_SLIDE_NOT_FOUND",
                    "err_msg": "Slide not found in the basket",
                },
            ),
        ],
        outcome="error",
    )
    for rec in part_a:
        if rec.get("message") == "workflow.end":
            rec["triggered_recovery_id"] = recovery_id
            rec["triggered_recovery_id_provenance"] = "synthetic"
    part_b = _emit_workflow(
        t0=t0 + 100.5,
        workflow="/robotic-arm/recovery",
        workflow_id=recovery_id,
        steps=[
            ("OPEN_AT_HOME", "ok", {"operation_type": "OPEN_AT_HOME"}),
            ("move_pick_basket_home", "ok", {"api": "/robotic-arm/move/pick-basket/home"}),
            (
                "CLOSE_AT_PICK_BASKET",
                "ok",
                {"operation_type": "CLOSE_AT_PICK_BASKET", "slide_present": True, "attempt": 2},
            ),
        ],
        outcome="ok",
    )
    for rec in part_b:
        rec["recovery_of"] = fail_id
        rec["recovery_of_provenance"] = "synthetic"
    scenarios["failure_then_recovery.jsonl"] = part_a + part_b

    # 3) Retry exhaustion / abort
    scenarios["retry_exhaustion.jsonl"] = _emit_workflow(
        t0=t0 + 200,
        workflow="/robotic-arm/pick/basket",
        workflow_id="syn:pick_basket:loadC:slide=3:b2-z1-r1-c4",
        steps=[
            (
                "CLOSE_AT_PICK_BASKET",
                "error",
                {
                    "operation_type": "CLOSE_AT_PICK_BASKET",
                    "attempt": 1,
                    "error_code": "CLDJ_SLIDE_NOT_FOUND",
                    "err_msg": "Slide not found in the basket",
                },
            ),
            (
                "CLOSE_AT_PICK_BASKET",
                "error",
                {
                    "operation_type": "CLOSE_AT_PICK_BASKET",
                    "attempt": 2,
                    "error_code": "CLDJ_SLIDE_NOT_FOUND",
                    "err_msg": "Slide not found in the basket",
                },
            ),
            (
                "CLOSE_AT_PICK_BASKET",
                "error",
                {
                    "operation_type": "CLOSE_AT_PICK_BASKET",
                    "attempt": 3,
                    "error_code": "CLDJ_SLIDE_NOT_FOUND",
                    "err_msg": "Slide not found in the basket",
                },
            ),
            (
                "abort",
                "error",
                {"error_code": "PICK_RETRY_EXHAUSTED", "err_msg": "retries exhausted"},
            ),
        ],
        outcome="aborted",
    )

    # 4) Incomplete workflow (no workflow.end)
    reset()
    configure(console=False, level="DEBUG", span_events=True)
    with _patched_clock(t0 + 300) as advance:
        with capture_logs() as captured:
            log = get_logger("robotic_arm_service").bind(
                workflow="/robotic-arm/pick/basket",
                workflow_id="syn:pick_basket:loadD:incomplete",
                fixture="synthetic",
                service_version="build-6.0.10-synthetic",
            )
            log.info("workflow.start", kind="workflow.lifecycle", workflow_outcome="running")
            advance(0.01)
            with log.span("OPEN_AT_PICK_BASKET", operation_type="OPEN_AT_PICK_BASKET"):
                log.info("step.body", kind="step.body")
                advance(0.05)
            # Intentionally no workflow.end / no terminal CLOSE step.
        scenarios["incomplete_workflow.jsonl"] = list(captured)
    reset()

    # 5) Repeated steps where attempt identity matters + equal timestamps
    reset()
    configure(console=False, level="DEBUG", span_events=True)
    with _patched_clock(t0 + 400) as advance:
        with capture_logs() as captured:
            log = get_logger("robotic_arm_service").bind(
                workflow="/robotic-arm/pick/basket",
                workflow_id="syn:pick_basket:loadE:attempts",
                fixture="synthetic",
            )
            log.info("workflow.start", kind="workflow.lifecycle")
            for attempt in (1, 2, 3):
                # Equal timestamp: two records without advance between them.
                log.info(
                    "observation.slide_present",
                    kind="observation",
                    slide_present=False,
                    attempt=attempt,
                    step_occurrence_id=f"close-{attempt}",
                )
                log.info(
                    "gripper.operation",
                    kind="step.entry",
                    operation_type="CLOSE_AT_PICK_BASKET",
                    attempt=attempt,
                    step_occurrence_id=f"close-{attempt}",
                )
                advance(0.01)
            log.info("workflow.end", kind="workflow.lifecycle", workflow_outcome="error")
        scenarios["repeated_steps_equal_ts.jsonl"] = list(captured)
    reset()

    # 6) Interleaved background + separate episodes (two workflows)
    ep1 = _emit_workflow(
        t0=t0 + 500,
        workflow="/robotic-arm/pick/basket",
        workflow_id="syn:pick_basket:loadF:ep1",
        steps=[
            ("OPEN_AT_PICK_BASKET", "ok", {}),
            ("CLOSE_AT_PICK_BASKET", "ok", {"slide_present": True}),
        ],
        outcome="ok",
        background=[(0.02, "buffer.overflow", {"api": "internal"})],
    )
    ep2 = _emit_workflow(
        t0=t0 + 500.2,
        workflow="/robotic-arm/place/scanner",
        workflow_id="syn:place_scanner:loadF:ep2",
        steps=[
            ("place_scanner", "ok", {"api": "/robotic-arm/place/scanner"}),
        ],
        outcome="ok",
        background=[(0.01, "is_alive.tick", {"api": "/is_alive"})],
    )
    # Merge by timestamp to simulate interleaving in one file.
    scenarios["interleaved_episodes.jsonl"] = sorted(
        ep1 + ep2, key=lambda r: (r["timestamp"], r.get("workflow_id", ""), r["message"])
    )

    # 7) Near-match wrong order (same names, different order) — single episode
    scenarios["near_match_wrong_order.jsonl"] = _emit_workflow(
        t0=t0 + 600,
        workflow="/robotic-arm/pick/basket",
        workflow_id="syn:pick_basket:loadG:wrong_order",
        steps=[
            ("CLOSE_AT_PICK_BASKET", "ok", {"slide_present": True}),
            ("OPEN_AT_PICK_BASKET", "ok", {}),
            ("place_scanner", "ok", {}),
        ],
        outcome="ok",
    )

    # 8) Alternate legitimate success path (home correction before pick)
    scenarios["success_with_home_correction.jsonl"] = _emit_workflow(
        t0=t0 + 700,
        workflow="/robotic-arm/pick/basket",
        workflow_id="syn:pick_basket:loadH:home_corr",
        steps=[
            ("home_mismatch", "ok", {"detail": "Robot is not at the correct home to pick"}),
            ("move_z2_home", "ok", {}),
            ("OPEN_AT_PICK_BASKET", "ok", {}),
            ("CLOSE_AT_PICK_BASKET", "ok", {"slide_present": True}),
            ("place_scanner", "ok", {}),
        ],
        outcome="ok",
    )

    for name, recs in scenarios.items():
        _write_jsonl(SYNTHETIC / name, recs)

    index = {
        "schema_version": 1,
        "generator": "tests/fixtures/logs/sequence/build_corpus.py",
        "synthetic_note": (
            "Durations, span IDs, and workflow_outcome values are synthetic. "
            "Vocabulary (API paths, operation_type, error codes) is taken from "
            "the 2026-09-23 robotic_arm_service log."
        ),
        "files": {name: len(recs) for name, recs in scenarios.items()},
    }
    (SYNTHETIC / "index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        help="Path to the attached plain-text robotic_arm_service log",
    )
    parser.add_argument(
        "--skip-source",
        action="store_true",
        help="Only regenerate synthetic fixtures",
    )
    args = parser.parse_args()
    if not args.skip_source:
        if args.source is None:
            raise SystemExit("--source is required unless --skip-source")
        build_source_derived(args.source)
    build_synthetic()
    print("Wrote", SOURCE_DERIVED)
    print("Wrote", SYNTHETIC)


if __name__ == "__main__":
    main()
