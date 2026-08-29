"""Field extraction from MMS Form 2010 PDFs -> per-report JSON.

Reads PDFs from ``data/raw/``, writes one JSON per report to ``data/interim/``.
All positional work lives in :mod:`psm.layout`; this module only segments the
reconstructed line stream into numbered fields.

Run:  ``uv run python -m psm.extract``
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import pdfplumber
import yaml

from psm.layout import Line, checkbox_labels, document_lines

REPO = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO / "schema" / "bsee_form2010.yaml"
DEFAULT_RAW = REPO / "data" / "raw"
DEFAULT_INTERIM = REPO / "data" / "interim"

# A field anchor: a number, a dot, then a label. Anchors can appear mid-line
# because the admin block is two-column ("25. DATE ...   28. ACCIDENT CLASS...").
ANCHOR_RE = re.compile(r"(?:(?<=^)|(?<=\s))(\d{1,2})\s*\.\s+(?=[A-Z(])")

# A PDF whose fonts carry no ToUnicode mapping extracts as "(cid:N)" tokens. The
# text layer is present, so nothing errors and fields are "found" -- they just
# hold mojibake. Silent, plausible, wrong: the failure mode this project keeps
# meeting. Found on 15 of 1,289 reports, 14 of which were reported ok.
CID_RE = re.compile(r"\(cid:\d+\)")
# Judged by the share of characters that are cid tokens, not by their count: a
# few stray unmapped glyphs (bullets, symbols) in an otherwise clean report are
# harmless, while a document whose body is largely cid is unusable. Observed
# extremes in the corpus: 3 tokens in a readable report vs 282 in a garbled one.
CID_CHAR_SHARE = 0.05

# "src_f" alone also matches src_form_revision and src_fields_found, which would
# make the body look non-empty and suppress the raw-text fallback below.
FIELD_KEY_RE = re.compile(r"^src_f\d{2}_")


def load_schema(path: Path = SCHEMA_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _furniture(schema: dict) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in schema.get("furniture_patterns", [])]


def _inline_strips(schema: dict) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in schema.get("inline_strip_patterns", [])]


def _label_matches(field_no: int, tail: str, schema: dict) -> bool:
    """Confirm an anchor by its label, tolerating era-to-era wording drift.

    ``label_hint`` may be a single string or a list of alternates; a list
    matches if ANY alternate is present. Field 17 needs this: the pre-2010
    revision reads "DESCRIBE IN SEQUENCE HOW ACCIDENT HAPPENED" where the modern
    one reads "INVESTIGATION FINDINGS".
    """
    spec = schema["fields"].get(field_no)
    if not spec:
        return False
    hint = spec.get("label_hint", "")
    if not hint:
        return True
    hints = [hint] if isinstance(hint, str) else hint
    up = tail.upper()
    return any(h.upper() in up for h in hints)


def detect_form_revision(kept, schema: dict) -> str:
    """Identify which form revision a document uses.

    Read from the raw anchor stream rather than from extracted fields: on
    revisions A and B the relevant anchors are *rejected* by the label hints, so
    by the time ``fields`` exists the evidence has already been discarded.

    Returns "A", "B", "C" or "unknown". Never raises.
    """
    cfg = schema.get("form_revisions") or {}
    by_depth = {int(k): v for k, v in (cfg.get("water_depth_anchor") or {}).items()}
    by_f3 = {k.upper(): v for k, v in (cfg.get("field3_label") or {}).items()}

    verdict = None
    f3_tail = None
    for ln in kept:
        for m in ANCHOR_RE.finditer(ln.text):
            num = int(m.group(1))
            tail = ln.text[m.end(): m.end() + 90].upper()
            if verdict is None and "WATER DEPTH" in tail and num in by_depth:
                verdict = by_depth[num]
            if num == 3 and f3_tail is None:
                f3_tail = tail
    if verdict == "C":
        return "C"
    if verdict == "AB" or verdict is None:
        # Revision A has no field 3 at all, so absence is itself evidence — but
        # only once we already know we are not looking at revision C.
        if f3_tail is not None:
            for label, rev in by_f3.items():
                if label in f3_tail:
                    return rev
        if verdict == "AB":
            return "A" if f3_tail is None else "unknown"
    return "unknown"


def check_field_lengths(fields: dict[int, str], schema: dict) -> list[dict]:
    """Flag structured fields holding far more text than their kind allows.

    A ``checkbox_set`` carrying 2,356 characters of prose means an anchor was
    rejected and its content absorbed into the previous accepted field. That is
    the project's recurring failure mode -- silent, plausible, wrong -- and this
    turns it loud. Raises anomalies only; never truncates or repairs.
    """
    limits = schema.get("max_length_by_kind") or {}
    out: list[dict] = []
    for num, text in sorted(fields.items()):
        spec = schema["fields"].get(num) or {}
        cap = limits.get(spec.get("kind"))
        if cap is not None and len(text) > cap:
            out.append({
                "type": "field_length_exceeded",
                "field": num,
                "kind": spec.get("kind"),
                "length": len(text),
                "limit": cap,
                "head": text[:80],
            })
    return out


def kept_lines(lines, schema: dict) -> list[Line]:
    """Drop page furniture and strip inline watermarks, preserving visual order.

    Shared by :func:`segment_fields` and :func:`detect_form_revision` so both see
    exactly the same line stream.
    """
    furn = _furniture(schema)
    strips = _inline_strips(schema)
    out: list[Line] = []
    for ln in lines:
        text = ln.text.strip()
        for p in strips:
            text = p.sub(" ", text)
        text = re.sub(r"\s{2,}", " ", text).strip()
        if not text or any(p.match(text) for p in furn):
            continue
        out.append(Line(ln.page, ln.top, ln.x0, text, ln.column))
    return out


def segment_fields(lines, schema: dict) -> tuple[dict[int, str], list[dict]]:
    """Split visual-order lines into ``{field_number: text}``.

    Returns the field map plus a list of anomaly records. Anchors are accepted
    only when the field number is plausible (monotonically advancing) AND the
    label hint matches, so a stray "21. " inside prose does not open a field.
    """
    anomalies: list[dict] = []
    kept = kept_lines(lines, schema)

    # Pass 1: locate accepted anchors.
    #
    # Acceptance rests on the label hint, NOT on field numbers arriving in
    # ascending order. The form face and the closing admin block are both
    # two-column, so a stream can legitimately read 25, 26, 27, 28 down the left
    # column then jump back. An earlier strict-ascending rule silently discarded
    # fields 4-7, 26, 27 and 29 on most reports. Duplicates keep the first hit.
    anchors: list[tuple[int, int, int]] = []  # (line_idx, char_offset, field_no)
    seen: set[int] = set()
    highest = 0
    for i, ln in enumerate(kept):
        for m in ANCHOR_RE.finditer(ln.text):
            num = int(m.group(1))
            if not (1 <= num <= 30):
                continue
            tail = ln.text[m.end(): m.end() + 90]
            if not _label_matches(num, tail, schema):
                continue
            if num in seen:
                anomalies.append({
                    "type": "duplicate_anchor", "field": num,
                    "line": ln.text[:120], "page": ln.page,
                })
                continue
            if num < highest:
                # Informational only: a real signal of column reordering, but
                # not a reason to drop a field whose label matched.
                anomalies.append({
                    "type": "out_of_order_anchor", "field": num, "after": highest,
                    "line": ln.text[:120], "page": ln.page,
                })
            anchors.append((i, m.start(), num))
            seen.add(num)
            highest = max(highest, num)

    if not anchors:
        return {}, anomalies + [{"type": "no_anchors_found"}]

    # Pass 2: content runs from one anchor to the next.
    fields: dict[int, str] = {}
    for a, (li, ci, num) in enumerate(anchors):
        if a + 1 < len(anchors):
            lj, cj, _ = anchors[a + 1]
        else:
            lj, cj = len(kept) - 1, len(kept[-1].text)

        if li == lj:
            chunk = [kept[li].text[ci:cj]]
        else:
            chunk = [kept[li].text[ci:]]
            chunk += [kept[k].text for k in range(li + 1, lj)]
            chunk.append(kept[lj].text[:cj])

        body = "\n".join(chunk)
        # Drop the label itself: everything up to and including the first colon
        # on the first line, when a colon is present there.
        first, _, rest = body.partition("\n")
        if ":" in first:
            first = first.split(":", 1)[1]
        fields[num] = (first + ("\n" + rest if rest else "")).strip()

    missing = [n for n in schema["fields"] if n not in fields]
    if missing:
        anomalies.append({"type": "fields_not_located", "fields": missing})
    return fields, anomalies


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def extract_report(pdf_path: Path, schema: dict) -> dict:
    """Extract one report. Never raises on bad input — records the failure."""
    rec: dict = {
        "src_source_file": pdf_path.name,
        "src_sha256": sha256_of(pdf_path),
        "src_extract_status": "ok",
        "anomalies": [],
    }
    try:
        with pdfplumber.open(pdf_path) as pdf:
            rec["src_page_count"] = len(pdf.pages)
            lines = document_lines(pdf)
            rec["src_line_count"] = len(lines)
            if not lines:
                rec["src_extract_status"] = "no_text_layer"
                rec["anomalies"].append({
                    "type": "no_text_layer",
                    "note": "zero words extracted; likely a scanned image requiring OCR",
                })
                return rec
            rec["src_form_revision"] = detect_form_revision(kept_lines(lines, schema), schema)
            fields, anomalies = segment_fields(lines, schema)
            rec["anomalies"].extend(anomalies)
            rec["anomalies"].extend(check_field_lengths(fields, schema))
            for num, text in sorted(fields.items()):
                name = schema["fields"][num]["name"]
                rec[f"src_f{num:02d}_{name}"] = text
            rec["src_fields_found"] = sorted(fields)
            if pdf.pages:
                rec["src_checkboxes_page0"] = [
                    lbl for lbl, _, _ in checkbox_labels(pdf.pages[0], 0)
                ]
            # Check the extracted fields, falling back to the raw line stream:
            # when the labels themselves are cid-garbled no anchor matches, so
            # there are no fields to inspect and the document would otherwise be
            # misread as "not an investigation report".
            body = " ".join(v for k, v in rec.items()
                            if FIELD_KEY_RE.match(k) and isinstance(v, str))
            if not body.strip():
                body = " ".join(ln.text for ln in lines)
            cid_chars = sum(len(m.group(0)) for m in CID_RE.finditer(body))
            if body and cid_chars / max(len(body), 1) > CID_CHAR_SHARE:
                rec["src_extract_status"] = "text_layer_unmapped"
                rec["anomalies"].append({
                    "type": "text_layer_unmapped",
                    "note": "font carries no ToUnicode mapping; text extracts as (cid:N) "
                            "tokens. The text layer exists, so nothing errors and fields may "
                            "appear located -- their content is simply unreadable. Needs OCR.",
                    "cid_share": round(cid_chars / max(len(body), 1), 3),
                    "body_chars": len(body),
                })
                return rec
            if not fields:
                rec["src_extract_status"] = "parse_failed"
                # A text layer but no form anchors at all: either a genuinely
                # unparseable layout, or the URL does not serve an investigation
                # report. BSEE serves a 2008 MMS press release at one incident
                # URL (090517-pdf). Distinguish so the second is not chased as
                # a parser bug.
                blob = " ".join(ln.text for ln in lines[:60]).upper()
                if not any(k in blob for k in ("FORM 2010", "ACCIDENT INVESTIGATION", "OCCURRED")):
                    rec["src_extract_status"] = "not_an_investigation_report"
                    rec["anomalies"].append({
                        "type": "not_an_investigation_report",
                        "note": "text layer present but no Form 2010 markers; "
                                "upstream: BSEE serves a non-report document at this URL",
                        "head": " ".join(ln.text for ln in lines[:6])[:200],
                    })
    except Exception as exc:  # noqa: BLE001 - a corrupt PDF must not kill the run
        rec["src_extract_status"] = "parse_failed"
        rec["anomalies"].append({"type": "exception", "error": f"{type(exc).__name__}: {exc}"})
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    ap.add_argument("--out", type=Path, default=DEFAULT_INTERIM)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)

    schema = load_schema()
    args.out.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(args.raw.rglob("*.pdf"))[: args.limit]
    if not pdfs:
        print(f"no PDFs under {args.raw} — run `python -m psm.fetch` first", file=sys.stderr)
        return 1

    counts: dict[str, int] = {}
    anomaly_log = args.out / "anomalies.jsonl"
    with open(anomaly_log, "w", encoding="utf-8") as alog:
        for path in pdfs:
            rec = extract_report(path, schema)
            counts[rec["src_extract_status"]] = counts.get(rec["src_extract_status"], 0) + 1
            out = args.out / (path.stem + ".json")
            out.write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
            for a in rec["anomalies"]:
                alog.write(json.dumps({"file": path.name, **a}, ensure_ascii=False) + "\n")

    print(f"extracted {len(pdfs)} reports -> {args.out}")
    for status, n in sorted(counts.items()):
        print(f"  {status}: {n}")
    print(f"anomalies -> {anomaly_log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
