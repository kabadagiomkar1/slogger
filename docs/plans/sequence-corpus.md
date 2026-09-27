# Sequence-analysis corpus (exploratory)

Status: fixtures and expectations only. **No sequence tools are implemented.**
P2 (`explain`, completion, MCP, published aggregate schemas) remains deferred.

This document analyses attached `robotic_arm_service` plain-text logs
(`2026-09-23.log`, uploaded as `2026-09-23_4d57.log`; `2026-09-24-truncated.log`,
uploaded as `2026-09-24-truncated_5011.log`) and describes the fixture corpus
under `tests/fixtures/logs/sequence/`. Application source for the robot
service is **not** in this workspace; all conclusions below are **log-only**
unless marked otherwise.

## 1. What the source log is

- Plain text, not JSONL. Pattern:
  `[robotic_arm_service] [DD/MM/YYYY HH:MM:SS.mmm] [LEVEL] : message`
- ~42k lines for one calendar day; heavy WARNING volume is mostly
  `Buffer overflow: Maximum records reached` (telemetry buffer), not workflow
  failures.
- Sep 23: no `[ERROR]` lines; logical failures appear as INFO/WARNING with
  `err_msg` / `error_code` / `pick_status: False` while HTTP-ish
  `status: True` and `robot_activity_status: …::completed` still fire.
- Sep 24 truncated log: `[ERROR]` appears for force-stop (`Stop playing`) and
  in-call retry abort (`breaking out of retry loop`), still with activity
  `completed` and API `status: True` / `pick_status: False`.
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

### Episode boundaries

Domain rule: an episode is uniquely identified by
`(load_identifier, row_number, column_number)`. Corpus `episode_id` format:
`{load_identifier}:r{row}-c{column}`.

Transport bound for a pick attempt is still one `/robotic-arm/pick/basket`
invocation (`robot_activity_status: …::in-progress` → `…::completed`).
`load_identifier` alone is too coarse (many slots). `slide_id`, basket, and
zone remain useful diagnostics but are not required for episode identity.

A complete slide workflow is a **caller-driven multi-API sequence** under one
episode id:

`pick/basket` → (imaging / adjust / moves) → `place/scanner` →
(open-pose / home / scanner-pick moves) → `pick/scanner` → `drop-slide`

The service does not emit a parent workflow id; the corpus binds the chain with
shared `episode_id`. Fixtures `full_slide_cycle_a.jsonl` (Sep 23, r1-c2) and
`full_slide_cycle_b.jsonl` (Sep 24, r1-c20) are two successful instances.
Roughly 10 such completed cycles appear in Sep 23 and 19 in the Sep 24
truncated log.

### Identifiers and scope

| Field | Scope (from log) |
|---|---|
| `load_identifier` + `row_number` + `column_number` | **Episode identity** (domain rule) |
| `load_identifier` alone | Batch/load; many slot episodes |
| `slide_id` | Intended slide for an attempt (may be `-1` on failure docs); diagnostic |
| `basket_number`, `zone_number` | Slot metadata; diagnostic |
| `scanner_number` | Scanner resource |
| `cluster_id` | Site/cluster |
| `service_version` | Build id in `error_details` |
| Trace/span ids | **Absent** |

### Failure modes observed

1. **`CLDJ_SLIDE_NOT_FOUND` / “Slide not found in the basket”** (Sep 23;
   source lines ~8499, ~8680, ~8861 and matching API responses ~8518, ~8699,
   ~8880). Sequence inside the attempt: open → close → `Slide Present : False`
   → open → WARNING → activity `completed` with `pick_status: False`. API
   `status` remains `True`.
2. **`ROBOT_NOT_IN_CORRECT_POSITION`** WARNING during
   `/robotic-arm/move/scanner/imaging` (Sep 23, e.g. line 1911) while activity
   still reaches `completed` (line 1957). Not treated as abort in this log.
