"""Apply crosswalks to the E19 tables, producing an enriched copy.

`psm.project` emits **verbatim only** -- a cell is written when a BSEE field
carries the value literally. This module adds values that require a *mapping*,
which is a different epistemic claim and is kept separate on purpose.

Two outputs, both under ``data/processed/e19/enriched/``:

``incidents.csv``
    The same byte-exact E19 column names, with crosswalked values filled in
    where the verbatim pass left a blank. Never overwrites a verbatim value.

``provenance.csv``
    Identical shape, every cell holding ``src``, ``xw`` or empty. So any
    consumer can tell, per cell, whether a value was read or inferred -- without
    which the enriched table would quietly launder opinions as observations.

Run::

    uv run python -m psm.crosswalk
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
from collections import Counter
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
E19 = REPO / "data" / "processed" / "e19"
SPINE = REPO / "data" / "processed" / "investigations_index.csv"
XW_TYPE = REPO / "schema" / "xw_incident_type.yaml"
XW_ELEMENT = REPO / "schema" / "crosswalk.yaml"
DEFAULT_OUT = E19 / "enriched"

RE_HHMM = re.compile(r"(\d{1,2}):?(\d{2})")
RE_AB = re.compile(r"\s*([A-Z]{2,3})\s*[/ ]?\s*(\d{1,4})")


def load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def iso(s: str) -> str | None:
    for f in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime((s or "").strip(), f).date().isoformat()
        except ValueError:
            continue
    return None


def minutes(t: str) -> int | None:
    m = RE_HHMM.match((t or "").strip())
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def spine_index(spine: list[dict]) -> tuple[dict, dict]:
    """Two keys. Neither alone exceeds 82%; the union reaches 89.5%."""
    by_time: dict = {}
    by_ab: dict = {}
    for r in spine:
        d, m = iso(r["src_date_occurred"]), minutes(r["src_military_time"])
        if d and m is not None:
            by_time.setdefault((d, m), r)
        am = RE_AB.match((r["src_area_block"] or "").strip())
        if am and d:
            by_ab.setdefault((am.group(1), am.group(2).lstrip("0"), d), r)
    return by_time, by_ab


def atoms_for(row: dict, by_time: dict, by_ab: dict) -> list[str]:
    s = by_time.get((row["Date of Incident"], minutes(row["Time of Incident"])))
    if s is None:
        s = by_ab.get((row["Site"], (row["Area"] or "").lstrip("0"), row["Date of Incident"]))
    if s is None:
        return []
    return [t.strip(" -") for t in (s.get("src_accident_type") or "").split(" - ") if t.strip(" -")]


def _rank(atom: str, order: list[str]) -> int:
    """Position in the precedence order; unranked atoms sort last."""
    for i, key in enumerate(order):
        if key == "Scale":
            if "$" in atom:
                return i
        elif key == "Injury":
            if "Injury" in atom or atom.startswith(("LTA", "RW/JT")):
                return i
        elif key.lower() in atom.lower():
            return i
    return len(order)


def resolve_types(atoms: list[str], spec: dict) -> dict[str, str]:
    """Map one record's atoms onto Type A/B/C/D.

    A null in the rule file is a *decision* (see `Injury`, `Crane`), so an atom
    that maps to null must not fall through to a lower-precedence atom that
    happens to have a value -- that would reinstate exactly the guess the null
    was chosen to avoid.
    """
    outcome, scale = spec["outcome"], spec["scale"]
    mech, resp = spec["mechanism"], spec["response"]
    order = spec["precedence"]["order"]

    out: dict[str, str] = {}
    ranked = sorted((a for a in atoms if a in outcome or a in scale),
                    key=lambda a: _rank(a, order))
    if ranked:
        top = (outcome.get(ranked[0]) or scale.get(ranked[0]))
        if top.get("type_b"):
            out["Incident Type B"] = top["type_b"]
        if top.get("type_c"):
            out["Incident Type C"] = top["type_c"]

    for a in atoms:
        d = (mech.get(a) or {}).get("type_d")
        if d:
            out["Incident Type D"] = d
            break

    # A mechanism atom also establishes that something happened: a record tagged
    # only "Fire" is a loss event even with no injury or dollar figure attached.
    # An earlier version counted outcome and scale atoms only, which left every
    # mechanism-only record with no Type A at all.
    happened = any(a in outcome or a in scale or a in mech for a in atoms)
    has_resp = any(a in resp for a in atoms)
    if happened:
        out["Incident Type A"] = "Loss Event"
    elif has_resp:
        # Muster or evacuation with no outcome and no mechanism: the crew
        # responded to something that did not become a loss.
        out["Incident Type A"] = "Near Hit"
    return {k: v for k, v in out.items() if v}


PSM_COLUMN = " Failed PSM Framework Element"   # leading space is the template's


def enrich_causes(causes: list[dict], spec: dict) -> tuple[list[dict], list[dict], dict]:
    """Attach a PSM element number to each typed cause statement.

    Untyped statements and orphan subcategories are left blank on purpose --
    inferring a parent category from a subcategory is the class of quiet guess
    this repo exists to avoid, and both policies are declared in crosswalk.yaml.
    """
    from psm.causes import normalise_category, parse_statement

    aliases = {k.lower(): v for k, v in (spec.get("aliases") or {}).items()}
    cats = spec["categories"]
    cols = list(causes[0])
    out, prov = [], []
    stats = Counter()

    for row in causes:
        e = dict(row)
        p = {c: ("src" if (row.get(c) or "").strip() else "") for c in cols}
        st = parse_statement(row.get("Cause Description", "") or "")
        raw = getattr(st, "category", None)
        if not raw:
            stats["untyped_freetext"] += 1
        else:
            canon = aliases.get(normalise_category(raw))
            if canon and canon in cats:
                e[PSM_COLUMN] = str(cats[canon]["primary_element"])
                p[PSM_COLUMN] = "xw"
                stats["mapped"] += 1
                stats[f"  -> {canon}"] += 1
            else:
                stats["typed_but_unaliased"] += 1
        out.append(e)
        prov.append(p)
    return out, prov, stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    inc = load(E19 / "incidents.csv")
    spec = yaml.safe_load(XW_TYPE.read_text(encoding="utf-8"))
    by_time, by_ab = spine_index(load(SPINE))
    cols = list(inc[0])

    filled: dict[str, int] = {}
    unjoined = 0
    enriched, prov = [], []
    for row in inc:
        atoms = atoms_for(row, by_time, by_ab)
        if not atoms:
            unjoined += 1
        xw = resolve_types(atoms, spec)
        e = dict(row)
        p = {c: ("src" if (row.get(c) or "").strip() else "") for c in cols}
        for col, val in xw.items():
            if not (e.get(col) or "").strip():   # verbatim always wins
                e[col] = val
                p[col] = "xw"
                filled[col] = filled.get(col, 0) + 1
        enriched.append(e)
        prov.append(p)

    args.out.mkdir(parents=True, exist_ok=True)
    for name, data in (("incidents.csv", enriched), ("provenance.csv", prov)):
        with (args.out / name).open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(data)

    causes = load(E19 / "causes.csv")
    espec = yaml.safe_load(XW_ELEMENT.read_text(encoding="utf-8"))
    c_enriched, c_prov, c_stats = enrich_causes(causes, espec)
    ccols = list(causes[0])
    for name, data in (("causes.csv", c_enriched), ("causes_provenance.csv", c_prov)):
        with (args.out / name).open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=ccols, extrasaction="ignore")
            w.writeheader()
            w.writerows(data)

    n = len(inc)
    print(f"enriched {n} incidents -> {args.out}")
    print(f"  unjoined to spine (no atoms available): {unjoined} ({100*unjoined/n:.1f}%)")
    for col in ("Incident Type A", "Incident Type B", "Incident Type C", "Incident Type D"):
        k = filled.get(col, 0)
        print(f"  {col:20} filled by crosswalk: {k:5}/{n} = {100*k/n:5.1f}%")

    nc = len(causes)
    print(f"\nenriched {nc} cause statements")
    for k in ("mapped", "typed_but_unaliased", "untyped_freetext"):
        print(f"  {k:22} {c_stats[k]:5}/{nc} = {100*c_stats[k]/nc:5.1f}%")
    for k, v in sorted(c_stats.items()):
        if k.startswith("  ->"):
            print(f"    {k[5:]:26} {v:5}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
