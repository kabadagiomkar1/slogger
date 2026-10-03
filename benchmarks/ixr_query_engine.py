"""Reproducible caller-level benchmarks and independent diagnostic stage probes.

Run from an editable checkout. Measurements are observations, never test thresholds.
Private imports are confined to phase probes; end-to-end calls use QueryPlan.execute.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.metadata
import json
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from slogger.tools import Field, QueryPlan, any_of, count_rows, mean_of, scan, sum_of

WORKLOADS = ("selective_filter", "broad_filter", "sort_top50", "group")


def _milliseconds(start: int) -> float:
    return (time.perf_counter_ns() - start) / 1_000_000


def _rss() -> int | None:
    try:
        import resource
    except ImportError:
        return None
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(raw if sys.platform == "darwin" else raw * 1024)


def _timed(action: Callable[[], Any]) -> tuple[Any, float]:
    start = time.perf_counter_ns()
    output = action()
    return output, _milliseconds(start)


def _dataset(path: Path, size: int, shape: str) -> None:
    """Arithmetic generation is deterministic, without random-state dependencies."""
    with path.open("w", encoding="utf-8") as handle:
        for index in range(size):
            record: dict[str, Any] = {
                "timestamp": "2026-10-03T00:00:00.000Z",
                "level": "INFO",
                "logger": f"service.{index % 32}",
                "message": f"request {index}",
                "file": "app.py",
                "func": "handle",
                "line": index % 100 + 1,
                "duration_ms": (index * 17) % 1000,
            }
            if shape == "sparse":
                if index % 5 == 1:
                    record["request"] = {"duration_ms": None}
                elif index % 5 > 1:
                    record["request"] = {"duration_ms": (index * 17) % 1000}
                if index % 11:
                    record["context"] = [None, True, 1, 1.5, "ok"][index % 5]
            else:
                record["request"] = {"duration_ms": (index * 17) % 1000}
                record["context"] = "ok"
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")


def _plan(path: Path, shape: str, workload: str) -> QueryPlan:
    source = scan(path)
    if workload == "selective_filter":
        field = Field("request", "duration_ms") if shape == "sparse" else Field("duration_ms")
        return source.filter(field.ge(990)).select("message", "request", "context")
    if workload == "broad_filter":
        predicate = (
            any_of(Field("request", "duration_ms").ge(100), Field("context").missing())
            if shape == "sparse"
            else Field("duration_ms").ge(100)
        )
        return source.filter(predicate).select("message", "request", "context")
    if workload == "sort_top50":
        return source.sort_by("duration_ms", descending=True).limit(50).select("message")
    return source.group_by("logger").aggregate(
        rows=count_rows(),
        total_ms=sum_of(Field("duration_ms")),
        mean_ms=mean_of(Field("duration_ms")),
    )


def _digest(records: list[dict[str, Any]]) -> str:
    def canonical(value: Any) -> Any:
        if isinstance(value, float):
            # Floating mean parity permits tolerance; this digest is a coarse check,
            # supplemented by precise adapter semantic tests in the test suite.
            return round(value, 8)
        if isinstance(value, dict):
            return {
                k: str(v).rsplit(":", 1)[-1] if k == "_id" else canonical(v)
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [canonical(v) for v in value]
        return value

    encoded = json.dumps(canonical(records), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _phase_probes(plan: QueryPlan, path: Path, backend: str) -> dict[str, Any]:
    """Independent probes: these timings overlap conceptually and must not be summed."""
    from slogger.tools._execution import RecordRow, RecordSource, _adapter
    from slogger.tools._optimization import normalize
    from slogger.tools._planning import validate
    from slogger.tools.core.plan import Aggregate, Filter, Project, Sort
    from slogger.tools.reader import Reader

    records, ingestion = _timed(lambda: list(Reader(path)))
    rows, wrapping = _timed(lambda: [RecordRow(r, i, r.get("_id")) for i, r in enumerate(records)])

    def prepare() -> Any:
        return _adapter(backend).prepare(normalize(validate(plan), backend=backend))

    prepared, planning = _timed(prepare)
    probes: dict[str, Any] = {
        "reader_ingestion_ms": ingestion,
        "row_wrapping_ms": wrapping,
        "warm_plan_validation_preparation_ms": planning,
        "conversion_ms": None,
        "expression_lowering_ms": None,
        "native_collect_ms": None,
        "filter_reconstruction_ms": None,
        "global_operation_inclusive_ms": None,
    }
    if backend == "python":
        source = RecordSource(Reader(records))
        try:
            output, elapsed = _timed(lambda: prepared.run(source))
        finally:
            source.close()
        _, packaging = _timed(lambda: [row.record for row in output.rows])
        probes.update(prepared_engine_inclusive_ms=elapsed, result_packaging_ms=packaging)
        return probes

    import polars as pl

    from slogger.tools._columnar import bind_batch
    from slogger.tools._polars_engine import _BATCH_SIZE, _lower, _presence_only_fields, _project

    nodes = prepared.plan.operations
    target = next(node for node in nodes if isinstance(node, (Filter, Sort, Aggregate)))
    if isinstance(target, Filter):
        expression = target.expression
        project = next(node for node in nodes if isinstance(node, Project))
        totals = {
            key: 0.0
            for key in (
                "conversion_ms",
                "expression_lowering_ms",
                "native_collect_ms",
                "filter_reconstruction_ms",
            )
        }
        for offset in range(0, len(rows), _BATCH_SIZE):
            batch = rows[offset : offset + _BATCH_SIZE]
            bound, elapsed = _timed(
                lambda batch=batch: bind_batch(
                    batch,
                    expression.required_fields(),
                    pl,
                    presence_only=_presence_only_fields(expression),
                )
            )
            totals["conversion_ms"] += elapsed
            frame, bindings = bound
            mask, elapsed = _timed(
                lambda bindings=bindings, frame=frame: _lower(expression, bindings, frame, pl)
            )
            totals["expression_lowering_ms"] += elapsed
            native = frame.lazy().filter(mask).select("ordinal")
            selection, elapsed = _timed(native.collect)
            totals["native_collect_ms"] += elapsed
            _, elapsed = _timed(
                lambda batch=batch, selection=selection: list(
                    _project(
                        [batch[index] for index in selection["ordinal"]],
                        project.fields,
                    )
                )
            )
            totals["filter_reconstruction_ms"] += elapsed
        probes.update(totals)
    else:
        paths = (
            frozenset(((target.field,),))
            if isinstance(target, Sort)
            else frozenset((key,) for key in target.keys)
            | frozenset(spec.field.path for _, spec in target.aggregates if spec.field is not None)
        )
        _, conversion = _timed(lambda: bind_batch(rows, paths, pl))
        if isinstance(target, Sort):
            from slogger.tools._polars_sorting import sort_rows

            def action() -> Any:
                return sort_rows(rows, target, operation=1, pl=pl)
        else:
            from slogger.tools._polars_aggregation import aggregate_rows

            def action() -> Any:
                return aggregate_rows(rows, target, pl)

        _, elapsed = _timed(action)
        probes.update(conversion_ms=conversion, global_operation_inclusive_ms=elapsed)
    return probes


def _worker(path: Path, shape: str, workload: str, backend: str, repeats: int) -> dict[str, Any]:
    plan, builder = _timed(lambda: _plan(path, shape, workload))
    baseline_rss = _rss()
    result, cold = _timed(lambda: plan.execute(backend=backend))
    cold_rss = _rss()
    del result
    warm = []
    for _ in range(repeats):
        gc.collect()
        result, elapsed = _timed(lambda: plan.execute(backend=backend))
        warm.append(elapsed)
        if len(warm) != repeats:
            del result
    warm_rss = _rss()
    digest = _digest(result.records)
    report: dict[str, Any] = {
        "backend": backend,
        "builder_ms": builder,
        "cold_execute_ms": cold,
        "warm_execute_ms": warm,
        "warm_median_ms": statistics.median(warm),
        "warm_min_ms": min(warm),
        "warm_max_ms": max(warm),
        "baseline_rss_bytes": baseline_rss,
        "cold_peak_rss_bytes": cold_rss,
        "repeated_worker_peak_rss_bytes": warm_rss,
        "metadata": result.metadata,
        "output_digest": digest,
    }
    del result
    gc.collect()
    report["independent_stage_probes"] = _phase_probes(plan, path, backend)
    if backend == "polars":
        import polars as pl

        report["native_threads"] = pl.thread_pool_size()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--small", type=int, default=200)
    parser.add_argument("--large", type=int, default=100_000)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path("ixr-benchmark.json"))
    parser.add_argument("--worker", nargs=4, metavar=("PATH", "SHAPE", "WORKLOAD", "BACKEND"))
    args = parser.parse_args()
    if args.small <= 0 or args.large <= 0 or args.repeats <= 0:
        parser.error("sizes and repeats must be positive")
    if args.worker:
        path, shape, workload, backend = args.worker
        print(json.dumps(_worker(Path(path), shape, workload, backend, args.repeats)))
        return
    root = Path(__file__).resolve().parents[1]
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    report: dict[str, Any] = {
        "version": 1,
        "git_revision": revision,
        "python": sys.version,
        "polars": importlib.metadata.version("polars"),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "clock": "perf_counter_ns",
        "repeats": args.repeats,
        "dataset": "deterministic arithmetic generation, 32 loggers, duration (i * 17) % 1000",
        "rss": "fresh worker high-water mark; macOS bytes, other resource platforms KiB normalized",
        "stage_note": "independent probes; not additive attribution of public execute",
        "digest_note": "source-path prefixes normalized; floats rounded to 8 decimals",
        "cold_note": "fresh process/adapter/conversion; OS filesystem cache uncontrolled",
        "warm_note": "same logical plan, reparsing/rebinding each run; no frame cache",
        "cases": [],
    }
    with tempfile.TemporaryDirectory(prefix="slogger-ixr-benchmark-") as temporary:
        for scale, size in (("small", args.small), ("large", args.large)):
            for shape in ("homogeneous", "sparse"):
                path = Path(temporary) / f"{scale}-{shape}.jsonl"
                _dataset(path, size, shape)
                for workload in WORKLOADS:
                    case: dict[str, Any] = {
                        "scale": scale,
                        "rows": size,
                        "shape": shape,
                        "workload": workload,
                        "source_bytes": path.stat().st_size,
                        "backends": [],
                    }
                    for backend in ("python", "polars"):
                        command = [
                            sys.executable,
                            str(Path(__file__).resolve()),
                            "--worker",
                            str(path),
                            shape,
                            workload,
                            backend,
                            "--repeats",
                            str(args.repeats),
                        ]
                        completed = subprocess.run(
                            command, check=True, capture_output=True, text=True
                        )
                        case["backends"].append(json.loads(completed.stdout))
                    left, right = case["backends"]
                    if left["output_digest"] != right["output_digest"]:
                        raise RuntimeError(f"adapter result mismatch: {scale}/{shape}/{workload}")
                    report["cases"].append(case)
                    print(
                        f"{scale}/{shape}/{workload}: "
                        f"Python {left['cold_execute_ms']:.1f}ms, "
                        f"Polars {right['cold_execute_ms']:.1f}ms",
                        flush=True,
                    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(args.output.resolve())


if __name__ == "__main__":
    main()
