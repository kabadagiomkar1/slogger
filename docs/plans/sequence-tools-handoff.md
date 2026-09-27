# Sequence tools handoff: `episodes`, `episode`, `paths`, `match`, motifs, `path-diff`, `watch-seq`

Status: **planned, not implemented.** Nothing in this document exists in `src/` yet. P2
(`explain`, completion, MCP, published aggregate schemas) stays deferred.

Purpose: understand the sequence of records leading to an issue in a robot-control service and
automate recognition of recurring patterns, while keeping `slogger` domain-neutral. Every
robot-specific fact (API paths, `episode_id`, `pick_status`, …) lives in a **profile file**, never
in library code.

Written against the repository state at `origin/main` `69e4cbf` and the committed corpus under
`tests/fixtures/logs/sequence/`. Where this file and earlier sketches (`sequence-corpus.md` §6,
chat notes) differ, this file wins for sequence work. P0/P1 contracts
([`cli-p0-handoff.md`](cli-p0-handoff.md), [`cli-p1-handoff.md`](cli-p1-handoff.md)) are
preserved unchanged.

## Baseline (run 2026-09-27 on `origin/main` 69e4cbf)

| Check | Command | Result |
|---|---|---|
| Interpreter | `python3 --version` | Python 3.12.3; `python3.10`, `python3.11`, `python3.13` **absent** — the 3.10/3.13 matrix in `AGENTS.md` cannot run here |
| Tests | `python3 -m pytest -q` | 226 passed |
| Lint | `python3 -m ruff check src tests examples` | All checks passed |
| Types | `python3 -m pyrefly check` | **6 errors**, all in `tests/fixtures/logs/sequence/build_corpus.py` (lines 981, 1054, 1190, 1205, 1210, 1237: `configure(level="DEBUG")` typed as `int`; `list[LogRecord]` vs `list[dict]`). `src/` is clean. Fix belongs to the corpus generator, not to sequence tools; tasks below must not add new errors. |
| CLI | `python3 -m slogger --help` | 12 commands: `query meta fields trace tail tree stats errors validate context diff watch` |

Original plain-text service logs (`2026-09-23.log`, `2026-09-24-truncated.log`) are **not in the
repository**. Every source-line reference below is taken from committed JSONL (`source_line`) and
the provenance manifests; it cannot be re-verified against the raw text here.

## Facts checked in the code and fixtures

### Existing tools that sequence work reuses

| Symbol | File | Verified behaviour relevant here |
|---|---|---|
| `Reader(sources, after=, complete=, order=)` | `tools/reader.py` | Streams files / `-` / in-memory lists; `_id="<source>:<line>"`; `order="time"` is a heap merge with `out_of_order:<label>:<n>` / `untimestamped:<label>:<n>` warnings; `cursor()`; `resolve_sources` materialises one-shot iterables. |
| `parse_timestamp` | `tools/reader.py` | Aware UTC `datetime` or `None`. |
| `Filters`, `Where`, `parse_where` | `tools/filters.py` | Compact `KEYOPVALUE`; missing key never matches; `since/until` exclude unparseable timestamps. |
| `group_value` | `tools/grouping.py` | Type-tagged normalisation of a scalar/array/object key. |
| `SpanCollector`, `build_trace`, `SpanNode` | `tools/spans.py`, `tools/trace.py` | Per-group span reconstruction; unfinished → `status="unknown"`, `missing_start`, `duplicate_*`, `missing_parent`. |
| `query`, `Page`, `tail_once`, `follow` | `tools/query.py`, `tools/tail.py` | `Page(records, next_cursor, skipped_lines, warnings, context_meta)`; `tail_once` = `query(complete=False)` + always-a-cursor; `follow` reopen on inode change / shrink. |
| `watch`, `WatchResult` | `tools/watch.py` | Injectable `clock` / `sleep` / `stop`; stdin via daemon thread; timeout → exit 3. |
| `parse_duration_ms` | `tools/timeparse.py` | `500ms`, `1.5s`, `2m`, bare seconds. |
| `render_table`, `render_json_line`, `render_console_line` | `tools/render.py` | Table with `(no rows)`; JSONL line. |
| `ToolError(code, message, **extra)` | `tools/errors.py` | Exit 2 with JSON on stderr in JSON mode. |
| `cli.py` helpers | `cli.py` | `_Parser.error` → 64; `add_filter_args`, `add_output_args`, `add_order_arg`, `filters_from_args`, `resolve_format`, `write_page`, `emit_error`, `usage_error`. |

### Corpus facts (inspected records, not documentation)

| Fact | Evidence |
|---|---|
| Source-derived records carry **no** `span.start`/`span.end`, no `workflow_id`, no `attempt`. | `event` absent on all 240 source-derived records; keys profiled per file. |
| `episode_id` is present on **every** source-derived record; provenance is `domain_rule` (payload/activity lines), `carried_forward` (later records of the same slot), or `carried_backward` (request lines preceding the payload). | `episode_id_provenance` counts: cluster 12/39/8, force-exit 6/19/4, cycle A 30/44/2. |
| One episode spans many API invocations. | `full_slide_cycle_a`: 76 records, one `episode_id`, 12 `activity.in-progress` / 12 `activity.completed` pairs across 9 distinct `api` values (`open-pose` appears three times). |
| Business outcome fields are on `api.response` records: `pick_status`, `place_status`, `slide_error_code`, `error_code`; `api_status` is `true` on every response including failures. | cluster L8518/L8699/L8880: `api_status=true`, `pick_status=false`, `slide_error_code=CLDJ_SLIDE_NOT_FOUND`; force-exit L28383 `pick_status=false`. |
| `activity.completed` precedes `api.response` by a few ms for pick/basket, but for `move/scanner/pick` the response (L6283, `pick_status=true`) **precedes** `activity.completed` (L6286). | cycle A timestamps 22:00:55.731 vs .732. |
| Logical failures are `WARNING` (`pick.slide_not_found`) and `ERROR` (`pick.retry_loop_abort`, `force.stop_playing`); `force.handle_*` are `WARNING`. | levels per fixture: cluster 55 INFO / 4 WARNING; force-exit 22 INFO / 5 WARNING / 2 ERROR. |
| Timestamps are non-decreasing in every source-derived file; equal millisecond ties are common (cluster 7, force-exit 6, cycle A 20 tie pairs). | monotonic check on `timestamp`. |
| `fixture_seq` and `source_line` exist only on source-derived (and copied-into-enriched) records; synthetic records have neither. | key profile. |
| Enriched files insert proposed span rows with `span_enrichment="proposed"`, `span_boundary_start/end ∈ {observed, inferred}`, `duration_ms_provenance="derived_from_timestamps"`, `source_line_start/end`, `owner`, `span_role`, `workflow_outcome`; `file="span_enrichment"`, `func="proposed"`. A `span.start` shares its timestamp with the application record it was derived from and sorts **before** it. | enriched force-exit: 10 span rows; `episode` (inferred/inferred), `api./robotic-arm/pick/basket` (observed/observed), `retry_loop` (inferred/observed) with `status="error"`, `workflow_outcome="aborted"`. |
| Enriched `api.*` spans use `status="ok"` for a business failure that completed (CLDJ episodes) and `status="error"` only for the aborted episode; `workflow_outcome` carries `error`/`aborted`/`ok`/`ok_with_warning`. | enriched cluster / force-exit `span.end` rows. |
| Synthetic fixtures use real slogger spans: `workflow` root span + step spans, `workflow.start`/`workflow.end` records with `workflow_outcome` (`running`, `ok`, `error`, `aborted`), `workflow_id` on every record, `attempt` on retried steps, `step.failed` records at `ERROR` with `error_code`. | `retry_exhaustion`: attempts 1..3, `abort` span `status=error`, `workflow.end` `aborted` at `INFO`. |
| Synthetic recovery link fields: `triggered_recovery_id` on the failed episode's `workflow.end`; `recovery_of` (+`recovery_of_provenance="synthetic"`) on **every** record of the recovery episode. | `failure_then_recovery.jsonl`. |
| Synthetic `interleaved_episodes.jsonl` is **not** temporally interleaved: ep1 ends 22:08:20.121, ep2 starts 22:08:20.200. Background records (`logger="robotic_arm_service.bg"`, `kind="background"`) **inherit** `workflow_id`, `span_id`, `trace_id` from the active span. | record dump. Consequence: background exclusion must be by profile rule (`logger`/`kind`), never by "missing workflow_id". |
| `repeated_steps_equal_ts.jsonl` has no spans; three `CLOSE_AT_PICK_BASKET` entries with `attempt` 1..3 and `step_occurrence_id` `close-1..3`; observation and step share a timestamp per attempt. | record dump. |
| `incomplete_workflow.jsonl` has `workflow.start`, one completed `OPEN_AT_PICK_BASKET` span, and **no** `workflow.end`. | 4 records. |
| `full_slide_cycle.jsonl` (synthetic) has five `workflow_id`s (one per API) sharing one `episode_id`. | 5 `workflow.start`/`workflow.end` pairs. |

### Discrepancies and ambiguities found (reported, not rewritten)

| # | Where | Observed | Handling in this plan |
|---|---|---|---|
| 1 | `sequence-corpus.md` §3 "workflow_id / episode id **per attempt**" vs §1 "episode = multi-API slot story" | Two meanings of "episode". | **Resolved**: episode = multi-API slot story keyed by the profile episode key; one API call is an *invocation*; an in-call retry is an *occurrence* group inside an invocation (§D1). |
| 2 | `expectations.json` → `source_derived.episodes[1]` | `episode_id: "imaging_after_pick_259811"` with `provenance: "heuristic_label_only"`, but the underlying records (L1901–L1957) carry `episode_id="CS001-1-2-1790199851435:r1-c1"` (`carried_forward`). | Tools follow the records: imaging is an invocation inside episode `r1-c1`. The expectations entry is a *label*, not an episode key. Not rewritten. |
| 3 | `expectations.json` `source_derived.episodes` `workflow_outcome` values (`ok` for `r1-c1`) | Written per pick attempt; with a multi-API episode and the cycle-completion rule of §D4, episode `r1-c1` in this **slice** is `outcome=ok_with_warning, completion=incomplete` (pick + imaging only). | Report both fields; treat expectation values as **invocation** outcomes for `/robotic-arm/pick/basket`. Test S2 asserts invocation outcome, not episode outcome, for that entry. |
| 4 | `expectations.json` `path.success_pick_place.workflow_id` etc. | Synthetic `workflow_id`s keep the old `slide=…:b2-z1-r1-c1` shape while source-derived use `{load}:r{row}-c{col}`. | Harmless: synthetic profile keys on `workflow_id` verbatim. |
| 5 | `sequence-spans.md` §5 table | Lists three enriched inputs; `enriched/index.json` has four (`full_slide_cycle_b.spans.jsonl` too). | Documentation lag; index is authoritative. |
| 6 | `interleaved_episodes.jsonl` | Named "interleaved" but sequential; background records carry the episode's `workflow_id`. | Negative test for interleaving must be built from two **time-merged** sources (S2 acceptance uses `--order time` over `success_pick_place.jsonl` + `interleaved_episodes.jsonl`) rather than from this file alone. Not a corpus change. |
| 7 | Enriched `span.end` for CLDJ episodes has `status="ok"` and `workflow_outcome="error"` | Consistent with `sequence-spans.md` §4 but easy to misread in `tree`. | §D4 keeps span `status` as execution status; sequence outcome never reads span `status` when a profile outcome rule exists. |
| 8 | `full_slide_cycle_a` `move/scanner/pick` response before `activity.completed` | Outcome record can precede the invocation end boundary. | §D2 outcome attachment rule handles both orders. |