3. **Force-stop `E-200` + `RA_CANNOT_PICK_FROM_BASKET_MULTIPLE_ATTEMPTS`**
   (Sep 24, pick r2c9 slide 259969, lines ~27991–28383). After a successful
   close (`Slide Present : True`), exit motion trips force stop:
   `Stop playing` → `handle_generic_stop` / `handle_safety_stop` /
   `handle_force_stop` (`E-200`) → `recovered from force stop` →
   `executing force stop handler` → `OPEN_AT_PICK_BASKET` → later
   `motion failed` with `RA_CANNOT_PICK_FROM_BASKET_MULTIPLE_ATTEMPTS` →
   ERROR `breaking out of retry loop` → activity `completed` with
   `pick_status: False`. This is an **in-call retry loop abort**, not a new
   API call.
4. No dedicated recovery API name appears after either failure class; the
   caller proceeds to the **next slot** (new pick/basket with next
   `column_number` / `slide_id`). Sep 24 next slot r2c10 succeeds immediately
   after the abort — adjacent attempts, not an in-log `recovery_of` link.

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
| Sep24 L28118 `Stop playing. Force is…` | `kind=force.event`, `error_code=E-200` |
| Sep24 L28128 `debug.handle_force_stop` | `kind=force.handler`, `force_handler=handle_force_stop` |
| Sep24 L28369 `motion failed` + RA_CANNOT… | `kind=command.failed` |
| Sep24 L28371 `breaking out of retry loop` | `kind=workflow.abort` |
| Sep24 L28383 response `pick_status: False` | `slide_error_code=RA_CANNOT_PICK_FROM_BASKET_MULTIPLE_ATTEMPTS` |

Reserved slogger `status` is **not** used for application booleans; those are
stored as `api_status` / `pick_status` / `activity_phase`.

## 3. Smallest instrumentation additions

| Addition | Enables | Availability |
|---|---|---|
| `workflow` (= API path) on all records for an attempt | Filter / path by type | **Derivable** from endpoint / activity lines |
| `workflow_id` / episode id per attempt | Episode extract without heuristics | **Missing** in source — corpus derives `{load}:r{row}-c{col}` from domain rule |
| `attempt` / `retry` counter | Distinguish repeated `CLOSE` / post-force `OPEN` | **Missing** (synthetic only; Sep24 has unlabeled post-force OPEN) |
| `step_occurrence_id` | Stable identity when step names repeat | **Missing** |
| Parent `workflow` span + child step spans | `trace`/`tree`, durations | **Missing** in source; **synthetic** demos |
| `workflow_outcome` ∈ {ok, error, aborted, incomplete} separate from activity completed | Path success vs transport completion | **Partially derivable** (`pick_status`, retry-loop ERROR); not first-class |
| `recovery_of` / `triggered_recovery_id` | Link fail → recovery | **Missing** in source (next-slot only; no recovery API) |
| `service_version`, `cluster_id` on all lines | Compare equivalent builds | **Partial** (in responses) |
| Monotonic `seq` or ns timestamp | Order when ms timestamps tie | **Missing** (`fixture_seq` only in conversion) |

## 4. Corpus layout

```text
tests/fixtures/logs/sequence/
  build_corpus.py                 # converter + synthetic emitter
  expectations.json               # human-reviewed interpretations
  README.md
  source_derived/
    pick_basket_issue_cluster.jsonl   # Sep 23 empty-slot cluster
    provenance.json
    force_exit_retry_abort.jsonl      # Sep 24 force-stop / retry abort
    provenance_force_exit.json
    full_slide_cycle_a.jsonl          # Sep 23 complete pick→place→pick→drop
    provenance_full_slide_cycle_a.json
    full_slide_cycle_b.jsonl          # Sep 24 complete cycle (2nd case)
    provenance_full_slide_cycle_b.json
  synthetic/
    success_pick_place.jsonl
    success_with_home_correction.jsonl
    failure_then_recovery.jsonl
    retry_exhaustion.jsonl
    force_exit_retry_abort.jsonl
    full_slide_cycle.jsonl
    incomplete_workflow.jsonl
    repeated_steps_equal_ts.jsonl
    interleaved_episodes.jsonl
    near_match_wrong_order.jsonl
    index.json
```

