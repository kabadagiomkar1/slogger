"""Query finite structured logs through immutable IXR query plans.

Import tooling names here, independently of the core logging package.
Python execution is the default; Polars execution is optional.
"""

from slogger.tools.errors import ToolError
from slogger.tools.plan import (
    AggregateSpec,
    GroupedPlan,
    PlanResult,
    QueryPlan,
    count_rows,
    max_of,
    mean_of,
    min_of,
    scan,
    sum_of,
)
from slogger.tools.predicates import Field, Predicate, all_of, any_of, logger_prefix, not_

__all__ = [
    "AggregateSpec",
    "Field",
    "GroupedPlan",
    "PlanResult",
    "Predicate",
    "QueryPlan",
    "ToolError",
    "all_of",
    "any_of",
    "count_rows",
    "logger_prefix",
    "max_of",
    "mean_of",
    "min_of",
    "not_",
    "scan",
    "sum_of",
]