## Binding decisions

### D1. Identity and hierarchy

Five distinct things, top to bottom:

| Term | Definition | Identity | Corpus evidence |
|---|---|---|---|
| **Episode** | The multi-record story the user reasons about. May contain many API invocations. | `episode_key`: the tuple of profile `episode.key` field values, rendered as `"<k1>=<v1>&<k2>=<v2>"` (single key: the bare value). For the robot profile the key is `["episode_id"]`, whose value already encodes `(load_identifier,row_number,column_number)`. | `full_slide_cycle_a`: 76 records, 12 invocations, one key. |
| **Invocation** | One bounded call inside an episode (an API handler run). | `(episode_key, invocation_index)`; `invocation_index` is 0-based in episode reading order. Name = the profile `invocation.name` field (`api`). | `activity.in-progress` → `activity.completed` pairs. |
| **Occurrence** | One classified event; when the same step token repeats inside an invocation, occurrences are numbered. | `(episode_key, invocation_index, token, occurrence_n)`; `occurrence_n` counts from 1 per `(invocation, token)`. If the profile names an `occurrence_key` field (e.g. `attempt` or `step_occurrence_id`) and the record has it, that value is **also** recorded as `occurrence_label`; it never replaces the positional number. | force-exit: two `OPEN_AT_PICK_BASKET` occurrences in one invocation (L28031, L28135); `repeated_steps_equal_ts`: `attempt`/`step_occurrence_id`. |
| **In-call retry** | Not a separate entity. It is the *set of occurrences with n > 1* of a token inside one invocation, plus any `abort`-category event. | Derived. | force-exit abort L28371 inside invocation 0 of `r2-c9`. |
| **Linked recovery** | A **different episode** that declares a link to this one through a profile `links` field. | `links.recovery_of` value equals another episode's key. | synthetic `recovery_of` / `triggered_recovery_id`. |

Rules (each maps to a "do not" in the brief):

- Grouping is **only** by the profile episode key. `load_identifier` alone is never a key unless a
  profile says so (the shipped robot profile does not).
- An episode is **not** split when `api` changes; `api` names invocations, not episodes.
- Adjacent episodes are never linked. `r2-c10` after `r2-c9` is a sibling; it has no
  `recovery_of` field, so `links.recovery_of` is empty. Only explicit link fields create links.
- A second `OPEN_AT_PICK_BASKET` inside one invocation is an occurrence (n=2), not a new
  invocation: a new invocation requires a new `invocation.start` boundary event.

**Missing / conflicting identity**

| Situation | Behaviour |
|---|---|
| Record lacks every field of `episode.key` | Category `unassigned`; counted in `unassigned_records`; never attached to any episode (no carry-forward heuristics in the tool — the corpus converter already did that at fixture build time and marked it with `episode_id_provenance`). |
| `episode.key` present but `fallback_keys` also present | Primary key wins; fallback keys are only used when *all* primary fields are missing. |
| Record has an `episode_key` but arrives after that episode was reported complete (streaming) | Appended; `complete` may flip to `complete` again; warning `late_record:<key>:<_id>`. |
| Same `episode_key` in two sources with different `variant` (see D3) | Kept as **two** episodes `(variant, key)`; warning `variant_collision:<key>`. |
| Same `episode_key`, same variant, two files | Merged (that is normal rotation / multi-file input). |

### D2. Shared sequence model and profile

One module `src/slogger/tools/seq/model.py` used by every sequence command.

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

Category = Literal[
    "episode_start", "episode_end",        # explicit episode boundaries (synthetic workflow.start/end)
    "invocation_start", "invocation_end",  # activity.in-progress / activity.completed
    "step", "observation", "outcome", "error", "abort",
    "link", "background", "span_event", "other", "unassigned",
]
DurationKind = Literal["measured", "derived", "unavailable"]
OutcomeValue = Literal["ok", "ok_with_warning", "error", "aborted", "incomplete", "unknown"]
Completion = Literal["complete", "incomplete", "unknown"]

@dataclass(frozen=True)
class RecordRef:
    id: str                       # Reader _id, always present
    timestamp: str | None         # raw string as logged
    source_line: int | None       # only if the record carries source_line (fixture-derived); never required

@dataclass
class Duration:
    ms: float | None
    kind: DurationKind            # measured = duration_ms without *_provenance; derived = provenance
                                  # derived_from_timestamps or computed by the tool; unavailable = None

@dataclass
class SeqEvent:
    ref: RecordRef
    order: int                    # 0-based position in reading order of the whole input (tie-breaker)
    ts: datetime | None
    category: Category
    token: str | None             # path token at the profile granularity; None for background/other/span_event
    rule: str | None              # id of the profile rule that classified it
    occurrence_n: int             # per (invocation, token), from 1; 0 when token is None
    occurrence_label: str | None  # profile occurrence_key value when present
    invocation_index: int | None  # None for episode-level events
    attrs: dict[str, Any]         # only keys listed in profile.keep_attrs (small, explicit)

@dataclass
class Invocation:
    index: int
    name: str | None
    start: RecordRef | None
    end: RecordRef | None
    complete: bool
    outcome: "Outcome"
    duration: Duration
    events: list[int]             # indexes into Episode.events

@dataclass
class Outcome:
    value: OutcomeValue
    rule: str | None              # profile rule id, or "no_evidence"
    evidence: list[RecordRef]

@dataclass
class Links:
    recovery_of: str | None
    triggered_recovery: str | None

@dataclass
class Episode:
    key: str
    key_fields: dict[str, Any]
    variant: str                  # "default" unless profile.variant_key set
    events: list[SeqEvent]
    invocations: list[Invocation]
    outcome: Outcome
    completion: Completion
    links: Links
    first: RecordRef
    last: RecordRef
    duration: Duration            # derived from first/last ts unless an episode span supplies measured
    warnings: list[str]
    truncated: bool               # max_events_per_episode hit
