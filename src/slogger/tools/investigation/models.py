"""Headless captured-dataset contracts; application fields stay separate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ..core.runtime import SourceOrigin


@dataclass(frozen=True)
class SourceBoundary:
    source: str
    input_occurrence: int
    byte_length: int
    device: int
    inode: int


@dataclass(frozen=True)
class RecordIdentity:
    dataset_id: str
    ordinal: int
    input_occurrence: int


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    origin: SourceOrigin | None = None
    input_occurrence: int | None = None


@dataclass(frozen=True)
class CaptureStatus:
    phase: Literal["capturing", "complete", "failed", "closed"]
    record_count: int = 0
    captured_bytes: int = 0
    total_bytes: int = 0
    skipped_lines: int = 0

    @property
    def complete(self) -> bool:
        return self.phase == "complete"


@dataclass(frozen=True)
class RecordPage:
    dataset_id: str
    offset: int
    records: list[dict[str, Any]]
    origins: list[SourceOrigin]
    identities: list[RecordIdentity]
    next_offset: int
    complete: bool
