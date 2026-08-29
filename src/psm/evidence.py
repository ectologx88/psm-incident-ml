"""Build the E19 completion evidence pack.

Session 0 of docs/superpowers/plans/2026-08-29-e19-completion-walkthrough.md.

The walkthrough's operating rule is that a human must never be asked a question
that could have been answered by looking. This module does the looking: for each
field group still unfilled, it pulls the candidate source, its coverage, and its
distinct values or distribution, and writes them to ``docs/e19_evidence_pack.md``.

Run::

    uv run python -m psm.evidence
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import glob
import json
import re
from collections import Counter
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
E19 = REPO / "data" / "processed" / "e19"
SPINE = REPO / "data" / "processed" / "investigations_index.csv"
INTERIM = REPO / "data" / "interim"
LABELS = REPO / "schema" / "e19_labels.yaml"
CROSSWALK = REPO / "schema" / "crosswalk.yaml"
OUT = REPO / "docs" / "e19_evidence_pack.md"

HEAD_MIN_COUNT = 15  # an ACCIDENT_TYPE atom below this is tail, not vocabulary
RE_AB = re.compile(r"\s*([A-Z]{2,3})\s*[/ ]?\s*(\d{1,4})")
RE_HHMM = re.compile(r"(\d{1,2}):?(\d{2})")
RE_MONEY = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")


def rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
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


def area_block(s: str) -> tuple[str | None, str | None]:
    m = RE_AB.match((s or "").strip())
    return (m.group(1), m.group(2).lstrip("0")) if m else (None, None)


def money(s: str) -> float | None:
    m = RE_MONEY.search(s or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def pct(k: int, n: int) -> str:
    return f"{100 * k / n:.1f}%" if n else "-"


def session1(inc, spine, interim) -> list[str]:
    """Incident Type A-D: what BSEE publishes, and how far it reaches."""
    by_time, by_ab = {}, {}
    for r in spine:
        d, m = iso(r["src_date_occurred"]), minutes(r["src_military_time"])
        if d and m is not None:
            by_time.setdefault((d, m), []).append(r)
        a, b = area_block(r["src_area_block"])
        if a and d:
            by_ab.setdefault((a, b, d), []).append(r)

    joined = 0
    for r in inc:
        k1 = (r["Date of Incident"], minutes(r["Time of Incident"]))
        k2 = (r["Site"], (r["Area"] or "").lstrip("0"), r["Date of Incident"])
        if k1 in by_time or k2 in by_ab:
            joined += 1

    atoms, per_row = Counter(), []
    for r in spine:
        a = [t.strip(" -") for t in (r["src_accident_type"] or "").split(" - ") if t.strip(" -")]
        per_row.append(a)
        atoms.update(a)
    head = {k for k, v in atoms.items() if v >= HEAD_MIN_COUNT}
    reach = sum(1 for a in per_row if a and any(x in head for x in a))

    cb = Counter()
    n_cb = 0
    for d in interim:
        marks = d.get("src_checkboxes_page0") or []
        if marks:
            n_cb += 1
        cb.update(str(m).strip().upper()[:28] for m in marks)

    L = ["## Session 1 — Incident Type A/B/C/D", "",
         f"Spine joins to **{joined}/{len(inc)} = {pct(joined, len(inc))}** of incidents "
         "(union of `(date, minutes)` and `(area, block, date)`; neither key alone exceeds 82%).", "",
         f"`ACCIDENT_TYPE` has **{len(atoms)} distinct atoms**, but only **{len(head)}** occur "
         f"{HEAD_MIN_COUNT}+ times. Mapping those {len(head)} reaches "
         f"**{pct(reach, len(per_row))}** of spine rows.", "",
         "### The vocabulary to map", "", "| n | ACCIDENT_TYPE atom |", "|---|---|"]
    L += [f"| {v} | `{k}` |" for k, v in atoms.most_common() if v >= HEAD_MIN_COUNT]

    tailc = Counter({k: v for k, v in atoms.items() if v < HEAD_MIN_COUNT})
    groups: dict[str, list[str]] = {}
    for k in tailc:
        groups.setdefault(re.sub(r"[^a-z]", "", k.lower()), []).append(k)
    dupes = [v for v in groups.values() if len(v) > 1]
    L += ["", f"### The tail — {len(tailc)} atoms, free text not vocabulary", "",
          f"Collapses to {len(groups)} after case/space normalisation. Pure case variants:", ""]
    L += [f"- {v}" for v in dupes[:10]]
    L += ["", "**Decision needed:** `ACCIDENT_TYPE` is multi-valued "
          "(`Fire - Injury - Required Evacuation`) but E19 Type C and D are single-valued. "
          "Which atom wins when a record carries several?", ""]

    L += [f"### Fallback for unjoined records — `src_checkboxes_page0` ({n_cb} records)", "",
          "**Do not use `bsee_type_checkboxes` for this.** That field holds the form's printed "
          "label list, so `FATALITY` appears in 89% of records regardless of what happened. "
          "The marks below are positionally detected selections.", "",
          "| n | detected mark |", "|---|---|"]
    L += [f"| {v} | `{k}` |" for k, v in cb.most_common(20)]
    return L


def session2(labels, crosswalk) -> list[str]:
    """PSM element re-base: the template's numbering vs the crosswalk's."""
    elements: list[str] = []
    for v in labels.get("vocabularies", []):
        if v.get("name") == "Failed PSM Framework Element":
            continue
        vals = v.get("values") or []
        if len(vals) == 20 and any(str(x)[0].isdigit() for x in vals):
            elements = [str(x) for x in vals]
            break
    L = ["## Session 2 — Re-base the PSM element crosswalk", "",
         "`schema/crosswalk.yaml` is keyed to a different numbering than the template. "
         "It was written deliberately blind (energyinst.org returns 403), so the reasoning "
         "is sound and only the anchoring is wrong.", "",
         "### The template's elements (authoritative)", ""]
    L += [f"{e}" for e in elements] or ["(numbered element list not found in e19_labels.yaml)"]
    L += ["", "### Current crosswalk, to confirm or correct", "",
          "| BSEE category | current element | confidence | current note says |", "|---|---|---|---|"]
    for cat, spec in (crosswalk.get("categories") or {}).items():
        note = " ".join(str(spec.get("note", "")).split())[:80]
        L.append(f"| {cat} | {spec.get('primary_element')} "
                 f"{'(+' + str(spec.get('also_touches')) + ')' if spec.get('also_touches') else ''} "
                 f"| {spec.get('confidence')} | {note} |")
    return L


def session3(causes, labels) -> list[str]:
    """Cause qualifiers, induced across every extracted statement."""
    from psm.causes import normalise_category, parse_statement

    raw, cats, subs, untyped = Counter(), Counter(), Counter(), 0
    for r in causes:
        st = parse_statement(r.get("Cause Description", "") or "")
        cat = getattr(st, "category", None)
        sub = getattr(st, "subcategory", None)
        if cat:
            raw[cat] += 1
            norm = normalise_category(cat)
            cats[norm] += 1
            if sub:
                subs[(norm, sub)] += 1
        else:
            untyped += 1
    n = len(causes)

    # Case folding merges HUMAN ERROR with Human Error but not "human error" with
    # "human performance error", nor singular with plural. Whether those are one
    # category is a judgement call about BSEE's usage, not a string problem.
    names = sorted(cats)
    near: list[tuple[str, str, int, int]] = []
    for i, a in enumerate(names):
        ta = {w.rstrip("s") for w in a.split()}
        for b in names[i + 1:]:
            tb = {w.rstrip("s") for w in b.split()}
            # Substring and plural catch "management system"/"management systems".
            # Token overlap is needed for "human error" vs "human performance
            # error", where neither contains the other -- and that pair is the
            # single largest open question in the vocabulary.
            jaccard = len(ta & tb) / len(ta | tb) if (ta | tb) else 0
            if a.rstrip("s") == b.rstrip("s") or a in b or b in a or jaccard >= 0.5:
                near.append((a, b, cats[a], cats[b]))

    # A "category" of six words that reads as a sentence fragment is furniture the
    # parser accepted, not vocabulary. The furniture filter was tuned on 194 texts;
    # this is the first look at it across 3,462.
    suspect = [(k, v) for k, v in cats.items() if len(k.split()) >= 4]

    L = ["## Session 3 — Cause qualifiers", "",
         f"Induced across **all {n} extracted cause statements** — the earlier figure in "
         "`findings.md` came from 82 statements in a 63-report sample.", "",
         f"- typed: **{n - untyped}** ({pct(n - untyped, n)})",
         f"- untyped free prose: **{untyped}** ({pct(untyped, n)}) — reaches nothing in this session",
         "",
         f"**The typed share fell to {pct(n - untyped, n)} at full scale**, against the "
         "`<= 28%` ceiling recorded in `findings.md` from a 100-report sample.", "",
         f"{len(raw)} raw spellings collapse to {len(cats)} after case folding.", "",
         "### Categories, case-folded", "", "| n | category |", "|---|---|"]
    L += [f"| {v} | {k} |" for k, v in cats.most_common(25)]

    if near:
        L += ["", "### Still separate after folding — same category or not?", "",
              "**A judgement call, and the highest-leverage question in this session.** "
              "BSEE authors used both forms; whether they mean one thing is domain knowledge.", "",
              "| A | n | B | n |", "|---|---|---|---|"]
        # Rank by the SMALLER side. Sorting by the sum buries the real vocabulary
        # splits under "equipment failure" vs "equipment failure <subcategory>",
        # which are parse artifacts where the two levels failed to separate.
        L += [f"| {a} | {ca} | {b} | {cb} |" for a, b, ca, cb in
              sorted(near, key=lambda t: -min(t[2], t[3]))[:12]]

    if suspect:
        L += ["", f"### Suspected furniture — {len(suspect)} 'categories' of 4+ words", "",
              "Sentence fragments the parser accepted as category heads. The furniture filter "
              "in `causes.py` was tuned on 194 texts; these are what it misses at 3,462.", "",
              "| n | accepted as a category |", "|---|---|"]
        L += [f"| {v} | {k} |" for k, v in sorted(suspect, key=lambda t: -t[1])[:12]]
    L += ["", f"### Subcategories — {len(subs)} distinct pairs", "",
          "Whether level 2 is a closed vocabulary was flagged unverified in `findings.md`. "
          "This is the first look at it at full scale.", "",
          "| n | category | subcategory |", "|---|---|---|"]
    L += [f"| {v} | {c} | {s} |" for (c, s), v in subs.most_common(30)]

    for name in ("Cause Type", "Risk Management Cause", "Human Factors"):
        for v in labels.get("vocabularies", []):
            if v.get("name") == name:
                L += ["", f"### E19 `{name}` picklist — map onto this", ""]
                L += [f"- {x}" for x in v["values"]]
    return L


def session4(inc, side, interim) -> list[str]:
    """Consequence tiers: the real distributions to set A-E boundaries against."""
    amounts = sorted(x for x in (money(r.get("bsee_property_damaged", "")) for r in side)
                     if x is not None)
    buckets = [(0, 1), (1, 25_000), (25_000, 100_000), (100_000, 1_000_000),
               (1_000_000, 10_000_000), (10_000_000, float("inf"))]
    L = ["## Session 4 — Consequence tiers", "",
         "### Financial — `ESTIMATED AMOUNT (TOTAL)` parsed from field 21", "",
         f"Parsed on **{len(amounts)}/{len(side)}** records ({pct(len(amounts), len(side))}).", "",
         "| range | n |", "|---|---|"]
    for lo, hi in buckets:
        k = sum(1 for a in amounts if lo <= a < hi)
        label = f"${lo:,.0f}–${hi:,.0f}" if hi != float("inf") else f"over ${lo:,.0f}"
        L.append(f"| {label} | {k} |")
    if amounts:
        L += ["", f"median ${amounts[len(amounts)//2]:,.0f} · "
                  f"p90 ${amounts[int(0.9*(len(amounts)-1))]:,.0f} · max ${amounts[-1]:,.0f}", ""]

    marks = Counter()
    for d in interim:
        for m in (d.get("src_checkboxes_page0") or []):
            marks[str(m).strip().upper()[:28]] += 1
    hs = ["FATALITY", "LTA (>3", "LTA (1-3", "RW/JT", "OTHER INJURY", "REQUIRED"]
    L += ["### Health & Safety — detected outcome marks", "", "| n | mark |", "|---|---|"]
    L += [f"| {v} | `{k}` |" for k, v in marks.most_common() if any(h in k for h in hs)]

    poll = sum(1 for k, v in marks.items() if "POLLUTION" in k for _ in range(v))
    L += ["", "### Environment", "",
          f"`POLLUTION` mark detected on **{poll}** records. Spill volumes appear in field 17 "
          "narrative prose (e.g. *17,098 gallons of Mono Ethylene Glycol*) but are not a "
          "structured field — extracting them is a separate NLP pass.", "",
          "> **Methodological note for the rule file.** These distributions describe the "
          "**actual** outcome. E19 Section 3 asks for the **worst reasonably expected** "
          "outcome. Deriving potential from actual will systematically under-rate near "
          "misses — the class E19 exists to catch.", ""]
    return L


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)

    inc = rows(E19 / "incidents.csv")
    causes = rows(E19 / "causes.csv")
    side = rows(E19 / "bsee_unmapped.csv")
    spine = rows(SPINE)
    interim = [json.loads(Path(p).read_text(encoding="utf-8"))
               for p in glob.glob(str(INTERIM / "*.json"))]
    labels = yaml.safe_load(LABELS.read_text(encoding="utf-8"))
    crosswalk = yaml.safe_load(CROSSWALK.read_text(encoding="utf-8"))

    doc = ["# E19 completion — evidence pack", "",
           "*Generated by `psm.evidence` (Session 0). Do not edit by hand — re-run it.*", "",
           f"Corpus: **{len(inc)} incidents**, **{len(causes)} cause statements**, "
           f"**{len(spine)} spine rows**, **{len(interim)} extracted documents**.", "",
           "Every table below exists so that no question in Sessions 1–4 has to be asked "
           "when it could have been looked up.", "", "---", ""]
    doc += session1(inc, spine, interim) + ["", "---", ""]
    doc += session2(labels, crosswalk) + ["", "---", ""]
    doc += session3(causes, labels) + ["", "---", ""]
    doc += session4(inc, side, interim)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(doc) + "\n", encoding="utf-8")
    print(f"wrote {args.out} ({len(doc)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
