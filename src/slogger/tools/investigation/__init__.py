"""Headless stable investigation capture, storage, and paging."""

from .cache import CacheClearResult, CacheStore, default_cache_dir
from .models import CaptureStatus, Diagnostic, RecordIdentity, RecordPage, SourceBoundary
from .resources import ManagedStorage, ResourceConfiguration, ResourceLimits, ResourceUsage
from .search import SearchJob, SearchOptions, SearchProjection, SearchResult, SearchScope
from .session import Investigation
from .tree import TraceTree, TreeJob, TreePage, TreeRow, TreeScope, TreeStatus

__all__ = [
    "DiscoveryChoice",
    "DiscoveryCompletionPage",
    "DiscoveryIndex",
    "DiscoveryJob",
    "DiscoveryPage",
    "DiscoveryScope",
    "DiscoveryStatus",

    "SearchJob",
    "SearchOptions",
    "SearchProjection",
    "SearchResult",
    "SearchScope",
    "AggregateJob",
    "AggregatePage",
    "AggregateResult",
    "AggregateScope",
    "FilterJob",
    "FilterScope",
    "OperationStatus",
    "RecordView",
    "ViewScope",
    "CaptureStatus",
    "CacheClearResult",
    "CacheStore",
    "default_cache_dir",
    "Diagnostic",
    "Investigation",
    "ManagedStorage",
    "RecordIdentity",
    "RecordPage",
    "ResourceConfiguration",
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

from .aggregates import AggregateJob, AggregatePage, AggregateResult, AggregateScope
from .discovery import (
    DiscoveryChoice,
    DiscoveryCompletionPage,
    DiscoveryIndex,
    DiscoveryJob,
    DiscoveryPage,
    DiscoveryScope,
    DiscoveryStatus,
)
from .filters import FilterJob, FilterScope, OperationStatus, RecordView, ViewScope
