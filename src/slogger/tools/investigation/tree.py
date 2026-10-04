"""Dataset-scoped, disk-backed trace evidence and bounded structural pages.

SQLite is a disposable staging index: no journal/WAL, no engine sort workspace,
no mmap, a bounded page cache, and a reserved main-file page ceiling before each
transaction. Original captured records remain the evidence authority.
"""

from __future__ import annotations

import json
import math
import sqlite3
import struct
import threading
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Literal

from ..errors import ToolError
from .filters import RecordView, ViewScope
from .models import Diagnostic, RecordPage
from .resources import resident_size

if TYPE_CHECKING:
    from .session import Investigation


@dataclass(frozen=True)
class TreeScope:
    dataset_id: str
    request_id: str
    population: Literal["unfiltered", "filtered"] = "unfiltered"
    input_scope: ViewScope | None = None
    request_generation: int = 0


@dataclass(frozen=True)
class TreeStatus:
    phase: Literal["pending", "building", "complete", "failed", "canceled", "closed"]
    processed_records: int = 0
    total_records: int = 0
    diagnostic: Diagnostic | None = None


@dataclass(frozen=True)
class TreeRow:
    key: int
    parent_key: int | None
    kind: str
    first_ordinal: int
    trace_id: str | None = None
    span_id: str | None = None
    label: str = ""
    ordinal: int | None = None
    relationship: str = ""
    lifecycle: str = "unavailable"
    start_count: int = 0
    end_count: int = 0
    status: str | None = None
    duration_ms: int | float | None = None
    child_count: int = 0
    record_count: int = 0
    name_conflict: bool = False
    match_count: int = 0
    context_only: bool = False


@dataclass(frozen=True)
class TreePage:
    scope: TreeScope
    rows: list[TreeRow]
    next_offset: int
    has_more: bool