Regenerate:

```bash
python3 tests/fixtures/logs/sequence/build_corpus.py \
  --source /path/to/2026-09-23.log \
  --source-sep24 /path/to/2026-09-24-truncated.log
# or synthetic only:
python3 tests/fixtures/logs/sequence/build_corpus.py --skip-source
```

## 5. What this corpus can / cannot test later

**Can test reliably (with expectations.json):**

- Episode grouping by inferred/synthetic `workflow_id` / `episode_id`
- Ordered subsequences for slide-not-found motif (open → close → slide_present false → error)
- Full slide cycle path: pick/basket → place/scanner → pick/scanner → drop-slide
  under one `episode_id` (two source cases + synthetic)
- Path diff between success-with-home-correction vs success-pick-place (two legitimate successes)
- Negative match: interleaved episodes must not fuse
- Near-match wrong order must not match open→close motif
- Recovered failure remains visible (`workflow_outcome=error` on first episode) even if recovery succeeds
- Incomplete workflow (no terminal `workflow.end`)
- Equal timestamps + repeated step names need `attempt` / `step_occurrence_id`
- Background `/is_alive` / buffer lines ignored for path alphabet

**Still lacks representative evidence:**

- True in-service recovery workflow after fault (not observed; synthetic only)
- Empty-slot retry exhaustion inside one API call (Sep 23 uses new API calls
  per slot; Sep 24 aborts on force/`RA_CANNOT` instead)
- Concurrent overlapping workflows
- Application-emitted spans (source-derived has none)
- Explicit `attempt` on post-force OPEN

**Filled by Sep 24 source fixture:**

- Force-fault `E-200` + handler chain + in-call retry-loop abort
- `RA_CANNOT_PICK_FROM_BASKET_MULTIPLE_ATTEMPTS` on motion failure and response

## 6. Example P1 commands (implemented today)

```bash
python3 -m slogger validate tests/fixtures/logs/sequence/source_derived/pick_basket_issue_cluster.jsonl
python3 -m slogger validate tests/fixtures/logs/sequence/source_derived/force_exit_retry_abort.jsonl
python3 -m slogger meta tests/fixtures/logs/sequence/source_derived/pick_basket_issue_cluster.jsonl --format table
python3 -m slogger query tests/fixtures/logs/sequence/source_derived/pick_basket_issue_cluster.jsonl \
  --where 'error_code=CLDJ_SLIDE_NOT_FOUND' --format json
python3 -m slogger query tests/fixtures/logs/sequence/source_derived/force_exit_retry_abort.jsonl \
  --where 'error_code=RA_CANNOT_PICK_FROM_BASKET_MULTIPLE_ATTEMPTS' --format json
python3 -m slogger query tests/fixtures/logs/sequence/source_derived/full_slide_cycle_a.jsonl \
  --where 'episode_id=CS001-1-1-1790200023515:r1-c2'
python3 -m slogger query tests/fixtures/logs/sequence/source_derived/pick_basket_issue_cluster.jsonl \
  --where 'episode_id=CS001-1-2-1790199851435:r1-c3'
python3 -m slogger tree tests/fixtures/logs/sequence/synthetic/failure_then_recovery.jsonl --format table
python3 -m slogger stats tests/fixtures/logs/sequence/synthetic/force_exit_retry_abort.jsonl --spans --format table
python3 -m slogger errors tests/fixtures/logs/sequence/synthetic/force_exit_retry_abort.jsonl --format table
```

There are no `episodes` / `paths` / `match` / `path-diff` / `watch-seq` commands.