```

`SeqEvent.attrs` is the only place record fields are retained; everything else references
records by `RecordRef.id` so any command can re-fetch via `context --id`. `fixture_seq`,
`source_line`, `episode_id_provenance` are **optional attrs**, never inputs to logic.

**Separated stages** (functions in `tools/seq/episodes.py`, composed by `extract_episodes`):

1. `group(record) -> str | None` — episode key from profile (D1).
2. `classify(record) -> (Category, token, rule_id)` — first matching profile rule wins.
3. `build(episode_records) -> Episode` — boundaries, invocations, occurrences, outcome, completion.
4. `normalise(episode, granularity) -> list[str]` — path tokens (D6).

**Profile file** (`tools/seq/profile.py`; JSON, stdlib only)

```json
{
  "schema_version": 1,
  "name": "robotic-arm-observed",
  "profile_version": "1",
  "episode": {
    "key": ["episode_id"],
    "fallback_keys": [["workflow_id"]],
    "start": [],
    "end": [],
    "complete_when": {
      "invocations": ["/robotic-arm/pick/basket", "/robotic-arm/place/scanner",
                      "/robotic-arm/pick/scanner", "/robotic-arm/drop-slide"]
    }
  },
  "variant_key": null,
  "occurrence_key": ["attempt", "step_occurrence_id"],
  "invocation": {
    "name": "api",
    "start": ["message=activity.in-progress"],
    "end": ["message=activity.completed"],
    "outcome_window": "same_name_nearest"
  },
  "rules": [
    {"id": "bg",        "category": "background", "when": ["logger~\\.bg$"]},
    {"id": "bg_kind",   "category": "background", "when": ["kind=background"]},
    {"id": "abort",     "category": "abort",       "when": ["kind=workflow.abort"],     "token": "message"},
    {"id": "err",       "category": "error",       "when": ["kind=workflow.error"],     "token": "error_code"},
    {"id": "cmd_fail",  "category": "error",       "when": ["kind=command.failed"],     "token": "message"},
    {"id": "force",     "category": "error",       "when": ["kind~^force\\."],          "token": "message"},
    {"id": "warn",      "category": "observation", "when": ["kind=diagnostic.warning"], "token": "error_code"},
    {"id": "resp",      "category": "outcome",     "when": ["kind=api.response"],       "token": null},
    {"id": "gripper",   "category": "step",        "when": ["kind=step.entry"],         "token": "operation_type"},
    {"id": "observe",   "category": "observation", "when": ["kind=observation"],        "token": "message", "token_suffix": "slide_present"},
    {"id": "req",       "category": "other",       "when": ["kind~^api\\.(request|meta|payload)$"]},
    {"id": "meta",      "category": "other",       "when": ["kind~^step\\.(meta|decision)$"]},
    {"id": "intent",    "category": "other",       "when": ["kind=command.request"]}
  ],
  "outcome": {
    "invocation": [
      {"id": "aborted",  "value": "aborted",         "when": ["kind=workflow.abort"]},
      {"id": "biz_err",  "value": "error",           "when": ["kind=api.response", "pick_status=false"]},
      {"id": "biz_err2", "value": "error",           "when": ["kind=api.response", "place_status=false"]},
      {"id": "warned",   "value": "ok_with_warning", "when": ["kind=diagnostic.warning"]},
      {"id": "ok_pick",  "value": "ok",              "when": ["kind=api.response", "pick_status=true"]},
      {"id": "ok_place", "value": "ok",              "when": ["kind=api.response", "place_status=true"]}
    ],
    "episode": "aggregate"
  },
  "links": {"recovery_of": "recovery_of", "triggered_recovery": "triggered_recovery_id"},
  "keep_attrs": ["api", "operation_type", "error_code", "slide_error_code", "pick_status",
                 "place_status", "slide_present", "level", "source_line", "fixture_seq"]
}
```

Semantics:

- `when` items are existing compact `--where` tokens parsed with `parse_where`; ANDed. A rule with
  `when: []` never matches (explicit no-op) rather than matching everything.
- `token`: field name whose value becomes the path token; `null` → no token (event kept, not in
  paths); if the field is missing the token is `"<category>"`. `token_suffix` appends `=<value>`
  of that field when present (`observation.slide_present=false`).
- **Precedence**: `rules` are evaluated in order; **first match wins**. `background` rules should
  therefore come first. Span events (`event` in `span.start`/`span.end`) are classified
  `span_event` **before** any rule, unless the profile sets `"spans": "as_steps"` (used by the
  synthetic profile), in which case a `span.end` record produces category `step` with token =
  `span` and `span.start` is `span_event` (so a span counts once).
- Invocation boundaries: `invocation.start`/`end` are `when` lists; `name` is a field name. An
  `end` whose name does not equal the open invocation's name closes nothing and is warned
  `unmatched_invocation_end`. A `start` while an invocation of the **same name** is open closes
  the previous one as `complete=false` (warning `invocation_restart`). Profiles with no
  `invocation` block produce a single implicit invocation per episode.
- `outcome_window: same_name_nearest`: an `outcome` event attaches to the invocation whose `name`
  equals the event's `invocation.name` field value (`api`) and whose boundaries are closest in
  reading order — this covers responses that arrive **after** `activity.completed` (pick/basket)
  and **before** it (`move/scanner/pick`). If the event has no such field, it attaches to the
  most recent invocation.
- `outcome.invocation` rules: evaluated over the invocation's events **in rule order**; the first
  rule with any matching event fixes the value, so the list order is the precedence
  (`aborted > error > ok_with_warning > ok`). No matching rule → `unknown` (never `ok`).
- `outcome.episode: "aggregate"`: `aborted` if any invocation aborted; else `error` if any
  invocation `error`; else `ok_with_warning` if any; else `ok` only if **every** invocation is
  `ok` and completion is `complete`; else `unknown`. Explicit alternative
  `"episode": {"field": "workflow_outcome", "on": ["message=workflow.end"]}` reads a value from
  the episode-end record (synthetic profile) with the mapping `running → unknown`.
- `complete_when.invocations`: ordered subsequence of invocation names that must all be present
  and complete → `completion=complete`; missing any → `incomplete`. Alternatively
  `complete_when: {"end": true}` requires an `episode.end` boundary. No `complete_when` →
  `unknown`.
- `variant_key`: optional field name; the episode's `variant` is its value (`"default"` when the
  key is absent). Robot fixtures use `"span_enrichment"` to separate enriched from observed
  copies when both are supplied together (D3).
- `links`: field names copied to `Links`; values are compared to other episodes' `key` strings.

**Validation** (`load_profile(path) -> Profile` raises `ToolError("profile_invalid", ...)`):
`schema_version == 1`; `episode.key` non-empty list of str; every `when` token parses; every
`rule.id` unique; `category` in `Category`; `outcome.*.value` in `OutcomeValue`; unknown top-level
keys rejected (so typos fail loudly). `profile_version` is a free string included in fingerprints.

**Built-in profile** `generic` (no file): key `["episode_id"]`, fallbacks `[["workflow_id"],
["trace_id"]]`; spans `as_steps`; no invocation block; rule `background` for
`event=span.start`; outcome from `status=error` on any `span.end` → `error`, else `unknown`.
Domain-neutral and enough to run on any slogger file; anything richer needs `--profile FILE`.

Two **example profiles** are committed as fixtures, not package data:
`tests/fixtures/logs/sequence/profiles/robotic_arm_observed.json` (above) and
`tests/fixtures/logs/sequence/profiles/synthetic_workflow.json` (key `["workflow_id"]`,
`episode.start=["message=workflow.start"]`, `end=["message=workflow.end"]`, spans `as_steps`,
outcome `{"field": "workflow_outcome", "on": ["message=workflow.end"]}`, links as above,
background rules for `logger~\.bg$` / `kind=background`). Keeping them under `tests/fixtures`
keeps the library domain-neutral; the README documents copying one as a starting point.

### D3. Three corpus variants

| Variant | How recognised | Path tokens (granularity `app`) | Duration source |
|---|---|---|---|
| source-derived (observed) | no `event` key on any record | application events only | `derived` from first/last `ts` of invocation boundaries; `unavailable` when a boundary is missing |
| enriched | `event` present **and** `span_enrichment=proposed` on span rows | identical to observed (span rows are `span_event`, never tokens at `app` granularity) | if a span row with `span_role=api_invocation` and `source_line_start == invocation.start.source_line` exists, `Duration(ms, kind="derived")` from its `duration_ms` (because `duration_ms_provenance` is present); a span row **without** `*_provenance` would be `measured` |
| synthetic | `fixture=synthetic`, real spans | `app`: `workflow.*`/`step.*` records; `span`: span names | `measured` from `duration_ms` on `span.end` |

Rules:

- **No double counting**: at `app` granularity a `span.end` never yields a token; at `span`
  granularity application records never yield tokens. There is no mixed granularity.
- **Inferred structure is labelled**: `Invocation.duration.kind` and a per-episode
  `boundaries: {"start": "observed"|"inferred"|"unavailable", "end": ...}` are reported; values
  come from `span_boundary_*` when a proposed span supplied them, else from whether the
  application boundary record exists.
- **Duration kinds never mix**: `path-diff --timing` compares only invocations whose
  `Duration.kind` is equal on both sides and reports `n` per kind.
- **Evidence retained**: every `SeqEvent.ref` is the original record `_id`; when an invocation's
  duration came from a proposed span, `duration_evidence` lists that span row's `_id` and its
  `source_line_start/end` attrs.
- **Comparable views**: `episodes --format json` for `source_derived/X.jsonl` and
  `enriched/X.spans.jsonl` (same profile, `app` granularity) must produce identical
  `key`, `invocations[].name`, `outcome`, `completion`, `path_fingerprint`, and `match` results.
  Allowed differences: `duration.kind` (`derived` both, but the enriched one has evidence refs),
  `span_events` count, `boundaries`. Acceptance test S2-A7 pins this for all four pairs.
- **Do not pool variants**: when one input set contains records with different `variant`
  values for one key, they become separate episodes and the payload carries
  `variant_collision` warnings; `paths` groups fingerprints per variant; `path-diff` refuses to
  use an episode of a different variant as baseline unless `--allow-variant-mismatch`. No
  content-similarity deduplication anywhere.

### D4. Business outcomes vs execution status

Four independent facts per invocation/episode, all reported, none inferred from another:

| Field | Source | Values |
|---|---|---|
| `span_status` | slogger `status` on `span.end` (unchanged semantics) | `ok`/`error`/`unknown`, or `null` when no span |
| `complete` (invocation) | both `invocation.start` and `invocation.end` seen | bool |
| `outcome` (invocation) | profile `outcome.invocation` rules, first-hit precedence | `OutcomeValue` |
| `outcome` / `completion` (episode) | profile `outcome.episode` + `complete_when` | `OutcomeValue` / `Completion` |

Worked examples (robot profile, `app` granularity):

| Episode | Invocation facts | Episode |
|---|---|---|
| `r1-c3` (cluster) | pick/basket: complete, `span_status=null`, outcome `error` (rule `biz_err`, evidence L8518) | outcome `error`, completion `incomplete` (only pick/basket present) |
| `r2-c9` (force-exit) | pick/basket: complete, outcome `aborted` (rule `aborted`, evidence L28371); `error` events L28118, L28369, L28370 kept as evidence | outcome `aborted`, completion `incomplete` |
| `r2-c10` | pick/basket: complete, outcome `ok` (L28545) | outcome `unknown` (`ok` requires completion `complete`); completion `incomplete` |
| `r1-c2` (cycle A) | 12 invocations, three `outcome` events: pick/basket `ok` (L5675), move/scanner/pick `ok` (L6283), drop-slide `ok` (L6935); other invocations `unknown` | outcome **`unknown`**, completion `complete` — because nine invocations have no outcome evidence and the aggregate rule requires every invocation `ok` |
| `r1-c1` (cluster) | pick/basket `ok`; imaging `ok_with_warning` (L1911) | outcome `ok_with_warning`, completion `incomplete` |

The cycle-A result is deliberate: the tool must not report `ok` for invocations that emitted no
business outcome. The robot profile therefore sets
`"episode": {"aggregate": true, "require_outcome_from": ["/robotic-arm/pick/basket",
"/robotic-arm/drop-slide"]}` — only listed invocation names must have an explicit outcome; others
may be `unknown` without blocking `ok`. With that, cycle A/B are `ok` + `complete`. This is a
profile choice recorded in the profile file, not library behaviour. (Expectations
`path.full_slide_cycle_a/b` `workflow_outcome: ok` then hold.)

Other rules:

- Severity is **never** an outcome rule input unless a profile says so; `INFO`/`WARNING` logical
  failures classify through `kind`/`error_code` fields.
- "Recovered from force stop" (`force.recovered`) is an `error`-category event with no outcome
  effect; the later `abort` sets the outcome. An outcome is fixed only by `outcome` rules.
- No end is manufactured: an episode whose last invocation has no `end` is `completion=incomplete`
  (or `unknown` without `complete_when`) and its duration is `Duration(None, "unavailable")`
  unless first/last timestamps exist, in which case `elapsed_ms` (first→last) is reported as a
  separate field, explicitly *not* a duration.
- Recovery: a linked recovery episode's `outcome=ok` never changes the failed episode's
  `outcome=error`. `episodes` shows both rows; the failed row carries
  `links.triggered_recovery`, the recovery row `links.recovery_of` (synthetic fixture).

### D5. Extraction, ordering, limits, export

- **Input**: exactly the P1 `Reader` contract — paths, globs, `-`, in-memory iterables (materialised
  once), `--order concat|time`. `--order time` applies the D2 (P1) merge and its warnings.
- **Ordering inside an episode**: reading order of the chosen `--order`. `SeqEvent.order` is the
  global reading position; equal timestamps keep reading order; records without a parseable
  timestamp keep their position, `ts=None`, and are excluded from `--within` time windows (they
  count as "outside"). Out-of-order records (later timestamp then earlier) are **not** re-sorted;
  the episode carries warning `non_monotonic:<n>`. Reading order is *deterministic presentation*
  order; the payload states `"order_basis": "reading"` so nobody mistakes it for causality.
- **Episode filters vs record hiding**:
  - Episode **selection** flags: the shared `add_filter_args` set (`--level`, `--where`, `--grep`,
    …) select an episode when **any** of its records matches (P1 D3 semantics), plus
    `--episode KEY` (repeatable, exact), `--outcome VALUE` (repeatable), `--completion VALUE`,
    `--variant NAME`.
  - Record **hiding** flags (display only, never affect grouping/outcome/paths): `--hide TOKEN`
    (compact `--where` token; repeatable), `--show-background` (background hidden by default in
    record output), `--show-spans` (span rows hidden by default in `app` granularity output).
  - Finding an error therefore never removes its lead-up: selection is by episode.
- **Bounds** (memory caps → `*_capped`, output caps → `truncated`, both keep scanning):
  `max_open_episodes=10_000` (further new keys counted in `episodes_capped`),
  `max_events_per_episode=100_000` (further events counted, not stored; `Episode.truncated`),
  `--top N` (default 50) on `episodes`/`paths`/`match`, `--limit` on match results per episode.
  `episode KEY` has no caps except `max_events_per_episode`.
- **Pagination**: `episodes --format json` writes one JSON line per episode summary then `_meta`
  with `next_cursor` = the P1 reader cursor of the last *record* consumed when `--top` was hit
  (concat `_id` or `time;…`). Because an episode may be open until EOF, `--top` truncation is
  reported with `truncated: true` and `open_episodes_at_cut`; resuming with `--after` restarts
  grouping from that record position and is documented as "records after the cursor only".
- **Export / round trip**: `episode SOURCE KEY --records` writes the episode's **original records**
  (unchanged, `_id` kept, no summary fields injected), then one control line
  `{"_episode": {...Episode summary...}}`, then `{"_meta": {...}}`. Feeding those record lines
  (dropping the two control lines) back to `episodes` with the same profile must yield an
  identical `_episode` summary (test S2-A9). Control lines are recognised by their single
  underscore key; sequence summaries never appear as bare records.

### D6. Paths and normalisation

- **Granularity** `--granularity app|invocation|span`:
  - `invocation`: tokens = invocation names in order (`/robotic-arm/pick/basket`, …).
  - `app` (default): for each invocation, its name, then its `step`/`observation`/`error`/`abort`
    tokens in reading order; episode-level events of those categories are included where they
    fall. `outcome` events add no token (their effect is the outcome field).
  - `span`: tokens = `span` names of `span.end` records in reading order (synthetic fixtures;
    `generic` profile).
- **Token** = the profile `token` field value (+`token_suffix`), stringified with the same
  normalisation as `group_value` (numbers `1`/`1.0` equal, bools `true/false`).
- **Fingerprint** = first 16 hex of `sha256(json.dumps([FINGERPRINT_VERSION, profile.name,
  profile.profile_version, granularity, tokens], separators=(",",":"), ensure_ascii=True))`,
  `FINGERPRINT_VERSION = 1`. Payload always prints the four inputs alongside the hash so a
  fingerprint is meaningless without them.
- **Repeats** stay in `tokens`. `--collapse` adds `collapsed_tokens` (`A×3` rendering,
  `{"token": "A", "count": 3, "refs": [...]}` in JSON) and `collapsed_fingerprint` computed over
  the collapsed list with `FINGERPRINT_VERSION` and `"collapsed": true` in the hashed array. The
  uncollapsed fingerprint is always present.
- **Background** exclusion is by profile category; `--show-background` on `paths` lists excluded
  refs under `background_refs` without changing tokens.
- **Success vs conformity**: `paths` groups episodes by fingerprint and reports, per group,
  `outcomes: {ok: n, …}` and `completion: {...}`. A fingerprint that differs from the most common
  one is reported as *distinct*, never as *anomalous*; the word "anomaly" does not appear in output.

Expected tokens (robot profile, `app`):

| Fixture / episode | Tokens |
|---|---|
| `full_slide_cycle_a` `r1-c2` | `/robotic-arm/pick/basket, OPEN_AT_PICK_BASKET, CLOSE_AT_PICK_BASKET, observation.slide_present=true, /robotic-arm/move/scanner/imaging, /robotic-arm/scanner/adjust-position, /robotic-arm/place/scanner, PARTIAL_OPEN_AT_SCANNER_PLACE, /robotic-arm/move/scanner/open-pose, OPEN_AT_SCANNER_PLACE, /robotic-arm/move/scanner/open-pose/home, CLOSE_AT_HOME, observation.slide_present=false, OPEN_AT_HOME, /robotic-arm/move/pick-basket/home, /robotic-arm/move/scanner/open-pose, EXTREME_OPEN_AT_HOME_FOR_SCANNER_PICK, /robotic-arm/move/scanner/pick, CLOSE_AT_SCANNER_PICK, observation.slide_present=true, /robotic-arm/pick/scanner, /robotic-arm/move/scanner/open-pose, /robotic-arm/drop-slide, OPEN_AT_PICK_BASKET` (24 tokens) |
| `full_slide_cycle_b` `r1-c20` | same 24 tokens → **same fingerprint** as A (test S3-A2; this is the strongest cross-source check in the corpus) |
| cluster `r1-c3` | `/robotic-arm/pick/basket, OPEN_AT_PICK_BASKET, CLOSE_AT_PICK_BASKET, observation.slide_present=false, OPEN_AT_PICK_BASKET, CLDJ_SLIDE_NOT_FOUND` |
| force-exit `r2-c9` | `/robotic-arm/pick/basket, OPEN_AT_PICK_BASKET, CLOSE_AT_PICK_BASKET, observation.slide_present=true, force.stop_playing, force.handle_generic_stop, force.handle_safety_stop, force.handle_force_stop, force.recovered, force.handler_executing, OPEN_AT_PICK_BASKET, motion.failed, RA_CANNOT_PICK_FROM_BASKET_MULTIPLE_ATTEMPTS, pick.retry_loop_abort` |
| synthetic `success_pick_place` (`span`, synthetic profile) | `move_to_pick, OPEN_AT_PICK_BASKET, CLOSE_AT_PICK_BASKET, PARTIAL_OPEN_AT_PICK_BASKET, CLOSE_AT_PICK_BASKET, move_scanner_imaging, place_scanner, workflow` (the root `workflow` span ends last) |
| synthetic `success_with_home_correction` (`span`) | `home_mismatch, move_z2_home, OPEN_AT_PICK_BASKET, CLOSE_AT_PICK_BASKET, place_scanner, workflow` — different fingerprint, `outcome=ok`: two legitimate successes |
| synthetic `repeated_steps_equal_ts` (`app`, synthetic profile with `steps` rule `kind=step.entry`→`operation_type`, observations `kind=observation`) | `observation.slide_present=false, CLOSE_AT_PICK_BASKET` repeated three times (6 tokens); `--collapse` leaves six entries of `count 1` because the two tokens alternate; `occurrence_label` = `close-1..3` |

(`expectations.json` `path_span_names` lists `workflow` first; the tool lists it last because
tokens are taken at `span.end`. Report as an ordering convention difference in S3 tests — assert
set equality plus the documented end-order, do not rewrite the expectation.)

### D7. Matching and motifs

**Pattern** = ordered list of **positions**; each position is a list of compact `--where` tokens
ANDed against the *record* of an event (so `operation_type=CLOSE_AT_PICK_BASKET`,
`slide_present=false`, `error_code=CLDJ_SLIDE_NOT_FOUND`, `message=force.recovered`,
`span=OPEN_AT_PICK_BASKET` all work unchanged). A position may also target the derived token with
the pseudo-key `token=` (e.g. `token=/robotic-arm/drop-slide`) and the category with
`category=`; these two pseudo-keys are the only additions to the `--where` grammar and are only
valid inside patterns.

CLI grammar: `--step 'TOKEN[;TOKEN...]'` repeatable, one position per flag; `;` separates ANDed
tokens (same separator already used by time cursors, so shell quoting is familiar).

| Question | Decision |
|---|---|
| Which events are candidates | `SeqEvent`s whose category is one of `episode_start`, `episode_end`, `invocation_start`, `invocation_end`, `step`, `observation`, `outcome`, `error`, `abort`, `link`. Excluded: `background`, `other`, `span_event`, `unassigned`. `--include-spans` adds `span_event` rows (needed for `span=` patterns on synthetic files). |
| Adjacency vs subsequence | `--mode subsequence` (default): positions match in order, any events may intervene. `--mode adjacent`: consecutive matched events must be consecutive **candidate** events of the episode (so `api.meta`/`api.payload` `other` records never break adjacency, but an unmatched `step` does). |
| Entry / completion / observation | A position matches the event record as-is. `invocation_start`/`invocation_end` events are matchable (`message=activity.completed`), so "completion" is expressed by matching the boundary record; `outcome` events (`kind=api.response`) are matchable for business results. |
| One event, several positions | **No**: each event satisfies at most one position; positions consume events strictly increasing in `order`. |
| Overlaps / dedup | Default returns the **first** (earliest-ending, leftmost) match per episode. `--all` returns non-overlapping matches found by restarting after the last consumed event. Matches are identified by `(episode_key, first_ref.id, last_ref.id)`. |
| Time window | `--within DUR`: `ts(last) - ts(first) <= DUR`; any matched event with `ts=None` fails the window; without `--within` timestamps are ignored. |
| Incomplete episodes | Matched normally; each match carries `episode_completion` so a caller can filter with `--completion complete`. |
| Cross-episode | Never. `--follow-links` (off by default) additionally evaluates the pattern over the concatenation `[episode events] + [recovery episode events]` **only** when `links.triggered_recovery` resolves to a loaded episode; the match then reports both keys and `via: "triggered_recovery"`. |
| Negative constraints | Not in this scope. Absence is tested by the caller (`--fail-if-any` on a positive pattern, or comparing `match` counts). |

Corpus-grounded cases (all asserted in S4):

| Case | Pattern | Fixture | Expect |
|---|---|---|---|
| Empty slot | `--step operation_type=CLOSE_AT_PICK_BASKET --step 'message=observation.slide_present;slide_present=false' --step error_code=CLDJ_SLIDE_NOT_FOUND` | cluster | matches `r1-c3`, `r1-c4`, `r1-c5`; **not** `r1-c1` (its `slide_present=false` is followed by no error) |
| Force exit → abort | `--step error_code=E-200 --step message=force.recovered --step operation_type=OPEN_AT_PICK_BASKET --step error_code=RA_CANNOT_PICK_FROM_BASKET_MULTIPLE_ATTEMPTS --step message=pick.retry_loop_abort` | force-exit | one match in `r2-c9`; none in `r2-c10` |
| Wrong order | `--step span=OPEN_AT_PICK_BASKET --step span=CLOSE_AT_PICK_BASKET --include-spans` | `near_match_wrong_order` (synthetic profile) | 0 matches |
| Interleaving | `--step span=OPEN_AT_PICK_BASKET --step span=place_scanner --include-spans` over `--order time` of `success_pick_place.jsonl` + `interleaved_episodes.jsonl` | 1 match (`loadA`, which really has both); **0** in `loadF:ep1`/`ep2` because they are different episodes |
| Next slot ≠ recovery | `episodes` on force-exit | `r2-c9` `outcome=aborted`, `r2-c10` `outcome=unknown` (see D4), both rows present, `links` empty on both |
| Linked recovery keeps failure | `episodes` on `failure_then_recovery` (synthetic profile) | `loadB…` `outcome=error`, `links.triggered_recovery` set; `syn:recovery…` `outcome=ok`, `links.recovery_of` set |
| Same-episode full cycle | `--step token=/robotic-arm/pick/basket --step token=/robotic-arm/place/scanner --step token=/robotic-arm/pick/scanner --step token=/robotic-arm/drop-slide` | cycle A, cycle B, enriched copies | 1 match each; identical `first_ref/last_ref` ids between source and enriched (same `_id` line numbers differ — compare `source_line` attrs instead; test asserts attrs) |

**Motif file** (`tools/seq/motifs.py`): JSON, one file per motif, directory = `--motif-dir` or
`$SLOGGER_MOTIF_DIR` or `./.slogger/motifs/`. Name must match `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`.

```json
{"schema_version": 1, "name": "empty_slot", "description": "…",
 "profile": "robotic-arm-observed", "profile_version": "1", "granularity": "app",
 "mode": "subsequence", "within_ms": null, "include_spans": false,
 "steps": [["operation_type=CLOSE_AT_PICK_BASKET"],
           ["message=observation.slide_present", "slide_present=false"],
           ["error_code=CLDJ_SLIDE_NOT_FOUND"]],
 "created": "2026-09-27T00:00:00.000Z"}
