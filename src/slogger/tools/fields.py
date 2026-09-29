"""Discover keys and value distributions in log sources."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from collections.abc import Sequence
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import Any

from slogger.tools.filters import Filters
from slogger.tools.reader import Order, Reader, Source, resolve_sources

_DISTINCT_CAP = 10_000
_SAMPLE_CAP = 5
_CACHE_VERSION = 2
_CACHE_SUFFIX = ".slogger-fields.json"


def _type_name(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _stable_value(value: object) -> object:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return value


def _filters_are_empty(filters: Filters | None) -> bool:
    if filters is None:
        return True
    empty = Filters()
    for field in dataclass_fields(Filters):
        if field.name.startswith("_"):
            continue
        if getattr(filters, field.name) != getattr(empty, field.name):
            return False
    return True


def _single_file_path(sources: Source | Sequence[Source]) -> str | None:
    """Return an absolute path when sources resolve to exactly one existing file."""
    if isinstance(sources, (str, os.PathLike)):
        text = os.fspath(sources)
        if text == "-" or any(ch in text for ch in "*?["):
            return None
        path = Path(text)
        if path.is_file():
            return str(path.resolve())
        return None

    if not isinstance(sources, Sequence) or any(
        not isinstance(item, (str, os.PathLike)) for item in sources
    ):
        return None

    try:
        resolved = resolve_sources(sources)
    except (FileNotFoundError, TypeError, ValueError):
        return None
    if len(resolved) != 1 or not isinstance(resolved[0], str):
        return None
    if resolved[0] == "-":
        return None
    path = Path(resolved[0])
    if path.is_file():
        return str(path.resolve())
    return None


def _cache_path(file_path: str, *, cache_dir: str | None) -> Path:
    if cache_dir is None:
        return Path(file_path + _CACHE_SUFFIX)
    digest = hashlib.sha256(file_path.encode("utf-8")).hexdigest()[:32]
    return Path(cache_dir) / f"{digest}{_CACHE_SUFFIX}"


def _file_identity(file_path: str) -> tuple[int, int]:
    stat = os.stat(file_path)
    mtime_ns = getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))
    return stat.st_size, int(mtime_ns)


def _read_cache(
    cache_file: Path,
    *,
    file_path: str,
    size: int,
    mtime_ns: int,
    scan: int,
) -> dict[str, Any] | None:
    try:
        raw = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    if raw.get("version") != _CACHE_VERSION:
        return None
    if raw.get("path") != file_path:
        return None
    if raw.get("size") != size or raw.get("mtime_ns") != mtime_ns:
        return None
    if raw.get("scan") != scan:
        return None
    payload = raw.get("payload")
    if not isinstance(payload, dict):
        return None
    return payload


def _write_cache(
    cache_file: Path,
    *,
    file_path: str,
    size: int,
    mtime_ns: int,
    scan: int,
    payload: dict[str, Any],
) -> None:
    document = {
        "version": _CACHE_VERSION,
        "path": file_path,
        "size": size,
        "mtime_ns": mtime_ns,
        "scan": scan,
        "payload": payload,
    }
    tmp: Path | None = None
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=cache_file.parent,
            prefix=cache_file.name + ".", suffix=".tmp", delete=False,
        ) as handle:
            tmp = Path(handle.name)
            json.dump(document, handle, default=str)
        tmp.replace(cache_file)
    except OSError:
        pass  # Cache writes are best-effort.
    finally:
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


def _scan_fields(
    sources: Source | Sequence[Source],
    *,
    filters: Filters,
    scan: int,
    key: str | None,
    top: int,
    order: Order,
) -> dict[str, Any]:
    reader = Reader(sources, order=order)
    limit = None if scan == 0 else scan

    if key is not None:
        counts: Counter[tuple[str, object]] = Counter()
        scanned = 0
        for record in reader:
            if not filters.matches(record):
                continue
            scanned += 1
            if key in record:
                counts[(_type_name(record[key]), _stable_value(record[key]))] += 1
            if limit is not None and scanned >= limit:
                break
        ranking = sorted(
            counts.items(), key=lambda item: (-item[1], str(item[0][1]), item[0][0])
        )[:top]
        return {
            "schema_version": 1,
            "key": key,
            "scanned": scanned,
            "top": [{"value": value, "count": count} for (_, value), count in ranking],
        }

    key_types: dict[str, Counter[str]] = {}
    key_counts: Counter[str] = Counter()
    key_distinct: dict[str, set[object]] = {}
    key_distinct_capped: dict[str, bool] = {}
    key_samples: dict[str, list[object]] = {}
    scanned = 0
    for record in reader:
        if not filters.matches(record):
            continue
        scanned += 1
        for name, value in record.items():
            if name == "_id":
                continue
            key_counts[name] += 1
            type_counter = key_types.setdefault(name, Counter())
            type_counter[_type_name(value)] += 1
            distinct = key_distinct.setdefault(name, set())
            stable = (_type_name(value), _stable_value(value))
            if stable not in distinct:
                if len(distinct) < _DISTINCT_CAP:
                    distinct.add(stable)
                    samples = key_samples.setdefault(name, [])
                    if len(samples) < _SAMPLE_CAP:
                        samples.append(
                            value if not isinstance(value, (dict, list)) else stable[1]
                        )
                else:
                    key_distinct_capped[name] = True
        if limit is not None and scanned >= limit:
            break

    keys_out: dict[str, Any] = {}
    for name, count in sorted(key_counts.items()):
        type_counter = key_types[name]
        most_common_type = type_counter.most_common(1)[0][0]
        keys_out[name] = {
            "type": most_common_type,
            "types": sorted(type_counter),
            "count": count,
            "present_pct": round(100.0 * count / scanned, 1) if scanned else 0.0,
            "distinct": len(key_distinct.get(name, ())),
            "distinct_capped": key_distinct_capped.get(name, False),
            "samples": key_samples.get(name, []),
        }

    return {
        "schema_version": 1,
        "scanned": scanned,
        "scan_capped": limit is not None and scanned >= limit,
        "keys": keys_out,
    }


def fields(
    sources: Source | Sequence[Source],
    *,
    filters: Filters | None = None,
    scan: int = 100_000,
    key: str | None = None,
    top: int = 10,
    order: Order = "concat",
    cache: bool = False,
    cache_dir: str | None = None,
) -> dict[str, Any]:
    """Discover keys (types, cardinality, samples) or top values for ``key``.

    ``scan`` caps how many matching records are examined (``0`` = unbounded).
    When ``key`` is set, returns ranked values instead of the full key map.

    ``cache=True`` may read/write a sidecar next to a single log file (or under
    ``cache_dir``). Only the unfiltered key overview is cached; filtered calls,
    ``key=`` rankings, stdin, in-memory sources, and multi-file globs always scan.

    Example::

        from slogger.tools import fields

        overview = fields("app.log")
        users = fields("app.log", key="user", top=20)
    """
    predicate = filters if filters is not None else Filters()
    can_cache = (
        cache
        and key is None
        and _filters_are_empty(predicate)
        and order == "concat"
    )
    file_path = _single_file_path(sources) if can_cache else None

    identity = None
    if file_path is not None:
        identity = _file_identity(file_path)
        size, mtime_ns = identity
        cache_file = _cache_path(file_path, cache_dir=cache_dir)
        cached = _read_cache(
            cache_file,
            file_path=file_path,
            size=size,
            mtime_ns=mtime_ns,
            scan=scan,
        )
        if cached is not None:
            return cached

    payload = _scan_fields(
        sources,
        filters=predicate,
        scan=scan,
        key=key,
        top=top,
        order=order,
    )

    if file_path is not None and identity is not None:
        try:
            unchanged = _file_identity(file_path) == identity
        except OSError:
            unchanged = False
        if not unchanged:
            return payload
        size, mtime_ns = identity
        _write_cache(
            _cache_path(file_path, cache_dir=cache_dir),
            file_path=file_path,
            size=size,
            mtime_ns=mtime_ns,
            scan=scan,
            payload=payload,
        )
    return payload
