# Sequence-analysis fixture corpus

Exploratory fixtures for future episode/path/motif tooling. See
[`docs/plans/sequence-corpus.md`](../../../../docs/plans/sequence-corpus.md).

## Regenerate

```bash
# Full rebuild (needs the attached plain-text service logs):
python3 tests/fixtures/logs/sequence/build_corpus.py \
  --source /path/to/2026-09-23.log \
  --source-sep24 /path/to/2026-09-24-truncated.log

# Synthetic + span-enriched variants (source_derived JSONL must already exist):
python3 tests/fixtures/logs/sequence/build_corpus.py --skip-source
```

Span proposals: [`docs/plans/sequence-spans.md`](../../../../docs/plans/sequence-spans.md).
Enriched copies (proposed spans only) live under `enriched/`; originals stay span-free.

## Inspect with P1 tools

```bash
python3 -m slogger validate tests/fixtures/logs/sequence/source_derived/pick_basket_issue_cluster.jsonl
python3 -m slogger validate tests/fixtures/logs/sequence/source_derived/full_slide_cycle_a.jsonl
python3 -m slogger query tests/fixtures/logs/sequence/source_derived/full_slide_cycle_a.jsonl \
  --where 'episode_id=CS001-1-1-1790200023515:r1-c2'
python3 -m slogger query tests/fixtures/logs/sequence/source_derived/force_exit_retry_abort.jsonl \
  --where 'error_code=E-200'
python3 -m slogger tree tests/fixtures/logs/sequence/enriched/force_exit_retry_abort.spans.jsonl --format table
python3 -m slogger tree tests/fixtures/logs/sequence/synthetic/full_slide_cycle.jsonl --format table
```

`expectations.json` is hand-authored; do not regenerate it from a matcher.
