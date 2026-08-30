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
import json
import re
from collections import Counter
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
E19 = REPO / "data" / "processed" / "e19"
SPINE = REPO / "data" / "processed" / "investigations_index.csv"
XW_TYPE = REPO / "schema" / "xw_incident_type.yaml"
XW_ELEMENT = REPO / "schema" / "crosswalk.yaml"
XW_QUAL = REPO / "schema" / "xw_cause_qualifiers.yaml"
XW_TIERS = REPO / "schema" / "xw_consequence_tiers.yaml"
XW_OUTCOME = REPO / "schema" / "xw_outcome.yaml"
DISPOSITION = REPO / "schema" / "e19_disposition.yaml"
INTERIM = REPO / "data" / "interim"
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
SEV = "ABCDE"
RE_MONEY = re.compile(r"\$\s*([\d,]+)")
CREWED_MARKS = ("DRILLING", "WORKOVER", "COMPLETION")


def _band(value: float, bands: list[dict], key: str) -> object:
    for b in bands:
        if key == "at_least" and value >= b["at_least"]:
            return b.get("likelihood", b.get("value"))
        if key == "under" and (b["under"] is None or value < b["under"]):
            return b["value"]
    return None


def section3(atoms: list[str], marks: list[str], damage: float | None, tiers: dict) -> dict:
    """E19 Section 3 from hazard energy, corpus-measured likelihood and cost.

    Consequence answers what the event COULD have done, not what it did --
    see the header of schema/xw_consequence_tiers.yaml for why that matters.
    """
    out: dict[str, str] = {}
    energy = tiers["hazard_energy"]
    present = [a for a in atoms if a in energy]

    if present:
        worst = max(energy[a] for a in present)
        crewed = any(any(c in m.upper() for c in CREWED_MARKS) for m in marks)
        if crewed and worst < "E":
            worst = SEV[SEV.index(worst) + 1]
        floors = [tiers["actual_outcome_floor"][a] for a in atoms
                  if a in tiers["actual_outcome_floor"]]
        consequence = max([worst] + floors)

        out["Health & Safety  - Consequence"] = consequence

        # Likelihood only where a rate could be estimated in the window where the
        # relevant codes were actually in use. A mechanism whose code was retired
        # before the outcome codes existed (Blowout, last used 2013) has no
        # estimable rate, and borrowing one from the pooled series would reinstate
        # the era artifact this file exists to remove. Consequence still applies;
        # score and classification do not, because they depend on likelihood.
        rates = tiers["likelihood"]["observed_rates"]
        estimable = [rates[a]["rate"] for a in present if a in rates]
        if estimable:
            lik = _band(max(estimable), tiers["likelihood"]["bands"], "at_least")
            score = (SEV.index(consequence) + 1) * int(lik)
            cls = _band(score, tiers["classification_bands"], "at_least")
            out["Health & Safety - Likelihood"] = str(lik)
            out["Health & Safety - Risk Score"] = str(score)
            out["Health & Safety Incident - Classification"] = cls
            out["Incident Classification"] = cls
            out["Incident Classificatioin"] = cls

    if "Pollution" in atoms:
        out["Environment & Reputation  - Consequence"] = energy["Pollution"]
    if damage is not None:
        out["Financial Cost & Business Interruption  - Consequence"] = _band(
            damage, tiers["financial_consequence"]["bands"], "under")
    return out


def _first_pattern(text: str, patterns: list[dict]) -> dict | None:
    """First match wins, in listed order -- so sharper rules are listed first."""
    low = (text or "").lower()
    for p in patterns:
        if p["match"].lower() in low:
            return p
    return None