class TraceTree:
    """Immutable evidence index. Folds and selection belong to its consumer."""

    def __init__(
        self, session: Investigation, scope: TreeScope, path: Path, record_count: int | None = None
    ) -> None:
        self.session = session
        self.scope = scope
        self.path = path
        self.record_count = session.status.record_count if record_count is None else record_count
        self.evidence_record_count = session.status.record_count
        self._closed = False
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA query_only=ON")
        self._connection.execute("PRAGMA mmap_size=0")
        self._connection.execute(
            f"PRAGMA cache_size=-{max(1, session.limits.working_memory_bytes // 8192)}"
        )
        try:
            session.register_view(self)
        except BaseException:
            self._connection.close()
            raise

    def _ready(self) -> None:
        if self._closed or self.session.status.phase == "closed":
            raise ToolError("result_closed", "Trace tree is closed.")

    def _row(self, key: int) -> TreeRow:
        row = self._connection.execute("SELECT * FROM entries WHERE key=?", (key,)).fetchone()
        if row is None or not row["visible"]:
            raise ValueError("tree node is outside the delivered population")
        parent = row["parent"] or None
        if row["ordinal"] is not None:
            return TreeRow(
                key,
                parent,
                "record",
                row["first"],
                ordinal=row["ordinal"],
                relationship=row["evidence"],
                match_count=1,
            )
        node = self._connection.execute("SELECT * FROM nodes WHERE id=?", (key,)).fetchone()
        assert node is not None
        return TreeRow(
            key,
            parent,
            node["kind"],
            node["first"],
            node["trace"],
            node["span"],
            node["label"],
            relationship=node["relationship"],
            child_count=node["children"],
            record_count=node["records"],
            lifecycle=node["lifecycle"],
            start_count=node["starts"],
            end_count=node["ends"],
            status=node["end_status"] if node["lifecycle"] == "complete" else None,
            duration_ms=json.loads(node["duration"]) if node["lifecycle"] == "complete" else None,
            name_conflict=bool(node["name_conflict"]),
            match_count=node["matches"] if self.scope.population == "filtered" else node["records"],
            context_only=self.scope.population == "filtered" and not node["matches"],
        )

    def row(self, key: int) -> TreeRow:
        with self._lock:
            self._ready()
            return self._row(key)

    def children(
        self, parent_key: int | None = None, offset: int = 0, limit: int = 100
    ) -> TreePage:
        """Page direct children in source first-appearance order, including leaves."""
        with self._lock:
            self._ready()
            if offset < 0 or limit < 0 or limit > self.session.limits.max_page_records:
                raise ValueError("tree page exceeds page contract")
            cursor = self._connection.execute(
                "SELECT key FROM entries WHERE parent=? AND visible=1 "
                "ORDER BY first,key LIMIT ? OFFSET ?",
                (parent_key or 0, limit + 1, offset),
            )
            rows: list[TreeRow] = []
            size = 0
            more = False
            for item in cursor:
                if len(rows) == limit:
                    more = True
                    break
                row = self._row(item[0])
                cost = resident_size(row.__dict__) + 128
                if size + cost > self.session.limits.page_memory_bytes:
                    if not rows:
                        raise ToolError(
                            "resource_limit", "Tree node exceeds page memory admission."
                        )
                    more = True
                    break
                rows.append(row)
                size += cost
            return TreePage(self.scope, rows, offset + len(rows), more)

    def sibling(self, key: int, *, previous: bool = False) -> TreeRow | None:
        """Navigate siblings using the indexed source-order cursor."""
        with self._lock:
            self._ready()
            row = self._row(key)
            operator, order = ("<", "DESC") if previous else (">", "ASC")
            found = self._connection.execute(
                "SELECT key FROM entries WHERE parent=? AND visible=1 "
                f"AND (first,key){operator}(?,?) "
                f"ORDER BY first {order},key {order} LIMIT 1",
                (row.parent_key or 0, row.first_ordinal, key),
            ).fetchone()
            return self._row(found[0]) if found is not None else None

    def edge_child(self, key: int | None = None, *, last: bool = False) -> TreeRow | None:
        with self._lock:
            self._ready()
            order = "DESC" if last else "ASC"
            found = self._connection.execute(
                "SELECT key FROM entries WHERE parent=? AND visible=1 "
                f"ORDER BY first {order},key {order} LIMIT 1",
                (key or 0,),
            ).fetchone()
            return self._row(found[0]) if found is not None else None

    def node_for_record(self, ordinal: int) -> TreeRow | None:
        with self._lock:
            self._ready()
            row = self._row(-(ordinal + 1))
            return self._row(row.parent_key) if row.parent_key is not None else None

    def is_ancestor(self, key: int, ordinal: int) -> bool:
        """Test a delivered record path with constant resident state, without a depth cap."""
        with self._lock:
            self._ready()
            row = self._row(-(ordinal + 1))
            while row.parent_key is not None:
                if row.parent_key == key:
                    return True
                row = self._row(row.parent_key)
            return False

    def record_page(self, key: int, offset: int = 0, limit: int = 100) -> RecordPage:
        """Original direct contributor records, with separate origins/identities."""
        with self._lock:
            self._ready()
            if offset < 0 or limit < 0 or limit > self.session.limits.max_page_records:
                raise ValueError("tree evidence page exceeds page contract")
            records, origins, identities = [], [], []
            size = 0
            for item in self._connection.execute(
                "SELECT ordinal FROM entries WHERE parent=? AND ordinal IS NOT NULL "
                "ORDER BY first,key LIMIT ? OFFSET ?",
                (key, limit, offset),
            ):
                page = self.session.page(item[0], 1)
                cost = resident_size(page.records[0]) + 128
                if size + cost > self.session.limits.page_memory_bytes:
                    break
                records.extend(page.records)
                origins.extend(page.origins)
                identities.extend(page.identities)
                size += cost
            return RecordPage(
                self.scope.dataset_id,
                offset,
                records,
                origins,
                identities,
                offset + len(records),
                True,
            )

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._connection.close()
                self._closed = True
                # Close readers before the allocation owner reclaims this file.
                self.session.storage.remove_file(self.path)


