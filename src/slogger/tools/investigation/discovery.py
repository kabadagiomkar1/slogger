"""Complete, dataset-scoped field/scalar discovery in bounded managed storage."""

from __future__ import annotations

import json
import math
import sqlite3
import threading
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from ..core.encoding import json_spelling
from ..core.filter_language import FilterChoice, FilterCompletion, format_field_path
from ..errors import ToolError
from .models import Diagnostic
from .resources import SqliteBatch, resident_size

if TYPE_CHECKING:
    from .session import Investigation


@dataclass(frozen=True)
class DiscoveryScope:
    dataset_id: str
    request_id: str


@dataclass(frozen=True)
class DiscoveryStatus:
    phase: Literal["pending", "building", "complete", "failed", "canceled", "closed"]
    processed_records: int = 0
    total_records: int = 0
    unsupported_paths: int = 0
    unsupported_values: int = 0
    unsupported_elements: int = 0
    diagnostic: Diagnostic | None = None


@dataclass(frozen=True)
class DiscoveryChoice:
    path: tuple[str, ...]
    insertion: str
    occurrences: int
    kind: str
    value: Any = None
    guidance: str = ""
    source: str | None = None


@dataclass(frozen=True)
class DiscoveryPage:
    scope: DiscoveryScope
    choices: list[DiscoveryChoice]
    next_offset: int
    has_more: bool


@dataclass(frozen=True)
class DiscoveryCompletionPage:
    scope: DiscoveryScope
    completion: FilterCompletion
    next_offset: int
    has_more: bool


_GUIDANCE = (
    "Array traversal and empty field components are unsupported by IXR; "
    "target an array as a whole field"
)


def _encoded_path(path: tuple[str, ...]) -> str:
    return json.dumps(path, ensure_ascii=False, separators=(",", ":"))


