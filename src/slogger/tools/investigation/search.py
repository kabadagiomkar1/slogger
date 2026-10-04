"""Decoded literal text matching and bounded complete record-match indexes."""

from __future__ import annotations

import json
import struct
import threading
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from ..errors import ToolError
from .filters import OperationStatus, RecordView, ViewScope
from .models import Diagnostic
from .resources import resident_size

if TYPE_CHECKING:
    from .session import Investigation

_MEMBER = struct.Struct("<Q")
_INDEX = struct.Struct("<QQQQ")


@dataclass(frozen=True)
class SearchProjection:
    """Explicit console field policy, supplied by a consumer rather than inferred.

    Known primary fields select console-shaped records. Other fields are visible
    unless hidden. A fallback is visible only if its corresponding primary key is
    absent. Records without any primary key expose all fields when requested.
    """

    primary_fields: tuple[str, ...]
    hidden_fields: tuple[str, ...]
    include_fields: tuple[str, ...] = ()
    fallback_fields: tuple[tuple[str, str], ...] = ()
    generic_fallback: bool = True

    def fields(self, record: dict[str, Any]) -> Iterator[tuple[str, Any]]:
        if self.generic_fallback and not any(key in record for key in self.primary_fields):
            yield from record.items()
            return
        for key, value in record.items():
            if (
                key in self.primary_fields
                or key in self.include_fields
                or key not in self.hidden_fields
            ):
                yield key, value
            elif any(
                key == fallback and primary not in record
                for primary, fallback in self.fallback_fields
            ):
                yield key, value


@dataclass(frozen=True)
class SearchOptions:
    text: str
    scope: Literal["console", "full"] = "full"
    case_sensitive: bool = False
    whole_word: bool = False
    projection: SearchProjection | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("Search text must be a string.")
        if self.scope not in ("console", "full"):
            raise ValueError("Search scope must be console or full.")
        if self.scope == "console" and self.projection is None:
            raise ValueError("Console search requires an explicit field projection.")


@dataclass(frozen=True)
class SearchScope:
    input_scope: ViewScope
    options: SearchOptions
    request_generation: int = 0


def _word(character: str) -> bool:
    # Python's Unicode alphanumeric categories plus underscore; combining marks
    # continue a word as well, so decomposed accented words have no interior edge.
    import unicodedata

    return (
        character == "_" or character.isalnum() or unicodedata.category(character).startswith("M")
    )


def match_ranges(text: str, options: SearchOptions) -> Iterator[tuple[int, int]]:
    """Original Unicode scalar offsets, including complete casefold expansions.

    No normalization is implied. Whole word means neither adjacent original
    character is alphanumeric, underscore, or a Unicode combining mark. Casefold
    expansions can match as a whole (ss matches ß), never a partial scalar.
    """
    if not options.text:
        return
    needle = options.text if options.case_sensitive else options.text.casefold()
    haystack = text if options.case_sensitive else text.casefold()
    folded_position, original_position = 0, 0
    found = haystack.find(needle)
    while found >= 0:
        finish = found + len(needle)
        while original_position < len(text) and folded_position < found:
            folded_position += len(
                text[original_position]
                if options.case_sensitive
                else text[original_position].casefold()
            )
            original_position += 1
        start, boundary = original_position, folded_position == found
        while original_position < len(text) and folded_position < finish:
            folded_position += len(
                text[original_position]
                if options.case_sensitive
                else text[original_position].casefold()
            )
            original_position += 1
        end = original_position
        if (
            boundary
            and folded_position == finish
            and (
                not options.whole_word
                or (
                    (start == 0 or not _word(text[start - 1]))
                    and (end == len(text) or not _word(text[end]))
                )
            )
        ):
            yield start, end
        found = haystack.find(needle, finish)


def decoded_texts(value: Any) -> Iterator[str]:
    """Names and separate decoded leaves, without invented joining or escapes."""
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from decoded_texts(child)
    elif isinstance(value, list):
        for child in value:
            yield from decoded_texts(child)
    elif isinstance(value, str):
        yield value
    else:
        yield json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def record_matches(record: dict[str, Any], options: SearchOptions) -> bool:
    if not options.text:
        return False
    fields = (
        options.projection.fields(record)
        if options.scope == "console" and options.projection
        else record.items()
    )
    for name, value in fields:
        if next(match_ranges(name, options), None) is not None:
            return True
        for text in decoded_texts(value):
            if next(match_ranges(text, options), None) is not None:
                return True
    return False


class SearchResult(RecordView):
    """Paged record matches, with ordered next/previous navigation and wrapping."""

    def __init__(self, session: Investigation, path: Path, count: int, scope: SearchScope):
        super().__init__(session, path, count, scope)
        self._search_scope = scope

    @property
    def scope(self) -> SearchScope:
        return self._search_scope

    def neighbor(self, ordinal: int, *, previous: bool = False) -> int | None:
        with self._lock:
            self._check()
            if not self.record_count:
                return None
            with self._path.open("rb") as members:
                low, high = 0, self.record_count
                while low < high:
                    middle = (low + high) // 2
                    members.seek(middle * _MEMBER.size)
                    current = _MEMBER.unpack(members.read(_MEMBER.size))[0]
                    if current < ordinal or (current == ordinal and not previous):
                        low = middle + 1
                    else:
                        high = middle
                position = (low - 1) % self.record_count if previous else low % self.record_count
                members.seek(position * _MEMBER.size)
                return _MEMBER.unpack(members.read(_MEMBER.size))[0]


