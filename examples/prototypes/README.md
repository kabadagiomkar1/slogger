# Throwaway TUI prototypes

The current deliverable is the **native terminal prototype**, based on the
selected layout A. Run it directly in your terminal from the repository root:

```sh
uv run --with-editable . examples/prototypes/native_tui.py
```

With no arguments it creates a small synthetic demo. Append JSONL file paths to
browse your own files in supplied order. See [native usage, measurements, and
limits](NATIVE.md).

The revised native prototype includes compact console rows, a narrower colored
JSON inspector, live search, selectable completions, clickable field aggregates,
tree folding, and presentation settings. Its demo has 54 different ASCII-message
records across checkout, billing, and shipping investigations.

## Earlier browser layout study

The following sketch is retained as historical evidence for the layout choice.
It is not the native prototype.

Question: how should browsing, trace navigation, record inspection, searching,
filtering, aggregates, and settings fit together?

Run from the repository root, with no dependencies:

```sh
python3 examples/prototypes/serve_tui.py
```

Open <http://127.0.0.1:8765/tui-prototype.html?variant=A>.
The HTML also opens directly in a browser without the server.

- A: console stream with a right JSON inspector and optional aggregate below.
- B: persistent source/trace navigation alongside the stream and inspector.
- C: wide console with a bottom JSON/aggregate dock.

Use the floating arrows to compare layouts without losing the investigation.
The six buttons above the terminal demonstrate common workflows. Click JSON
keys or custom fields in console rows to aggregate them. A detached aggregate
retains a separate editable filter. Search respects the main filter. Tree
ancestors remain visible as context, and missing parents are explicit.

Keyboard shortcuts are shown along the terminal footer. A focused record pane
uses arrow keys for navigation and horizontal scrolling; left/right arrows
outside inputs and that pane switch layouts. `/` focuses search, `f` focuses
the query, `n`/`N` navigate matches, `t` switches tree mode, `a` toggles the
aggregate, and `,` opens settings. Backspace returns to a previous selected
record if it remains in the current filter.

## Limits

This is a browser sketch of a future terminal interface. It uses 35 synthetic
records across three named sources. It does not read actual log files or use
IXR. The mock parser supports comparisons, string contains/starts_with,
exists/missing, and AND/OR with parentheses; it is not a final query syntax.
Autocomplete covers fields, operators, values, boolean connectors, presence
functions, and groups. Use up/down to select, Tab to complete, and Enter to
accept a selected suggestion or apply the query. Value suggestions come from
the fixtures. Mixed/object aggregates are
illustrative group counts, not a backend compatibility guarantee.

Preferences and simulated saved defaults live only in memory. Pane sizes,
themes, wrapping, timestamp format, and search preferences can be explored.
There is no real global settings file, live following, scalable ingestion,
search-history interface, or source refresh. The comparison switcher is only
present in this throwaway artifact, which is excluded from production packaging.

The user selected layout A with a toggleable JSON inspector. The prototype
remains throwaway; no production TUI has been implemented. Primary source branch:
`codex/tui-visual-prototype`. See the
[prototype issue](../../.scratch/tui-consumers/issues/01-visual-prototype.md).
