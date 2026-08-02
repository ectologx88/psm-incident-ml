"""Download source PDFs listed in ``data/manifest.csv`` into ``data/raw/``.

Fills the manifest's ``src_sha256`` column. On re-run, a file whose SHA already
matches is skipped; a file whose SHA *differs* is reported loudly rather than
silently overwritten — that is the reproducibility contract doing its job.

Run:  ``uv run python -m psm.fetch``
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
import time
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "data" / "manifest.csv"
RAW = REPO / "data" / "raw"

USER_AGENT = (
    "psm-incident-ml/0.1 (public research dataset; "
    "https://github.com/ectologx88/psm-incident-ml)"
)
DELAY_SECONDS = 0.7  # be a good citizen on bsee.gov


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _url_for(row: dict) -> str | None:
    """Prefer the canonical fetch URL; fall back to the published href.

    Some published links point at hosts that no longer resolve, so harvest
    records both forms. See docs/findings.md.
    """
    for key in ("src_url_canonical", "src_url", "src_url_published"):
        if row.get(key):
            return row[key]
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    ap.add_argument("--raw", type=Path, default=RAW)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--delay", type=float, default=DELAY_SECONDS)
    args = ap.parse_args(argv)

    if not args.manifest.exists():
        print(
            f"{args.manifest} not found — run `python -m psm.harvest` first",
            file=sys.stderr,
        )
        return 1

    with open(args.manifest, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    fieldnames = list(rows[0].keys()) if rows else []
    if "src_sha256" not in fieldnames:
        fieldnames.append("src_sha256")

    args.raw.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    stats = {"downloaded": 0, "cached": 0, "failed": 0, "sha_mismatch": 0}
    for row in rows[: args.limit]:
        url = _url_for(row)
        name = row.get("src_filename") or (url.rsplit("/", 1)[-1] if url else None)
        if not url or not name:
            stats["failed"] += 1
            row["src_fetch_note"] = "no usable url or filename in manifest"
            continue

        dest = args.raw / name
        expected = (row.get("src_sha256") or "").strip()

        if dest.exists():
            actual = sha256_file(dest)
            if not expected:
                row["src_sha256"] = actual
                stats["cached"] += 1
                continue
            if actual == expected:
                stats["cached"] += 1
                continue
            stats["sha_mismatch"] += 1
            row["src_fetch_note"] = f"SHA MISMATCH local={actual} manifest={expected}"
            print(f"  SHA MISMATCH {name}: local {actual[:12]} != manifest {expected[:12]}",
                  file=sys.stderr)
            continue

        try:
            resp = session.get(url, timeout=90)
            resp.raise_for_status()
            data = resp.content
        except Exception as exc:  # noqa: BLE001 - one bad URL must not stop the run
            stats["failed"] += 1
            row["src_fetch_note"] = f"{type(exc).__name__}: {exc}"
            print(f"  FAILED {name}: {type(exc).__name__}", file=sys.stderr)
            time.sleep(args.delay)
            continue

        actual = sha256_bytes(data)
        if expected and actual != expected:
            stats["sha_mismatch"] += 1
            row["src_fetch_note"] = f"SHA MISMATCH downloaded={actual} manifest={expected}"
            print(f"  SHA MISMATCH {name}: upstream file changed since manifest",
                  file=sys.stderr)
        dest.write_bytes(data)
        row["src_sha256"] = actual
        stats["downloaded"] += 1
        time.sleep(args.delay)

    if "src_fetch_note" not in fieldnames:
        fieldnames.append("src_fetch_note")
    with open(args.manifest, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fieldnames})

    print(f"fetch complete -> {args.raw}")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    return 1 if stats["sha_mismatch"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