class DiscoveryIndex:
    """Immutable whole-dataset observations. Completion drafts belong to callers."""

    def __init__(self, session: Investigation, scope: DiscoveryScope, path: Path):
        self.session, self.scope, self.path = session, scope, path
        self._lock = threading.RLock()
        self._closed = False
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA query_only=ON")
        self._db.execute("PRAGMA mmap_size=0")
        self._db.execute(
            f"PRAGMA cache_size=-{max(1, session.limits.working_memory_bytes // 8192)}"
        )
        try:
            session.register_view(self)
        except BaseException:
            self._db.close()
            raise

    guidance = _GUIDANCE

    @property
    def closed(self) -> bool:
        return self._closed or self.session.status.phase == "closed"

    def _ready(self, offset: int, limit: int) -> None:
        if self.closed:
            raise ToolError("result_closed", "Discovery index is closed.")
        if offset < 0 or not 0 <= limit <= self.session.limits.max_page_records:
            raise ValueError("discovery offset/limit exceed the page contract")

    def _page(
        self, cursor: sqlite3.Cursor, offset: int, limit: int, *, values: bool
    ) -> DiscoveryPage:
        choices = []
        size = 0
        more = False
        for row in cursor:
            if len(choices) == limit:
                more = True
                break
            path = tuple(json.loads(row["path"]))
            choice = DiscoveryChoice(
                path,
                row["spelling"],
                row["occurrences"],
                row["kind"] if values else "field",
                json.loads(row["spelling"]) if values else None,
                ""
                if values or not row["collections"]
                else (
                    "Collection field: use structural/immediate-array predicates; "
                    "array traversal is unsupported by IXR"
                ),
                row["source"] if values else None,
            )
            cost = resident_size(choice.__dict__) + 128
            if size + cost > self.session.limits.page_memory_bytes:
                if not choices:
                    raise ToolError(
                        "resource_limit", "Discovery choice exceeds page memory admission."
                    )
                more = True
                break
            choices.append(choice)
            size += cost
        return DiscoveryPage(self.scope, choices, offset + len(choices), more)

    def fields(
        self,
        *,
        prefix: str = "",
        parent: tuple[str, ...] | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> DiscoveryPage:
        """Page exact path spellings; optional parent restricts to direct components."""
        with self._lock:
            self._ready(offset, limit)
            if parent is None:
                cursor = self._db.execute(
                    "SELECT * FROM fields WHERE substr(spelling,1,?)=? "
                    "ORDER BY spelling LIMIT ? OFFSET ?",
                    (len(prefix), prefix, limit + 1, offset),
                )
            else:
                cursor = self._db.execute(
                    "SELECT * FROM fields WHERE parent=? AND substr(component,1,?)=? "
                    "ORDER BY spelling LIMIT ? OFFSET ?",
                    (_encoded_path(parent), len(prefix), prefix, limit + 1, offset),
                )
            return self._page(cursor, offset, limit, values=False)

    def values(
        self,
        path: tuple[str, ...],
        *,
        prefix: str = "",
        offset: int = 0,
        limit: int = 50,
        kinds: tuple[str, ...] = ("string", "number", "boolean", "null"),
        source: Literal["field", "array_element"] = "field",
    ) -> DiscoveryPage:
        """Page typed JSON scalar spellings; no-prefix pages rank by occurrence count."""
        with self._lock:
            self._ready(offset, limit)
            if source not in ("field", "array_element"):
                raise ValueError("discovery value source must be field or array_element")
            placeholders = ",".join("?" for _ in kinds)
            order = "v.spelling" if prefix else "v.occurrences DESC,v.spelling"
            cursor = self._db.execute(
                "SELECT v.*,f.path FROM scalar_values v JOIN fields f ON f.spelling=v.field "
                "WHERE v.field=? AND v.source=? AND substr(v.spelling,1,?)=? "
                f"AND v.kind IN ({placeholders}) "
                f"ORDER BY {order} LIMIT ? OFFSET ?",
                (format_field_path(path), source, len(prefix), prefix, *kinds, limit + 1, offset),
            )
            return self._page(cursor, offset, limit, values=True)

    def complete(
        self,
        request: FilterCompletion,
        *,
        offset: int = 0,
        limit: int = 20,
        cancel_event: threading.Event | None = None,
    ) -> DiscoveryCompletionPage:
        """Read a bounded exact-request page, optionally interrupted by its caller."""
        with self._lock:
            self._ready(offset, limit)
            if cancel_event is not None and cancel_event.is_set():
                raise ToolError("operation_canceled", "Completion canceled.")
            self._db.set_progress_handler(
                (lambda: int(cancel_event.is_set())) if cancel_event is not None else None, 1000
            )
            try:
                return self._complete(request, offset=offset, limit=limit)
            except sqlite3.OperationalError as error:
                if cancel_event is not None and cancel_event.is_set():
                    raise ToolError("operation_canceled", "Completion canceled.") from error
                raise ToolError("discovery_failed", str(error)) from error
            finally:
                self._db.set_progress_handler(None, 0)

    def _complete(
        self, request: FilterCompletion, *, offset: int = 0, limit: int = 20
    ) -> DiscoveryCompletionPage:
        """Extend grammar choices with one exact-request page of dataset observations."""
        choices = []
        guidance = request.guidance
        next_offset, more = offset, False
        if request.kind in ("expression", "field"):
            page = self.fields(
                prefix=request.prefix, parent=request.field_path, offset=offset, limit=limit
            )
            replace_dot = bool(
                request.field_path and request.start and request.text[request.start - 1] == "."
            )
            if replace_dot:
                request = replace(request, start=request.start - 1)
            for observed in page.choices:
                relative = observed.path[len(request.field_path or ()) :]
                insertion = format_field_path(relative)
                if replace_dot and not insertion.startswith("["):
                    insertion = "." + insertion
                choices.append(
                    FilterChoice(format_field_path(observed.path), insertion, observed.guidance)
                )
            next_offset, more = page.next_offset, page.has_more
        elif request.kind == "value" and request.value_kind == "path_component":
            # A bracket component is a JSON string, not a field's scalar operand.
            # Prefix matching uses that exact escaped spelling, never SQL wildcards.
            prefix = request.prefix
            parent = request.field_path or ()
            with self._lock:
                self._ready(offset, limit)
                cursor = self._db.execute(
                    "SELECT * FROM fields WHERE parent=? AND substr(quoted,1,?)=? "
                    "ORDER BY spelling LIMIT ? OFFSET ?",
                    (_encoded_path(parent), len(prefix), prefix, limit + 1, offset),
                )
                page = self._page(cursor, offset, limit, values=False)
            for observed in page.choices:
                insertion = json_spelling(observed.path[-1]) + "]"
                choices.append(
                    FilterChoice(
                        format_field_path(observed.path),
                        insertion,
                        observed.guidance,
                        len(insertion),
                    )
                )
            if request.text[request.end : request.end + 1] == "]":
                request = replace(request, end=request.end + 1)
            next_offset, more = page.next_offset, page.has_more
        elif request.kind == "value" and request.field_path and request.value_kind != "array":
            kinds = (
                ("string",)
                if request.value_kind == "string"
                else ("string", "number")
                if request.value_kind == "ordered"
                else ("string", "number", "boolean", "null")
            )
            page = self.values(
                request.field_path,
                prefix=request.prefix,
                kinds=kinds,
                offset=offset,
                limit=limit,
                source="array_element" if request.value_source == "array_element" else "field",
            )
            choices = [
                FilterChoice(c.insertion, c.insertion, f"{c.kind} · {c.occurrences:,} occurrences")
                for c in page.choices
            ]
            next_offset, more = page.next_offset, page.has_more
        if not choices and (
            request.kind == "field" or request.value_kind in ("array", "path_component")
        ):
            guidance += " · " + self.guidance
        # Observations precede grammar templates and do not duplicate their spelling.
        insertions = {choice.insertion for choice in choices}
        choices.extend(c for c in request.choices if c.insertion not in insertions)
        completion = replace(request, choices=tuple(choices), guidance=guidance)
        return DiscoveryCompletionPage(self.scope, completion, next_offset, more)

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._db.close()
                self._closed = True
            self.session.storage.remove_file(self.path)


class DiscoveryJob:
    """Cancellable complete index construction; no observations publish before readiness."""

    def __init__(self, session: Investigation, background: bool):
        self.session = session
        self.scope = DiscoveryScope(session.dataset_id, uuid.uuid4().hex)
        self.status = DiscoveryStatus("pending", total_records=session.status.record_count)
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._done = threading.Event()
        self._result: DiscoveryIndex | None = None
        self._batch: SqliteBatch | None = None
        self.diagnostics: tuple[Diagnostic, ...] = ()
        self._path = session.storage.create_file(f"discovery-{self.scope.request_id}.sqlite")
        self._worker = None
        if background:
            self._worker = threading.Thread(
                target=self._run, name=f"slogger-discovery-{self.scope.request_id}", daemon=True
            )
            self._worker.start()
        else:
            self._run()

    @property
    def done(self) -> bool:
        """True after indexing and owned staging cleanup have settled."""
        return self._done.is_set()

    def cancel(self) -> None:
        with self._lock:
            self._cancel.set()

    def wait(self, timeout: float | None = None) -> DiscoveryStatus:
        self._done.wait(timeout)
        return self.status

    def result(self) -> DiscoveryIndex:
        if self.status.phase != "complete" or self._result is None:
            raise ToolError(
                "discovery_not_ready", "Discovery index is not complete.", phase=self.status.phase
            )
        return self._result

    def close(self) -> None:
        self.cancel()
        self.wait()
        if self._result is not None:
            try:
                self._result.close()
            except (OSError, ToolError, sqlite3.Error) as error:
                diagnostic = Diagnostic("cleanup_failed", str(error))
                self.diagnostics += (diagnostic,)
                self.status = replace(self.status, phase="failed", diagnostic=diagnostic)
                raise ToolError(
                    "cleanup_failed", "Cannot release discovery index storage."
                ) from error
            self._result = None
        self.status = replace(self.status, phase="closed")

    def _check(self) -> None:
        if self._cancel.is_set():
            raise ToolError("operation_canceled", "Discovery canceled.")
        self.session.require_ready("discovery")

    def _write(
        self, db: sqlite3.Connection, operation: Callable[[], object], payload: int = 0
    ) -> None:
        self._check()
        if self._batch is not None:
            self._batch.write(operation, payload)
            return
        pages = db.execute("PRAGMA page_count").fetchone()[0]
        allowance = (64 * (max(1, pages).bit_length() + 2) + math.ceil(payload * 4 / 4096)) * 4096
        with self.session.storage.external_growth(self._path, byte_count=allowance):
            db.execute(f"PRAGMA max_page_count={pages + allowance // 4096}")
            with db:
                operation()

    def _run(self) -> None:
        db = None
        try:
            self.status = replace(self.status, phase="building")
            db = sqlite3.connect(self._path)
            db.execute("PRAGMA page_size=4096")
            db.execute("PRAGMA journal_mode=OFF")
            db.execute("PRAGMA synchronous=OFF")
            db.execute("PRAGMA mmap_size=0")
            db.execute(
                f"PRAGMA cache_size=-{max(1, self.session.limits.working_memory_bytes // 8192)}"
            )
            db.execute("PRAGMA temp_store=MEMORY")
            self._write(
                db,
                lambda: db.executescript("""
              CREATE TABLE fields(spelling TEXT PRIMARY KEY,path TEXT,parent TEXT,
                  component TEXT,quoted TEXT,occurrences INTEGER,
                  collections INTEGER) WITHOUT ROWID;
              CREATE INDEX parents ON fields(parent,spelling);
              CREATE TABLE scalar_values(field TEXT,source TEXT,spelling TEXT,kind TEXT,
                  occurrences INTEGER,PRIMARY KEY(field,source,spelling)) WITHOUT ROWID;
              CREATE INDEX common_values ON scalar_values(field,source,occurrences DESC,spelling);
            """),
            )
            with SqliteBatch(self.session.storage, db, self._path, self._check, 64) as batch:
                self._batch = batch
                try:
                    for ordinal in range(self.status.total_records):
                        self._check()
                        record = self.session.page(ordinal, 1).records[0]
                        record_cost = resident_size(record)
                        stack_cost = 128
                        stack: list[tuple[tuple[str, ...], Iterator[tuple[str, Any]], int]] = [
                            ((), iter(record.items()), 128)
                        ]
                        while stack:
                            self._check()
                            parent, iterator, entry_cost = stack[-1]
                            pair = next(iterator, None)
                            if pair is None:
                                stack.pop()
                                stack_cost -= entry_cost
                                continue
                            key, value = pair
                            if not key:
                                self.status = replace(
                                    self.status, unsupported_paths=self.status.unsupported_paths + 1
                                )
                                continue
                            path = parent + (key,)
                            spelling, encoded = format_field_path(path), _encoded_path(path)
                            collection = isinstance(value, (dict, list))
                            scalar = None
                            kind = (
                                "null"
                                if value is None
                                else "boolean"
                                if isinstance(value, bool)
                                else "string"
                                if isinstance(value, str)
                                else "number"
                            )
                            if not collection:
                                try:
                                    scalar = json_spelling(value, allow_nan=False)
                                except ValueError:
                                    self.status = replace(
                                        self.status,
                                        unsupported_values=self.status.unsupported_values + 1,
                                    )
                            payload = resident_size((spelling, encoded, scalar))
                            if (
                                payload > self.session.limits.working_memory_bytes // 4
                                or record_cost + stack_cost + payload
                                > self.session.limits.working_memory_bytes * 3 // 4
                            ):
                                raise ToolError(
                                    "resource_limit",
                                    "Discovery path/value exceeds working memory admission.",
                                )

                            def insert(
                                db=db,
                                spelling=spelling,
                                encoded=encoded,
                                parent=parent,
                                key=key,
                                collection=collection,
                                scalar=scalar,
                                kind=kind,
                            ) -> None:
                                db.execute(
                                    "INSERT INTO fields VALUES(?,?,?,?,?,1,?) "
                                    "ON CONFLICT(spelling) "
                                    "DO UPDATE SET occurrences=occurrences+1,"
                                    "collections=collections+excluded.collections",
                                    (
                                        spelling,
                                        encoded,
                                        _encoded_path(parent),
                                        key,
                                        json_spelling(key),
                                        int(collection),
                                    ),
                                )
                                if scalar is not None:
                                    db.execute(
                                        "INSERT INTO scalar_values VALUES(?,'field',?,?,1) "
                                        "ON CONFLICT(field,source,spelling) "
                                        "DO UPDATE SET occurrences=occurrences+1",
                                        (spelling, scalar, kind),
                                    )

                            self._write(db, insert, payload)
                            if isinstance(value, list):
                                for element in value:
                                    self._check()
                                    if isinstance(element, (dict, list)) or (
                                        isinstance(element, float) and not math.isfinite(element)
                                    ):
                                        self.status = replace(
                                            self.status,
                                            unsupported_elements=self.status.unsupported_elements
                                            + 1,
                                        )
                                        continue
                                    encoded_element = json_spelling(element, allow_nan=False)
                                    element_kind = (
                                        "null"
                                        if element is None
                                        else "boolean"
                                        if isinstance(element, bool)
                                        else "string"
                                        if isinstance(element, str)
                                        else "number"
                                    )
                                    element_payload = resident_size((spelling, encoded_element))
                                    if (
                                        element_payload
                                        > self.session.limits.working_memory_bytes // 4
                                        or record_cost + stack_cost + element_payload
                                        > self.session.limits.working_memory_bytes * 3 // 4
                                    ):
                                        raise ToolError(
                                            "resource_limit",
                                            "Discovery array element exceeds working "
                                            "memory admission.",
                                        )

                                    def insert_element(
                                        db=db,
                                        spelling=spelling,
                                        encoded_element=encoded_element,
                                        element_kind=element_kind,
                                    ):
                                        db.execute(
                                            "INSERT INTO scalar_values "
                                            "VALUES(?,'array_element',?,?,1) "
                                            "ON CONFLICT(field,source,spelling) "
                                            "DO UPDATE SET occurrences=occurrences+1",
                                            (spelling, encoded_element, element_kind),
                                        )

                                    self._write(db, insert_element, element_payload)
                            if isinstance(value, dict):
                                cost = resident_size(path) + 128
                                if (
                                    record_cost + stack_cost + cost
                                    > self.session.limits.working_memory_bytes * 3 // 4
                                ):
                                    raise ToolError(
                                        "resource_limit",
                                        "Discovery traversal exceeds working memory admission.",
                                    )
                                stack.append((path, iter(value.items()), cost))
                                stack_cost += cost
                        self.status = replace(self.status, processed_records=ordinal + 1)
                finally:
                    self._batch = None
            db.close()
            db = None
            with self._lock:
                self._check()
                self._result = DiscoveryIndex(self.session, self.scope, self._path)
                self.status = replace(self.status, phase="complete")
        except Exception as error:
            code = error.code if isinstance(error, ToolError) else "discovery_failed"
            if isinstance(error, sqlite3.Error) and (
                getattr(error, "sqlite_errorcode", None) == 13
                or "database or disk is full" in str(error).lower()
            ):
                code = "resource_limit"
            diagnostics = [Diagnostic(code, str(error))]
            try:
                if db is not None:
                    db.close()
                self.session.storage.remove_file(self._path)
            except (OSError, ToolError, sqlite3.Error) as cleanup_error:
                diagnostics.append(Diagnostic("cleanup_failed", str(cleanup_error)))
            self.diagnostics = tuple(diagnostics)
            self.status = replace(
                self.status,
                phase="canceled" if code == "operation_canceled" else "failed",
                diagnostic=self.diagnostics[0],
            )
        finally:
            self._done.set()
