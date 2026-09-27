#!/usr/bin/env python3
"""Build the sequence-analysis fixture corpus (source-derived + synthetic).

Run from the repo root after ``pip install -e ".[dev]"``::

    python3 tests/fixtures/logs/sequence/build_corpus.py \\
        --source /path/to/2026-09-23.log \\
        --source-sep24 /path/to/2026-09-24-truncated.log

``--source`` rebuilds the Sep 23 slide-not-found cluster and full cycle A;
``--source-sep24`` rebuilds force-exit, full cycle B.
``--skip-source`` regenerates synthetic fixtures and span-enriched variants
from already-committed source-derived JSONL. Generation is deterministic:
fixed clocks and IDs; no sleeps or network.

See ``docs/plans/sequence-spans.md`` for the proposed span hierarchy. Source-
derived fixtures stay span-free; enriched copies live under ``enriched/``.
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
ENRICHED = HERE / "enriched"

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


def _episode_id_slot(payload: dict[str, Any]) -> str | None:
    """Episode key for a basket-slot attempt.

    Domain rule: ``load_identifier`` + ``row_number`` + ``column_number``
    uniquely identify an episode. Not emitted by the service; inferred in the
    corpus only. ``slide_id`` / basket / zone remain diagnostic fields.
    """
    load = payload.get("load_identifier")
    row = payload.get("row_number")
    col = payload.get("column_number")
    if load is None or row is None or col is None:
        return None
    return f"{load}:r{row}-c{col}"


def _convert_selected(
    lines: list[Src], wanted: set[int]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_no = {s.line_no: s for s in lines}
    records: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    seq = 0
    # Carry episode_id across APIs that omit load/row/col (e.g. imaging).
    current_episode: str | None = None

    def emit(src: Src, message: str, kind: str, fields: dict[str, Any], *, note: str) -> None:
        nonlocal seq, current_episode
        if "episode_id" in fields:
            current_episode = fields["episode_id"]
        elif current_episode is not None and "episode_id" not in fields:
            fields = {
                **fields,
                "episode_id": current_episode,
                "episode_id_provenance": "carried_forward",
            }
            note = note + "+episode_carried" if note else "episode_carried"
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
            # New pick/basket attempt starts a new slot episode; do not carry the
            # previous episode onto this request line before its payload arrives.
            if api == "/robotic-arm/pick/basket":
                current_episode = None
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
                    "to",
                    "from",
                ):
                    if key in payload:
                        fields[key] = payload[key]
                ep = _episode_id_slot(payload)
                if ep is not None:
                    fields["episode_id"] = ep
                    fields["episode_id_provenance"] = "domain_rule"
            emit(
                src,
                "api.request_payload",
                "api.payload",
                fields,
                note="observed+domain_episode_id",
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
                ep = _episode_id_slot(payload)
                if ep is not None:
                    fields["episode_id"] = ep
                    fields["episode_id_provenance"] = "domain_rule"
            phase = am.group("phase")
            emit(
                src,
                f"activity.{phase}",
                "activity.lifecycle",
                fields,
                note="observed+domain_episode_id",
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

        if msg.startswith("err_msg:") and "err_code:" in msg:
            # e.g. force-exit abort: err_msg: …, err_code: RA_CANNOT_…
            body = msg[len("err_msg:") :].strip()
            err_msg_part, _, code_part = body.partition(", err_code:")
            fields = {
                "err_msg": err_msg_part.strip().rstrip(","),
                "error_code": code_part.strip(),
            }
            emit(src, "workflow.error_detail", "workflow.error", fields, note="observed")
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

        if msg.startswith("Stop playing"):
            # Force threshold trip; code E-200 appears on following handle_* lines.
            force_m = re.search(r"Force is\s+([0-9.]+)", msg)
            fields = {"error_code": "E-200", "force_event": "stop_playing"}
            if force_m:
                fields["force_value"] = float(force_m.group(1))
            emit(src, "force.stop_playing", "force.event", fields, note="observed")
            continue

        if msg.startswith("debug.handle_") and "stop" in msg.split(":", 1)[0]:
            # debug.handle_generic_stop / handle_safety_stop / handle_force_stop
            handler = msg.split(":", 1)[0].removeprefix("debug.")
            fields: dict[str, Any] = {"force_handler": handler, "error_code": "E-200"}
            if "E-200" in msg:
                fields["error_code"] = "E-200"
            emit(src, f"force.{handler}", "force.handler", fields, note="observed")
            continue

        if msg.startswith("recovered from force stop"):
            emit(
                src,
                "force.recovered",
                "force.lifecycle",
                {"force_phase": "recovered"},
                note="observed",
            )
            continue

        if msg.startswith("executing force stop handler"):
            emit(
                src,
                "force.handler_executing",
                "force.lifecycle",
                {"force_phase": "handler_executing"},
                note="observed",
            )
            continue

        if msg.startswith("motion failed"):
            fields = {"motion_ok": False}
            # Exception('…', 'RA_CANNOT_…') or similar
            code_m = re.search(r"'([A-Z0-9_-]+)'\)\s*$", msg)
            if code_m:
                fields["error_code"] = code_m.group(1)
            text_m = re.search(r"Exception\('([^']*)'", msg)
            if text_m:
                fields["err_msg"] = text_m.group(1)
            emit(src, "motion.failed", "command.failed", fields, note="observed")
            continue

        if "breaking out of retry loop" in msg:
            fields = {"retry_outcome": "aborted"}
            code_m = re.search(r"err_code:\s*([A-Z0-9_-]+)", msg)
            if code_m:
                fields["error_code"] = code_m.group(1)
            msg_m = re.search(r"err_msg:\s*(.+?)(?:,\s*err_code:|$)", msg)
            if msg_m:
                fields["err_msg"] = msg_m.group(1).strip()
            emit(
                src,
                "pick.retry_loop_abort",
                "workflow.abort",
                fields,
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
                    "place_status",
                    "slide_placing_status",
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

    # Backfill episode_id onto request/meta lines that precede their payload
    # (e.g. API Endpoint/Method before Request Payload after a pick/basket reset).
    upcoming: str | None = None
    for rec in reversed(records):
        if rec.get("episode_id"):
            upcoming = rec["episode_id"]
        elif upcoming is not None:
            rec["episode_id"] = upcoming
            rec["episode_id_provenance"] = "carried_backward"
            for entry in provenance:
                if entry.get("fixture_line") == rec["fixture_seq"]:
                    entry["classification"] = (
                        str(entry.get("classification") or "observed")
                        + "+episode_backfilled"
                    )
                    break

    return records, provenance


# Curated source line numbers (2026-09-23.log): successful pick lead-in +
# imaging warning + three consecutive slide-not-found pick attempts. Chosen for
# sequence design, not exhaustive telemetry.
WANTED_LINES_SEP23 = {
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

# Curated lines from 2026-09-24-truncated.log: force-stop (E-200) during exit
# from pick slot → OPEN retry → RA_CANNOT_PICK_FROM_BASKET_MULTIPLE_ATTEMPTS
# abort of in-call retry loop → next-slot pick success (adjacent attempt).
WANTED_LINES_SEP24_FORCE_EXIT = {
    # Failed pick r2c9 slide 259969
    27991,
    27992,
    27995,
    28001,
    28002,
    28031,
    28072,
    28088,
    28118,
    28120,
    28126,
    28128,
    28129,
    28130,
    28135,
    28369,
    28370,
    28371,
    28377,
    28383,
    # Next-slot success r2c10 slide 259970 (not recovery_of; new API call)
    28402,
    28403,
    28406,
    28412,
    28442,
    28483,
    28499,
    28539,
    28545,
}

# Full slide cycle (multi-API): pick/basket → imaging/adjust → place/scanner →
# open-pose/home moves → pick/scanner → drop-slide. Same episode_id
# ({load}:r{row}-c{col}) across the chain.
WANTED_LINES_SEP23_FULL_CYCLE = {
    5542,
    5543,
    5546,
    5552,
    5553,
    5582,
    5623,
    5639,
    5669,
    5675,
    5681,
    5682,
    5685,
    5686,
    5735,
    5738,
    5739,
    5742,
    5743,
    5753,
    5828,
    5829,
    5832,
    5833,
    5868,
    5895,
    5914,
    5915,
    5918,
    5919,
    5938,
    5974,
    5977,
    5978,
    5981,
    5982,
    6010,
    6029,
    6039,
    6064,
    6077,
    6078,
    6081,
    6082,
    6097,
    6127,
    6128,
    6131,
    6132,
    6164,
    6186,
    6199,
    6200,
    6203,
    6204,
    6254,
    6270,
    6283,
    6286,
    6289,
    6290,
    6293,
    6294,
    6419,
    6449,
    6450,
    6453,
    6454,
    6486,
    6489,
    6490,
    6493,
    6494,
    6780,
    6935,
    6938,
}

WANTED_LINES_SEP24_FULL_CYCLE = {
    851,
    852,
    855,
    861,
    862,
    890,
    931,
    947,
    977,
    983,
    989,
    990,
    993,
    994,
    1043,
    1046,
    1047,
    1050,
    1051,
    1061,
    1136,
    1137,
    1140,
    1141,
    1176,
    1203,
    1222,
    1223,
    1226,
    1227,
    1247,
    1282,
    1285,
    1286,
    1289,
    1290,
    1312,
    1337,
    1347,
    1372,
    1385,
    1386,
    1389,
    1390,
    1405,
    1435,
    1436,
    1439,
    1440,
    1472,
    1494,
    1507,
    1508,
    1511,
    1512,
    1562,
    1578,
    1591,
    1594,
    1597,
    1598,
    1601,
    1602,
    1727,
    1757,
    1758,
    1761,
    1762,
    1794,
    1797,
    1798,
    1801,
    1802,
    2088,
    2243,
    2246,
}

FULL_CYCLE_CORE_APIS = [
    "/robotic-arm/pick/basket",
    "/robotic-arm/place/scanner",
    "/robotic-arm/pick/scanner",
    "/robotic-arm/drop-slide",
]


def _write_source_fixture(
    *,
    source: Path,
    wanted: set[int],
    out_name: str,
    provenance_name: str,
    unresolved: list[str],
    notes: dict[str, Any] | None = None,
) -> None:
    SOURCE_DERIVED.mkdir(parents=True, exist_ok=True)
    lines = _parse_source(source)
    missing = sorted(wanted - {s.line_no for s in lines})
    if missing:
        raise SystemExit(f"{source.name}: missing expected lines: {missing[:20]}")
    records, provenance = _convert_selected(lines, wanted)
    out = SOURCE_DERIVED / out_name
    with out.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, separators=(",", ":"), ensure_ascii=True) + "\n")
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "source_file": source.name,
        "source_sha256_note": "compute locally if needed; upload may be renamed",
        "bracket_time_interpretation": "UTC (aligned with created_at UTC in same log)",
        "episode_id_rule": "{load_identifier}:r{row_number}-c{column_number}",
        "episode_id_note": (
            "Domain rule: load_identifier + row_number + column_number uniquely "
            "identify a slot episode. Not emitted by the service; derived in the "
            "corpus. slide_id / basket / zone stay as diagnostic fields."
        ),
        "no_span_events": True,
        "reason_no_spans": "Source log has no span.start/span.end; activity_phase used instead.",
        "unresolved": unresolved,
        "records": len(records),
        "provenance": provenance,
    }
    if notes:
        manifest.update(notes)
    (SOURCE_DERIVED / provenance_name).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def build_source_derived_sep23(source: Path) -> None:
    _write_source_fixture(
        source=source,
        wanted=WANTED_LINES_SEP23,
        out_name="pick_basket_issue_cluster.jsonl",
        provenance_name="provenance.json",
        unresolved=[
            "No explicit workflow outcome field distinct from activity completed",
            "No recovery workflow after CLDJ_SLIDE_NOT_FOUND in this slice "
            "(caller moves to next slot)",
            "ROBOT_NOT_IN_CORRECT_POSITION does not abort the imaging activity in this log",
            "No application source in this workspace; interpretations are log-only",
        ],
    )
    _write_source_fixture(
        source=source,
        wanted=WANTED_LINES_SEP23_FULL_CYCLE,
        out_name="full_slide_cycle_a.jsonl",
        provenance_name="provenance_full_slide_cycle_a.json",
        unresolved=[
            "Service does not emit a parent workflow id for the multi-API cycle",
            "Some intermediate APIs omit load/row/col; episode_id is carried forward "
            "in the converter for those records",
            "Vision helper APIs and LED toggles omitted from this fixture",
            "No application source in this workspace; interpretations are log-only",
        ],
        notes={
            "focus": (
                "Complete slide cycle for one slot: pick/basket → place/scanner → "
                "pick/scanner → drop-slide, with key move/adjust APIs between"
            ),
            "episode_id": "CS001-1-1-1790200023515:r1-c2",
            "core_apis": FULL_CYCLE_CORE_APIS,
            "slide_id": 259932,
        },
    )


def build_source_derived_sep24(source: Path) -> None:
    _write_source_fixture(
        source=source,
        wanted=WANTED_LINES_SEP24_FORCE_EXIT,
        out_name="force_exit_retry_abort.jsonl",
        provenance_name="provenance_force_exit.json",
        unresolved=[
            "No explicit attempt counter on the post-force OPEN_AT_PICK_BASKET",
            "Long motion (~27s) between force-handler OPEN and motion.failed is "
            "omitted from the fixture (cmd_str / waypoint noise)",
            "Next-slot success is a new API call, not a recovery_of link",
            "No application source in this workspace; interpretations are log-only",
        ],
        notes={
            "focus": (
                "In-call force-stop (E-200) during slot exit, force-stop handler "
                "OPEN retry, then RA_CANNOT_PICK_FROM_BASKET_MULTIPLE_ATTEMPTS "
                "abort of the pick retry loop"
            ),
            "has_error_level_lines": True,
        },
    )
    _write_source_fixture(
        source=source,
        wanted=WANTED_LINES_SEP24_FULL_CYCLE,
        out_name="full_slide_cycle_b.jsonl",
        provenance_name="provenance_full_slide_cycle_b.json",
        unresolved=[
            "Service does not emit a parent workflow id for the multi-API cycle",
            "Some intermediate APIs omit load/row/col; episode_id is carried forward "
            "in the converter for those records",
            "Vision helper APIs and LED toggles omitted from this fixture",
            "No application source in this workspace; interpretations are log-only",
        ],
        notes={
            "focus": (
                "Second complete slide cycle (Sep 24) for the same multi-API pattern "
                "as full_slide_cycle_a"
            ),
            "episode_id": "CS001-1-1-1790200023515:r1-c20",
            "core_apis": FULL_CYCLE_CORE_APIS,
            "slide_id": 259950,
        },
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

    # 9) Full slide cycle as linked API workflows under one episode_id
    ep_full = "syn:CS001-loadJ:r1-c2"
    parts = []
    for offset, api, steps, outcome in (
        (
            900.0,
            "/robotic-arm/pick/basket",
            [
                ("OPEN_AT_PICK_BASKET", "ok", {"operation_type": "OPEN_AT_PICK_BASKET"}),
                (
                    "CLOSE_AT_PICK_BASKET",
                    "ok",
                    {"operation_type": "CLOSE_AT_PICK_BASKET", "slide_present": True},
                ),
            ],
            "ok",
        ),
        (
            900.5,
            "/robotic-arm/move/scanner/imaging",
            [("move_scanner_imaging", "ok", {"api": "/robotic-arm/move/scanner/imaging"})],
            "ok",
        ),
        (
            901.0,
            "/robotic-arm/place/scanner",
            [
                (
                    "PARTIAL_OPEN_AT_SCANNER_PLACE",
                    "ok",
                    {"operation_type": "PARTIAL_OPEN_AT_SCANNER_PLACE"},
                ),
                ("place_scanner", "ok", {"api": "/robotic-arm/place/scanner"}),
            ],
            "ok",
        ),
        (
            901.5,
            "/robotic-arm/pick/scanner",
            [
                (
                    "CLOSE_AT_SCANNER_PICK",
                    "ok",
                    {"operation_type": "CLOSE_AT_SCANNER_PICK", "slide_present": True},
                ),
                ("pick_scanner", "ok", {"api": "/robotic-arm/pick/scanner"}),
            ],
            "ok",
        ),
        (
            902.0,
            "/robotic-arm/drop-slide",
            [
                ("OPEN_AT_PICK_BASKET", "ok", {"operation_type": "OPEN_AT_PICK_BASKET"}),
                ("drop_slide", "ok", {"api": "/robotic-arm/drop-slide"}),
            ],
            "ok",
        ),
    ):
        chunk = _emit_workflow(
            t0=t0 + offset,
            workflow=api,
            workflow_id=f"syn:{api}:{ep_full}",
            steps=steps,
            outcome=outcome,
        )
        for rec in chunk:
            rec["episode_id"] = ep_full
            rec["episode_id_provenance"] = "synthetic"
        parts.extend(chunk)
    scenarios["full_slide_cycle.jsonl"] = parts

    # 10) Force-exit then in-call retry abort (vocabulary from 2026-09-24 log)
    scenarios["force_exit_retry_abort.jsonl"] = _emit_workflow(
        t0=t0 + 800,
        workflow="/robotic-arm/pick/basket",
        workflow_id="syn:pick_basket:loadI:force_exit",
        steps=[
            ("OPEN_AT_PICK_BASKET", "ok", {"operation_type": "OPEN_AT_PICK_BASKET"}),
            (
                "CLOSE_AT_PICK_BASKET",
                "ok",
                {"operation_type": "CLOSE_AT_PICK_BASKET", "slide_present": True},
            ),
            (
                "force_stop",
                "error",
                {
                    "error_code": "E-200",
                    "err_msg": "Force is 15.038371F",
                    "force_event": "stop_playing",
                },
            ),
            (
                "OPEN_AT_PICK_BASKET",
                "ok",
                {
                    "operation_type": "OPEN_AT_PICK_BASKET",
                    "attempt": 2,
                    "after_force_stop": True,
                },
            ),
            (
                "exit_slot",
                "error",
                {
                    "error_code": "RA_CANNOT_PICK_FROM_BASKET_MULTIPLE_ATTEMPTS",
                    "err_msg": (
                        "Robotic-Arm encountered force while exiting from the pick slot"
                    ),
                },
            ),
            (
                "retry_loop_abort",
                "error",
                {
                    "error_code": "RA_CANNOT_PICK_FROM_BASKET_MULTIPLE_ATTEMPTS",
                    "err_msg": (
                        "Unhandled error in pick sequence, breaking out of retry loop"
                    ),
                },
            ),
        ],
        outcome="aborted",
    )

    for name, recs in scenarios.items():
        _write_jsonl(SYNTHETIC / name, recs)

    index = {
        "schema_version": 1,
        "generator": "tests/fixtures/logs/sequence/build_corpus.py",
        "synthetic_note": (
            "Durations, span IDs, and workflow_outcome values are synthetic. "
            "Vocabulary (API paths, operation_type, error codes) is taken from "
            "the 2026-09-23 and 2026-09-24 robotic_arm_service logs."
        ),
        "files": {name: len(recs) for name, recs in scenarios.items()},
    }
    (SYNTHETIC / "index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _parse_ts(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


def _duration_ms(start_ts: str, end_ts: str) -> float:
    return round((_parse_ts(end_ts) - _parse_ts(start_ts)).total_seconds() * 1000, 3)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class _SpanIds:
    """Deterministic span/trace ids for enriched fixtures."""

    def __init__(self, seed: int) -> None:
        self._n = seed

    def span(self) -> str:
        self._n += 1
        return f"{self._n:016x}"

    def trace(self) -> str:
        self._n += 1
        a = self._n
        self._n += 1
        return f"{a:016x}{self._n:016x}"


def _span_record(
    *,
    template: dict[str, Any],
    event: str,
    span_name: str,
    span_id: str,
    trace_id: str,
    parent_span_id: str | None,
    timestamp: str,
    status: str | None = None,
    duration_ms: float | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "timestamp": timestamp,
        "level": "DEBUG" if event == "span.start" else ("ERROR" if status == "error" else "DEBUG"),
        "logger": template.get("logger", "robotic_arm_service"),
        "message": event,
        "file": "span_enrichment",
        "func": "proposed",
        "line": int(template.get("source_line") or template.get("line") or 0),
        "event": event,
        "span": span_name,
        "span_id": span_id,
        "trace_id": trace_id,
        "span_enrichment": "proposed",
        "service_version": template.get("service_version", "build-6.0.10"),
        "cluster_id": template.get("cluster_id", "CS001"),
        "entity_id": template.get("entity_id", "R1"),
    }
    if parent_span_id is not None:
        rec["parent_span_id"] = parent_span_id
    if status is not None:
        rec["status"] = status
    if duration_ms is not None:
        rec["duration_ms"] = duration_ms
        rec["duration_ms_provenance"] = "derived_from_timestamps"
    if template.get("episode_id") is not None:
        rec["episode_id"] = template["episode_id"]
    if extra:
        rec.update(extra)
    validate_log_record(rec)
    return rec


def _api_workflow_outcome(window: list[dict[str, Any]]) -> tuple[str, str]:
    """Return (workflow_outcome, span_status) for one API activity window.

    ``span_status`` is execution-oriented (slogger only allows ok|error).
    Business failure with completed activity stays ``ok`` plus outcome fields.
    """
    if any(r.get("message") == "pick.retry_loop_abort" for r in window):
        return "aborted", "error"
    for r in window:
        if r.get("kind") == "api.response":
            if r.get("pick_status") is False or r.get("place_status") is False:
                return "error", "ok"
            if r.get("pick_status") is True or r.get("place_status") is True:
                return "ok", "ok"
    if any(r.get("error_code") == "ROBOT_NOT_IN_CORRECT_POSITION" for r in window):
        return "ok_with_warning", "ok"
    if any(r.get("message") == "activity.completed" for r in window):
        return "ok", "ok"
    return "incomplete", "error"


def _enrich_one(records: list[dict[str, Any]], *, id_seed: int) -> list[dict[str, Any]]:
    """Copy originals and insert proposed episode/api/(optional retry) spans."""
    ids = _SpanIds(id_seed)
    # Preserve originals verbatim (no span events on them).
    out: list[dict[str, Any]] = [dict(r) for r in records]
    span_events: list[dict[str, Any]] = []

    by_episode: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        ep = rec.get("episode_id")
        if not ep:
            continue
        by_episode.setdefault(ep, []).append(rec)

    for ep, ep_recs in by_episode.items():
        ep_recs_sorted = sorted(
            ep_recs,
            key=lambda r: (
                r["timestamp"],
                r.get("fixture_seq", 0),
                r.get("source_line", 0),
            ),
        )
        trace_id = ids.trace()
        episode_span_id = ids.span()
        first, last = ep_recs_sorted[0], ep_recs_sorted[-1]
        # Episode business outcome from terminal signals (not activity.completed).
        outcomes: list[str] = []
        for r in ep_recs_sorted:
            if r.get("message") == "pick.retry_loop_abort":
                outcomes.append("aborted")
            elif r.get("kind") == "api.response":
                if r.get("pick_status") is False or r.get("place_status") is False:
                    outcomes.append("error")
                elif r.get("pick_status") is True or r.get("place_status") is True:
                    outcomes.append("ok")
        if outcomes and outcomes[-1] == "ok":
            ep_outcome, ep_status = "ok", "ok"
        elif "aborted" in outcomes:
            ep_outcome, ep_status = "aborted", "error"
        elif "error" in outcomes:
            # Execution completed; business failed — span status stays ok.
            ep_outcome, ep_status = "error", "ok"
        else:
            ep_outcome, ep_status = "unknown", "ok"

        span_events.append(
            _span_record(
                template=first,
                event="span.start",
                span_name="episode",
                span_id=episode_span_id,
                trace_id=trace_id,
                parent_span_id=None,
                timestamp=first["timestamp"],
                extra={
                    "span_boundary_start": "inferred",
                    "source_line_start": first.get("source_line"),
                    "workflow_outcome": "running",
                    "owner": "caller_orchestrator",
                    "span_role": "multi_api_episode",
                },
            )
        )
        span_events.append(
            _span_record(
                template=last,
                event="span.end",
                span_name="episode",
                span_id=episode_span_id,
                trace_id=trace_id,
                parent_span_id=None,
                timestamp=last["timestamp"],
                status=ep_status,
                duration_ms=_duration_ms(first["timestamp"], last["timestamp"]),
                extra={
                    "span_boundary_end": "inferred",
                    "source_line_start": first.get("source_line"),
                    "source_line_end": last.get("source_line"),
                    "workflow_outcome": ep_outcome,
                    "owner": "caller_orchestrator",
                    "span_role": "multi_api_episode",
                },
            )
        )

        # Pair activity.in-progress with later activity.completed for same api.
        i = 0
        while i < len(ep_recs_sorted):
            rec = ep_recs_sorted[i]
            if rec.get("message") != "activity.in-progress" or not rec.get("api"):
                i += 1
                continue
            api = rec["api"]
            end = None
            j = i + 1
            window = [rec]
            while j < len(ep_recs_sorted):
                nxt = ep_recs_sorted[j]
                window.append(nxt)
                if (
                    nxt.get("message") == "activity.completed"
                    and nxt.get("api") == api
                ):
                    end = nxt
                    break
                # Do not cross into a new pick/basket request for another slot.
                if (
                    nxt.get("message") == "api.endpoint"
                    and nxt.get("api") == "/robotic-arm/pick/basket"
                    and nxt.get("episode_id") != ep
                ):
                    break
                j += 1
            if end is None:
                # Incomplete API: emit start only — do not invent an end.
                api_span_id = ids.span()
                span_events.append(
                    _span_record(
                        template=rec,
                        event="span.start",
                        span_name=f"api.{api}",
                        span_id=api_span_id,
                        trace_id=trace_id,
                        parent_span_id=episode_span_id,
                        timestamp=rec["timestamp"],
                        extra={
                            "span_boundary_start": "observed",
                            "source_line_start": rec.get("source_line"),
                            "api": api,
                            "workflow": api,
                            "owner": "robotic_arm_service",
                            "span_role": "api_invocation",
                            "workflow_outcome": "incomplete",
                        },
                    )
                )
                i = j + 1
                continue

            outcome, span_status = _api_workflow_outcome(window)
            api_span_id = ids.span()
            span_events.append(
                _span_record(
                    template=rec,
                    event="span.start",
                    span_name=f"api.{api}",
                    span_id=api_span_id,
                    trace_id=trace_id,
                    parent_span_id=episode_span_id,
                    timestamp=rec["timestamp"],
                    extra={
                        "span_boundary_start": "observed",
                        "source_line_start": rec.get("source_line"),
                        "api": api,
                        "workflow": api,
                        "owner": "robotic_arm_service",
                        "span_role": "api_invocation",
                    },
                )
            )
            span_events.append(
                _span_record(
                    template=end,
                    event="span.end",
                    span_name=f"api.{api}",
                    span_id=api_span_id,
                    trace_id=trace_id,
                    parent_span_id=episode_span_id,
                    timestamp=end["timestamp"],
                    status=span_status,
                    duration_ms=_duration_ms(rec["timestamp"], end["timestamp"]),
                    extra={
                        "span_boundary_end": "observed",
                        "source_line_start": rec.get("source_line"),
                        "source_line_end": end.get("source_line"),
                        "api": api,
                        "workflow": api,
                        "owner": "robotic_arm_service",
                        "span_role": "api_invocation",
                        "workflow_outcome": outcome,
                    },
                )
            )

            # Optional retry_loop under pick/basket when abort is observed.
            if api == "/robotic-arm/pick/basket":
                abort = next(
                    (r for r in window if r.get("message") == "pick.retry_loop_abort"),
                    None,
                )
                first_open = next(
                    (
                        r
                        for r in window
                        if r.get("operation_type") == "OPEN_AT_PICK_BASKET"
                    ),
                    None,
                )
                if abort is not None and first_open is not None:
                    retry_id = ids.span()
                    span_events.append(
                        _span_record(
                            template=first_open,
                            event="span.start",
                            span_name="retry_loop",
                            span_id=retry_id,
                            trace_id=trace_id,
                            parent_span_id=api_span_id,
                            timestamp=first_open["timestamp"],
                            extra={
                                "span_boundary_start": "inferred",
                                "source_line_start": first_open.get("source_line"),
                                "owner": "robotic_arm_service.pick_handler",
                                "span_role": "in_call_retry",
                                "api": api,
                            },
                        )
                    )
                    span_events.append(
                        _span_record(
                            template=abort,
                            event="span.end",
                            span_name="retry_loop",
                            span_id=retry_id,
                            trace_id=trace_id,
                            parent_span_id=api_span_id,
                            timestamp=abort["timestamp"],
                            status="error",
                            duration_ms=_duration_ms(
                                first_open["timestamp"], abort["timestamp"]
                            ),
                            extra={
                                "span_boundary_end": "observed",
                                "source_line_start": first_open.get("source_line"),
                                "source_line_end": abort.get("source_line"),
                                "owner": "robotic_arm_service.pick_handler",
                                "span_role": "in_call_retry",
                                "workflow_outcome": "aborted",
                                "error_code": abort.get("error_code"),
                                "api": api,
                            },
                        )
                    )

            i = j + 1

    # Merge: originals + span events, stable sort.
    merged = out + span_events
    merged.sort(
        key=lambda r: (
            r["timestamp"],
            0 if r.get("event") == "span.start" else (2 if r.get("event") == "span.end" else 1),
            r.get("fixture_seq", 0),
            r.get("span", ""),
            r.get("message", ""),
        )
    )
    return merged


def build_enriched_spans() -> None:
    """Build proposed-span variants from committed source-derived JSONL."""
    ENRICHED.mkdir(parents=True, exist_ok=True)
    targets = [
        ("full_slide_cycle_a.jsonl", "full_slide_cycle_a.spans.jsonl", 1000),
        ("full_slide_cycle_b.jsonl", "full_slide_cycle_b.spans.jsonl", 2000),
        ("force_exit_retry_abort.jsonl", "force_exit_retry_abort.spans.jsonl", 3000),
        ("pick_basket_issue_cluster.jsonl", "pick_basket_issue_cluster.spans.jsonl", 4000),
    ]
    index: dict[str, Any] = {
        "schema_version": 1,
        "doc": "docs/plans/sequence-spans.md",
        "note": (
            "Proposed spans only. duration_ms is derived from record timestamps. "
            "Originals under source_derived/ remain span-free. Gripper/motion "
            "ops stay events unless the app emits clear start/end bounds."
        ),
        "files": {},
    }
    for src_name, out_name, seed in targets:
        src = SOURCE_DERIVED / src_name
        if not src.is_file():
            continue
        original = _read_jsonl(src)
        assert not any(
            r.get("event") in ("span.start", "span.end") for r in original
        ), f"{src_name} must remain span-free"
        enriched = _enrich_one(original, id_seed=seed)
        out = ENRICHED / out_name
        with out.open("w", encoding="utf-8") as fh:
            for rec in enriched:
                line = json.dumps(
                    rec, sort_keys=True, separators=(",", ":"), ensure_ascii=True
                )
                fh.write(line + "\n")
        n_spans = sum(
            1 for r in enriched if r.get("event") in ("span.start", "span.end")
        )
        index["files"][out_name] = {
            "source": f"source_derived/{src_name}",
            "records": len(enriched),
            "original_records": len(original),
            "span_events": n_spans,
        }
    (ENRICHED / "index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (ENRICHED / "README.md").write_text(
        (
            "# Span-enriched sequence fixtures\n\n"
            "Generated by `build_corpus.py` (`build_enriched_spans`).\n\n"
            "- **Originals** in `../source_derived/` have no `span.start`/`span.end`.\n"
            "- **These files** copy those records and add *proposed* spans.\n"
            "- See [`docs/plans/sequence-spans.md`](../../../../docs/plans/sequence-spans.md).\n"
            "- `duration_ms` is `derived_from_timestamps`, not app-measured.\n"
        ),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        help="Path to 2026-09-23 robotic_arm_service plain-text log",
    )
    parser.add_argument(
        "--source-sep24",
        type=Path,
        help="Path to 2026-09-24 truncated log (force-exit / retry-abort slice)",
    )
    parser.add_argument(
        "--skip-source",
        action="store_true",
        help="Only regenerate synthetic + enriched fixtures",
    )
    args = parser.parse_args()
    if not args.skip_source:
        if args.source is None and args.source_sep24 is None:
            raise SystemExit(
                "pass --source and/or --source-sep24, or use --skip-source"
            )
        if args.source is not None:
            build_source_derived_sep23(args.source)
        if args.source_sep24 is not None:
            build_source_derived_sep24(args.source_sep24)
    build_synthetic()
    build_enriched_spans()
    print("Wrote", SOURCE_DERIVED)
    print("Wrote", SYNTHETIC)
    print("Wrote", ENRICHED)


if __name__ == "__main__":
    main()