class TreeJob:
    """One explicitly dataset/request-scoped cancellable tree reconstruction."""

    def __init__(
        self,
        session: Investigation,
        background: bool,
        input_view: RecordView | None = None,
        request_generation: int = 0,
    ) -> None:
        if input_view is not None and input_view.session is not session:
            raise ToolError("scope_mismatch", "Tree input belongs to a different investigation.")
        self.session = session
        self.scope = TreeScope(
            session.dataset_id,
            uuid.uuid4().hex,
            "filtered" if input_view is not None else "unfiltered",
            input_view.view_scope
            if input_view is not None
            else ViewScope(session.dataset_id, session.dataset_id),
            request_generation,
        )
        self._input = input_view
        self._record_count = (
            input_view.record_count if input_view is not None else session.status.record_count
        )
        self.status = TreeStatus("pending", total_records=session.status.record_count)
        self._cancel = threading.Event()
        self._done = threading.Event()
        self._lock = threading.RLock()
        self._result: TraceTree | None = None
        self._worker: threading.Thread | None = None
        if input_view is not None:
            input_view._acquire()
        try:
            self._path = session.storage.create_file(f"tree-{self.scope.request_id}.sqlite")
            if background:
                self._worker = threading.Thread(
                    target=self._run, name=f"slogger-tree-{self.scope.request_id}", daemon=True
                )
                self._worker.start()
            else:
                self._run()
        except BaseException:
            try:
                if hasattr(self, "_path"):
                    session.storage.remove_file(self._path)
            finally:
                if input_view is not None:
                    input_view._release()
            raise

    @property
    def done(self) -> bool:
        """True after build work and staging cleanup have settled."""
        return self._done.is_set()

    def cancel(self) -> None:
        with self._lock:
            if not self.done and self.status.phase != "complete":
                self._cancel.set()

    def wait(self, timeout: float | None = None) -> TreeStatus:
        self._done.wait(timeout)
        return self.status

    def result(self) -> TraceTree:
        with self._lock:
            if self.status.phase != "complete" or self._result is None:
                raise ToolError(
                    "tree_not_ready", "Tree result is not complete.", phase=self.status.phase
                )
            return self._result

    def close(self) -> None:
        self.cancel()
        self.wait()
        with self._lock:
            if self._result is not None:
                self._result.close()
                self._result = None
            self.status = replace(self.status, phase="closed")

    def _check(self) -> None:
        if self._cancel.is_set():
            raise ToolError("operation_canceled", "Trace reconstruction canceled.")
        self.session.require_ready("trace reconstruction")

    def _run(self) -> None:
        connection = None
        try:
            self.status = replace(self.status, phase="building")
            connection = sqlite3.connect(self._path)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA page_size=4096")
            connection.execute("PRAGMA journal_mode=OFF")
            connection.execute("PRAGMA synchronous=OFF")
            connection.execute("PRAGMA mmap_size=0")
            connection.execute(
                f"PRAGMA cache_size=-{max(1, self.session.limits.working_memory_bytes // 8192)}"
            )
            connection.execute("PRAGMA temp_store=MEMORY")
            self._build(connection)
            if self._input is not None:
                self._apply_population(connection)
            connection.close()
            connection = None
            with self._lock, self.session._lifecycle_lock:
                self._check()
                self._result = TraceTree(self.session, self.scope, self._path, self._record_count)
                self.status = replace(self.status, phase="complete")
        except Exception as error:
            if connection is not None:
                connection.close()
            code = error.code if isinstance(error, ToolError) else "tree_failed"
            self.status = replace(
                self.status,
                phase="canceled" if code == "operation_canceled" else "failed",
                diagnostic=Diagnostic(code, str(error)),
            )
        finally:
            cleanup_errors = []
            if self._result is None:
                try:
                    self.session.storage.remove_file(self._path)
                except Exception as error:
                    cleanup_errors.append(str(error))
            if self._input is not None:
                try:
                    self._input._release()
                except Exception as error:
                    cleanup_errors.append(str(error))
                self._input = None
            if cleanup_errors:
                if self._result is not None:
                    try:
                        self._result.close()
                    except Exception as error:
                        cleanup_errors.append(str(error))
                    self._result = None
                self.status = replace(
                    self.status,
                    phase="failed",
                    diagnostic=Diagnostic("cleanup_failed", "; ".join(cleanup_errors)),
                )
            self._done.set()

    def _apply_population(self, db: sqlite3.Connection) -> None:
        """Disk-mark admitted leaves and ancestor closure, one indexed row at a time."""
        assert self._input is not None
        member = struct.Struct("<Q")
        with self._input._path.open("rb") as members:
            for _ in range(self._record_count):
                self._check()
                ordinal = member.unpack(members.read(member.size))[0]
                key = -(ordinal + 1)
                parent = db.execute("SELECT parent FROM entries WHERE key=?", (key,)).fetchone()[0]

                def admit(key=key, parent=parent) -> None:
                    db.execute("UPDATE entries SET visible=1 WHERE key=?", (key,))
                    if parent:
                        db.execute(
                            "UPDATE nodes SET matches=matches+1,children=children+1 WHERE id=?",
                            (parent,),
                        )

                self._write(db, admit)
                while parent:
                    self._check()
                    entry = db.execute(
                        "SELECT parent,visible FROM entries WHERE key=?", (parent,)
                    ).fetchone()
                    if entry["visible"]:
                        break

                    def ancestor(parent=parent, entry=entry) -> None:
                        db.execute("UPDATE entries SET visible=1 WHERE key=?", (parent,))
                        if entry["parent"]:
                            db.execute(
                                "UPDATE nodes SET children=children+1 WHERE id=?",
                                (entry["parent"],),
                            )

                    self._write(db, ancestor)
                    parent = entry["parent"]

    def _write(
        self, connection: sqlite3.Connection, operation: Callable[[], object], payload: int = 0
    ) -> None:
        self._check()
        pages = connection.execute("PRAGMA page_count").fetchone()[0]
        # SQLite itself enforces this admitted ceiling. Splits/overflow that
        # need more space fail the unpublished job; they cannot overspend it.
        allowance = (128 * (max(1, pages).bit_length() + 2) + math.ceil(payload * 4 / 4096)) * 4096
        with self.session.storage.external_growth(self._path, byte_count=allowance):
            connection.execute(f"PRAGMA max_page_count={pages + allowance // 4096}")
            with connection:
                operation()

    @staticmethod
    def _identity(value: object) -> str | None:
        return value if isinstance(value, str) and value else None

    def _build(self, db: sqlite3.Connection) -> None:
        def schema() -> None:
            db.executescript("""
            CREATE TABLE nodes(id INTEGER PRIMARY KEY, identity TEXT UNIQUE, kind TEXT,
              trace TEXT, span TEXT, first INTEGER, label TEXT, records INTEGER DEFAULT 0,
              relationship TEXT DEFAULT 'parent not observed', parent INTEGER DEFAULT 0,
              label_source TEXT DEFAULT 'id', starts INTEGER DEFAULT 0, ends INTEGER DEFAULT 0,
              end_status TEXT, duration TEXT, invalid_end INTEGER DEFAULT 0,
              lifecycle TEXT DEFAULT 'unavailable', name_conflict INTEGER DEFAULT 0,
              color INTEGER DEFAULT 0, token INTEGER DEFAULT 0, step INTEGER DEFAULT 0,
              children INTEGER DEFAULT 0, matches INTEGER DEFAULT 0);
            CREATE INDEX unfinished ON nodes(color,id);
            CREATE INDEX walks ON nodes(token,step);
            CREATE TABLE names(node INTEGER, kind TEXT, value TEXT,
              count INTEGER, PRIMARY KEY(node,kind,value)) WITHOUT ROWID;
            CREATE TABLE entries(key INTEGER PRIMARY KEY, parent INTEGER,
              first INTEGER, ordinal INTEGER, evidence TEXT, visible INTEGER);
            CREATE INDEX entry_order ON entries(parent,first,key);
            CREATE INDEX visible_order ON entries(parent,visible,first,key);
            CREATE TABLE parents(node INTEGER, kind TEXT, value TEXT, first INTEGER,
              count INTEGER, PRIMARY KEY(node,kind,value)) WITHOUT ROWID;
            """)

        self._write(db, schema)

        def node(kind: str, trace: str, span: str | None, first: int, label: str) -> int:
            metadata = TreeRow(0, None, kind, first, trace, span, label)
            if resident_size(metadata.__dict__) + 4096 > self.session.limits.page_memory_bytes:
                raise ToolError("resource_limit", "Trace metadata exceeds page memory admission.")
            identity = json.dumps((kind, trace, span), ensure_ascii=False)
            db.execute(
                "INSERT OR IGNORE INTO nodes(identity,kind,trace,span,first,label) "
                "VALUES(?,?,?,?,?,?)",
                (identity, kind, trace, span, first, label),
            )
            return db.execute("SELECT id FROM nodes WHERE identity=?", (identity,)).fetchone()[0]

        for ordinal in range(self.status.total_records):
            self._check()
            record = self.session.page(ordinal, 1).records[0]
            if resident_size(record) * 6 > self.session.limits.working_memory_bytes * 7 // 8:
                raise ToolError(
                    "resource_limit", "Trace evidence exceeds working memory admission."
                )
            trace = self._identity(record.get("trace_id"))
            span = self._identity(record.get("span_id"))

            def insert(record=record, trace=trace, span=span, ordinal=ordinal) -> None:
                parent = 0
                evidence = ""
                if trace is None:
                    evidence = "invalid trace identifier" if "trace_id" in record else "untraced"
                elif span is None:
                    evidence = (
                        "invalid span identifier" if "span_id" in record else "span not identified"
                    )
                if trace is not None:
                    trace_key = node("trace", trace, None, ordinal, trace)
                    parent = trace_key
                    if span is not None:
                        label = record.get("span", record.get("span_name", span))
                        label_source = (
                            "canonical"
                            if "span" in record
                            else "external"
                            if "span_name" in record
                            else "id"
                        )
                        if not isinstance(label, str):
                            label = span
                        parent = node("span", trace, span, ordinal, label)
                        db.execute("UPDATE nodes SET records=records+1 WHERE id=?", (parent,))
                        if label_source != "id":
                            raw_label = (
                                record.get("span")
                                if label_source == "canonical"
                                else record.get("span_name")
                            )
                            db.execute(
                                "INSERT INTO names VALUES(?,?,?,1) ON CONFLICT(node,kind,value) "
                                "DO UPDATE SET count=count+1",
                                (parent, label_source, json.dumps(raw_label, ensure_ascii=False)),
                            )
                            db.execute(
                                "UPDATE nodes SET label=?,label_source=? WHERE id=? AND "
                                "(label_source='id' OR "
                                "(label_source='external' AND ?='canonical'))",
                                (label, label_source, parent, label_source),
                            )
                        event = record.get("event")
                        if event == "span.start":
                            db.execute("UPDATE nodes SET starts=starts+1 WHERE id=?", (parent,))
                        elif event == "span.end":
                            duration = record.get("duration_ms")
                            status = record.get("status")
                            valid_duration = (
                                isinstance(duration, (int, float))
                                and not isinstance(duration, bool)
                                and duration >= 0
                                and (not isinstance(duration, float) or math.isfinite(duration))
                            )
                            valid = (
                                isinstance(status, str)
                                and status in ("ok", "error")
                                and valid_duration
                            )
                            db.execute(
                                "UPDATE nodes SET ends=ends+1,end_status=?,duration=?,"
                                "invalid_end=invalid_end+? WHERE id=?",
                                (
                                    status if isinstance(status, str) else None,
                                    json.dumps(duration) if valid_duration else None,
                                    not valid,
                                    parent,
                                ),
                            )
                        if "parent_span_id" not in record:
                            kind, value = (
                                ("root" if record.get("event") == "span.start" else "unobserved"),
                                "",
                            )
                        else:
                            raw = record["parent_span_id"]
                            kind = (
                                "id"
                                if self._identity(raw) is not None
                                else "null"
                                if raw is None
                                else "empty"
                                if raw == ""
                                else "invalid"
                            )
                            value = json.dumps(raw, ensure_ascii=False)
                        db.execute(
                            "INSERT INTO parents VALUES(?,?,?,?,1) ON CONFLICT(node,kind,value) "
                            "DO UPDATE SET count=count+1",
                            (parent, kind, value, ordinal),
                        )
                db.execute(
                    "INSERT INTO entries VALUES(?,?,?,?,?,?)",
                    (-(ordinal + 1), parent, ordinal, ordinal, evidence, int(self._input is None)),
                )
                if parent:
                    if self._input is None:
                        db.execute("UPDATE nodes SET children=children+1 WHERE id=?", (parent,))
                    if span is None:
                        db.execute("UPDATE nodes SET records=records+1 WHERE id=?", (parent,))

            self._write(db, insert, resident_size(record))
            self.status = replace(self.status, processed_records=ordinal + 1)
            del insert, record

        last = 0
        while True:
            item = db.execute(
                "SELECT * FROM nodes WHERE id>? ORDER BY id LIMIT 1", (last,)
            ).fetchone()
            if item is None:
                break
            last = item["id"]

            def relate(item=item, last=last) -> None:
                if item["kind"] == "trace":
                    parent, relationship = 0, "trace"
                else:
                    parent = node("trace", item["trace"], None, item["first"], item["trace"])
                    observed = db.execute(
                        "SELECT kind,value FROM parents WHERE node=? "
                        "AND kind!='unobserved' LIMIT 2",
                        (last,),
                    ).fetchall()
                    relationship = (
                        "missing parent" if item["kind"] == "placeholder" else "parent not observed"
                    )
                    if len(observed) == 1:
                        kind, value = observed[0]
                        if kind == "root":
                            relationship = "root"
                        elif kind == "id":
                            parent = node(
                                "span",
                                item["trace"],
                                json.loads(value),
                                item["first"],
                                "missing parent",
                            )
                            db.execute(
                                "UPDATE nodes SET kind='placeholder' WHERE id=? AND records=0",
                                (parent,),
                            )
                            relationship = "parent observed"
                        else:
                            relationship = f"{kind} parent"
                    elif len(observed) > 1:
                        relationship = "conflicting parents"
                starts, ends = item["starts"], item["ends"]
                lifecycle = "unavailable" if not starts and not ends else "incomplete"
                if starts > 1 or ends > 1 or item["invalid_end"]:
                    lifecycle = "conflicting"
                elif starts == ends == 1:
                    lifecycle = "complete"
                names = db.execute(
                    "SELECT value FROM names WHERE node=? AND kind=? LIMIT 2",
                    (last, item["label_source"]),
                ).fetchall()
                db.execute(
                    "UPDATE nodes SET parent=?,relationship=?,lifecycle=?,"
                    "name_conflict=? WHERE id=?",
                    (parent, relationship, lifecycle, len(names) > 1, last),
                )

            self._write(db, relate, resident_size(dict(item)))

        # Functional-graph walks use disk visitation/path state, never recursion
        # or a Python set proportional to the depth of a trace.
        while True:
            first = db.execute("SELECT id FROM nodes WHERE color=0 ORDER BY id LIMIT 1").fetchone()
            if first is None:
                break
            token, current, step = first[0], first[0], 0
            while current:
                self._check()
                item = db.execute(
                    "SELECT parent,color,token,step FROM nodes WHERE id=?", (current,)
                ).fetchone()
                if item["color"]:
                    if item["color"] == 1 and item["token"] == token:
                        cycle_step = item["step"]
                        while True:
                            cycle = db.execute(
                                "SELECT id,trace FROM nodes WHERE token=? AND step>=? "
                                "ORDER BY step LIMIT 1",
                                (token, cycle_step),
                            ).fetchone()
                            if cycle is None:
                                break
                            trace_key = db.execute(
                                "SELECT id FROM nodes WHERE identity=?",
                                (json.dumps(("trace", cycle["trace"], None), ensure_ascii=False),),
                            ).fetchone()[0]
                            self._write(
                                db,
                                lambda cycle=cycle, trace_key=trace_key: db.execute(
                                    "UPDATE nodes SET relationship='cycle',parent=? WHERE id=?",
                                    (trace_key, cycle["id"]),
                                ),
                            )
                            cycle_step = (
                                db.execute(
                                    "SELECT step FROM nodes WHERE id=?", (cycle["id"],)
                                ).fetchone()[0]
                                + 1
                            )
                    break
                self._write(
                    db,
                    lambda token=token, step=step, current=current: db.execute(
                        "UPDATE nodes SET color=1,token=?,step=? WHERE id=?", (token, step, current)
                    ),
                )
                current, step = item["parent"], step + 1
            finished_step = 0
            while True:
                finished = db.execute(
                    "SELECT id,step FROM nodes WHERE token=? AND step>=? ORDER BY step LIMIT 1",
                    (token, finished_step),
                ).fetchone()
                if finished is None:
                    break
                self._write(
                    db,
                    lambda finished=finished: db.execute(
                        "UPDATE nodes SET color=2 WHERE id=?", (finished["id"],)
                    ),
                )
                finished_step = finished["step"] + 1

        last = 0
        while True:
            item = db.execute(
                "SELECT id,parent,first FROM nodes WHERE id>? ORDER BY id LIMIT 1", (last,)
            ).fetchone()
            if item is None:
                break
            last = item["id"]

            def entry(item=item, last=last) -> None:
                db.execute(
                    "INSERT INTO entries VALUES(?,?,?,NULL,NULL,?)",
                    (last, item["parent"], item["first"], int(self._input is None)),
                )
                if item["parent"] and self._input is None:
                    db.execute("UPDATE nodes SET children=children+1 WHERE id=?", (item["parent"],))

            self._write(db, entry)