def enrich_causes(causes: list[dict], spec: dict, qual: dict) -> tuple[list[dict], list[dict], dict]:
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
                # `also_touches` has existed in crosswalk.yaml since v1 and was
                # emitted by nothing -- the only reference in src/ was a print in
                # evidence.py. It is not hedging: Equipment Failure -> 15
                # (inspection and maintenance) vs 11 (standards and practices) is
                # the difference between a maintenance finding not actioned and a
                # design that was wrong from the day it was fitted, and the cause
                # text usually says which.
                #
                # It goes to a SIDECAR, not into the E19 cell. The template's
                # `Failed PSM Framework Element` is one picklist value per cause;
                # multi-valuing it would break the byte-exact projection guarantee
                # the whole layer exists to provide. Same pattern as
                # causes_confidence.csv and causes_source_field.csv.
                e["_xw_secondary_elements"] = ";".join(
                    str(x) for x in (cats[canon].get("also_touches") or []))
            else:
                stats["typed_but_unaliased"] += 1

            sub = getattr(st, "subcategory", None)
            if sub:
                rmc = _first_pattern(sub, qual["risk_management_cause"]["patterns"])
                if rmc:
                    e["Risk Management Cause"] = rmc["value"]
                    p["Risk Management Cause"] = "xw"
                    stats["risk_mgmt_cause"] += 1
                hf_spec = qual["human_factors"]
                if canon in hf_spec["applies_to_categories"]:
                    hf = _first_pattern(sub, hf_spec["patterns"])
                    if hf:
                        e["Human Factors  Cause"] = hf["value"]
                        p["Human Factors  Cause"] = "xw"
                        e["_xw_human_factor_confidence"] = hf["confidence"]
                        stats["human_factor"] += 1
                        stats[f"    hf_{hf['confidence']}"] += 1
        out.append(e)
        prov.append(p)
    return out, prov, stats


def synth_for_row(row: dict, side: dict, atoms: list[str],
                  rules: dict) -> tuple[dict, str | None]:
    """Every `syn_*` field for one incident, plus why it was skipped if it was.

    synth.py has existed and been tested since 2026-08-09 and was imported by
    nothing in production -- `grep -rn "from psm.synth" src/` returned tests
    only. This is the wiring.

    Returns the reason rather than swallowing it. The first version here had a
    bare `except Exception: return {}` and silently produced ZERO synthetic
    cells across the whole corpus, because `synth_date_fields` wants a `date`
    and was handed a string. Silent, plausible, wrong -- the failure this repo
    keeps meeting, reintroduced by the very code meant to be careful.
    """
    from psm.synth import synthesize_row
    raw_date = (row.get("Date of Incident") or "").strip()
    if not raw_date:
        return {}, "no_incident_date"
    try:
        incident_date = dt.date.fromisoformat(raw_date)
    except ValueError:
        return {}, "unparseable_date"
    dm = RE_MONEY.search(side.get("bsee_property_damaged", "") or "")
    try:
        return synthesize_row({
            "report_id": row["Incident Number"],
            "incident_date": incident_date,
            "incident_types": set(atoms),
            "property_damage_usd": float(dm.group(1).replace(",", "")) if dm else None,
            "area_block": f"{row.get('Site', '')} {row.get('Area', '')}".strip(),
        }, rules), None
    except Exception as exc:
        return {}, f"{type(exc).__name__}: {exc}"[:80]


def outcome_text(atoms: list[str], damage: str | None, spec: dict) -> str:
    """Render BSEE outcome atoms as an English sentence -- E19's "What was the
    outcome?", fallback tier.

    Translation, not inference: every phrase names a code BSEE published, at the
    same granularity. See schema/xw_outcome.yaml for why that keeps this `xw`
    rather than `syn_`, and for the severity language that must never enter it.

    Returns "" when there are no atoms. An outcome sentence assembled from no
    outcome data would be fabrication carrying an `xw` label.
    """
    clauses = []
    for group in ("injury", "event", "response"):
        table = spec[group]
        # Preserve the rule file's order, not the atom order: the atom order
        # comes from a BSEE string and varies between otherwise identical rows.
        found = [phrase for atom, phrase in table.items() if atom in atoms]
        if not found:
            continue
        if group == "injury":
            clauses.append("The incident resulted in " + _join(found))
        elif group == "event":
            clauses.append("Reported as " + _join(found))
        else:
            clauses.append(_join(found).capitalize())
    if not clauses:
        return ""
    out = ". ".join(clauses) + "."
    if damage:
        out += " " + spec["damage_clause"].replace("{amount}", damage)
    return out


