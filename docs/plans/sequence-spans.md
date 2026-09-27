# Proposed span instrumentation (robotic_arm_service)

Status: design + enriched fixtures only. **Source-derived fixtures remain
span-free.** Enriched variants under `tests/fixtures/logs/sequence/enriched/`
add *proposed* spans for richer tooling tests. Initial sequence tools must keep
working on the originals.

Grounded in committed fixtures (`full_slide_cycle_a`, `force_exit_retry_abort`,
`pick_basket_issue_cluster`). Application source is not in this repo.

## 1. Why spans help here

Without spans, the log only has timestamps + `activity_phase`. That is enough
for ordered motifs, but weak for:

- Wall duration of an API call vs a multi-API episode
- Nesting gripper/motion work inside an API invocation
- Distinguishing transport completion from business outcome
- Correlating sibling API calls that share an episode without inventing
  parentage from time alone

## 2. Ideal hierarchy (proposed)

```text
episode                         # multi-API slot story; shared episode_id
 └── api.<path>                 # one HTTP/activity invocation
      ├── (events)              # observations, decisions, force trips
      ├── gripper.<op>          # only if app emits clear start/end
      ├── motion.<phase>        # only if app emits start/end pair
      └── retry_loop            # in-call retry region (when present)
```

**Events (not spans):** `observation.slide_present`, `pick.home_mismatch`,
`force.stop_playing`, `force.handle_*`, `workflow.error_detail`,
`pick.slide_not_found`, position warnings, API payload/method lines.

**Do not** treat temporal adjacency of API B after API A as proof that B is a
child of A. Sibling APIs under the same episode are **peers**; the episode
span is the only parent that correlates them.

## 3. Span catalog

### 3.1 `episode`

| | |
|---|---|
| **Owner** | External caller / load orchestrator (not `robotic_arm_service` alone) |
| **Start evidence** | First record of the slot episode (usually `api.endpoint` pick/basket) |
| **End evidence** | Last record of that episode in the analyzed window (e.g. `drop-slide` `activity.completed`, or failed pick `api.response`) |
| **Start/end class** | **Inferred** in enriched fixtures — service never emits an episode span |
| **Parent** | none (root). Children: `api.*` invocations with the same `episode_id` |
| **Correlation** | `episode_id` = `{load}:r{row}-c{col}`; enriched fixtures also assign one `trace_id` per episode |
| **Duration measures** | Wall time across the multi-API slot story (derived from record timestamps) |
| **Business outcome** | Aggregate of child API outcomes (e.g. full cycle ok if drop `place_status` true and picks succeeded). **Not** equal to any single `activity.completed` |

**Fixture refs (full cycle A):** start ~L5542, end ~L6938, episode
`CS001-1-1-1790200023515:r1-c2`.

**Limitation:** The caller that owns this lifecycle is outside the service log.
App instrumentation should start/end the episode span in the orchestrator and
propagate `trace_id` / `episode_id` into each service call.

### 3.2 `api.<path>` (individual API invocation)

| | |
|---|---|
| **Owner** | `robotic_arm_service` request handler for that endpoint |
| **Start evidence** | `activity.in-progress` for that API (**observed**) |
| **End evidence** | matching `activity.completed` (**observed**) |
| **Alternate start** | `API Endpoint` line is earlier but is request accept, not handler body; enriched uses `in-progress` as span start |
| **Parent** | proposed `episode` (correlation by `episode_id` / `trace_id`, not by time nesting alone) |
| **Children** | proposed gripper/motion/retry spans *when* those have observed bounds |
| **Duration measures** | Handler wall time from in-progress → completed (derived in enriched fixtures from timestamps; also compare to `total_time_s` in responses when present) |
| **Business outcome** | From `api.response` (`pick_status` / `place_status` / `slide_error_code`) or abort events — **separate** from span `status` |

**Examples**

| API | Start | End | Business outcome field |
|---|---|---|---|
| pick/basket (cycle A) | L5552 in-progress | L5669 completed | L5675 `pick_status=true` |
| place/scanner (cycle A) | L5833 | L5895 | place success via later drop / activity only in fixture |
| pick/scanner (cycle A) | L6294 | L6419 | (no pick_status on this API in fixture) |
| drop-slide (cycle A) | L6494 | L6938 | L6935 `place_status=true` |
| pick/basket (force abort) | L28001 | L28377 | L28383 `pick_status=false` + L28371 abort |
| pick/basket (empty slot) | L8366 | L8512 | L8518 `pick_status=false`, `CLDJ_SLIDE_NOT_FOUND` |
| imaging (warning) | L1906 | L1957 | completed despite L1911 warning → outcome `ok_with_warning` |

### 3.3 Gripper operations — prefer events unless app adds bounds

Source lines `operation type: OPEN_AT_PICK_BASKET` etc. mark **entry** only.
The curated fixtures omit gripper DB completion dumps, so a reliable **end is
unavailable**.

