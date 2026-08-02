"""Build the incident-investigation *spine*: the structured index of every BSEE
incident investigation, from BSEE's own bulk raw-data download.

The spine is metadata only. It carries date, time, lease, area/block, incident
type, panel-vs-district, and completion status -- and **no cause, narrative,
finding, or recommendation text**. See ``docs/_spine.md`` for the evidence.
Cause data lives only in the per-incident PDFs, which is why the PDF pipeline
cannot be skipped.

Retrieval path
--------------
BSEE publishes this table as a nightly-refreshed zip on its raw-data hub:

    https://www.data.bsee.gov/Main/RawData.aspx
      -> https://www.data.bsee.gov/Other/Files/IncInvRawData.zip
           IncInvRawData/mv_acc_investigations.txt   (cp1252, CSV, quoted)

No browser, no JavaScript, no ASP.NET postback, no session cookie. A plain
GET is enough. The DevExpress grid on
``/Other/DataTables/IncidentInvestigations.aspx`` serves byte-equivalent
content, but it requires a ``__VIEWSTATE`` round-trip and it mangles non-ASCII
(see ``ENCODING`` note below), so the zip is the canonical path here.

Usage
-----
    uv run python -m psm.spine              # download (cached) + build
    uv run python -m psm.spine --force      # re-download even if cached
    uv run python -m psm.spine --verify     # hash-only check, no rebuild

Idempotent: re-running with an unchanged upstream file rewrites an identical
``data/processed/investigations_index.csv``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

import requests

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

RAW_DATA_HUB = "https://www.data.bsee.gov/Main/RawData.aspx"
ZIP_URL = "https://www.data.bsee.gov/Other/Files/IncInvRawData.zip"
MEMBER = "IncInvRawData/mv_acc_investigations.txt"

# BSEE serves this file as Windows-1252, not UTF-8. As of 2026-08-02 exactly one
# byte in the whole file is non-ASCII: 0x96 (EN DASH) in an MC 300 incident-type
# string. Decoding as UTF-8 raises; decoding as latin-1 silently yields U+0096.
# cp1252 is the only decoding that round-trips it to the intended U+2013.
ENCODING = "cp1252"

# Upstream is regenerated nightly ("Updated Daily" on the hub), so these are a
# *last observed* fingerprint, not a pin. A mismatch means the data moved, which
# is expected; it is reported, never fatal.
LAST_OBSERVED = {
    "captured_utc": "2026-08-02",
    "zip_sha256": "70cc083f9a20a791889a2bff366894c81f1dde6b8ce958f79434457fa8882faf",
    "txt_sha256": "8537697daebe6cdb0fef0ffef7f52bc752edc13803df7ed9aa64250074c5a335",
    "txt_bytes": 174107,
    "n_rows": 2014,
}

# Verbatim upstream header -> committed column name. Every column is `src_`
# because every column is lifted unaltered from the BSEE export. Note that
# ACCIDENT_TYPE is present in the data but *absent* from BSEE's own field
# definitions page, which lists AREA_BLOCK twice instead.
COLUMNS = {
    "DATE_OCCURRED": "src_date_occurred",
    "MILITARY_TIME": "src_military_time",
    "LEASE_NUMBER": "src_lease_number",
    "AREA_BLOCK": "src_area_block",
    "ACCIDENT_TYPE": "src_accident_type",
    "PANEL_DISTRICT": "src_panel_district",
    "STATUS": "src_status",
}

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw"
ZIP_PATH = RAW_DIR / "IncInvRawData.zip"
OUT_CSV = REPO_ROOT / "data" / "processed" / "investigations_index.csv"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_zip(force: bool = False) -> bytes:
    """Return the raw zip bytes, downloading only if absent or ``force``."""
    if ZIP_PATH.exists() and not force:
        print(f"[spine] cached  {ZIP_PATH.relative_to(REPO_ROOT)}")
        return ZIP_PATH.read_bytes()

    print(f"[spine] GET     {ZIP_URL}")
    resp = requests.get(
        ZIP_URL,
        headers={"User-Agent": UA, "Referer": RAW_DATA_HUB},
        timeout=120,
    )
    resp.raise_for_status()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    ZIP_PATH.write_bytes(resp.content)
    print(f"[spine] saved   {ZIP_PATH.relative_to(REPO_ROOT)} ({len(resp.content):,} bytes)")
    return resp.content


def extract_member(zip_bytes: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = [n for n in zf.namelist() if n.endswith(".txt")]
        if MEMBER in names:
            name = MEMBER
        elif len(names) == 1:
            name = names[0]
            print(f"[spine] WARNING upstream member renamed: {MEMBER!r} -> {name!r}")
        else:
            raise RuntimeError(f"cannot pick a data member from {zf.namelist()!r}")
        return zf.read(name)


def parse(txt_bytes: bytes) -> tuple[list[str], list[list[str]]]:
    """Decode and CSV-parse. Values are returned **verbatim** -- no trimming,
    no case folding, no date normalisation. Source data is dirty and stays
    dirty; anomalies are reported, not repaired."""
    text = txt_bytes.decode(ENCODING)
    rows = list(csv.reader(io.StringIO(text)))
    header, data = rows[0], [r for r in rows[1:] if r]
    return header, data


# --------------------------------------------------------------------------
# Anomaly detection (report-only)
# --------------------------------------------------------------------------


@dataclass
class Anomaly:
    kind: str
    detail: str
    n: int

    def as_json(self) -> str:
        return json.dumps(
            {"source": "spine", "kind": self.kind, "detail": self.detail, "n": self.n}
        )


def find_anomalies(header: list[str], data: list[list[str]], txt_bytes: bytes) -> list[Anomaly]:
    out: list[Anomaly] = []

    if header != list(COLUMNS):
        out.append(Anomaly("header_drift", f"upstream header changed: {header!r}", 1))

    non_ascii = sorted({b for b in txt_bytes if b > 0x7F})
    if non_ascii:
        out.append(
            Anomaly(
                "non_utf8_bytes",
                "bytes " + ",".join(hex(b) for b in non_ascii) + f" require {ENCODING} decoding",
                sum(1 for b in txt_bytes if b > 0x7F),
            )
        )

    idx = {n: i for i, n in enumerate(header)}

    def col(name: str) -> list[str]:
        return [r[idx[name]] for r in data] if name in idx else []

    blank_lease = sum(1 for v in col("LEASE_NUMBER") if not v.strip())
    if blank_lease:
        out.append(Anomaly("blank_lease_number", "LEASE_NUMBER empty", blank_lease))

    lead_ws = sum(1 for v in col("LEASE_NUMBER") if v != v.strip() and v.strip())
    if lead_ws:
        out.append(
            Anomaly(
                "lease_number_padded",
                "LEASE_NUMBER carries leading whitespace (non-'G' state leases)",
                lead_ws,
            )
        )

    trail_ws = sum(1 for v in col("ACCIDENT_TYPE") if v != v.rstrip())
    if trail_ws:
        out.append(
            Anomaly("accident_type_padded", "ACCIDENT_TYPE has trailing whitespace", trail_ws)
        )

    lead_dash = sum(1 for v in col("ACCIDENT_TYPE") if v.lstrip().startswith("-"))
    if lead_dash:
        out.append(
            Anomaly(
                "accident_type_leading_delimiter",
                "ACCIDENT_TYPE is a '- '-joined multi-value list with a leading delimiter",
                lead_dash,
            )
        )

    bad_date = [v for v in col("DATE_OCCURRED") if not re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", v)]
    if bad_date:
        out.append(Anomaly("date_format", f"unexpected DATE_OCCURRED e.g. {bad_date[:3]}", len(bad_date)))

    bad_time = [v for v in col("MILITARY_TIME") if not re.fullmatch(r"\d{1,2}:\d{2}", v)]
    if bad_time:
        out.append(Anomaly("time_format", f"unexpected MILITARY_TIME e.g. {bad_time[:3]}", len(bad_time)))

    return out


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------


def write_index(header: list[str], data: list[list[str]]) -> None:
    """Write the committed spine. UTF-8, LF, values verbatim."""
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out_header = [COLUMNS.get(h, "src_" + h.lower()) for h in header]
    with OUT_CSV.open("w", encoding="utf-8", newline="\n") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(out_header)
        w.writerows(data)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="psm.spine", description=__doc__)
    ap.add_argument("--force", action="store_true", help="re-download even if cached")
    ap.add_argument("--verify", action="store_true", help="hash check only, do not rebuild")
    args = ap.parse_args(argv)

    zip_bytes = fetch_zip(force=args.force)
    txt_bytes = extract_member(zip_bytes)

    z_hash, t_hash = sha256(zip_bytes), sha256(txt_bytes)
    print(f"[spine] sha256  zip {z_hash}")
    print(f"[spine] sha256  txt {t_hash}  ({len(txt_bytes):,} bytes)")
    if z_hash != LAST_OBSERVED["zip_sha256"]:
        print(
            f"[spine] NOTE    upstream differs from the {LAST_OBSERVED['captured_utc']} capture "
            f"(expected zip {LAST_OBSERVED['zip_sha256']}). BSEE refreshes this file daily; "
            "this is informational, not an error."
        )

    header, data = parse(txt_bytes)
    print(f"[spine] parsed  {len(data):,} rows x {len(header)} columns")
    print(f"[spine] columns {[COLUMNS.get(h, 'src_' + h.lower()) for h in header]}")

    anomalies = find_anomalies(header, data, txt_bytes)
    # NOTE: repo convention puts anomalies in data/interim/anomalies.jsonl. This
    # module only prints them, to avoid contending with the concurrently-written
    # harvest pipeline for that file. Redirect stdout to append if you want them
    # persisted:  uv run python -m psm.spine | grep '^{' >> data/interim/anomalies.jsonl
    for a in anomalies:
        print(a.as_json())

    if args.verify:
        return 0

    write_index(header, data)
    built = OUT_CSV.read_bytes()
    print(f"[spine] wrote   {OUT_CSV.relative_to(REPO_ROOT)} ({len(built):,} bytes)")
    print(f"[spine] sha256  out {sha256(built)}")
    print(
        "[spine] manifest row: "
        f"data/raw/IncInvRawData.zip,{ZIP_URL},{z_hash},{len(zip_bytes)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
