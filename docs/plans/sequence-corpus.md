# Sequence-analysis corpus (exploratory)

Status: fixtures and expectations only. **No sequence tools are implemented.**
P2 (`explain`, completion, MCP, published aggregate schemas) remains deferred.

This document analyses the attached `robotic_arm_service` plain-text log
(`2026-09-23.log`, uploaded as `2026-09-23_4d57.log`) and describes the
fixture corpus under `tests/fixtures/logs/sequence/`. Application source for
the robot service is **not** in this workspace; all conclusions below are
**log-only** unless marked otherwise.

## 1. What the source log is

- Plain text, not JSONL. Pattern:
  `[robotic_arm_service] [DD/MM/YYYY HH:MM:SS.mmm] [LEVEL] : message`
- ~42k lines for one calendar day; heavy WARNING volume is mostly
  `Buffer overflow: Maximum records reached` (telemetry buffer), not workflow
  failures.
- No `[ERROR]` lines. Logical failures appear as INFO/WARNING with
  `err_msg` / `error_code` / `pick_status: False` while HTTP-ish
  `status: True` and `robot_activity_status: …::completed` still fire.
- Service version observed in responses: `build-6.0.10`.
- Cluster / entity: `CS001`, `R1`.

### Workflow vocabulary (APIs as workflow types)

Observed `API Endpoint` values (counts approximate for the day):

| API | Role in sequences |
|---|---|
| `/robotic-arm/pick/basket` | Pick slide from basket slot |
| `/robotic-arm/place/scanner` | Place slide on scanner |
| `/robotic-arm/pick/scanner` | Pick from scanner |
| `/robotic-arm/drop-slide` | Drop / unload |
| `/robotic-arm/move/scanner/imaging` | Move to imaging pose |
| `/robotic-arm/move/scanner/pick` | Move to scanner pick |
| `/robotic-arm/move/scanner/open-pose` (+ `/home`) | Open-pose moves |
| `/robotic-arm/move/pick-basket/home` | Return home after pick |
| `/robotic-arm/move/load` (+ `/home`) | Load-station moves |
| `/robotic-arm/scanner/*`, `/log/slide-detection-data`, `/update-scanner-pick-info` | Vision / placement helpers |
| `/robotic-arm/led/on\|off`, `/gripper`, `/is_alive`, `/robotic-arm` | Support / health / pose query |

Illustrative names from earlier design chats (`approach`, `grasp`, `lift`,
`SlipDetected`) do **not** appear. Observed step-like tokens include gripper
`operation type` values such as `OPEN_AT_PICK_BASKET`, `CLOSE_AT_PICK_BASKET`,
`PARTIAL_OPEN_AT_PICK_BASKET`, `OPEN_AT_SCANNER_PLACE`, `CLOSE_AT_HOME`, and
motion lines `motion started` / `motion completed successfully`.

### Episode boundaries (plausible)

Best-supported episode unit for pick: one `/robotic-arm/pick/basket` invocation
bounded by `robot_activity_status: …::in-progress` → `…::completed`, keyed by
payload fields `(load_identifier, slide_id, basket_number, zone_number,
row_number, column_number)`.

`load_identifier` alone is **too coarse**: the same load
`CS001-1-2-1790199851435` spans many slot attempts (columns 1…5) and later
scanner APIs.

A higher-level “scan this slide end-to-end” episode is only loosely visible as
a **caller-driven API sequence** (pick → imaging → adjust → place → …). The
service log does not emit a parent workflow id linking those APIs.

### Identifiers and scope

| Field | Scope (from log) |
|---|---|
| `load_identifier` | Batch/load; many API calls |
| `slide_id` | Intended slide for an attempt (may be `-1` on failure docs) |
| `basket_number`, `zone_number`, `row_number`, `column_number` | Slot |
| `scanner_number` | Scanner resource |
| `cluster_id` | Site/cluster |
| `service_version` | Build id in `error_details` |
| Trace/span ids | **Absent** |

### Failure modes observed in the day log

1. **`CLDJ_SLIDE_NOT_FOUND` / “Slide not found in the basket”** (source lines
   ~8499, ~8680, ~8861 and matching API responses ~8518, ~8699, ~8880).
   Sequence inside the attempt: open → close → `Slide Present : False` → open
   → WARNING → activity `completed` with `pick_status: False`. API `status`
   remains `True`.