```

Commands: `motif save NAME --step … [--mode] [--within] [--description]`, `motif list`,
`motif show NAME`, `motif rm NAME`. `match … --motif NAME` loads it; if the loaded profile
`name`/`profile_version` differ from the motif's, the match still runs but `_meta.warnings`
contains `motif_profile_mismatch`. Errors: `motif_not_found`, `motif_invalid`, `motif_exists`
(save without `--force`), all exit 2. Motifs are data; no code is ever loaded from them.

### D8. Path comparison (`path-diff`)

- **Baseline eligibility**: an episode with `completion=complete` (or `unknown` when the profile
  has no `complete_when`, reported as such), same `profile.name`/`profile_version`, same
  granularity, same `variant`; `--require-same VALUE` (repeatable field name, e.g.
  `service_version`) additionally requires equality of that attr on the first record.
- **Baseline selection**, exactly one of: `--baseline KEY` (explicit episode in the same input);
  `--baseline-file PATH` (a separate input read with the same profile; its **first eligible
  episode in reading order** is used unless `--baseline KEY` is also given); or the default
  **representative rule**: among eligible episodes with `outcome=ok`, take the most frequent
  fingerprint; ties → the fingerprint whose first episode appears earliest in reading order; the
  baseline *episode* is that group's first episode. The payload states which rule chose it. There
  is no "median path".
- **Alignment**: `difflib.SequenceMatcher(None, baseline_tokens, episode_tokens, autojunk=False)`
  opcodes → `equal`/`insert`/`delete`/`replace` with token slices and `RecordRef`s for the episode
  side (and baseline side). Repeated tokens align positionally (SequenceMatcher is deterministic
  for fixed inputs). `--collapse` compares collapsed lists instead and reports count deltas.
- **Structural vs timing**: default output is structural only. `--timing` adds, per invocation
  name present on both sides, `{"baseline_ms", "episode_ms", "kind"}` **only when both
  `Duration.kind` are equal and not `unavailable`**, plus `n_compared`, `n_skipped_kind_mismatch`.
  Nothing is aggregated across episodes; no percentiles, no frequencies, no significance.
- **Wording**: payload keys are `divergence` and `evidence`; documentation and console text say
  "diverges from baseline at …", never "root cause".

Expected (computed with `difflib.SequenceMatcher(None, a, b, autojunk=False)` on the D6 token
lists while writing this plan): `path-diff` of `full_slide_cycle_b` against baseline
`full_slide_cycle_a` (two files) → one opcode `("equal", 0, 24, 0, 24)`; cluster `r1-c3` against
baseline `r1-c1` (12 vs 6 tokens) → `[("equal", 0, 5, 0, 5), ("replace", 5, 12, 5, 6)]`, i.e. the
shared prefix `/robotic-arm/pick/basket, OPEN_AT_PICK_BASKET, CLOSE_AT_PICK_BASKET,
observation.slide_present=false, OPEN_AT_PICK_BASKET`, then the baseline's seven remaining tokens
(`CLOSE_AT_PICK_BASKET … ROBOT_NOT_IN_CORRECT_POSITION`) replaced by `CLDJ_SLIDE_NOT_FOUND`.
`r1-c4` and `r1-c5` produce the same opcodes.

### D9. Incremental detection (`watch-seq`)

Same model, same profile, same matcher as `match`; only the record source differs.

- **Source**: one file or `-`; globs / several files / `--order time` → 64 (as `watch`).
- **Backlog**: default starts at EOF (like `watch`): episodes whose lead-up precedes start
  **cannot** match — documented. `--existing` first runs the offline `match` over the whole file,
  emits any matches, then continues from EOF with the resulting open-episode state.
- **State**: open `Episode`s keyed by `(variant, key)`, each with partial-match cursors (the
  position index reached per pattern). `--max-open N` (default 1 000) evicts the least recently
  updated episode (`evicted` counter in `_meta`); `--expire DUR` closes an episode when no record
  for it arrives for `DUR` of wall clock (`expired` counter); expired episodes report
  `completion=incomplete` if they later match nothing. Eviction/expiry are reported, never silent.
- **Ordering / late records**: reading order of appended complete lines; a late record for an
  expired or evicted key starts a **new** episode object with warning `late_record:<key>`.
- **Partial lines, rotation, EOF, timeout, cancel**: identical mechanics to `watch` (`tail_once`
  hold-back, inode/shrink reopen resets the cursor and keeps open-episode state, stdin EOF →
  `eof_without_match` exit 2 when nothing matched, deadline → exit 3, `KeyboardInterrupt` → 130).
- **Notification**: on each completed match write the JSONL match object immediately
  (`flush=True`); default exit 0 after the first match; `--count N` waits for N matches;
  `--all` runs until timeout/EOF and exits 0 if ≥1 match else 3. A match is emitted at most once
  per `(episode_key, first_ref.id, last_ref.id)`; restarting the process has **no** memory of
  earlier notifications — no durable exactly-once claim.
- **Equivalence requirement** (S6 tests): appending a fixture line by line to a temp file while
  `watch_seq(existing=False, max_open=large, expire=None)` runs from an empty file must produce the
  same match set as offline `match --all` on the fixture; with `existing=True` on the complete
  file, the same. Deterministic timeout test with fake clock; bounded-state test asserting
  `evicted` increments at `max_open+1` episodes.
- **Offline `--fail-if-any`**: `match --fail-if-any` exits 1 when ≥1 match, 0 otherwise
  (P1 convention). `watch-seq` does not take `--fail-if-any` (its exit codes already encode it).

External actions and robot control are out of scope.

## Public API (all exported from `slogger.tools.__all__`)

```python
# tools/seq/model.py
RecordRef, Duration, SeqEvent, Invocation, Outcome, Links, Episode   # dataclasses above
FINGERPRINT_VERSION: int = 1