| | |
|---|---|
| **Owner** | Gripper subsystem inside the API handler |
| **Start** | `gripper.operation` (**observed**) |
| **End** | **Unavailable** in source-derived fixtures |
| **Enriched treatment** | **Left as events** (no invented `span.end`) |
| **App recommendation** | Wrap each gripper command in `with log.span(operation_type):` so start/end and `duration_ms` are application-measured |

Same for `PARTIAL_OPEN_*`, `CLOSE_AT_HOME`, `EXTREME_OPEN_*`, etc.

### 3.4 Motion operations

Raw service logs often have `motion started` / `motion completed successfully`
pairs. Many are omitted from curated fixtures (noise).

| | |
|---|---|
| **Owner** | Motion controller helper inside the API handler |
| **Start/end** | Those motion lines when present (**observed**); else **unavailable** |
| **Enriched treatment** | Not synthesized when the pair is absent from the fixture |
| **App recommendation** | Emit motion spans (or keep the existing start/complete lines and also open a span) |

**Force-exit case:** `motion.failed` at L28369 is an end-like failure event;
the matching `motion started` for that exit move is **not** in the curated
fixture → do **not** invent an `exit_motion` span start.

### 3.5 `retry_loop` (in-call, force-exit path)

| | |
|---|---|
| **Owner** | Pick/basket handler retry logic |
| **Start evidence** | Weak: first grasp attempt (`OPEN_AT_PICK_BASKET` L28031) or activity in-progress |
| **End evidence** | L28371 `pick.retry_loop_abort` (**observed**) or successful exit from loop (**unavailable** as explicit success marker) |
| **Boundary class** | Start **inferred**; end **observed** on abort |
| **Parent** | `api./robotic-arm/pick/basket` |
| **Duration** | Time inside the handler's retry region (derived) |
| **Business outcome** | `aborted` when L28371 fires; span `status=error` on abort |

**Enriched treatment:** emit `retry_loop` only for the force-exit episode, with
`span_boundary_start=inferred`, `span_boundary_end=observed`, and
`workflow_outcome=aborted` on the end event.

### 3.6 Force-stop handling — events, not a fake recovery workflow

`Stop playing` / `handle_*_stop` / `recovered` / `executing force stop handler`
are instantaneous or loosely bounded. No clear owner span end before the
post-force `OPEN`. Keep as **events** under the API (and retry_loop) span.
App may later add a short `force_stop_handler` span around
`executing force stop handler` → handler return.

## 4. Slogger span API limitations (do not stretch the schema)

| Need | Slogger today | Recommendation |
|---|---|---|
| Business outcome ≠ execution status | `status` only `ok`\|`error` on `span.end` | Keep `status` = execution/transport; put `workflow_outcome` / `pick_status` / `slide_error_code` in span attributes (extra keys; schema allows) |
| Aborted vs error | No `aborted` status | Use `status=error` plus `workflow_outcome=aborted` / `retry_outcome` |
| Incomplete operation | Span API always ends on context exit | Do not emit `span.end` in fixtures when end evidence is missing; app should avoid opening a span without a clear end site |
| Episode owned by caller | Service cannot truthfully open it alone | Orchestrator opens episode span and propagates `trace_id` |
| Parent/child across processes | `parent_span_id` is in-process ContextVar | Cross-API correlation via `trace_id` + `episode_id`; do not fake nesting from timestamps |

**Record schema is unchanged.** Enriched fixtures only add allowed extra keys
(`span_enrichment`, `span_boundary_*`, `duration_ms_provenance`,
`source_line_start` / `source_line_end`, `workflow_outcome`, …).

## 5. Enriched fixture variant

Generator: `tests/fixtures/logs/sequence/build_corpus.py` →
`build_enriched_spans()` (also run with `--skip-source`).

| Input (span-free) | Output (proposed spans) |
|---|---|
| `source_derived/full_slide_cycle_a.jsonl` | `enriched/full_slide_cycle_a.spans.jsonl` |
| `source_derived/force_exit_retry_abort.jsonl` | `enriched/force_exit_retry_abort.spans.jsonl` |
| `source_derived/pick_basket_issue_cluster.jsonl` | `enriched/pick_basket_issue_cluster.spans.jsonl` |

Each enriched file:

1. Copies every original record (same `source_line`, still the authority)
2. Inserts proposed `span.start` / `span.end` rows with:
   - `span_enrichment=proposed`
   - `span_boundary_start` / `span_boundary_end` ∈ {`observed`,`inferred`}
   - `duration_ms` + `duration_ms_provenance=derived_from_timestamps`
   - `source_line_start` / `source_line_end`
   - deterministic `span_id` / `trace_id` / `parent_span_id`

Durations are **derived**, not application-measured. Do not treat them as
proof of production timing.

## 6. Tooling expectations

- Sequence tools (when built) must accept **original** span-free JSONL.
- Enriched files are for testing span-aware views (`tree`, `stats --spans`,
  future path tools) and for documenting the target instrumentation shape.
- How the planned tools consume all three variants without double counting is
  specified in [`sequence-tools-handoff.md`](sequence-tools-handoff.md) §D3.
