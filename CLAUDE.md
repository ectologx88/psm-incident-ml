# psm-incident-ml — conventions

Public, reproducible dataset + baseline models for process-safety incident
investigation ML. Source: US federal offshore incident reports (BSEE).
Target schema: Energy Institute PSM Framework **Element 19** (Incident Reporting
& Investigation).

Audience is a public hackathon. **Every claim this repo makes about data
provenance must be checkable by a stranger.**

---

## Column provenance prefixes — the single most important convention

Every column in every processed table carries its origin in the name, because
this project deliberately mixes real and generated data.

| Prefix  | Meaning |
|---------|---------|
| `src_`  | extracted verbatim from a BSEE PDF or CSV |
| `xw_`   | deterministic crosswalk from a `src_` field via `schema/crosswalk.yaml` |
| `llm_`  | assigned by a model — never treated as ground truth |
| `gold_` | assigned by a human — the only thing you may score against |
| `syn_`  | fully generated, corresponds to nothing real |

A column with no prefix is a bug. `tests/test_conventions.py` enforces this.

## The crosswalk is data, not code

`schema/crosswalk.yaml` encodes an *opinion* about how BSEE cause categories map
to EI PSM elements. It will be argued with. Keep it readable in one screen,
version it, and **never bury a mapping in a Python dict.**

## Never report a metric scored against `llm_` columns

Accuracy against model-generated labels measures agreement with the labeller,
not correctness. Score against `gold_` only, and always state n.

---

## Extraction rules (learned the hard way — do not regress)

**1. Text-stream order ≠ visual order.** In sampled MMS Form 2010 PDFs the field
label `18. LIST THE PROBABLE CAUSE(S)` appears *after* its own content in the
extracted text stream. Pre-2021 reports linearize as interleaved two-column soup
where checkbox `X` marks detach from their labels entirely:

```
1. OCCURRED
X
X STRUCTURAL DAMAGE
DATE: 17-OCT-2020 TIME: 0445 HOURS CRANE
```

Use **coordinate-aware extraction** (`pdfplumber`, bbox) and reconstruct fields
by position. `pypdf` / naive `extract_text()` produces confidently wrong labels.
Do not use the `pdf` skill's text path for field assignment.

**2. Empty ≠ parse failure.** Some reports have genuinely blank fields 18/19
(e.g. SP 57-B Cox, Oct 2020 — third-party vessel allision outside BSEE
jurisdiction). Every record carries an explicit `src_cause_status`:

| Value | Meaning |
|---|---|
| `typed` | controlled-vocabulary category present in field 18/19 |
| `freetext` | prose present, no controlled category |
| `absent_legitimate` | field present and genuinely empty |
| `parse_failed` | could not locate or read the field |

Conflating these sends you chasing phantom bugs and silently dropping valid
records.

**3. Source data is dirty and stays dirty.** One report dates its onsite
investigation `29-JUN-0202`. Log anomalies to `data/interim/anomalies.jsonl`;
do not silently repair them.

---

## Reproducibility contract

`data/raw/` is gitignored. `data/manifest.csv` is **committed**, with a SHA256
per file, so anyone can rebuild byte-identical inputs from a fresh clone.

Committed: `data/manifest.csv`, `data/processed/*.csv` (<10MB), `gold/`, `schema/`.
Gitignored: `data/raw/`, `data/interim/`.

## Do not commit

- `E19 Investigation Report - Rev2.xlsx` or any derivative of that workbook —
  it is a workplace document. `schema/e19_target.yaml` is **hand-written** and
  contains only field names and picklist vocabularies needed as targets.
- EI PSM Framework element *names* may be referenced with attribution (they are
  published by the Energy Institute); the workbook, its formulas, and its
  rollup dashboards may not.

## Stack

Python 3.11+, `uv`. Run entry points as modules:

```bash
uv run python -m psm.harvest && uv run python -m psm.fetch && uv run python -m psm.extract
```

## Running log

`docs/findings.md` — dated entries, append-only. Record what was verified and by
what method, including negative results.