# tools/seq/profile.py
@dataclass(frozen=True) class Profile: ...   # parsed form; .name, .profile_version, .episode_key, ...
def load_profile(path: str | os.PathLike[str] | None) -> Profile        # None → GENERIC_PROFILE
GENERIC_PROFILE: Profile
def classify(profile: Profile, record: Mapping[str, Any]) -> tuple[Category, str | None, str | None]

# tools/seq/episodes.py
def extract_episodes(sources, *, profile: Profile, filters: Filters | None = None,
                     episode_keys: Sequence[str] = (), outcomes: Sequence[str] = (),
                     completion: str | None = None, variant: str | None = None,
                     order: Order = "concat", after: str | None = None,
                     max_open_episodes: int = 10_000, max_events_per_episode: int = 100_000,
                     top: int | None = 50) -> EpisodesResult
@dataclass class EpisodesResult:
    episodes: list[Episode]; total: int; returned: int; truncated: bool
    episodes_capped: bool; unassigned_records: int; skipped_lines: int
    next_cursor: str | None; warnings: list[str]; order_basis: Literal["reading"]
def episode_summary(ep: Episode) -> dict[str, Any]     # the `_episode` / JSON row shape
def get_episode(sources, key: str, *, profile, variant=None, order="concat",
                max_events_per_episode=100_000) -> tuple[Episode, list[dict[str, Any]]]  # (episode, original records)

# tools/seq/paths.py
Granularity = Literal["app", "invocation", "span"]
def path_tokens(ep: Episode, granularity: Granularity) -> list[str]
def fingerprint(profile: Profile, granularity: Granularity, tokens: Sequence[str], *, collapsed: bool = False) -> str
def collapse(tokens: Sequence[str], refs: Sequence[RecordRef]) -> list[dict[str, Any]]
def paths(sources, *, profile, granularity="app", collapse=False, filters=None, ..., top=50) -> dict[str, Any]

