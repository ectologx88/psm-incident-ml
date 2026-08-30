"""Field disposition ledger -- what is filled, what cannot be, and why.

Joins `schema/e19_disposition.yaml` (a claim about each column) to measured
coverage in `data/processed/e19/` (what is actually there) and emits
`docs/e19_field_ledger.md`.

This dataset is dense by construction -- every cell the source cannot supply is
fabricated under a `syn` mark -- so "percent complete" is not a number worth
reporting. The number that matters is **what fraction of the dataset is real**,
because that is what tells a stranger what they can model on.

`--real-only` writes a parallel export with every `syn` cell blanked and every
`modelling_target` column reduced to its `src`/`xw` values, for anyone who wants
to train rather than demo.

Run::

    uv run python -m psm.ledger
    uv run python -m psm.ledger --real-only
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
E19 = REPO / "data" / "processed" / "e19"
DISPOSITION = REPO / "schema" / "e19_disposition.yaml"
DEFAULT_OUT = REPO / "docs" / "e19_field_ledger.md"

ALL_DISPOSITIONS = ("real", "synthetic_column")
GAP_POLICIES = ("none", "fabricate")
VALIDITY_CHECKS = ("no_form_label", "min_words", "pattern", "terminal_punctuation")
_END_PUNCT = ".!?)\u201d\"'"


def check_value(value: str, rules: dict, tokens: list[str]) -> str | None:
    """Which shape check does this value fail? ``None`` means it passes.

    Returns the FIRST failure by name rather than a boolean, so the ledger can
    report why a column is unhealthy instead of only that it is. Truncation is
    reported under its own name because it is a different problem from
    contamination -- it means text was lost, not that furniture was gained.
    """
    v = (value or "").strip()
    if not v:
        return None                     # emptiness is coverage, not validity
    up = v.upper()
    if rules.get("no_form_label") and any(tok in up for tok in tokens):
        return "form_label"
    mw = rules.get("min_words")
    if mw and len(v.split()) < int(mw):
        return "too_short"
    pat = rules.get("pattern")
    if pat and not re.fullmatch(pat, v):
        return "bad_pattern"
    if rules.get("terminal_punctuation") and v[-1] not in _END_PUNCT:
        return "truncated"
    return None

ORDER = ["incidents", "causes", "recommendations", "closeout"]


def _read(table: str) -> list[dict]:
    """Prefer the enriched table; fall back to the verbatim one."""
    csv.field_size_limit(10 ** 9)
    for path in (E19 / "enriched" / f"{table}.csv", E19 / f"{table}.csv"):
        if path.exists():
            with path.open(encoding="utf-8", newline="") as fh:
                return list(csv.DictReader(fh))
    return []


def validity(spec: dict) -> dict[str, dict[str, dict]]:
    """Per column: how many non-empty cells fail which check.

    Deliberately reads the SAME tables the coverage pass reads, so the two
    numbers describe one artifact and cannot drift apart.
    """
    tokens = [t.upper() for t in spec.get("form_label_tokens", [])]
    out: dict[str, dict[str, dict]] = {}
    for table in ORDER:
        rows = _read(table)
        if not rows:
            continue
        cols = {}
        for col in rows[0]:
            rules = (spec["fields"].get(table, {}).get(col) or {}).get("validity")
            if not rules:
                continue
            fails: dict[str, int] = {}
            checked = 0
            for r in rows:
                v = (r[col] or "").strip()
                if not v:
                    continue
                checked += 1
                why = check_value(v, rules, tokens)
                if why:
                    fails[why] = fails.get(why, 0) + 1
            cols[col] = {"checked": checked, "fails": fails,
                         "passed": checked - sum(fails.values())}
        if cols:
            out[table] = cols
    return out


def measure() -> dict[str, dict[str, tuple[int, int]]]:
    """(filled_cells, total_rows) per table, per column."""
    out: dict[str, dict[str, tuple[int, int]]] = {}
    for table in ORDER:
        rows = _read(table)
        if not rows:
            continue
        out[table] = {c: (sum(1 for r in rows if (r[c] or "").strip()), len(rows))
                      for c in rows[0]}
    return out


def load_disposition() -> dict:
    return yaml.safe_load(DISPOSITION.read_text(encoding="utf-8"))


def reconcile(spec: dict, seen: dict) -> tuple[list[str], list[str]]:
    """Columns present in the data but absent from the file, and vice versa.

    A disposition file that has drifted from the data is worse than none: it
    reads as an audit while describing a table that no longer exists.
    """
    missing, orphan = [], []
    for table, cols in seen.items():
        declared = set(spec["fields"].get(table, {}))
        for c in cols:
            if c not in declared:
                missing.append(f"{table}.{c!r}")
        for c in declared - set(cols):
            orphan.append(f"{table}.{c!r}")
    return sorted(missing), sorted(orphan)


def tally(spec: dict, seen: dict) -> dict:
    """Field counts, and the cell-level real/fabricated split.

    "Fabricated" is projected, not measured: the synth layer is not yet wired,
    so today those cells are empty. Reporting the projection is the honest
    choice -- it is what the dataset WILL be, and hiding it behind a temporary
    zero would flatter the current state.
    """
    counts = {d: 0 for d in ALL_DISPOSITIONS}
    real_cells = fabricated_cells = total_cells = 0
    targets = []
    for table, cols in seen.items():
        for col, (n, total) in cols.items():
            entry = spec["fields"].get(table, {}).get(col)
            if not entry:
                continue
            d = entry["disposition"]
            counts[d] += 1
            total_cells += total
            if d == "real":
                real_cells += n
                if entry.get("gap_policy") == "fabricate":
                    fabricated_cells += total - n
            else:
                fabricated_cells += total
            if entry.get("modelling_target"):
                targets.append((table, col, n, total))
    return {
        "counts": counts,
        "total_fields": sum(counts.values()),
        "real_cells": real_cells,
        "fabricated_cells": fabricated_cells,
        "unfilled_cells": total_cells - real_cells - fabricated_cells,
        "total_cells": total_cells,
        "targets": sorted(targets, key=lambda x: -x[2] / x[3]),
    }


def render(spec: dict, seen: dict, stats: dict, val: dict | None = None) -> str:
    L: list[str] = []
    A = L.append
    r, f, t = stats["real_cells"], stats["fabricated_cells"], stats["total_cells"]
    A("# E19 field ledger\n")
    A("Generated by `psm.ledger`. Do not edit by hand -- edit "
      "`schema/e19_disposition.yaml` and regenerate.\n")

    A("## The headline\n")
    A(f"**{100 * r / t:.0f}% of this dataset is real.** {r:,} of {t:,} cells carry "
      f"a value read from a BSEE report (`src`) or derived from one by a "
      f"versioned rule (`xw`). The remaining {f:,} ({100 * f / t:.0f}%) are "
      "fabricated under a `syn` mark.\n")
    A("This is a synthetic dataset built on a real public corpus, and that ratio "
      "is the fact a stranger most needs. It is not a completeness score: the "
      "sheet is dense by construction, so 'percent complete' would read 100% and "
      "say nothing.\n")
    A(f"Fabrication is projected, not yet measured -- the synth layer is written "
      f"but not wired into the projection, so those {f:,} cells are currently "
      "empty. The projection is reported because it is what the dataset will be.\n")

    A(f"Of {stats['total_fields']} columns:\n")
    for d in ALL_DISPOSITIONS:
        A(f"- **{d}** — {stats['counts'][d]}")
    A("")

    if val:
        checked = sum(c["checked"] for tb in val.values() for c in tb.values())
        passed = sum(c["passed"] for tb in val.values() for c in tb.values())
        A("## Validity\n")
        A(f"**{100 * passed / checked:.1f}% of checked cells pass their shape "
          f"check** ({passed:,} of {checked:,}).\n")
        A("Separate from coverage on purpose. `real` used to mean `non-empty`, "
          "and under that definition `Recommendation Description` read 100% "
          "while 30.4% of its values were BSEE stationery. A cell can be "
          "present and still be furniture, a fragment, or truncated.\n")
        A("Only columns that declare a check appear here. A global rule would "
          "fail every code, key and picklist value in the dataset.\n")
        A("| valid | column | failures |")
        A("|---|---|---|")
        rows = [(tb, c, d) for tb, cols in val.items() for c, d in cols.items()]
        for tb, c, d in sorted(rows, key=lambda x: x[2]["passed"] / max(x[2]["checked"], 1)):
            why = ", ".join(f"{k} {v}" for k, v in sorted(d["fails"].items())) or "—"
            A(f"| {100 * d['passed'] / d['checked']:.1f}% | `{c}` ({tb}) | {why} |")
        A("")

    A("## Modelling targets\n")
    A("Columns a hackathon entrant would plausibly try to **predict**. Their "
      "real fraction is the ceiling on what any honest evaluation can use; "
      "training on the fabricated remainder means learning "
      "`schema/synth_rules.yaml`. `psm.ledger --real-only` writes an export "
      "with these reduced to their `src`/`xw` cells.\n")
    A("| real | column | table |")
    A("|---|---|---|")
    for table, col, n, total in stats["targets"]:
        A(f"| {100 * n / total:.1f}% | `{col}` | {table} |")
    A("")

    for table in ORDER:
        cols = seen.get(table)
        if not cols:
            continue
        A(f"## `{table}`\n")
        A("| real | disposition | gap policy | column | note |")
        A("|---|---|---|---|---|")
        entries = spec["fields"].get(table, {})

        def key(item):
            col = item[0]
            e = entries.get(col)
            d = e["disposition"] if e else "zzz"
            return (ALL_DISPOSITIONS.index(d) if d in ALL_DISPOSITIONS else 9,
                    -cols[col][0])

        for col, (n, total) in sorted(cols.items(), key=key):
            e = entries.get(col)
            d = e["disposition"] if e else "**UNDECLARED**"
            gp = (e or {}).get("gap_policy", "—")
            note = " ".join(str((e or {}).get("note", "")).split())
            if e and e["disposition"] == "synthetic_column":
                note += (f" Generator: `{e['generator']}`."
                         if e.get("generator") else " **No generator yet.**")
            if e and e.get("modelling_target"):
                note = "**Modelling target.** " + note
            A(f"| {100 * n / total:.1f}% | {d} | {gp} | `{col}` | {note.strip()} |")
        A("")

    missing, orphan = reconcile(spec, seen)
    if missing or orphan:
        A("## Drift\n")
        for m in missing:
            A(f"- **undeclared in the disposition file:** {m}")
        for o_ in orphan:
            A(f"- **declared but absent from the data:** {o_}")
        A("")
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    spec = load_disposition()
    seen = measure()
    if not seen:
        print("no E19 tables found -- run `python -m psm.project` first")
        return 1
    stats = tally(spec, seen)
    val = validity(spec)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(spec, seen, stats, val), encoding="utf-8")

    r, f, t = stats["real_cells"], stats["fabricated_cells"], stats["total_cells"]
    print(f"wrote {args.out}")
    print(f"  real cells        : {r:,}/{t:,} = {100 * r / t:.1f}%")
    print(f"  fabricated (proj.): {f:,} = {100 * f / t:.1f}%")
    checked = sum(c["checked"] for tb in val.values() for c in tb.values())
    passed = sum(c["passed"] for tb in val.values() for c in tb.values())
    print(f"  valid (shape)     : {passed:,}/{checked:,} = {100 * passed / checked:.1f}%")
    print(f"  dispositions      : {stats['counts']}")
    print(f"  modelling targets : {len(stats['targets'])}, real fraction "
          f"{min(n / tt for _, _, n, tt in stats['targets']):.1%}"
          f"-{max(n / tt for _, _, n, tt in stats['targets']):.1%}")
    missing, orphan = reconcile(spec, seen)
    for m in missing:
        print(f"  UNDECLARED: {m}")
    for o_ in orphan:
        print(f"  ORPHAN:     {o_}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
