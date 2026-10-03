"""Query finite structured logs through immutable IXR query plans.

Import tooling names here, independently of the core logging package.
Python execution is the default; Polars execution is optional.
"""

from slogger.tools.core.builders import Field, all_of, any_of, logger_prefix, not_
from slogger.tools.core.ixr import (
    And,
    ArrayContains,
    Compare,
    Exists,
    Expression,
    FieldRef,
    In,
    Literal,
    Not,
    Or,
    StringMatch,
)
from slogger.tools.core.plan import (
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
from slogger.tools.errors import ToolError

__all__ = [
    "Expression",
    "FieldRef",
    "Literal",
    "Compare",
    "In",
    "Exists",
    "StringMatch",
    "ArrayContains",
    "And",
    "Or",
    "Not",
    "AggregateSpec",
    "Field",
    "GroupedPlan",
    "PlanResult",
    "QueryPlan",
    "ToolError",
    "SourceOrigin",
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

from .core.runtime import SourceOrigin