class SearchJob:
    """One cancellable literal search; only successful complete indexes publish."""

    def __init__(
        self,
        session: Investigation,
        options: SearchOptions,
        input_view: RecordView | None,
        request_generation: int,
    ):
        session.require_ready("search")
        if input_view is not None and input_view.session is not session:
            raise ToolError("scope_mismatch", "Search input belongs to a different investigation.")
        if (
            resident_size(options.text)
            + resident_size(options.text.casefold())
            + (resident_size(options.projection.__dict__) if options.projection else 0)
        ) > session.limits.working_memory_bytes // 4:
            raise ToolError("resource_limit", "Search request exceeds working memory admission.")
        self.session = session
        self.scope = SearchScope(
            input_view.view_scope
            if input_view
            else ViewScope(session.dataset_id, session.dataset_id),
            options,
            request_generation,
        )
        self.status = OperationStatus(
            "pending",
            total_records=input_view.record_count if input_view else session.status.record_count,
        )
        self.diagnostics: tuple[Diagnostic, ...] = ()
        self.view: SearchResult | None = None
        self._input = input_view
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._done = threading.Event()
        if input_view:
            input_view._acquire()
        try:
            self._path = session.storage.create_file("search-" + uuid.uuid4().hex + ".members")
            self._thread = threading.Thread(
                target=self._run, name=f"slogger-{self._path.stem}", daemon=True
            )
            self._thread.start()
        except BaseException:
            if hasattr(self, "_path"):
                session.storage.remove_file(self._path)
            if input_view:
                input_view._release()
            raise

    def _run(self) -> None:
        self.status = replace(self.status, phase="running")
        try:
            with (
                self.session._data.open("rb") as data,
                self.session._index.open("rb") as index,
                self.session.storage.writer(self._path) as writer,
            ):
                members = self._input._path.open("rb") if self._input else None
                try:
                    output = bytearray()
                    for position in range(self.status.total_records):
                        if self._cancel.is_set():
                            break
                        ordinal = (
                            _MEMBER.unpack(members.read(_MEMBER.size))[0] if members else position
                        )
                        index.seek(ordinal * _INDEX.size)
                        start, length, _, _ = _INDEX.unpack(index.read(_INDEX.size))
                        data.seek(start)
                        record = json.loads(data.read(length))
                        if resident_size(record) * 3 > self.session.limits.working_memory_bytes:
                            raise ToolError(
                                "resource_limit", "Search record exceeds working memory admission."
                            )
                        if record_matches(record, self.scope.options):
                            output.extend(_MEMBER.pack(ordinal))
                        if (position + 1) % 128 == 0 or position + 1 == self.status.total_records:
                            writer.stage({self._path: bytes(output)})
                            writer.flush()
                            self.status = replace(
                                self.status,
                                processed_records=position + 1,
                                result_records=self.status.result_records
                                + len(output) // _MEMBER.size,
                            )
                            output.clear()
                finally:
                    if members:
                        members.close()
            with self._lock, self.session._lifecycle_lock:
                if not self._cancel.is_set():
                    self.session.require_ready("search publication")
                    self.view = SearchResult(
                        self.session, self._path, self.status.result_records, self.scope
                    )
                    self.status = replace(self.status, phase="complete")
        except Exception as error:
            if not self._cancel.is_set():
                code = error.code if isinstance(error, ToolError) else "execution_failed"
                self.diagnostics = (Diagnostic(code, str(error)),)
                self.status = replace(self.status, phase="failed")
        finally:
            if self._cancel.is_set() and self.status.phase != "complete":
                self.status = replace(self.status, phase="cancelled")
            try:
                if self.view is None:
                    self.session.storage.remove_file(self._path)
            except Exception as error:
                self.diagnostics = (*self.diagnostics, Diagnostic("cleanup_failed", str(error)))
                self.status = replace(self.status, phase="failed")
            try:
                if self._input:
                    self._input._release()
                    self._input = None
            except Exception as error:
                self.diagnostics = (*self.diagnostics, Diagnostic("cleanup_failed", str(error)))
                self.status = replace(self.status, phase="failed")
            if self.view is not None and self.status.phase != "complete":
                try:
                    self.view.close()
                except Exception as error:
                    self.diagnostics = (*self.diagnostics, Diagnostic("cleanup_failed", str(error)))
                self.view = None
            self._done.set()

    @property
    def done(self) -> bool:
        return self._done.is_set()

    def cancel(self) -> None:
        with self._lock:
            if self.status.phase != "complete":
                self._cancel.set()

    def wait(self, timeout: float | None = None) -> SearchResult | None:
        if not self._done.wait(timeout):
            raise TimeoutError("Search is still running.")
        return self.view