2. **`ROBOT_NOT_IN_CORRECT_POSITION`** WARNING during
   `/robotic-arm/move/scanner/imaging` (e.g. line 1911) while activity still
   reaches `completed` (line 1957). Not treated as abort in this log.
3. No dedicated recovery API name appears after slide-not-found; the caller
   proceeds to the **next slot** (new pick/basket with next `column_number` /
   `slide_id`). That is adjacent attempts, not an in-log recovery workflow.

### Background / high-volume noise

- `cmd_str` (~13k), motion waypoint dumps, FT sensor resets, DB insert dumps,
  `Buffer overflow` warnings, `/is_alive` polls.
- These can still explain timeouts; they are classified as optional telemetry
  in the mapping below, not deleted from the original file (original is
  preserved outside the repo upload).

### Ambiguities

- Bracket timestamps match UTC `created_at` in DB dump lines; DB also stores
  `time_zone: MDT`. Corpus treats bracket time as UTC.
- `activity_phase=completed` ≠ business success (`pick_status`).
- No explicit link field from failed attempt → next attempt/recovery.
- No session/run id for the service process.
- Concurrent API overlap was not observed (`in-progress` nesting count 0), but
  many lines share equal millisecond timestamps.

## 2. Representation mapping

### Categories → sequence views

| Category | Example source text | Default sequence view | Diagnostic context | High-volume telemetry |
|---|---|---|---|---|
| API request | `API Endpoint: /robotic-arm/pick/basket` | yes (`api.request`) | | |
| Payload | `Request Payload: {…}` | yes (selected keys) | full payload | |
| Activity lifecycle | `robot_activity_status: api::phase::json` | yes | | |
| Gripper op | `operation type: CLOSE_AT_PICK_BASKET` | yes (`step.entry`) | | |
| Observation | `Slide Present : False` | yes | | |
| Motion start/complete | `motion started` / `completed successfully` | optional | yes (timeouts) | raw `cmd_str` |
| Business error | `err_msg: Slide not found…` | yes | | |
| API response | `API Response: {pick_status…}` | yes (outcome) | timings | |
| Position warning | `ROBOT_NOT_IN_CORRECT_POSITION` | yes (diagnostic step) | | |
| DB inserts / cmd_str / buffer | long dumps | | samples | default omit from sequence fixtures |
| `/is_alive` | health | | | background |

### Command vs observation (supported distinctions)

| Stage | Evidence in log | Represented as |
|---|---|---|
| Requested | `API Endpoint` + `Request Payload` | `api.request` / `api.payload` |
| Accepted / started | `activity …::in-progress` | `activity.lifecycle` phase |
| Sub-command started | `motion started`, `operation type` | `command.started` / `step.entry` |
| Sub-command completed | `motion completed successfully` | `command.completed` |
| Physical observation | `Slide Present : True/False` | `observation` |
| Attempt finished (transport) | `activity …::completed` | `activity.lifecycle` |
| Business outcome | `pick_status`, `slide_error_code`, `err_msg` | `api.response` / `workflow.error` |

Span `span.start` / `span.end` are **not** invented in the source-derived
fixture. Synthetic fixtures use real slogger spans as **proposed**
instrumentation.

### Compact original → structured examples

| Source (abbrev.) | Structured fields |
|---|---|
| L1552 `API Endpoint: /robotic-arm/pick/basket` | `kind=api.request`, `api=…`, `workflow=…` |
| L1562 `…pick/basket::in-progress::{load…}` | `kind=activity.lifecycle`, `activity_phase=in-progress`, inferred `episode_id` |
| L1651 `Slide Present : False` | `kind=observation`, `slide_present=false` |
| L1889 `…::completed::…` | `activity_phase=completed` |
| L1895 response `pick_status: True` | `kind=api.response`, `api_status=true`, `pick_status=true` |
| L1911 WARNING position | `kind=diagnostic.warning`, `error_code=ROBOT_NOT_IN_CORRECT_POSITION` |
| L8499 WARNING slide not found | `kind=workflow.error`, `error_code=CLDJ_SLIDE_NOT_FOUND` |
| L8518 response `pick_status: False` | `api_status=true`, `pick_status=false`, `slide_error_code=CLDJ_SLIDE_NOT_FOUND` |

Reserved slogger `status` is **not** used for application booleans; those are
stored as `api_status` / `pick_status` / `activity_phase`.

