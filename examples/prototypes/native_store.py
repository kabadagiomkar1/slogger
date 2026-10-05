"""THROWAWAY capture/paging experiment, not a slogger public storage API."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
import time
import uuid
from collections import Counter, OrderedDict
from pathlib import Path

FORMAT = 1
MAX_LINE = 8 * 1024 * 1024
BATCH = 2048


def path_spelling(path):
    return "".join(
        ("." if i else "") + key if key.isidentifier() else "[" + json.dumps(key) + "]"
        for i, key in enumerate(path)
    )


def discover(record, samples, path=()):
    if len(path) > 6:
        return
    for key, value in record.items():
        parts = (*path, key)
        spelling = path_spelling(parts)
        if spelling not in samples and len(samples) >= 512:
            continue
        counts = samples.setdefault(spelling, Counter())
        if isinstance(value, dict):
            discover(value, samples, parts)
        elif value is None or isinstance(value, (bool, int, float, str)):
            text = json.dumps(value, ensure_ascii=False)
            if len(text) <= 200 and (text in counts or len(counts) < 64):
                counts[text] += 1


def connect(path):
    db = sqlite3.connect(path, timeout=30, check_same_thread=False)
    db.execute("PRAGMA cache_size=-4096")
    return db


def size_of(root):
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file())


def lock(path, blocking=False):
    handle = path.open("a+b")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
    except BlockingIOError:
        handle.close()
        return None
    return handle


def check_cancel(cancel):
    if cancel.is_set():
        raise InterruptedError("Cancelled")


class Store:
    def __init__(self, directory, manifest, lease=None, ram_mib=32, disk_gb=10):
        self.directory = directory
        self.manifest = manifest
        self.lease = lease
        self.count = manifest["count"]
        self.db_path = directory / "index.sqlite"
        self.raw = (directory / "records.jsonl").open("rb")
        self.db = connect(self.db_path)
        self.cache = OrderedDict()
        self.cache_bytes = 0
        self.ram_limit = ram_mib * 1024 * 1024
        self.disk_gb = disk_gb
        self.view = None
        self.view_count = self.count
        self.search = None

    def close(self):
        self.drop(self.search)
        self.drop(self.view)
        self.raw.close()
        self.db.close()
        if self.lease is not None:
            self.lease.close()
            self.lease = None

    def row_id(self, position):
        if self.view is None:
            return position + 1
        row = self.db.execute(
            f'SELECT rid FROM "{self.view}" WHERE seq=?', (position + 1,)
        ).fetchone()
        return row[0] if row else None

    def position_of(self, rid):
        if self.view is None:
            return rid - 1 if rid <= self.count else None
        row = self.db.execute(f'SELECT seq FROM "{self.view}" WHERE rid=?', (rid,)).fetchone()
        return row[0] - 1 if row else None

    def record(self, rid):
        if rid in self.cache:
            self.cache.move_to_end(rid)
            return self.cache[rid][0]
        source, line, offset, length = self.db.execute(
            "SELECT source,line,offset,length FROM records WHERE id=?", (rid,)
        ).fetchone()
        self.raw.seek(offset)
        data = self.raw.read(length)
        result = (json.loads(data), self.manifest["files"][source]["path"], line)
        # Conservative admission weight for decoded objects, not an RSS guarantee.
        weight = len(data) * 8 + 512
        if weight <= self.ram_limit:
            self.cache[rid] = (result, weight)
            self.cache_bytes += weight
            while self.cache_bytes > self.ram_limit:
                _, (_, old_weight) = self.cache.popitem(last=False)
                self.cache_bytes -= old_weight
        return result

    def batches(self, cancel, view=None):
        with connect(self.db_path) as db, (self.directory / "records.jsonl").open("rb") as raw:
            if view:
                sql = (
                    f'SELECT r.id,r.offset,r.length,v.seq FROM "{view}" v '
                    "JOIN records r ON r.id=v.rid ORDER BY v.seq"
                )
            else:
                sql = "SELECT id,offset,length,id FROM records ORDER BY id"
            cursor = db.execute(sql)
            while rows := cursor.fetchmany(BATCH):
                check_cancel(cancel)
                batch = []
                batch_bytes = 0
                for rid, offset, length, seq in rows:
                    if batch and batch_bytes + length > 2 * 1024 * 1024:
                        yield batch
                        check_cancel(cancel)
                        batch = []
                        batch_bytes = 0
                    raw.seek(offset)
                    batch.append((rid, seq, json.loads(raw.read(length))))
                    batch_bytes += length
                if batch:
                    yield batch

    def new_table(self, prefix):
        name = prefix + uuid.uuid4().hex
        with connect(self.db_path) as db:
            db.execute(f'CREATE TABLE "{name}" (seq INTEGER PRIMARY KEY, rid INTEGER)')
        return name

    def drop(self, name):
        if name:
            with connect(self.db_path) as db:
                db.execute(f'DROP TABLE IF EXISTS "{name}"')

    def check_budget(self):
        if size_of(self.directory.parent) > self.disk_gb * 1_000_000_000:
            raise RuntimeError("Managed cache budget exceeded; clear unused datasets in Settings")


def open_capture(
    paths, root, cancel, progress, partial=None, budget_gb=10, ram_mib=32, active_store=None
):
    """Capture fixed byte boundaries; validate old captures by SHA-256 content."""
    started = time.monotonic()
    root.mkdir(parents=True, exist_ok=True)
    capture_lock = lock(root / "capture.lock")
    if capture_lock is None:
        raise RuntimeError("Another prototype is capturing here; try another --cache-dir")
    directory = None
    lease = None
    try:
        boundaries = []
        for item in paths:
            path = Path(item).resolve(strict=True)
            stat = path.stat()
            if not path.is_file():
                raise ValueError(f"Not a regular file: {path}")
            boundaries.append({"path": str(path), "size": stat.st_size, "inode": stat.st_ino})
        total = sum(item["size"] for item in boundaries)
        budget = int(budget_gb * 1_000_000_000)

        def reclaim(required=0, exclude=None):
            entries = sorted(root.glob("dataset-*"), key=lambda p: p.stat().st_mtime)
            usage = size_of(root)
            for entry in entries:
                expired = time.time() - entry.stat().st_mtime > 7 * 86400
                if entry == exclude or (not expired and usage + required <= budget):
                    continue
                entry_lock = lock(entry / "lease.lock")
                if entry_lock is None:
                    continue
                try:
                    weight = size_of(entry)
                    shutil.rmtree(entry)
                    usage -= weight
                finally:
                    entry_lock.close()
            if usage + required > budget:
                raise RuntimeError(
                    "10 GB prototype cache budget exhausted; active captures protected"
                )

        # Abandoned partial captures have no reusable manifest and are safe to clean
        # while the capture lock is held. Active readers protect complete datasets.
        for abandoned in root.glob("partial-*"):
            abandoned_lock = lock(abandoned / "lease.lock")
            if abandoned_lock:
                shutil.rmtree(abandoned)
                abandoned_lock.close()
        reclaim()
        candidates = sorted(root.glob("dataset-*"), key=lambda p: p.stat().st_mtime, reverse=True)
        for candidate in candidates:
            try:
                manifest = json.loads((candidate / "manifest.json").read_text())
            except (OSError, ValueError):
                continue
            files = manifest.get("files", [])
            if manifest.get("format") != FORMAT or [(f["path"], f["size"]) for f in files] != [
                (f["path"], f["size"]) for f in boundaries
            ]:
                continue
            candidate_lease = lock(candidate / "lease.lock")
            borrowed = (
                candidate_lease is None
                and active_store is not None
                and active_store.directory == candidate
            )
            if candidate_lease is None and not borrowed:
                continue
            verified = 0
            valid = True
            try:
                for expected, boundary in zip(files, boundaries, strict=True):
                    digest = hashlib.sha256()
                    with open(boundary["path"], "rb") as source:
                        remaining = boundary["size"]
                        before = os.fstat(source.fileno())
                        while remaining:
                            check_cancel(cancel)
                            chunk = source.read(min(4 * 1024 * 1024, remaining))
                            if not chunk:
                                raise RuntimeError("Source truncated during verification")
                            digest.update(chunk)
                            remaining -= len(chunk)
                            verified += len(chunk)
                            progress("Verifying saved capture", verified, total, manifest["count"])
                        after = os.fstat(source.fileno())
                        if before.st_mtime_ns != after.st_mtime_ns:
                            raise RuntimeError("Source changed during verification; retry")
                    if digest.hexdigest() != expected["sha256"]:
                        valid = False
                        break
                if valid:
                    os.utime(candidate, None)
                    # Clear abandoned result tables from prior exited processes.
                    with connect(candidate / "index.sqlite") as db:
                        if not borrowed:
                            names = db.execute(
                                "SELECT name FROM sqlite_master WHERE type='table' "
                                "AND (name LIKE 'filter_%' OR name LIKE 'search_%')"
                            ).fetchall()
                            for (name,) in names:
                                if name.removeprefix("filter_").removeprefix("search_").isalnum():
                                    db.execute(f'DROP TABLE "{name}"')
                    store = Store(candidate, manifest, candidate_lease, ram_mib, budget_gb)
                    return store, {"mode": "verified reuse", "seconds": time.monotonic() - started}
            except BaseException:
                if candidate_lease:
                    candidate_lease.close()
                raise
            if candidate_lease:
                candidate_lease.close()

        reclaim(total)
        directory = root / ("partial-" + uuid.uuid4().hex)
        directory.mkdir()
        lease = lock(directory / "lease.lock")
        db = connect(directory / "index.sqlite")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute(
            "CREATE TABLE records (id INTEGER PRIMARY KEY, source INTEGER, line INTEGER, "
            "offset INTEGER, length INTEGER, trace TEXT, span TEXT, parent TEXT, name TEXT)"
        )
        manifest = {"format": FORMAT, "files": boundaries, "count": 0, "skipped": 0, "samples": {}}
        samples = {}
        count = skipped = copied = max_record_bytes = 0
        pending = []
        last_tick = time.monotonic()
        first_visible = None
        announced = False
        with (directory / "records.jsonl").open("wb") as output:
            for ordinal, boundary in enumerate(boundaries):
                digest = hashlib.sha256()
                with open(boundary["path"], "rb") as source:
                    remaining = boundary["size"]
                    before = os.fstat(source.fileno())
                    if before.st_ino != boundary["inode"] or before.st_size < remaining:
                        raise RuntimeError("Source replaced/truncated before capture; retry")
                    line = 0
                    while remaining:
                        check_cancel(cancel)
                        line += 1
                        offset = copied
                        data = source.readline(min(MAX_LINE + 1, remaining))
                        if not data:
                            raise RuntimeError("Source truncated during capture")
                        oversized = len(data) > MAX_LINE
                        output.write(data)
                        digest.update(data)
                        remaining -= len(data)
                        copied += len(data)
                        while oversized and not data.endswith(b"\n") and remaining:
                            data = source.readline(min(MAX_LINE, remaining))
                            if not data:
                                raise RuntimeError("Source truncated during long record")
                            output.write(data)
                            digest.update(data)
                            remaining -= len(data)
                            copied += len(data)
                        try:
                            record = None if oversized else json.loads(data)
                        except (ValueError, UnicodeError):
                            record = None
                        if isinstance(record, dict):
                            count += 1
                            max_record_bytes = max(max_record_bytes, copied - offset)
                            if line <= 5000:
                                discover(record, samples)
                            context = record.get("context", {})
                            if not isinstance(context, dict):
                                context = {}

                            def text_value(key, fallback="", record=record, context=context):
                                value = record.get(key, context.get(key, fallback))
                                return str(value) if value is not None else ""

                            pending.append(
                                (
                                    count,
                                    ordinal,
                                    line,
                                    offset,
                                    copied - offset,
                                    text_value("trace_id"),
                                    text_value("span_id"),
                                    text_value("parent_span_id"),
                                    text_value("span_name"),
                                )
                            )
                        elif oversized or data.strip():
                            skipped += 1
                        now = time.monotonic()
                        if len(pending) >= BATCH or now - last_tick >= 0.5:
                            output.flush()
                            db.executemany(
                                "INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?)", pending
                            )
                            db.commit()
                            pending.clear()
                            manifest["count"] = count
                            manifest["skipped"] = skipped
                            manifest["max_record_bytes"] = max_record_bytes
                            if count and not announced:
                                first_visible = now - started
                                if partial:
                                    partial(directory, dict(manifest))
                                announced = True
                            progress("Capturing", copied, total, count)
                            reclaim(exclude=directory)
                            last_tick = now
                    after = os.fstat(source.fileno())
                    # Appends beyond the fixed boundary are excluded. A same-size
                    # rewrite during capture is detected, not silently accepted.
                    if after.st_size < before.st_size or (
                        after.st_size == before.st_size and after.st_mtime_ns != before.st_mtime_ns
                    ):
                        raise RuntimeError("Source modified during capture; retry")
                boundary["sha256"] = digest.hexdigest()
            output.flush()
        db.executemany("INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?)", pending)
        db.commit()
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        db.close()
        manifest.update(
            count=count,
            skipped=skipped,
            samples={key: dict(values) for key, values in samples.items()},
            captured_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            bytes=total,
            max_record_bytes=max_record_bytes,
        )
        (directory / "manifest.json").write_text(json.dumps(manifest))
        reclaim(exclude=directory)
        target = root / ("dataset-" + directory.name.removeprefix("partial-"))
        directory.rename(target)
        directory = None
        store = Store(target, manifest, lease, ram_mib, budget_gb)
        lease = None
        return store, {
            "mode": "cold capture",
            "seconds": time.monotonic() - started,
            "first_records_seconds": first_visible or time.monotonic() - started,
        }
    except BaseException:
        if lease:
            lease.close()
        # The UI may be inspecting a partial capture. Preserve it until next
        # opening; capture.lock ensures abandoned captures are cleaned then.
        raise
    finally:
        capture_lock.close()


def demo_files(root):
    """Three realistic investigations, varied user fields, and ASCII-only log text."""
    root.mkdir(parents=True, exist_ok=True)
    flows = [
        (
            "checkout-2281",
            "Checkout",
            {"order_id": "ORD-2281", "customer": "Maya", "region": "eu-west", "total": 149.50},
        ),
        (
            "invoice-707",
            "Invoice run",
            {"invoice_id": "INV-707", "account": "Northwind", "currency": "USD", "total": 420.00},
        ),
        (
            "delivery-401",
            "Delivery",
            {
                "shipment_id": "SHP-401",
                "carrier": "ParcelCo",
                "warehouse": "BLR-02",
                "total": 89.00,
            },
        ),
    ]
    recipes = [
        [
            (
                "shop.api",
                "INFO",
                "Received checkout request",
                "flow",
                "",
                {"route": "/v1/orders", "items": 3},
            ),
            (
                "shop.cart",
                "DEBUG",
                "Loaded cart from session",
                "validate",
                "flow",
                {"cart_id": "CART-39", "sku": "HEADPHONES-01"},
            ),
            (
                "shop.cart",
                "INFO",
                "Validated discount code",
                "validate",
                "flow",
                {"coupon": "WELCOME10", "discount": 15.00},
            ),
            (
                "shop.api",
                "INFO",
                "Accepted order for processing",
                "flow",
                "",
                {"status": "queued", "priority": "normal"},
            ),
            (
                "shop.auth",
                "WARN",
                "Access token expires soon",
                "flow",
                "",
                {"user_id": "usr-42", "expires_in_s": 45},
            ),
            (
                "shop.api",
                "INFO",
                "Returned checkout response",
                "flow",
                "",
                {"http_status": 202, "request_id": "req-001"},
            ),
            (
                "billing.api",
                "INFO",
                "Started monthly invoice run",
                "flow",
                "",
                {"period": "2026-09", "accounts": 24},
            ),
            (
                "billing.rules",
                "DEBUG",
                "Matched enterprise billing plan",
                "validate",
                "flow",
                {"plan": "enterprise", "seats": 18},
            ),
            (
                "billing.rules",
                "INFO",
                "Applied account credit",
                "validate",
                "flow",
                {"credit": 30.00, "reason": "service-credit"},
            ),
            (
                "billing.api",
                "WARN",
                "Account has no purchase order",
                "flow",
                "",
                {"contact": "finance@example.test", "action": "notify"},
            ),
            (
                "billing.api",
                "INFO",
                "Queued invoice document",
                "flow",
                "",
                {"template": "monthly-v2", "format": "PDF"},
            ),
            (
                "billing.api",
                "INFO",
                "Invoice run accepted",
                "flow",
                "",
                {"http_status": 200, "request_id": "req-002"},
            ),
            (
                "shipping.api",
                "INFO",
                "Received dispatch instruction",
                "flow",
                "",
                {"destination": "Pune", "packages": 2},
            ),
            (
                "shipping.routes",
                "DEBUG",
                "Selected delivery service",
                "validate",
                "flow",
                {"service": "express", "eta_days": 2},
            ),
            (
                "shipping.routes",
                "WARN",
                "Preferred pickup slot unavailable",
                "validate",
                "flow",
                {"requested_slot": "09:00", "fallback_slot": "11:30"},
            ),
            (
                "shipping.api",
                "INFO",
                "Reserved carrier pickup",
                "flow",
                "",
                {"booking_id": "PK-019", "dock": "B4"},
            ),
            (
                "shipping.api",
                "INFO",
                "Published tracking link",
                "flow",
                "",
                {"tracking": "PC-840199", "channel": "email"},
            ),
            (
                "shipping.api",
                "INFO",
                "Dispatch request completed",
                "flow",
                "",
                {"http_status": 201, "request_id": "req-003"},
            ),
        ],
        [
            (
                "shop.payments",
                "INFO",
                "Authorising card payment",
                "payment",
                "flow",
                {"provider": "stripe", "amount": 149.50, "attempt": 1},
            ),
            (
                "shop.payments",
                "ERROR",
                "Payment gateway timeout",
                "payment",
                "flow",
                {"provider": "stripe", "error_code": "GATEWAY_TIMEOUT", "retry_in_s": 2},
            ),
            (
                "shop.payments",
                "WARN",
                "Retrying payment with idempotency key",
                "payment",
                "flow",
                {"attempt": 2, "idempotency_key": "pay-2281"},
            ),
            (
                "shop.payments",
                "INFO",
                "Payment authorised",
                "payment",
                "flow",
                {"transaction_id": "TX-8192", "amount": 149.50},
            ),
            (
                "shop.inventory",
                "INFO",
                "Reserved requested items",
                "inventory",
                "flow",
                {"sku": "HEADPHONES-01", "quantity": 3, "remaining": 47},
            ),
            (
                "shop.notifications",
                "INFO",
                "Sent order confirmation",
                "notify",
                "flow",
                {"channel": "email", "template": "order-confirmation"},
            ),
            (
                "billing.worker",
                "INFO",
                "Calculating invoice line items",
                "payment",
                "flow",
                {"line_items": 4, "tax_rate": 0.18},
            ),
            (
                "billing.worker",
                "DEBUG",
                "Rounded invoice tax",
                "payment",
                "flow",
                {"tax": 75.60, "rounding": "half-up"},
            ),
            (
                "billing.worker",
                "INFO",
                "Rendered invoice document",
                "inventory",
                "flow",
                {"pages": 2, "bytes": 18432},
            ),
            (
                "billing.mail",
                "ERROR",
                "Invoice email rejected by recipient server",
                "notify",
                "flow",
                {"smtp_code": 550, "recipient": "billing@example.test", "attempt": 1},
            ),
            (
                "billing.mail",
                "WARN",
                "Moved invoice to manual delivery queue",
                "notify",
                "flow",
                {"queue": "invoice-review", "reason": "mailbox-unavailable"},
            ),
            (
                "billing.worker",
                "INFO",
                "Invoice document archived",
                "inventory",
                "flow",
                {"bucket": "invoices", "retention_days": 365},
            ),
            (
                "shipping.labels",
                "INFO",
                "Generating carrier label",
                "payment",
                "flow",
                {"format": "ZPL", "printer": "warehouse-label-2"},
            ),
            (
                "shipping.labels",
                "DEBUG",
                "Validated parcel dimensions",
                "payment",
                "flow",
                {"weight_kg": 1.8, "size": "30x20x12"},
            ),
            (
                "shipping.inventory",
                "WARN",
                "Parcel moved to overflow staging",
                "inventory",
                "flow",
                {"zone": "overflow-A", "capacity_pct": 92},
            ),
            (
                "shipping.events",
                "INFO",
                "Carrier acknowledged booking",
                "notify",
                "flow",
                {"carrier_ref": "PC-840199", "status": "confirmed"},
            ),
            (
                "shipping.events",
                "INFO",
                "Published dispatch event",
                "notify",
                "flow",
                {"topic": "shipment.dispatched", "partition": 2},
            ),
            (
                "shipping.worker",
                "INFO",
                "Dispatch workflow completed",
                "inventory",
                "flow",
                {"processed": 2, "result": "success"},
            ),
        ],
        [
            (
                "shop.db",
                "DEBUG",
                "Acquired pooled connection",
                "database",
                "payment",
                {"pool": "primary", "in_use": 7, "available": 13},
            ),
            (
                "shop.db",
                "INFO",
                "Inserted order row",
                "database",
                "payment",
                {"table": "orders", "rows_affected": 1},
            ),
            (
                "shop.db",
                "DEBUG",
                "Wrote payment transaction",
                "database",
                "payment",
                {"table": "payments", "transaction_id": "TX-8192"},
            ),
            (
                "shop.db",
                "INFO",
                "Committed checkout transaction",
                "database",
                "payment",
                {"isolation": "read_committed", "statements": 4},
            ),
            (
                "shop.cache",
                "DEBUG",
                "Invalidated customer cart",
                "cache",
                "flow",
                {"cache_key": "cart:usr-42", "cache_hit": True},
            ),
            (
                "shop.db",
                "INFO",
                "Released pooled connection",
                "database",
                "payment",
                {"pool": "primary", "in_use": 6},
            ),
            (
                "billing.db",
                "DEBUG",
                "Fetched usage for billing period",
                "database",
                "payment",
                {"table": "usage", "rows": 1842},
            ),
            (
                "billing.db",
                "WARN",
                "Usage export is missing one day",
                "database",
                "payment",
                {"missing_date": "2026-09-18", "completeness_pct": 96.7},
            ),
            (
                "billing.db",
                "INFO",
                "Saved invoice summary",
                "database",
                "payment",
                {"table": "invoices", "subtotal": 420.00},
            ),
            (
                "billing.db",
                "INFO",
                "Recorded invoice audit entry",
                "database",
                "payment",
                {"actor": "billing-service", "action": "invoice.created"},
            ),
            (
                "billing.cache",
                "DEBUG",
                "Updated account billing cache",
                "cache",
                "flow",
                {"ttl_s": 3600, "cache_hit": False},
            ),
            (
                "billing.db",
                "INFO",
                "Billing transaction committed",
                "database",
                "payment",
                {"statements": 6, "result": "success"},
            ),
            (
                "shipping.db",
                "INFO",
                "Loaded warehouse stock allocation",
                "database",
                "payment",
                {"table": "allocations", "rows": 2},
            ),
            (
                "shipping.db",
                "WARN",
                "Retried allocation after lock conflict",
                "database",
                "payment",
                {"lock_wait_ms": 240, "attempt": 2},
            ),
            (
                "shipping.db",
                "INFO",
                "Saved shipment tracking record",
                "database",
                "payment",
                {"table": "shipments", "tracking": "PC-840199"},
            ),
            (
                "shipping.db",
                "DEBUG",
                "Updated inventory reservation",
                "database",
                "payment",
                {"sku": "HEADPHONES-01", "reserved": 2},
            ),
            (
                "shipping.cache",
                "INFO",
                "Refreshed warehouse availability",
                "cache",
                "flow",
                {"warehouse": "BLR-02", "ttl_s": 120},
            ),
            (
                "shipping.db",
                "INFO",
                "Shipping transaction committed",
                "database",
                "payment",
                {"statements": 3, "result": "success"},
            ),
        ],
    ]
    paths = []
    for source, rows in enumerate(recipes):
        path = root / ("api.jsonl", "worker.jsonl", "database.jsonl")[source]
        paths.append(str(path))
        with path.open("w") as output:
            for i, (logger, level, message, span, parent, fields) in enumerate(rows):
                trace, flow_name, context = flows[i // 6]
                names = {
                    "flow": flow_name,
                    "validate": "validate",
                    "payment": "authorise" if i // 6 == 0 else "process",
                    "inventory": "reserve" if i // 6 == 0 else "prepare",
                    "notify": "notify",
                    "database": "db",
                    "cache": "cache",
                }
                record = {
                    "timestamp": (
                        f"2026-10-04T09:{41 + i // 6:02}:{source * 12 + i % 6:02}."
                        f"{137 + i * 11:03}Z"
                    ),
                    "level": level,
                    "logger": logger,
                    "message": message,
                    "span_name": names[span],
                    **(
                        context
                        if i % 6 == 0
                        else {next(iter(context)): next(iter(context.values()))}
                    ),
                    **fields,
                    "trace_id": "trace-" + trace,
                    "span_id": span,
                    "parent_span_id": parent,
                    "event": "span_start" if i % 6 == 0 else "span_end" if i % 6 == 5 else "log",
                    "duration_ms": 800 if level == "ERROR" else 12 + i * 9,
                    "filename": logger.replace(".", "/") + ".py",
                    "lineno": 74 + i,
                }
                if level == "ERROR":
                    record["exception"] = {
                        "type": "TimeoutError" if source == 1 and i == 1 else "DeliveryError",
                        "message": message,
                        "retryable": True,
                    }
                output.write(json.dumps(record) + "\n")
    return paths
