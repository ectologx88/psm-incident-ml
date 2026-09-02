"""Field disposition ledger -- what is filled, what cannot be, and why.

Joins `schema/e19_disposition.yaml` (a claim about each column) to measured
coverage in `data/processed/e19/` (what is actually there) and emits
`docs/e19_field_ledger.md`.

The dataset is NOT dense, and that is a decision rather than an unmet goal: a
cell is filled only where the source supplies it, a versioned rule derives it,
or synth can fabricate it without asserting something false about a real
incident. Everything else stays blank with a recorded reason. So "percent
complete" is not the number worth reporting. **What fraction of the dataset is
real** is, because that is what tells a stranger what they can model on.

`--real-only` writes a parallel export with every `syn` cell blanked, for anyone
who wants to train rather than demo. It also writes an era-stratified split,
because a random split on this corpus leaks the reporting regime -- see
`splits.json`.

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
GAP_POLICIES = ("none", "fabricate", "leave_blank")
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


# The tables that carry a per-cell provenance file. recommendations/closeout
# do not; their cells count under the column's *declared* disposition, and the
# render says so.
PROV_FILES = {"incidents": "provenance.csv", "causes": "causes_provenance.csv"}
REAL_TOKENS = ("src", "xw")
FAB_TOKENS = ("syn", "llm", "key")


def measure_provenance() -> dict[str, dict[str, dict[str, int]]]:
    """Per provenanced table, per column: cells counted by what their token
    says they are -- real (src/xw), pseud, fabricated (syn/llm/key).

    This is the 2026-09-01 correction: `measure()` counts presence, and
    rendering presence as "real" reported a column of 1,147 pseudonyms as
    100.0% real. "Real" must mean what the headline defines it to mean, and
    only the token files know that per cell.
    """
    csv.field_size_limit(10 ** 9)
    out: dict[str, dict[str, dict[str, int]]] = {}
    for table, name in PROV_FILES.items():
        path = E19 / "enriched" / name
        if not path.exists():
            continue
        with path.open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        if not rows:
            continue
        cols: dict[str, dict[str, int]] = {}
        for c in rows[0]:
            tokens = [r[c] for r in rows]
            cols[c] = {
                "real": sum(tokens.count(t) for t in REAL_TOKENS),
                "pseud": tokens.count("pseud"),
                "fab": sum(tokens.count(t) for t in FAB_TOKENS),
            }
        out[table] = cols
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


def tally(spec: dict, seen: dict, prov: dict | None = None) -> dict:
    """Field counts, and the cell-level real/pseud/fabricated split.

    Where a table has a per-cell provenance file (``prov`` from
    `measure_provenance`), every count is MEASURED from the tokens: real is
    src/xw, pseud is its own class (a salted token derived from a real value
    is neither real nor invented), fabricated is syn/llm/key. Without one
    (recommendations/closeout), cells count under the column's declared
    disposition -- presence for `real` columns, the projected total for
    synthetic ones -- which is a claim, not a measurement, and the render
    says so.
    """
    counts = {d: 0 for d in ALL_DISPOSITIONS}
    real_cells = fabricated_cells = pseud_cells = total_cells = honest_blanks = 0
    targets = []
    for table, cols in seen.items():
        pcols = (prov or {}).get(table)
        for col, (n, total) in cols.items():
            entry = spec["fields"].get(table, {}).get(col)
            if not entry:
                continue
            d = entry["disposition"]
            counts[d] += 1
            total_cells += total
            pc = pcols.get(col) if pcols else None
            if pc is not None:
                real_cells += pc["real"]
                pseud_cells += pc["pseud"]
                fabricated_cells += pc["fab"]
                # `leave_blank` gaps fall through to unfilled_cells. That is
                # the whole point of the policy: the blank is the deliverable,
                # and counting it as fabrication would misreport the dataset
                # as more invented than it is.
                if d == "real" and entry.get("gap_policy") == "leave_blank":
                    honest_blanks += total - n
            elif d == "real":
                real_cells += n
                if entry.get("gap_policy") == "fabricate":
                    fabricated_cells += total - n
                elif entry.get("gap_policy") == "leave_blank":
                    honest_blanks += total - n
            else:
                fabricated_cells += total
            if entry.get("modelling_target"):
                targets.append((table, col, pc["real"] if pc else n, total))
    return {
        "counts": counts,
        "total_fields": sum(counts.values()),
        "real_cells": real_cells,
        "pseud_cells": pseud_cells,
        "fabricated_cells": fabricated_cells,
        "unfilled_cells": total_cells - real_cells - pseud_cells - fabricated_cells,
        "total_cells": total_cells,
        "targets": sorted(targets, key=lambda x: -x[2] / x[3]),
        "honest_blanks": honest_blanks,
    }


def render(spec: dict, seen: dict, stats: dict, val: dict | None = None,
           prov: dict | None = None) -> str:
    L: list[str] = []
    A = L.append
    r, f, t = stats["real_cells"], stats["fabricated_cells"], stats["total_cells"]
    p = stats.get("pseud_cells", 0)
    A("# E19 field ledger\n")
    A("Generated by `psm.ledger`. Do not edit by hand -- edit "
      "`schema/e19_disposition.yaml` and regenerate.\n")

    A("## The headline\n")
    A(f"**{100 * r / t:.0f}% of this dataset is real.** {r:,} of {t:,} cells carry "
      f"a value read from a BSEE report (`src`) or derived from one by a "
      f"versioned rule (`xw`), counted from the per-cell provenance files. "
      f"{f:,} ({100 * f / t:.0f}%) are fabricated or model-assigned "
      f"(`syn`/`llm`/`key`), and {p:,} ({100 * p / t:.1f}%) are salted "
      "pseudonyms of real names (`pseud`) -- derived from a real value but "
      "not verbatim, so counted as neither real nor fabricated.\n")
    A("This is a synthetic dataset built on a real public corpus, and that ratio "
      "is the fact a stranger most needs. It is not a completeness score: the "
      "sheet is dense by construction, so 'percent complete' would read 100% and "
      "say nothing.\n")
    hb = stats.get("honest_blanks", 0)
    if hb:
        A(f"A further **{hb:,} cells ({100 * hb / t:.0f}%) are deliberately left "
          "blank**, in the six columns where fabrication would dominate rather "
          "than supplement. Those are the cause labels and two consequence "
          "columns -- the modelling task itself. The blank is information: it "
          "says BSEE recorded nothing, and that silence is strongly non-random "
          "by era.\n")
    A("For the incidents and causes tables every count above is measured from "
      "the per-cell provenance files. The recommendations and closeout tables "
      "carry no such file; their cells count under each column's declared "
      "disposition -- a claim rather than a measurement -- and their sections "
      "below are marked accordingly.\n")

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
        pcols = (prov or {}).get(table)
        A(f"## `{table}`\n")
        if pcols:
            A("| real | filled | disposition | gap policy | column | note |")
            A("|---|---|---|---|---|---|")
        else:
            A("_No per-cell provenance file for this table: 'filled' is "
              "presence, and realness rests on the column's **declared** "
              "disposition -- a claim rather than a measurement._\n")
            A("| filled | disposition | gap policy | column | note |")
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
            pc = pcols.get(col) if pcols else None
            if pc is not None:
                if pc["pseud"]:
                    note = (f"{pc['pseud']:,} cells are `pseud` tokens "
                            "(salted pseudonyms of real names). " + note)
                A(f"| {100 * pc['real'] / total:.1f}% | {100 * n / total:.1f}% "
                  f"| {d} | {gp} | `{col}` | {note.strip()} |")
            else:
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


# BSEE's cause vocabulary is non-stationary and changed in four sharp steps, not
# a ramp (docs/findings.md, 2026-08-29). A random train/test split leaks the
# regime, and a model can score well by recognising the decade. Boundaries are
# where the vocabulary changed, not round numbers.
ERA_REGIMES = [
    ("free_prose", 1900, 2006,
     "no controlled vocabulary at all; 0% of statements map"),
    ("human_error", 2007, 2009,
     "a brief 'Human Error' era -- almost every mapped statement is that one head"),
    ("ad_hoc", 2010, 2018,
     "'Human Error' dies out before the modern six arrive; investigators write "
     "68 distinct heads of their own"),
    ("modern_six", 2019, 2100,
     "the modern vocabulary; adoption jumps 5 -> 17 occurrences between 2018 "
     "and 2019 and never falls back"),
]


def regime_for(year: int | None) -> str | None:
    if year is None:
        return None
    for name, lo, hi, _ in ERA_REGIMES:
        if lo <= year <= hi:
            return name
    return None


def real_only(out_dir: Path) -> dict:
    """Write every table with `syn` cells blanked, plus an era-stratified split.

    Blanking rather than dropping: the row still exists, so joins hold and the
    absence is visible. A consumer who wants only real values gets them; a
    consumer who silently ignored provenance gets a blank instead of a
    fabrication, which is the safer failure.
    """
    csv.field_size_limit(10 ** 9)
    out_dir.mkdir(parents=True, exist_ok=True)
    removed: dict[str, int] = {}
    for table in ORDER:
        rows = _read(table)
        if not rows:
            continue
        prov_name = {"incidents": "provenance.csv",
                     "causes": "causes_provenance.csv"}.get(table)
        prov = []
        if prov_name and (E19 / "enriched" / prov_name).exists():
            with (E19 / "enriched" / prov_name).open(encoding="utf-8", newline="") as fh:
                prov = list(csv.DictReader(fh))
        cleaned = []
        for i, r in enumerate(rows):
            d = dict(r)
            if prov and i < len(prov):
                for c in d:
                    if prov[i].get(c) == "syn" and (d[c] or "").strip():
                        d[c] = ""
                        removed[f"{table}.{c}"] = removed.get(f"{table}.{c}", 0) + 1
            cleaned.append(d)
        with (out_dir / f"{table}.csv").open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(cleaned)

    # Era split, keyed by incident, so causes/recommendations inherit it.
    inc = _read("incidents")
    split: dict[str, list[str]] = {name: [] for name, *_ in ERA_REGIMES}
    undated = []
    for r in inc:
        d = (r.get("Date of Incident") or "").strip()
        year = int(d[:4]) if len(d) >= 4 and d[:4].isdigit() else None
        g = regime_for(year)
        (split[g] if g else undated).append(r["Incident Number"])
    import json
    (out_dir / "splits.json").write_text(json.dumps({
        "why": ("BSEE's cause vocabulary changed in four sharp steps. A random "
                "split leaks the regime and rewards recognising the decade."),
        "regimes": {name: {"years": f"{lo}-{hi}", "what": what,
                           "n_incidents": len(split[name])}
                    for name, lo, hi, what in ERA_REGIMES},
        "undated_excluded": len(undated),
        "incident_ids": split,
    }, indent=2), encoding="utf-8")
    return {"removed": removed, "split": {k: len(v) for k, v in split.items()},
            "undated": len(undated)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--real-only", action="store_true",
                    help="also write data/processed/e19/real_only/ with syn cells blanked")
    args = ap.parse_args(argv)

    spec = load_disposition()
    seen = measure()
    if not seen:
        print("no E19 tables found -- run `python -m psm.project` first")
        return 1
    prov = measure_provenance()
    stats = tally(spec, seen, prov)
    val = validity(spec)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(spec, seen, stats, val, prov), encoding="utf-8")

    r, f, t = stats["real_cells"], stats["fabricated_cells"], stats["total_cells"]
    print(f"wrote {args.out}")
    print(f"  real cells        : {r:,}/{t:,} = {100 * r / t:.1f}%")
    print(f"  fabricated/model  : {f:,} = {100 * f / t:.1f}%")
    print(f"  pseudonyms        : {stats['pseud_cells']:,} = "
          f"{100 * stats['pseud_cells'] / t:.1f}%")
    hb = stats["honest_blanks"]
    print(f"  deliberately blank: {hb:,} = {100 * hb / t:.1f}%")
    checked = sum(c["checked"] for tb in val.values() for c in tb.values())
    passed = sum(c["passed"] for tb in val.values() for c in tb.values())
    print(f"  valid (shape)     : {passed:,}/{checked:,} = {100 * passed / checked:.1f}%")
    print(f"  dispositions      : {stats['counts']}")
    print(f"  modelling targets : {len(stats['targets'])}, real fraction "
          f"{min(n / tt for _, _, n, tt in stats['targets']):.1%}"
          f"-{max(n / tt for _, _, n, tt in stats['targets']):.1%}")
    if args.real_only:
        res = real_only(E19 / "real_only")
        print(f"\n  real-only export -> {E19 / 'real_only'}")
        print(f"    syn cells blanked: {sum(res['removed'].values()):,}")
        print(f"    era split        : {res['split']}  (undated excluded: {res['undated']})")

    missing, orphan = reconcile(spec, seen)
    for m in missing:
        print(f"  UNDECLARED: {m}")
    for o_ in orphan:
        print(f"  ORPHAN:     {o_}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