# tools/seq/match.py
@dataclass(frozen=True) class Position: where: tuple[Where, ...]
@dataclass(frozen=True) class Pattern: positions: tuple[Position, ...]; mode: Literal["subsequence","adjacent"]
                                        within_ms: float | None; include_spans: bool
def parse_step(token: str) -> Position                    # "a=1;b~x" → Position; pseudo-keys token=, category=
@dataclass class Match: episode_key: str; variant: str; positions: list[RecordRef]; first: RecordRef; last: RecordRef
                        elapsed_ms: float | None; episode_completion: Completion; via: str | None
def match_episode(ep: Episode, pattern: Pattern, *, all_matches: bool = False) -> list[Match]
def match(sources, *, profile, pattern, granularity="app", filters=None, all_matches=False,
          follow_links=False, order="concat", top=50, ...) -> dict[str, Any]

# tools/seq/motifs.py
def motif_dir(explicit: str | None) -> Path
def save_motif(name, pattern, *, profile, granularity, description=None, force=False, directory=None) -> Path
def load_motif(name, *, directory=None) -> tuple[Pattern, dict[str, Any]]
def list_motifs(*, directory=None) -> list[dict[str, Any]]
def remove_motif(name, *, directory=None) -> None

# tools/seq/pathdiff.py
def path_diff(sources, *, profile, granularity="app", baseline_key=None, baseline_sources=None,
              require_same=(), timing=False, collapse=False, allow_variant_mismatch=False,
              filters=None, order="concat", top=50) -> dict[str, Any]

# tools/seq/watchseq.py
@dataclass class WatchSeqResult: matches: list[Match]; timed_out: bool; elapsed_ms: float
                                 records_seen: int; evicted: int; expired: int
def watch_seq(path, *, profile, pattern, granularity="app", timeout=30.0, existing=False,
              count=1, all_matches=False, interval=0.25, max_open=1_000, expire_s=None,
              stop=None, on_reopen=None, on_match=None, clock=time.monotonic,
              sleep=time.sleep, stdin=None) -> WatchSeqResult
```

## CLI (added to `python3 -m slogger`)

All commands take `--profile FILE` (default: built-in `generic`), `--granularity app|invocation|span`
(default `app`), the shared filter flags via `add_filter_args`, `--order` via `add_order_arg`
where noted, `--format`, `--color/--no-color`.

```text
episodes   SOURCE... [--episode KEY]... [--outcome V]... [--completion V] [--variant V]
                     [--top N] [--after CURSOR] [--order concat|time] [--format console|json|table]
episode    SOURCE... KEY [--records] [--hide TOKEN]... [--show-background] [--show-spans]
                     [--variant V] [--order ...] [--format console|json]
paths      SOURCE... [--collapse] [--show-background] [--top N] [--order ...] [--format console|json|table]
match      SOURCE... (--step TOKENS)... | --motif NAME  [--mode subsequence|adjacent] [--within DUR]
                     [--include-spans] [--all] [--follow-links] [--top N] [--order ...]
                     [--fail-if-any] [--format console|json|table]
motif      save NAME (--step TOKENS)... [--mode] [--within] [--include-spans] [--description TEXT] [--force]
           list | show NAME | rm NAME            [--motif-dir DIR]  [--format console|json]
path-diff  SOURCE... [--baseline KEY] [--baseline-file PATH] [--require-same FIELD]... [--timing]
                     [--collapse] [--allow-variant-mismatch] [--top N] [--order ...] [--format console|json|table]
watch-seq  SOURCE (--step TOKENS)... | --motif NAME [--mode] [--within] [--include-spans]
                     [--timeout DUR] [--existing] [--count N | --all] [--interval SEC]
                     [--max-open N] [--expire DUR] [--format console|json]