def _join(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    inc = load(E19 / "incidents.csv")
    spec = yaml.safe_load(XW_TYPE.read_text(encoding="utf-8"))
    by_time, by_ab = spine_index(load(SPINE))
    cols = list(inc[0])

    tiers = yaml.safe_load(XW_TIERS.read_text(encoding="utf-8"))
    ospec = yaml.safe_load(XW_OUTCOME.read_text(encoding="utf-8"))
    disp = yaml.safe_load(DISPOSITION.read_text(encoding="utf-8"))
    from psm.synth import load_rules
    srules = load_rules()
    # column -> syn_* generator, for the incidents table only. `synthetic_column`
    # entries fill wholesale; `fabricate` entries fill only where src/xw left a
    # hole. Both are marked `syn`, never `src` or `xw`.
    gen_for = {c: e["generator"] for c, e in disp["fields"]["incidents"].items()
               if e.get("generator")}
    marks_by_sha = {}
    for pth in INTERIM.glob("*.json"):
        d = json.loads(pth.read_text(encoding="utf-8"))
        marks_by_sha[d.get("src_sha256", "")] = [str(m) for m in (d.get("src_checkboxes_page0") or [])]
    side_by_id = {r["Incident Number"]: r for r in load(E19 / "bsee_unmapped.csv")}

    filled: dict[str, int] = {}
    synfilled: dict[str, int] = {}
    synskip: dict[str, int] = {}
    synillegal: dict[str, int] = {}
    # Picklists, by E19 column. Same source psm.project reads.
    from psm.project import load_yaml, picklists
    legal = picklists(yaml.safe_load((REPO / "schema" / "e19_labels.yaml")
                                     .read_text(encoding="utf-8")),
                      yaml.safe_load((REPO / "schema" / "e19_projection.yaml")
                                     .read_text(encoding="utf-8")))
    unjoined = 0
    enriched, prov = [], []
    for row in inc:
        atoms = atoms_for(row, by_time, by_ab)
        if not atoms:
            unjoined += 1
        xw = resolve_types(atoms, spec)
        sr = side_by_id.get(row["Incident Number"], {})
        dm = RE_MONEY.search(sr.get("bsee_property_damaged", "") or "")
        xw.update(section3(atoms, marks_by_sha.get(sr.get("bsee_sha256", ""), []),
                           float(dm.group(1).replace(",", "")) if dm else None, tiers))
        # Omit the key entirely when there is nothing to say. Setting it to ""
        # would mark the cell `xw` in provenance.csv with no value behind it --
        # the exact orphan that test_no_provenance_without_a_value forbids.
        got = outcome_text(atoms, dm.group(0).replace(" ", "") if dm else None, ospec)
        if got:
            xw["What was the outcome?"] = got
        e = dict(row)
        p = {c: ("src" if (row.get(c) or "").strip() else "") for c in cols}
        for col, val in xw.items():
            if not (e.get(col) or "").strip():   # verbatim always wins
                e[col] = val
                p[col] = "xw"
                filled[col] = filled.get(col, 0) + 1

        # Synthetic fill, LAST. src beats xw beats syn, always -- the precedence
        # that keeps `syn` from ever displacing something real.
        if gen_for:
            syn, why = synth_for_row(row, sr, atoms, srules)
            if why:
                synskip[why] = synskip.get(why, 0) + 1
            for col, key in gen_for.items():
                if col not in cols or (e.get(col) or "").strip():
                    continue
                v = syn.get(key)
                if v is None or str(v).strip() == "":
                    continue
                # A synthetic value must clear the same picklist guard that
                # psm.project applies to verbatim ones: "blank beats a wrong
                # value in a controlled column". synth's
                # `syn_incident_classification` emits "Unknown", which is not in
                # E19's three-value vocabulary; 143 illegal cells shipped before
                # test_projection caught it.
                if col in legal and str(v) not in legal[col]:
                    synillegal[col] = synillegal.get(col, 0) + 1
                    continue
                e[col] = str(v)
                p[col] = "syn"
                synfilled[col] = synfilled.get(col, 0) + 1
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
    qspec = yaml.safe_load(XW_QUAL.read_text(encoding="utf-8"))
    c_enriched, c_prov, c_stats = enrich_causes(causes, espec, qspec)
    ccols = list(causes[0])
    conf_rows = [{"Incident Number": r["Incident Number"], "Cause number": r["Cause number"],
                  "xw_human_factor_confidence": r.pop("_xw_human_factor_confidence", "")}
                 for r in c_enriched]
    with (args.out / "causes_confidence.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(conf_rows[0]))
        w.writeheader(); w.writerows(conf_rows)

    # Secondary elements. Sidecar rather than a second value in the E19 cell --
    # see enrich_causes. Semicolon-separated because a category may touch more
    # than one, even though today every entry touches exactly one.
    sec_rows = [{"Incident Number": r["Incident Number"], "Cause number": r["Cause number"],
                 "xw_secondary_elements": r.pop("_xw_secondary_elements", "")}
                for r in c_enriched]
    with (args.out / "causes_secondary_element.csv").open(
            "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(sec_rows[0]))
        w.writeheader(); w.writerows(sec_rows)
    n_sec = sum(1 for r in sec_rows if r["xw_secondary_elements"])
    print(f"  secondary elements       {n_sec}/{len(sec_rows)} = "
          f"{100 * n_sec / len(sec_rows):5.1f}%")
    for name, data in (("causes.csv", c_enriched), ("causes_provenance.csv", c_prov)):
        with (args.out / name).open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=ccols, extrasaction="ignore")
            w.writeheader()
            w.writerows(data)

    n = len(inc)
    print(f"enriched {n} incidents -> {args.out}")
    print(f"  synthetic fill: {sum(synfilled.values()):,} cells across "
          f"{len(synfilled)} columns")
    for c, k in sorted(synfilled.items(), key=lambda x: -x[1]):
        print(f"    {k:5d}  {c}")
    if synskip:
        print(f"  synth skipped {sum(synskip.values())} rows: {synskip}")
    if synillegal:
        print(f"  synth values rejected by picklist: {synillegal}")
    print(f"  unjoined to spine (no atoms available): {unjoined} ({100*unjoined/n:.1f}%)")
    for col in ("Incident Type A", "Incident Type B", "Incident Type C", "Incident Type D",
                "Health & Safety  - Consequence", "Health & Safety - Likelihood",
                "Health & Safety - Risk Score", "Health & Safety Incident - Classification",
                "Environment & Reputation  - Consequence",
                "Financial Cost & Business Interruption  - Consequence",
                "Incident Classification"):
        k = filled.get(col, 0)
        print(f"  {col[:46]:46} {k:5}/{n} = {100*k/n:5.1f}%")

    nc = len(causes)
    print(f"\nenriched {nc} cause statements")
    for k in ("mapped", "risk_mgmt_cause", "human_factor",
              "typed_but_unaliased", "untyped_freetext"):
        print(f"  {k:22} {c_stats[k]:5}/{nc} = {100*c_stats[k]/nc:5.1f}%")
    for k, v in sorted(c_stats.items()):
        if k.startswith("  ->"):
            print(f"    {k[5:]:26} {v:5}")
    for k, v in sorted(c_stats.items()):
        if k.startswith("    hf_"):
            print(f"    human factor {k[7:]:15} {v:5}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