## 3. Smallest instrumentation additions

| Addition | Enables | Availability |
|---|---|---|
| `workflow` (= API path) on all records for an attempt | Filter / path by type | **Derivable** from endpoint / activity lines |
| `workflow_id` / episode id per attempt | Episode extract without heuristics | **Missing** — inferred in corpus only |
| `attempt` / `retry` counter | Distinguish repeated `CLOSE_AT_PICK_BASKET` | **Missing** (synthetic only) |
| `step_occurrence_id` | Stable identity when step names repeat | **Missing** |
| Parent `workflow` span + child step spans | `trace`/`tree`, durations | **Missing** in source; **synthetic** demos |
| `workflow_outcome` ∈ {ok, error, aborted, incomplete} separate from activity completed | Path success vs transport completion | **Partially derivable** (`pick_status`); not first-class |
| `recovery_of` / `triggered_recovery_id` | Link fail → recovery | **Missing** in source (no recovery API observed) |
| `service_version`, `cluster_id` on all lines | Compare equivalent builds | **Partial** (in responses) |
| Monotonic `seq` or ns timestamp | Order when ms timestamps tie | **Missing** (`fixture_seq` only in conversion) |

## 4. Corpus layout

```text
tests/fixtures/logs/sequence/
  build_corpus.py                 # converter + synthetic emitter
  expectations.json               # human-reviewed interpretations
  README.md
  source_derived/
    pick_basket_issue_cluster.jsonl
    provenance.json
  synthetic/
    success_pick_place.jsonl
    success_with_home_correction.jsonl
    failure_then_recovery.jsonl
    retry_exhaustion.jsonl
    incomplete_workflow.jsonl
    repeated_steps_equal_ts.jsonl
    interleaved_episodes.jsonl
    near_match_wrong_order.jsonl
    index.json
```

Regenerate:

```bash
python3 tests/fixtures/logs/sequence/build_corpus.py \
  --source /path/to/2026-09-23.log
# or synthetic only:
python3 tests/fixtures/logs/sequence/build_corpus.py --skip-source
```

## 5. What this corpus can / cannot test later

**Can test reliably (with expectations.json):**

- Episode grouping by inferred/synthetic `workflow_id` / `episode_id`
- Ordered subsequences for slide-not-found motif (open → close → slide_present false → error)
- Path diff between success-with-home-correction vs success-pick-place (two legitimate successes)
- Negative match: interleaved episodes must not fuse
- Near-match wrong order must not match open→close motif
- Recovered failure remains visible (`workflow_outcome=error` on first episode) even if recovery succeeds
- Incomplete workflow (no terminal `workflow.end`)
- Equal timestamps + repeated step names need `attempt` / `step_occurrence_id`
- Background `/is_alive` / buffer lines ignored for path alphabet

**Still lacks representative evidence:**

- True in-service recovery workflow after fault (not observed; synthetic only)
- Retry exhaustion inside one API call (source shows new API calls per slot)
- Grasp slip / force-fault codes beyond `CLDJ_SLIDE_NOT_FOUND` and position warning
- Concurrent overlapping workflows
- Application-emitted spans (source-derived has none)

## 6. Example P1 commands (implemented today)

```bash
python3 -m slogger validate tests/fixtures/logs/sequence/source_derived/pick_basket_issue_cluster.jsonl
python3 -m slogger meta tests/fixtures/logs/sequence/source_derived/pick_basket_issue_cluster.jsonl --format table
python3 -m slogger query tests/fixtures/logs/sequence/source_derived/pick_basket_issue_cluster.jsonl \
  --where 'error_code=CLDJ_SLIDE_NOT_FOUND' --format json
python3 -m slogger query tests/fixtures/logs/sequence/source_derived/pick_basket_issue_cluster.jsonl \
  --where 'episode_id=pick_basket:CS001-1-2-1790199851435:slide=259813:b2-z1-r1-c3'
python3 -m slogger tree tests/fixtures/logs/sequence/synthetic/failure_then_recovery.jsonl --format table
python3 -m slogger stats tests/fixtures/logs/sequence/synthetic/retry_exhaustion.jsonl --spans --format table
python3 -m slogger errors tests/fixtures/logs/sequence/synthetic/retry_exhaustion.jsonl --format table
```

There are no `episodes` / `paths` / `match` / `path-diff` / `watch-seq` commands.
