"""Project extracted BSEE records onto the E19 schema, verbatim.

Emits four relational tables whose column names are byte-exact E19 field labels,
read from ``schema/e19_labels.yaml`` at runtime and never hardcoded here. That is
the whole point: every field-name mismatch found in review so far came from a
human retyping a label.

**Verbatim only.** A cell is written when a BSEE field carries the value
literally, or when it is structural (an ordinal, a foreign key). Nothing is
crosswalked, inferred or synthesised. The blanks are as much the deliverable as
the values -- they size what remains, split by reason code.

Run::

    uv run python -m psm.project
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import yaml

from psm.causes import segment_statements

REPO = Path(__file__).resolve().parents[2]
LABELS_PATH = REPO / "schema" / "e19_labels.yaml"
PROJECTION_PATH = REPO / "schema" / "e19_projection.yaml"
DEFAULT_INTERIM = REPO / "data" / "interim"
DEFAULT_MANIFEST = REPO / "data" / "manifest.csv"
DEFAULT_OUT = REPO / "data" / "processed" / "e19"

# Salt for pseudonymisation. Committed on purpose: the mapping must be
# reproducible from a fresh clone. This is de-amplification -- it stops the repo
# being a convenient index of named federal employees -- not anonymisation, since
# the source PDFs are public and re-extractable.
PSEUDONYM_SALT = "psm-incident-ml/e19/v1"

MONTHS = {m: i for i, m in enumerate(
    "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split(), start=1)}

RE_DATE = re.compile(r"(\d{1,2})-([A-Z]{3})-(\d{4})")
RE_TIME = re.compile(r"TIME:\s*(\d{3,4})")
RE_AREA = re.compile(r"AREA:\s*([A-Z]{2,3})\b")
RE_BLOCK = re.compile(r"BLOCK:\s*(\d{1,4})\b")
RE_RIG = re.compile(r"RIG NAME:\s*(.+)", re.IGNORECASE)
RE_OTHER = re.compile(r"\bOTHER\s+([A-Za-z][A-Za-z /&'-]{2,60})")

# Recommendations are enumerated, not paragraph-separated. An earlier splitter
# used a blank line and NEVER FIRED: zero of 1,077 non-empty field-22 values
# contain one, so every incident got exactly one row and the declared grain
# ("one row per recommendation") was false for the whole table.
RE_REC_ITEM = re.compile(r"\n\s*(?:\d{1,2}\s*[.)]|[a-h]\s*\)|[\u2022\u25cf\u25aa])\s+")

# BSEE writes a nil return as prose. Per the repo's absent_legitimate convention
# these are not recommendations and must not be counted as one.
NIL_RETURN = {"none", "n/a", "na", "no", "nil", "none.", "n/a.", "no recommendations"}


def split_recommendations(text: str) -> list[str]:
    """One string per recommendation. Empty list for a nil return."""
    body = (text or "").strip()
    if not body or body.lower().rstrip(".") in NIL_RETURN:
        return []
    # Only leading separator debris is stripped. A trailing full stop is part of
    # the sentence, and this project keeps source text verbatim.
    parts = [p.lstrip(" .);:-") for p in RE_REC_ITEM.split("\n" + body)]
    return [" ".join(p.split()) for p in parts if p.strip()]


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def label_groups(labels: dict) -> dict[str, list[str]]:
    """group name -> ordered field labels, duplicates preserved in order."""
    return {g["group"]: [f["label"] for f in g["fields"]] for g in labels["groups"]}


def pseudonym(raw: str, prefix: str) -> str:
    """Stable salted token. Same person -> same token corpus-wide."""
    cleaned = " ".join(raw.split()).strip(" /")
    if not cleaned:
        return ""
    digest = hashlib.sha256((PSEUDONYM_SALT + "|" + cleaned.upper()).encode()).hexdigest()
    return f"{prefix}-{digest[:6]}"


# --- value extractors -------------------------------------------------------
# Each takes the record and the field text and returns a string. They never
# raise and never guess: an unparseable input yields "".

def _iso_date(text: str) -> str:
    m = RE_DATE.search(text or "")
    if not m:
        return ""
    d, mon, y = m.groups()
    if mon not in MONTHS:
        return ""
    return f"{y}-{MONTHS[mon]:02d}-{int(d):02d}"


def _time(text: str) -> str:
    m = RE_TIME.search(text or "")
    if not m:
        return ""
    raw = m.group(1).zfill(4)
    hh, mm = raw[:2], raw[2:]
    return f"{hh}:{mm}" if hh.isdigit() and int(hh) < 24 else ""


def _first(pattern: re.Pattern, *texts: str) -> str:
    for t in texts:
        m = pattern.search(t or "")
        if m:
            return m.group(1).strip()
    return ""


LATER_SUBHEADS = re.compile(
    r"(SEQUENCE OF EVENTS|BSEE INVESTIGATION|IN CONCLUSION|CONCLUSION)")


def _subhead(text: str, head: str) -> str:
    """The opening section of field 17 -- E19's "What happened?".

    Only a minority of reports print an explicit ``INCIDENT SUMMARY`` heading, so
    keying solely on it returned 15/104. Where the heading is absent, the opening
    of the narrative *is* the summary: everything before the first later
    subheading. Where no subheadings exist at all, the whole narrative is the
    account of what happened.
    """
    if not text:
        return ""
    up = text.upper()
    i = up.find(head.upper())
    if i >= 0:
        start = text.find(":", i)
        start = (start + 1) if 0 <= start < i + len(head) + 4 else i + len(head)
        tail = text[start:]
    else:
        tail = text
    m = LATER_SUBHEADS.search(tail.upper())
    return (tail[: m.start()] if m else tail).strip()


def _sequence(text: str) -> str:
    """Everything from SEQUENCE OF EVENTS onward -- E19's "How did the incident
    occur".

    Returns "" when the report carries no such heading. Falling back to the whole
    narrative would duplicate "What happened?" into both columns and imply a
    separation the document does not make.
    """
    if not text:
        return ""
    i = text.upper().find("SEQUENCE OF EVENTS")
    return text[i:].strip() if i >= 0 else ""


FIELD_KEY_RE = re.compile(r"^src_f\d{2}_")


def whole_record_text(rec: dict) -> str:
    """All extracted field text. Matches src_fNN_ strictly: a bare "src_f" prefix
    also catches src_form_revision and src_fields_found."""
    return " ".join(v for k, v in rec.items() if FIELD_KEY_RE.match(k) and isinstance(v, str))


def field(rec: dict, num: str) -> str:
    """Fetch src_fNN_* by number without needing its name."""
    pre = f"src_f{int(num[1:]):02d}_"
    for k, v in rec.items():
        if k.startswith(pre) and isinstance(v, str):
            return v
    return ""


def resolve(rec: dict, spec: dict, manifest_row: dict) -> str:
    src = spec.get("source")
    if not src or src in ("ordinal", "constructed", "f18_f19"):
        return ""
    text = field(rec, src) if src.startswith("f") else str(rec.get(src, "") or "")
    kind = spec.get("extract", "text")

    if kind == "date":
        return _iso_date(text)
    if kind == "time":
        return _time(text)
    if kind in ("area", "block"):
        pat = RE_AREA if kind == "area" else RE_BLOCK
        val = _first(pat, text)
        if not val and spec.get("fallback") == "whole_record":
            val = _first(pat, whole_record_text(rec))
        if not val:
            val = (manifest_row.get("src_area" if kind == "area" else "src_block") or "").strip()
        return val
    if kind == "platform":
        head = text.split("\n", 1)[0]
        return re.sub(r"\bRIG NAME:.*$", "", head, flags=re.IGNORECASE).strip(" :")
    if kind == "rig_name":
        return _first(RE_RIG, text)
    if kind == "other_text":
        return _first(RE_OTHER, text)
    if kind == "pseudonym":
        return pseudonym(text, spec.get("prefix", "ID"))
    if kind == "literal_if_present":
        return spec.get("value", "") if text.strip() else ""
    if kind == "subhead":
        return _subhead(text, spec["subhead"])
    if kind == "sequence":
        return _sequence(text)
    return " ".join(text.split())


def incident_number(rec: dict, manifest_row: dict, mapping: dict) -> str:
    area = resolve(rec, mapping["Site"], manifest_row)
    block = resolve(rec, mapping["Area"], manifest_row)
    date = _iso_date(field(rec, "f01")).replace("-", "")
    time = _time(field(rec, "f01")).replace(":", "")
    parts = [p for p in (area, block, date, time) if p]
    return "-".join(parts) if len(parts) >= 3 else ""


def picklists(labels: dict, proj: dict) -> dict[str, set[str]]:
    """E19 column -> its legal values, for the columns declared picklist-backed.

    Without this a raw text dump lands in a controlled column and nothing
    notices: BSEE field 28 (MAJOR/MINOR) put 234 illegal values into
    `Incident Classification`, whose picklist is Very Serious Incident / Serious
    Incident / Incident -- and because verbatim wins, those illegal values
    suppressed 149 rows that had a valid crosswalked classification.

    Columns in `vocabulary_exempt` are skipped: the template ships Site/Area/Unit
    as placeholder facility names, and this project repurposes them for BSEE
    geography on purpose.
    """
    by_name = {v["name"]: {str(x) for x in v["values"]}
               for v in labels.get("vocabularies", []) if v.get("name")}
    exempt = set(proj.get("vocabulary_exempt") or {})
    out: dict[str, set[str]] = {}
    for col, vocab in (proj.get("vocabularies") or {}).items():
        if col not in exempt and vocab in by_name:
            out[col] = by_name[vocab]
    return out


def build(interim: Path, manifest: Path, labels: dict, proj: dict) -> dict:
    groups = label_groups(labels)
    mapping = proj["mapping"]
    legal = picklists(labels, proj)
    illegal: Counter = Counter()

    manifest_by_sha: dict[str, dict] = {}
    if manifest.exists():
        with open(manifest, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                manifest_by_sha[row.get("src_sha256", "")] = row

    def cols(table: str) -> list[str]:
        spec = proj["tables"][table]
        out = list(spec.get("foreign_keys", []))
        for g in spec["groups"]:
            for lab in groups[g]:
                if lab not in out:
                    out.append(lab)
        return out

    tables = {t: [] for t in proj["tables"]}
    sidecar_rows = []
    cause_fields: list[dict] = []
    reasons = Counter()
    collisions: list[str] = []
    seen_ids: set[str] = set()

    # Pass 1: assemble candidate rows and their keys, so collisions can be
    # resolved deterministically rather than by whichever file was read first.
    staged: list[tuple[str, dict, dict]] = []
    skipped = Counter()
    for path in sorted(interim.glob("*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        if rec.get("src_extract_status") != "ok":
            skipped[rec.get("src_extract_status", "unknown")] += 1
            continue
        mrow = manifest_by_sha.get(rec.get("src_sha256", ""), {})
        # Panel reports are a structurally different document that this pipeline
        # was never built against -- 57 of 61 fail outright and the 4 that report
        # ok matched a single anchor each, producing near-empty rows. Excluded
        # here for the same reason gold_sample.py excludes them.
        if mrow.get("src_report_type", "district") != "district":
            skipped["panel_report"] += 1
            continue
        staged.append((incident_number(rec, mrow, mapping), rec, mrow))

    # A composite of area, block, date and minute is not unique: two different
    # incidents can share a block and timestamp, and a few documents are
    # published twice. Suffix every member of a colliding group with a short
    # content hash -- applied to all members, so the result does not depend on
    # read order.
    counts = Counter(k for k, _, _ in staged if k)
    for idx, (key, rec, mrow) in enumerate(staged):
        if not key:
            key = f"UNKEYED-{rec.get('src_sha256','')[:12]}"
        elif counts[key] > 1:
            collisions.append(key)
            key = f"{key}-{rec.get('src_sha256','')[:8]}"
        staged[idx] = (key, rec, mrow)

    for inc_id, rec, mrow in staged:
        seen_ids.add(inc_id)
        row = {}
        for lab in cols("incidents"):
            spec = mapping.get(lab, {})
            val = inc_id if lab == "Incident Number" else resolve(rec, spec, mrow)
            if val and lab in legal and val not in legal[lab]:
                illegal[lab] += 1
                val = ""          # blank beats a wrong value in a controlled column
            row[lab] = val
        tables["incidents"].append(row)

        # Tag each statement with the field it came from. BSEE's field 18 is
        # "Probable Cause" and 19 is "Contributing Cause" -- an axis of primacy,
        # not the depth axis E19's `Cause type` asks for (see
        # schema/xw_cause_qualifiers.yaml). So it is NOT crosswalked, but it is
        # real provenance and an obvious feature for a later LLM-assisted pass,
        # and concatenating the two fields was silently discarding it.
        statements = []
        for fnum in ("f18", "f19"):
            statements += [(s, fnum[1:]) for s in segment_statements(field(rec, fnum) or "")
                           if s.strip()]
        for i, (stmt, src_field) in enumerate(statements, start=1):
            r = {c: "" for c in cols("causes")}
            r["Incident Number"] = inc_id
            r["Cause number"] = str(i)
            r["Cause Description"] = " ".join(stmt.split())
            tables["causes"].append(r)
            cause_fields.append({"Incident Number": inc_id, "Cause number": str(i),
                                 "bsee_source_field": src_field})

        recs22 = split_recommendations(field(rec, "f22"))
        for i, block in enumerate(recs22, start=1):
            r = {c: "" for c in cols("recommendations")}
            r["Incident Number"] = inc_id
            r["Recommendation Number"] = str(i)
            r["Recommendation Description"] = block
            tables["recommendations"].append(r)
            c = {k: "" for k in cols("closeout")}
            c["Incident Number"] = inc_id
            c["Recommendation Number"] = str(i)
            tables["closeout"].append(c)

        side = {"Incident Number": inc_id}
        for item in proj.get("sidecar", []):
            frm = item["from"]
            side[item["as"]] = (field(rec, frm) if frm.startswith("f")
                                else str(rec.get(frm, mrow.get(frm, "")) or ""))
            side[item["as"]] = " ".join(side[item["as"]].split())
        sidecar_rows.append(side)

    for lab, spec in mapping.items():
        if "blank" in spec:
            reasons[spec["blank"]] += 1

    return {"tables": tables, "sidecar": sidecar_rows, "cols": {t: cols(t) for t in tables},
            "reasons": reasons, "collisions": collisions, "skipped": skipped,
            "cause_fields": cause_fields, "illegal": illegal}


def write_csv(path: Path, cols: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--interim", type=Path, default=DEFAULT_INTERIM)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    labels = load_yaml(LABELS_PATH)
    proj = load_yaml(PROJECTION_PATH)
    built = build(args.interim, args.manifest, labels, proj)

    for name, rows in built["tables"].items():
        write_csv(args.out / f"{name}.csv", built["cols"][name], rows)
        print(f"  {name}.csv: {len(rows)} rows x {len(built['cols'][name])} cols")
    if built["cause_fields"]:
        cf = built["cause_fields"]
        write_csv(args.out / "causes_source_field.csv", list(cf[0]), cf)
        print(f"  causes_source_field.csv: {len(cf)} rows (BSEE field 18 vs 19)")
    if built["sidecar"]:
        side_cols = list(built["sidecar"][0])
        write_csv(args.out / "bsee_unmapped.csv", side_cols, built["sidecar"])
        print(f"  bsee_unmapped.csv: {len(built['sidecar'])} rows x {len(side_cols)} cols")

    print(f"\nblank-by-reason: {dict(built['reasons'])}")
    if built["illegal"]:
        print(f"\nblanked as outside the column's picklist: {dict(built['illegal'])}")
    if built["skipped"]:
        print(f"\nskipped: {dict(built['skipped'])}")
    if built["collisions"]:
        uniq = sorted(set(built["collisions"]))
        print(f"\n{len(built['collisions'])} rows in {len(uniq)} colliding key groups, "
              f"suffixed with a content hash: {uniq[:4]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