```

Compatibility (✓ accepted, 64 usage error, – not defined):

| Flag | episodes | episode | paths | match | motif | path-diff | watch-seq |
|---|---|---|---|---|---|---|---|
| record filters (select episodes) | ✓ | – | ✓ | ✓ | – | ✓ | ✓ |
| `--exclude-events` | 64 (spans are handled by granularity) | 64 | 64 | 64 | – | 64 | 64 |
| `--after CURSOR` | ✓ | – | – | – | – | – | 64 |
| `--limit/--last/--fields/--truncate` | – | – | – | – | – | – | – |
| `--fail-if-any` | – | – | – | ✓ | – | – | – |
| `--order time` | ✓ | ✓ | ✓ | ✓ | – | ✓ | 64 |
| `--format table` | ✓ | 64 | ✓ | ✓ | 64 | ✓ | 64 |
| stdin `-` | ✓ (buffered) | ✓ | ✓ | ✓ | – | one side | ✓ |

Error codes (exit 2, JSON on stderr in JSON mode): `profile_invalid`, `profile_not_found`,
`episode_not_found`, `motif_not_found`, `motif_invalid`, `motif_exists`, `baseline_not_found`,
`baseline_ineligible`, `variant_mismatch`, `eof_without_match`. Usage (64): bad `--step` token,
`--step` with `--motif`, `--count` with `--all`, unsupported flag combinations above.

Output contracts: `episodes`, `paths`, `match`, `path-diff` in JSON write **one object** with
`schema_version: 1`, `profile: {name, profile_version, source}`, `granularity`,
`order`, `order_basis: "reading"`, the payload, caps/truncation flags, `warnings`. `episode`
writes JSONL (records) + `_episode` + `_meta`. `watch-seq` writes one JSON object per match as it
happens, then a final `{"_meta": {...}}`.

Console example (`episodes`):

```text
key                              variant  invocations  outcome          completion  first                     last
CS001-1-1-1790200023515:r2-c9    default  1            aborted          incomplete  2026-09-24T02:42:42.451Z  2026-09-24T02:43:14.401Z
CS001-1-1-1790200023515:r2-c10   default  1            unknown          incomplete  2026-09-24T02:43:14.544Z  2026-09-24T02:43:17.933Z
total 2  returned 2  unassigned 0
```

## Fixtures

Existing corpus files are reused unchanged. New files (all small, hand-written, under
`tests/fixtures/logs/sequence/`):

| File | Purpose |
|---|---|
| `profiles/robotic_arm_observed.json` | D2 example profile (with `require_outcome_from`). |
| `profiles/synthetic_workflow.json` | Profile for synthetic fixtures. |
| `profiles/invalid_unknown_key.json` | `{"schema_version": 1, "episode": {"key": ["x"]}, "bogus": 1}` → `profile_invalid`. |
| `motifs/empty_slot.json`, `motifs/force_exit_abort.json` | Saved-motif fixtures for `match --motif` and `motif list/show`. |
| `edge/late_and_unassigned.jsonl` | 6 records: two with `episode_id=E1`, one with no key (unassigned), one `E1` record with an **earlier** timestamp than the previous `E1` record (non_monotonic), one with unparseable `timestamp: "bad"`, one `E2`. Pins D1 missing-key handling, D5 ordering warnings, `ts=None` window behaviour. |

Minimal missing cases identified (no broader corpus expansion): a genuinely time-interleaved
two-episode input is produced in tests by `--order time` over two existing synthetic files (see
discrepancy 6); a motif whose profile differs is produced by saving with the synthetic profile
and matching with the robot profile.

## Tasks

Regression after every task: `python3 -m pytest -q`, `python3 -m ruff check src tests examples`,
`python3 -m pyrefly check` (no **new** errors; the 6 baseline errors in `build_corpus.py` may be
fixed separately but are not part of these tasks). Every task adds its focused test file and
must leave every P0/P1 test unchanged.

### S1. Model + profile

Scope: new `src/slogger/tools/seq/__init__.py`, `model.py`, `profile.py`; two profile fixtures +
`invalid_unknown_key.json`; `tests/test_seq_profile.py`. Exports added to `slogger.tools.__all__`.
Depends on nothing. Excludes: extraction, CLI.

Reuse: `parse_where`, `Where`, `Filters` (for `when` evaluation build a `Filters(where=...)` per
rule), `group_value` (token normalisation), `ToolError`.

Acceptance:
- `load_profile(None) is GENERIC_PROFILE`; `GENERIC_PROFILE.episode_key == ("episode_id",)`.
- `load_profile(ROBOT)` parses; `profile.rules[0].id == "bg"`; `profile.invocation.name == "api"`.
- `load_profile(INVALID)` → `ToolError` code `profile_invalid`, message mentions `bogus`.
- A profile with a `when` token `"a b=1"` → `profile_invalid`; duplicate rule ids → `profile_invalid`; `schema_version: 2` → `profile_invalid`.
- `classify(ROBOT, {"kind": "step.entry", "operation_type": "OPEN_AT_PICK_BASKET"}) == ("step", "OPEN_AT_PICK_BASKET", "gripper")`.
- `classify(ROBOT, {"kind": "observation", "message": "observation.slide_present", "slide_present": False}) == ("observation", "observation.slide_present=false", "observe")`.
- `classify(ROBOT, {"logger": "robotic_arm_service.bg", "kind": "step.entry"}) == ("background", None, "bg")` (first rule wins).
- `classify(ROBOT, {"event": "span.end", "span": "x"}) == ("span_event", None, None)`; with `SYNTH` (spans `as_steps`) → `("step", "x", "spans")` and `span.start` → `("span_event", None, None)`.
- `classify(ROBOT, {"message": "hello"}) == ("other", None, None)` (no rule; not an error).

Prompt: "Implement S1 of `docs/plans/sequence-tools-handoff.md`: create `slogger/tools/seq/model.py` with the dataclasses in the Public API section and `slogger/tools/seq/profile.py` with `Profile`, `load_profile`, `GENERIC_PROFILE`, and `classify`, validating profiles exactly as D2 specifies (compact `--where` tokens via `parse_where`, first-match precedence, span handling). Add the two example profiles and the invalid profile fixture under `tests/fixtures/logs/sequence/profiles/`, export the new names from `slogger.tools.__all__`, and add `tests/test_seq_profile.py`. No extraction, no CLI."

### S2. Episode extraction + `episodes` / `episode` commands

Scope: `tools/seq/episodes.py`, `cli.py` (two subcommands), `edge/late_and_unassigned.jsonl`,
`tests/test_seq_episodes.py`, `tests/test_cli.py` additions. Depends on S1. Excludes: paths,
match.

Reuse: `Reader` (with `order`, `after`, `complete=True`), `Filters.matches` for selection,
`parse_timestamp`, `render_table`, `write_page`-style `_meta`, `emit_error`, `usage_error`.

Acceptance (`ROBOT` profile unless stated; `CL`=cluster, `FE`=force-exit, `CA`/`CB`=cycles):
- A1 `extract_episodes(CL, profile=ROBOT)`: 4 episodes in first-seen order `r1-c1, r1-c3, r1-c4, r1-c5`; `unassigned_records == 0`.
- A2 `r1-c1`: 2 invocations (`/robotic-arm/pick/basket` complete, outcome `ok` evidence `_id` of L1895; `/robotic-arm/move/scanner/imaging` complete, outcome `ok_with_warning` evidence L1911); episode outcome `ok_with_warning`, completion `incomplete`. `r1-c3`: 1 invocation outcome `error`, episode `error`/`incomplete`; the `OPEN_AT_PICK_BASKET` token has occurrences n=1 (L8401) and n=2 (L8474).
- A3 `FE`: `r2-c9` invocation 0 outcome `aborted` (evidence L28371), `error` events L28118/L28369/L28370 retained in `events`; `OPEN_AT_PICK_BASKET` occurrence n=2 at L28135; `r2-c10` outcome `ok` invocation, episode `unknown`/`incomplete`; both `links` empty.
- A4 `CA`: 12 invocations, names in the D6 order; completion `complete`; outcome `ok` (via `require_outcome_from`); `invocations[0].duration == Duration(3177.0, "derived")` (21:54:17.086 → 21:54:20.263); an invocation whose end is missing would be `Duration(None, "unavailable")` (assert via an in-memory truncation of CA after L5552).
- A5 synthetic profile: `failure_then_recovery` → two episodes; failed one `outcome=error`, `links.triggered_recovery == "syn:recovery:from=…"`; recovery `outcome=ok`, `links.recovery_of == "syn:pick_basket:loadB:…"`. `incomplete_workflow` → `completion=incomplete`, `outcome=unknown`, `duration.kind == "unavailable"`, `elapsed_ms == 59.0`. `retry_exhaustion` → `outcome=aborted`; `CLOSE_AT_PICK_BASKET` occurrences 1..3 with `occurrence_label` `"1","2","3"` (from `attempt`). `repeated_steps_equal_ts` → occurrence labels `close-1..3`, all three `CLOSE_AT_PICK_BASKET` events kept, two per timestamp pair.
- A6 `interleaved_episodes` + `success_pick_place` with `order="time"` → 3 episodes; background records are `category=background` in **their** episode (they carry `workflow_id`), never a fourth episode.
- A7 **variant equivalence**: for each of the four `(source_derived/X.jsonl, enriched/X.spans.jsonl)` pairs, `episode_summary` after deleting `duration_evidence`, `span_events`, `boundaries` is **equal**, and `invocations[*].duration.kind == "derived"` on both sides; enriched `boundaries.start` for `r2-c9` is `"inferred"` (episode) and invocation 0 `"observed"`.
- A8 both variants supplied together (`[source_derived/FE, enriched/FE]`): `span_enrichment` exists only on span rows, so the test profile sets `variant_key="file"` — `converted_from_plain_log` on copied application records vs `span_enrichment` on proposed span rows. Because copied application records in the enriched file also carry `file=converted_from_plain_log`, the two application copies share a variant and **merge** (events double, `r2-c9` has 40 events), while the span rows form `variant="span_enrichment"` episodes; assert the `variant_collision:<key>` warnings and that no `possible_duplicate_input`-style heuristic warning exists anywhere (no content-based dedup). This test documents that variant separation is only as good as the marker the producer supplies; the corpus could later add a per-file `variant` field, which is a maintainer decision (see below).
- A9 round trip: `get_episode(CA, "CS001-1-1-1790200023515:r1-c2")` returns the 76 original records byte-equal to the file lines (minus `_id`), and `extract_episodes(records, profile=ROBOT).episodes[0]` summary equals the first summary.
- A10 edge fixture: 2 episodes, `unassigned_records == 1`, `E1.warnings` contains `non_monotonic:1`; the `timestamp: "bad"` record has `ts is None` and is present in events.
- A11 caps: `max_open_episodes=1` on `CL` → `episodes_capped True`, `total 4`, 1 returned; `max_events_per_episode=5` → `truncated True` on each episode, `len(events) == 5`.
- A12 selection vs hiding: `extract_episodes(CL, profile=ROBOT, filters=Filters(where=(Where("error_code","=","CLDJ_SLIDE_NOT_FOUND"),)))` → 3 episodes each still containing its `activity.in-progress` and `OPEN_AT_PICK_BASKET` events (lead-up retained).
- A13 CLI: `episodes CL --profile ROBOT --format json` → one object, `total 4`; `--format table` columns `key, variant, invocations, outcome, completion, first, last`; `--exclude-events` → 64; `episode CL nope --profile ROBOT` → `episode_not_found` (2); `episode CA KEY --records --profile ROBOT --format json` → 76 record lines, then `_episode`, then `_meta`; `--hide kind=api.meta` removes 12 lines and `_episode.invocations` still has 12 entries; `--after CURSOR` accepted on `episodes` only.

Prompt: "Implement S2 of `docs/plans/sequence-tools-handoff.md`: `slogger/tools/seq/episodes.py` with `extract_episodes`, `get_episode`, `episode_summary` and `EpisodesResult`, following D1 (grouping only by profile key, occurrences, no adjacency links), D2 (classification, invocation boundaries, `same_name_nearest` outcome attachment, outcome precedence, `require_outcome_from`, completion), D3 (variant handling, derived vs unavailable durations, span rows as `span_event`), D5 (reading order, warnings, caps, cursor, `_episode` control line). Add CLI subcommands `episodes` and `episode`, the `edge/late_and_unassigned.jsonl` fixture, and `tests/test_seq_episodes.py` with acceptance A1–A13. No paths or match."

### S3. Paths and fingerprints

Scope: `tools/seq/paths.py`, `cli.py` (`paths`), `tests/test_seq_paths.py`. Depends on S2.

Acceptance:
- `path_tokens(CA_ep, "app")` equals the 24-token list in D6; `path_tokens(CB_ep, "app")` equals it; `fingerprint(ROBOT, "app", tokens)` identical for A and B and for their enriched copies; `path_tokens(_, "invocation")` for A is the 12-name list.
- `fingerprint` changes when `profile_version` changes (`replace(ROBOT, profile_version="2")`) and when granularity changes; `FINGERPRINT_VERSION` is hashed (monkeypatching it changes the value).
- `success_pick_place` and `success_with_home_correction` (synthetic profile, `span`): both `outcome ok`, different fingerprints; token **sets** equal the expectations `path_span_names` sets; `workflow` is the last token in both.
- `repeated_steps_equal_ts` (`app`): 6 tokens alternating `observation.slide_present=false, CLOSE_AT_PICK_BASKET`; `collapse` merges **adjacent** repeats only, so it yields six entries of `count 1` — assert exactly that. `retry_exhaustion` (`span`): `CLOSE_AT_PICK_BASKET ×3` adjacent → one collapsed entry `count 3` with three refs, followed by `abort`, `workflow`.
- `paths(CL)` → 2 fingerprint groups: `[r1-c1]` and `[r1-c3, r1-c4, r1-c5]` with `outcomes {"error": 3}`; payload contains `profile`, `granularity`, `fingerprint_version`; no key named `anomaly`.
- `--show-background` on `success_pick_place` lists the `is_alive.tick` ref under `background_refs`; tokens unchanged.
- CLI table columns `fingerprint, episodes, outcomes, completion, tokens` (tokens cell truncated by `render_table`).

Prompt: "Implement S3 of `docs/plans/sequence-tools-handoff.md`: `slogger/tools/seq/paths.py` with `path_tokens`, `fingerprint` (sha256 over `[FINGERPRINT_VERSION, profile.name, profile.profile_version, granularity, tokens]`), `collapse` (adjacent repeats only), and `paths()` grouping episodes by fingerprint with per-group outcome/completion counts; CLI `paths`. Use the exact token lists in D6 as tests."

### S4. Matching + motifs

Scope: `tools/seq/match.py`, `tools/seq/motifs.py`, `cli.py` (`match`, `motif`), motif fixtures,
`tests/test_seq_match.py`, `tests/test_seq_motifs.py`. Depends on S3 (for `token=` pseudo-key).

Acceptance: every row of the D7 case table, plus:
- `parse_step("a=1;b~x")` → two `Where`; `parse_step("token=/x")` → pseudo-key preserved; `parse_step("a = 1")` → `ValueError` (CLI 64); `parse_step("")` → `ValueError`.
- `--mode adjacent` on cluster `r1-c3` with `--step operation_type=OPEN_AT_PICK_BASKET --step error_code=CLDJ_SLIDE_NOT_FOUND` → 1 match (candidate sequence is L8366 in-progress, L8401 OPEN, L8442 CLOSE, L8464 observation, L8474 OPEN, L8499 error, L8512 completed, L8518 outcome; L8474→L8499 are consecutive); the same in `subsequence` also 1; with `--step operation_type=CLOSE_AT_PICK_BASKET --step error_code=CLDJ_SLIDE_NOT_FOUND --mode adjacent` → 0 (L8464 and L8474 intervene).
- `--within 1s` on the force-exit pattern → 0 matches (E-200 02:42:45.202 → abort 02:43:14.396 is 29 s); `--within 1m` → 1; a pattern touching the edge fixture's `ts=None` record with `--within` → 0.
- `--all` on `repeated_steps_equal_ts` with `--step 'message=observation.slide_present' --step operation_type=CLOSE_AT_PICK_BASKET` → 3 non-overlapping matches; default → 1.
- `--follow-links` on `failure_then_recovery` with `--step error_code=CLDJ_SLIDE_NOT_FOUND --step 'span=CLOSE_AT_PICK_BASKET;attempt=2' --include-spans` → 1 match with `via == "triggered_recovery"`; without the flag → 0.
- `match --fail-if-any` exit 1 on cluster empty-slot pattern; 0 on cycle A.
- Motifs: `save_motif` writes the D7 JSON; `load_motif` round-trips `Pattern` equality; `motif save` twice → `motif_exists` unless `--force`; `motif rm` then `show` → `motif_not_found`; `match --motif empty_slot --profile SYNTH` → runs with `motif_profile_mismatch` warning; bad name `../x` → `motif_invalid`; `SLOGGER_MOTIF_DIR` honoured; default dir `./.slogger/motifs/` created lazily on save only.

Prompt: "Implement S4 of `docs/plans/sequence-tools-handoff.md`: `slogger/tools/seq/match.py` (`Position`, `Pattern`, `parse_step`, `match_episode`, `match`) with subsequence/adjacent modes, strictly increasing event consumption, first-match default and `--all` non-overlapping restarts, `--within` on parsed timestamps (None fails), per-episode scope with optional `--follow-links` via `triggered_recovery`; `slogger/tools/seq/motifs.py` for versioned JSON motif files; CLI `match` and `motif save|list|show|rm`. Assert every case in the D7 table."

### S5. `path-diff`

Scope: `tools/seq/pathdiff.py`, `cli.py`, `tests/test_seq_pathdiff.py`. Depends on S3.

Acceptance:
- `path_diff([CA, CB], profile=ROBOT, baseline_key="CS001-1-1-1790200023515:r1-c2")` → one comparison (`r1-c20`) with opcodes all `equal`; `divergence == []`.
- `path_diff(CL, baseline_key="…:r1-c1")` → three comparisons; each has ≥1 `delete` and an `insert` containing `CLDJ_SLIDE_NOT_FOUND`; each opcode carries `refs` (episode side) whose ids resolve in the file. Pin the exact opcode list in the test after the first run.
- Default representative rule on `[CA, CB, CL]`: baseline is `r1-c2` (most frequent `ok`+`complete` fingerprint, 2 episodes; cluster episodes are ineligible: `incomplete`); payload `baseline.rule == "most_frequent_ok_complete"`.
- `--baseline-file CA` with sources `CB` → equal; `--baseline KEY` not present → `baseline_not_found`; baseline with `completion=incomplete` → `baseline_ineligible`; baseline from enriched with sources source-derived and `variant_key` set → `variant_mismatch` unless `--allow-variant-mismatch`.
- `--timing` on `[CA, CB]`: `n_compared == 12`, all `kind == "derived"`; mixing `CA` (derived) with a synthetic episode (measured) → `n_skipped_kind_mismatch > 0`, no numeric comparison for those.
- `--require-same service_version` passes for A/B (`build-6.0.10` both); a synthetic baseline (`build-6.0.10-synthetic`) fails eligibility.
- No key in the payload is named `frequency`, `median`, `p50`, or `root_cause`.

Prompt: "Implement S5 of `docs/plans/sequence-tools-handoff.md`: `slogger/tools/seq/pathdiff.py` with baseline eligibility/selection per D8 (explicit key, baseline file, or most-frequent ok+complete fingerprint with earliest-first tie-break), `difflib.SequenceMatcher(autojunk=False)` alignment with record refs, optional `--timing` restricted to equal `Duration.kind`, and CLI `path-diff`. Output speaks of divergence and evidence only."

### S6. `watch-seq`

Scope: `tools/seq/watchseq.py`, `cli.py`, `tests/test_seq_watchseq.py`. Depends on S4. Placed
after offline matching is stable by design.

Reuse: `tail_once`, the reopen/inode logic and fake-clock test pattern from `tools/watch.py`
(`tests/test_tools_watch.py::FakeClock`).

Acceptance (fake clock/sleep, no real waiting):
- Equivalence 1: temp file starts empty; a fake `sleep` appends the next line of `FE` on each poll; `watch_seq(existing=False, all_matches=True, timeout=…)` with the force-exit pattern → the same single match `(key, first.source_line, last.source_line)` as offline `match --all`; `records_seen == 29`.
- Equivalence 2: `existing=True` on the complete `CL` file with the empty-slot pattern → 3 matches, exit path 0, `records_seen == 59`.
- Partial line: the abort record written without `\n` → no match until the newline arrives on a later poll.
- Rotation: rename + new file containing a full `r2-c10`-style episode → open-episode state kept, `on_reopen` once, new episode matched only if the pattern fits it.
- Timeout: quiet file, `timeout=1.0, interval=0.25` → `timed_out True`, 4 sleeps, `elapsed_ms == 1000.0`.
- Bounded state: `max_open=2`, feed three episodes' first records → `evicted == 1`; `expire_s=10` with clock jumps → `expired` increments and a late record starts a new episode with `late_record` warning.
- Stdin: two-line feed → match on the second; empty stdin → `eof_without_match` (2).
- CLI: `watch-seq FE --step … --timeout 0.2 --interval 0.05` subprocess on an empty temp file → exit 3, single `_meta`; `--count 2 --all` → 64; `--order time` → 64; `--fail-if-any` not accepted (argparse 64).

Prompt: "Implement S6 of `docs/plans/sequence-tools-handoff.md`: `slogger/tools/seq/watchseq.py` `watch_seq` reusing `tail_once` polling and `watch`'s reopen/deadline/stdin mechanics, maintaining open-episode state with per-pattern partial-match cursors, LRU eviction (`max_open`) and wall-clock expiry (`expire_s`) reported in the result, at-most-once emission per `(key, first, last)` within one process, and CLI `watch-seq` with exit 0/2/3/64/130. Add the batch-vs-streaming equivalence tests."

### S7. Documentation and status

Scope: `README.md` ("Reading logs": new commands, profiles, motif dir), `CHANGELOG.md`,
`AGENTS.md` (layout: `tools/seq/`; deferred table: sequence tools → implemented, keep P2
deferred), `docs/plans/sequence-corpus.md` §6 (replace "no commands" note with a pointer here),
`docs/plans/cli.md` (command table rows), this file (status line). Depends on S1–S6.

Acceptance: `python3 -m slogger --help` lists 19 commands; README examples run against the
fixtures with `--profile tests/fixtures/logs/sequence/profiles/robotic_arm_observed.json`;
ruff/pyrefly/pytest green.

Prompt: "Implement S7 of `docs/plans/sequence-tools-handoff.md`: update README, CHANGELOG, AGENTS.md, `docs/plans/cli.md`, `docs/plans/sequence-corpus.md`, and mark this handoff implemented."

## Acceptance tests comparing variants (cross-task)

| Id | Check | Task |
|---|---|---|
| V1 | `episode_summary` equality (minus `duration_evidence`, `span_events`, `boundaries`) for all four source/enriched pairs | S2-A7 |
| V2 | identical `fingerprint` for source vs enriched, `app` and `invocation` granularity | S3 |
| V3 | identical `match` results (compared by `source_line` attrs) for the empty-slot, force-exit, and full-cycle patterns on source vs enriched | S4 |
| V4 | `path-diff` source-vs-enriched of the same episode with `--allow-variant-mismatch` → all `equal` | S5 |
| V5 | `paths --granularity span` on enriched files yields tokens `episode, api./robotic-arm/pick/basket, retry_loop, …` and is **never** compared to `app` fingerprints (different granularity → different fingerprint inputs) | S3 |

## Decisions made and rationale

1. **Episode = multi-API story; invocation = API call; occurrence = repeated step.** Matches the
   fixtures (76 records / one key / 12 invocations) and removes the "per attempt" ambiguity.
2. **Grouping only by the profile key; no carry-forward heuristics in the tool.** The corpus
   converter already did carry-forward at fixture-build time and labelled it; a runtime tool
   guessing keys would be a second, invisible source of truth.
3. **Profile as JSON with existing `--where` tokens, first-match precedence, strict validation.**
   Reuses `parse_where`/`Filters`, keeps the core stdlib-only and domain-neutral, and fails
   loudly on typos. Not a rules engine: no `or`, no nesting, no expressions.
4. **Span rows never produce tokens at `app` granularity; application records never at `span`.**
   Guarantees source/enriched equivalence by construction and prevents double counting.
5. **Outcome precedence is the profile's rule order; default is `unknown`, never `ok`.** Absence
   of errors is not success; `require_outcome_from` lets a profile say which invocations must
   speak.
6. **Durations carry a kind (`measured`/`derived`/`unavailable`) and never mix.** Enriched
   durations are timestamp-derived and say so.
7. **Reading order is the presentation order; no re-sorting inside an episode.** Same as P0 D3;
   `--order time` is the only cross-file merge; `order_basis: "reading"` is printed.
8. **Matches are per episode; cross-episode only via explicit `triggered_recovery` links.**
9. **Representative baseline = most frequent `ok`+`complete` fingerprint, earliest-first tie.**
   Simple, deterministic, and declared in the payload; there is no median path.
10. **`watch-seq` = `match` on a growing file with bounded, reported state and no persistence.**

## Maintainer decisions still required

1. Whether the two example profiles should ship as **package data** (`slogger/profiles/*.json`)
   instead of test fixtures. This plan keeps them out of the wheel to stay domain-neutral; a
   generic `--profile-template` command could print them later.
2. Default motif directory: `./.slogger/motifs/` (project-local, versionable) vs
   `~/.config/slogger/motifs/`. Plan chooses project-local.
3. Whether `episodes --format json` should be one object (chosen, like aggregates) or JSONL rows
   (like `query`). One object keeps `truncated`/`episodes_capped` unambiguous.
4. Whether to fix the 6 pyrefly errors in `build_corpus.py` in S1 (small, unrelated) or leave
   them for a corpus maintenance PR. Plan: separate PR.
5. Whether `build_enriched_spans()` should stamp a per-record `variant: "enriched"` field on the
   copied application records so that source and enriched copies never merge when supplied
   together (see S2-A8). Plan: not required for S1–S7; the tool behaves correctly given the
   markers that exist.

## Known limits

- Original plain-text logs are absent; `source_line` references are trusted from the fixtures.
- The corpus has two full cycles, one force-exit, three empty-slot episodes: enough for exact
  expectations, not for frequencies. No task may derive rates from it.
- No temporally interleaved **observed** episodes exist; interleaving is exercised with synthetic
  files under `--order time`.
- Application-measured durations exist only in synthetic fixtures; observed/enriched are derived.
- Episode start/end in observed data are inferred from first/last record; `episode` spans are
  `inferred` on both boundaries and the plan never upgrades them.
- `watch-seq` cannot match an episode whose lead-up predates the watch start unless `--existing`.
- Python 3.10/3.13 cannot be exercised on this VM.

## Recommended implementation order

S1 → S2 → S3 → S4 → S5 → S6 → S7. S3 and S5 could be parallelised after S2, but S4 must precede
S6.

## First task to hand to Cursor

S1 (Model + profile). Its prompt is in the S1 section; it has no dependencies, adds no CLI, and
its tests fix the classification semantics that every later task relies on.
