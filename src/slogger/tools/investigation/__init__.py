"""Headless stable investigation capture, storage, and paging."""

from slogger.tools.investigation.search import (
    SearchJob,
    SearchOptions,
    SearchProjection,
    SearchResult,
    SearchScope,
)

from .models import CaptureStatus, Diagnostic, RecordIdentity, RecordPage, SourceBoundary
from .resources import ManagedStorage, ResourceLimits, ResourceUsage
from .session import Investigation
from .tree import TraceTree, TreeJob, TreePage, TreeRow, TreeScope, TreeStatus

__all__ = [
    "SearchJob",
    "SearchOptions",
    "SearchProjection",
    "SearchResult",
    "SearchScope",
    "FilterJob",
    "FilterScope",
    "OperationStatus",
    "RecordView",
    "ViewScope",
    "CaptureStatus",
    "Diagnostic",
    "Investigation",
    "ManagedStorage",
    "RecordIdentity",
    "RecordPage",
    "ResourceLimits",
    "ResourceUsage",
    "SourceBoundary",
    "TraceTree",
    "TreeJob",
    "TreePage",
    "TreeRow",
    "TreeScope",
    "TreeStatus",
]

from .filters import FilterJob, FilterScope, OperationStatus, RecordView, ViewScope
