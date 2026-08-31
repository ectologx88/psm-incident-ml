# Findings

Running verification log. Dated, append-only. Records what was checked, by what
method, and what came back — including negative results and things that
contradicted our starting assumptions.

---

## 2026-08-02 — Stage 1: acquisition and vocabulary induction

### Summary of what changed relative to the project brief

| Brief said | Actually |
|---|---|
| 2,011 investigations in the structured listing | **2,014** (the site's own pager says `Page 1 of 101 (2014 items)`) |
| 342 PDF links, covering 2018–2026 | **576 unique PDF hrefs**, covering **2014–2026** on the same page |
| Cause vocabulary has 6 categories incl. "Human error" | 6 categories confirmed, but the label is **"Human Performance Error"** |
| Typing standardises around 2023–24 | Boundary is **2021→2022**, and it is a **gradient, not a switch** |
| Typing may be district-specific | **It is not.** Temporal signal is ~3x stronger than district |
| Structured export might carry cause data | **It does not.** Metadata only — the PDF pipeline is required |

---

### Task 2 — does the structured export carry cause data?

**No. Definitively metadata only.** This was the gating question, and the answer
means the PDF pipeline cannot be reduced.

Seven columns: `DATE_OCCURRED`, `MILITARY_TIME`, `LEASE_NUMBER`, `AREA_BLOCK`,
`ACCIDENT_TYPE`, `PANEL_DISTRICT`, `STATUS`. No cause, narrative, findings, or
recommendation field.

Verified three independent ways rather than by inference:
1. Bulk zip export → 7 columns.
2. ASP.NET CSV export driven to completion → same 7 columns.
3. The rendered grid declares exactly 7 filter editors (`DXFREditorcol1`…`col7`)
   and 7 header cells — no hidden column, no detail row, **no link column**.

Row-multiset diff of paths 1 and 2: 2,013 of 2,014 rows identical; the single
difference is an encoding artifact, not data.

`ACCIDENT_TYPE` is the closest thing to causation and is **not** a cause. It is
an incident *classification* (`- Fire`, `- Pollution`, `- Crane`, `- Fatality`)
mirroring the 30 CFR 250.188 reportable-incident thresholds — *what tripped*,
not *why*.

**Retrieval — no browser, no postback, no session required:**

```bash
curl -L -A "Mozilla/5.0" -e "https://www.data.bsee.gov/Main/RawData.aspx" \
  https://www.data.bsee.gov/Other/Files/IncInvRawData.zip -o data/raw/IncInvRawData.zip
```

Verified idempotent across two consecutive runs (byte-identical output).

**Gotchas recorded so nobody re-derives them:**
- The file is **cp1252, not UTF-8** (one `0x96` EN DASH). UTF-8 decode raises;
  latin-1 silently corrupts. The *web CSV export* serves that byte inside a
  `charset=utf-8` response, so the postback path yields mojibake — **the bulk
  zip is the cleaner source**, the opposite of the intuitive assumption.
- The CSV export button sets `useSubmitBehavior: false`, so its `name=` is never
  submitted. Posting `ASPxFormLayout2$btnCsvExport=CSV` returns HTML; the actual
  trigger is `__EVENTTARGET=ASPxFormLayout2$btnCsvExport`.
- The field-definitions page lists `AREA_BLOCK` twice and never names
  `ACCIDENT_TYPE`. This is a **BSEE documentation defect**, not async
  truncation: the phantom row with a blank definition is positionally
  `ACCIDENT_TYPE`. The real column set is 7 and the page does list 7 rows,
  just mislabelled.

**Anomalies logged, not repaired:** 40 rows with a missing hour in
`MILITARY_TIME` (`":15"`, `":0"`, one bare `":"`) — present in *both* retrieval
paths, therefore upstream; 52 blank lease numbers; 265 leases with meaningful
**leading whitespace** (state vs federal — do not `strip()`).

**Join to the district PDFs — viable, but the reverse direction is the problem.**
Key is `(date, minutes-since-midnight)` with area/block as validator, falling
back to `(date, lease_number)`.

| Outcome | n | % |
|---|---|---|
| Tier 1 unique | 1,186 | 94.6% |
| Ambiguous | 0 | 0.0% |
| Tier 2 rescue | 10 | 0.8% |
| **Total unique** | **1,196** | **95.4%** |

Both normalisations are load-bearing — naive string equality on the same fields
scores 36%. **The number that should shape planning:** roughly **818 of 2,014
spine rows (~41%) have no district PDF at all** (the listing starts 2003, the
spine reaches 1995, plus 81 `PANEL` rows and 11 `Pending`). Budget for cause
text on well under two-thirds of rows.

---

### Extraction — text-stream order vs visual order

**Confirmed on real files.** `page.extract_text()` on a 2026 report returns:

```
1. OCCURRED
STRUCTURAL DAMAGE
DATE: 24-MAY-2026 TIME: 1138 HOURS CRANE
```

— two columns interleaved, checkbox `X` marks detached from their labels.

**The fix is cheaper than expected.** Bucketing words into rows by `top`
(tolerance 2.5pt), sorting rows top-to-bottom and words left-to-right, and
splitting the form face at its gutter, fully restores reading order. Field
labels then land *before* their content, so the reported label-after-content
inversion is purely an artifact of stream-order extraction, not a property of
the documents. No OCR needed anywhere in the sample — all 63 files had a text
layer.

Three bugs found and fixed while building this, worth recording because each
produced *plausible but wrong* output rather than an error:

1. **Gutter detection always returned `None`.** The row-crossing test correctly
   identified x≈270–302 as clear, then a second widening step re-measured the
   band against page-wide pixel occupancy — a stricter, contradictory
   criterion. Every page came back single-column. Fix: measure the band with
   the same test that selected it.
2. **Strict ascending field numbers silently dropped fields.** The closing
   admin block is two-column, so the stream reads `25. … 28. …` then
   `26. … 29. …`; requiring ascending numbers discarded fields 4–7, 26, 27 and
   29 on most reports. Fix: accept on label match, suppress duplicates, and
   treat out-of-order as an informational anomaly.
3. **`Flexi-Coil` parsed as a cause category.** A separator alternative
   `(?<=[a-z])-(?=[A-Z])` split ordinary hyphenated compounds, inventing a
   category `The Flexi`. Fix: an ASCII hyphen is a separator only when followed
   by whitespace.

**Extraction rate, n=63 stratified sample:**

| Field | Located | Non-empty |
|---|---|---|
| 17 Investigation Findings | 63/63 | 63/63 |
| **18 Probable Cause(s)** | **63/63** | **63/63** |
| **19 Contributing Cause(s)** | **63/63** | **58/63** |
| 22 Recommendations | 59/63 | 57/63 |
| 4 Lease/Area/Block | 63/63 | 63/63 |

0 parse failures, 0 files without a text layer. Fields 8–16 are missing on 10
reports and field 29 on 40 — a known remaining gap in form-face parsing on
older layouts, not yet chased because fields 17–24 carry the project's payload.

---

### Task 4 — cause vocabulary induction

**Method.** Induction was run **vocabulary-blind**: the parser extracts any
category-like prefix (≤6 words, title-ish, preceding the first `:` / `–` / `- `)
without consulting a category list. Had it matched against the six categories
from the brief, the "induced" vocabulary would just be those six reflected back.

**Sample:** 63 reports, stratified across 2014–2026, all six districts.
82 typed cause statements from fields 18 and 19.

**Result — the vocabulary collapses. 82% onto exactly six categories:**

| n | Category |
|---|---|
| 20 | Equipment Failure |
| 19 | Human Performance Error |
| 11 | Management Systems |
| 7 | Communication |
| 5 | Supervision |
| 5 | Work Environment |

**The remaining 18% is 14 distinct phrases, every one a singleton, and every one
a *subcategory* used without its parent** — `improper hand placement`,
`failure to follow safety protocols`, `lack of job safety analysis`,
`no stop work intervention`, `flawed equipment design`. These are not new
categories; they are level-2 terms appearing bare. That is a strong signal the
taxonomy is real and that authors sometimes skip the top level.

**Correction to the brief:** the dominant label is **"Human Performance Error"**
(19 occurrences), not "Human error" (which appears as a minority variant).
Anything keying on the string `Human error` will miss most of the category.

**Subcategory level is NOT yet shown to be closed.** Observed subcategories are
sparse — mostly 1–4 distinct per category at n=63 — and BSEE wording drifts
(`Inadequate equipment maintenance or equipment repairs` vs
`Inadequate preventative maintenance/Inadequate equipment repair`). Determining
whether level 2 is closed needs a substantially larger sample. **Do not assume
it is.**

### Where the typing boundary actually falls — temporal, not district

Bucketed on the incident date **inside the PDF** (field 1), not the filename —
filename years are unreliable, see below.

| Incident year | n | typed | % typed |
|---|---|---|---|
| 2014 | 4 | 1 | 25% |
| 2016 | 4 | 0 | 0% |
| 2018 | 7 | 3 | 43% |
| 2019 | 2 | 1 | 50% |
| 2020 | 4 | 1 | 25% |
| 2021 | 6 | 1 | 17% |
| **2022** | 6 | 5 | **83%** |
| 2023 | 7 | 6 | 86% |
| 2024 | 8 | 5 | 62% |
| 2025 | 7 | 6 | 86% |
| 2026 | 6 | 4 | 67% |

Collapsed: **2014–2021 = 7/27 typed (26%)**, **2022–2026 = 26/34 typed (76%)**.

| District | n | typed | % typed |
|---|---|---|---|
| New Orleans | 21 | 12 | 57% |
| Houma | 10 | 6 | 60% |
| Lake Charles | 4 | 2 | 50% |
| Lafayette | 13 | 5 | 38% |
| Houston | 2 | 2 | 100% |
| Unknown | 13 | 6 | 46% |

**Verdict: the boundary is temporal.** It falls at **2021→2022**, earlier than
the 2023–24 the brief hypothesised. The district hypothesis is not supported —
the four districts with usable n span 38–60%, a narrow band with no district
near 0% or 100%, while the temporal split is 26% vs 76%.

**Important qualifier: it is a gradient, not a switch.** 2022+ is ~76% typed,
not 100%, and 2018 was already 43%. Typing looks like a **practice that
spread**, not a form revision. Practically: **you cannot filter by year and
assume typed.** Every record needs its `cause_status` checked individually.

Caveats on this table: per-year n is 2–8, so individual years carry wide
intervals; the collapsed 26%-vs-76% split is the load-bearing claim, not any
single year. District was inferred by regex over narrative text and is
`UNKNOWN` for 13 of 63.

---

### Task 3 — corpus scope (harvest)

The "342 links, 2018–2026" figure in the brief understated the corpus in both
directions. `data/manifest.csv` holds **1,303 reports**: **1,241 district** +
**62 panel**.

Coverage reaches back to **2003**, because the district index has a **second
page** — a `district-investigation-reports-archive` — that the brief did not
account for. Split by index page: 591 rows from the main district page, 650
from the archive, 62 from the paginated panel listing.

Per-year counts on the archive side (2003:3, 2004:16, 2005:58, 2006:88,
2007:97, 2008:88, 2009:77, 2010:38, 2011:39, 2012:80, 2013:64, 2014:71,
2015:70, 2016:48, 2017:46) confirm the index's own "since 2005-01-01" claim and
slightly exceed it. 59 rows have no parseable year and carry a
`src_parse_note`; no row was dropped.

28 rows flagged redacted; 11 required URL canonicalisation. 635 of 1,303 rows
carry a non-empty `src_parse_note` — filenames are far more irregular in the
2003–2013 archive than in recent years, so filename-derived area/operator/date
should be treated as a convenience field only. **The authoritative values are
inside the PDF** (form fields 1, 2 and 4).

Spot-checked extraction against five archive-era reports (2006, 2007, 2011,
2017, 2023): all five parsed, all five located field 18 with non-empty content,
and **all five were `freetext`** — an independent confirmation of the temporal
typing finding on documents outside the induction sample.

### Corpus-level gotchas found in passing

**Filename years lie.** `2010` in a BSEE filename is usually the **form
number**, not a year — these are MMS **Form 2010**, and it leaks in as
`EV2010`, `EV2010R`, `2010_Report`, trailing `-2010`. Confirmed examples:
`W_&_T__HI_A_379-B_2010_Report_21-Feb-2024.pdf` is a 2024 report;
`gb-426-31mar19-sanitized-2010.pdf` is 2019. A last-4-digit-year heuristic
produces a spurious 2010 cohort. Parse a **date token**, and fall back to the
in-PDF field 1 date, which is authoritative.

**9 of 576 published PDF links (~1.6%) are dead as published.** They point at
`bsee_prod.opengov.ibmcloud.com`, which does not resolve (SERVFAIL; the
hostname contains an underscore, invalid in DNS). All recover by canonicalising
to `https://www.bsee.gov/sites/bsee.gov/files/<basename>.pdf` — verified
returning HTTP 200 for three of them. Two further links point at
`connect.bsee.gov` and an Acquia staging host. The manifest records both the
as-published href and the canonical fetch URL, because silently rewriting a
broken link would defeat the provenance standard.

**Redactions are undercounted by the obvious test.** 15 of 576 current district
PDFs are redacted, with inconsistent naming (`_Redacted`, ` redacted`,
` Redacted`, mid-filename); `endswith("_Redacted.pdf")` catches about a third.
The 2003–2013 archive has 0 of 656 marked, which is ambiguous between "never
reviewed" and "redacted without the convention" — treated as **unverified for
PII**, not clean.

**Dirty data left dirty**, per convention: BSEE stamps approval dates as
free-floating text that lands *inside* field 18 in visual order (e.g. a stray
`15-JUN-2021` between a category and its description). These are filtered as
page furniture at parse time, and the filter is declared in
`schema/bsee_form2010.yaml` rather than hidden in code.

---

### What is not yet verified

- Whether the level-2 subcategory vocabulary is closed (needs n >> 63).
- Panel-report joinability to the spine — not measured.
- Whether the Xls/Xlsx/Pdf/Rtf grid exports carry a wider column set than CSV.
  They render from the same server-side `ASPxGridView`, so a wider set is
  implausible rather than ruled out.
- Form-face fields 8–16 on ~16% of reports and field 29 on ~63%.
- The 2003–2013 archive has not been extracted, only counted.

## 2026-08-09 — Resolving the coverage fork (labeling vs. free-text handling)

**The fork was a false dichotomy.** Since the vocabulary induction (Task 4,
above) confirmed the extraction premise but left ~68% of the corpus as
free-text prose with no controlled cause vocabulary, the open question was
whether to (a) hand-label the gold set now against the ~32% typed subset, or
(b) first build an LLM-assisted path for the free-text majority. Gold-set
construction does not actually depend on that answer: a human labeller reads
the source PDF directly and assigns `gold_` fields regardless of whether
field 18/19 happened to use the controlled vocabulary. `src_cause_status` is
recorded per report for reference, not as a gate on whether a report is
eligible for the gold set. Building the gold set first is also the right
sequencing on its own merits — it is the fixed yardstick any future
extraction approach (crosswalk-only or LLM-assisted) gets evaluated against;
designing the extraction approach before the eval set exists risks shaping
the eval set around whatever the approach happens to handle well.

**Resolution:** proceed with gold-set construction now, stratified across
the full 2003–2026 corpus (typed and free-text eras alike), not just the
typed subset. The LLM-assisted free-text path is deferred, to be built and
scored against this gold set once it exists — not before.

**What was built**, per Task 5 of the original brief (100 reports,
stratified across years):

- `src/psm/gold_sample.py` — deterministic, year-stratified sampling from
  `data/manifest.csv`. District reports only (`src_report_type ==
  "district"`); panel reports are excluded because they are a structurally
  different, unverified document type (see "not yet verified" below) that
  this project's extraction pipeline was never built against. Selection
  within each year is by ascending `sha256(src_url)` — no stored seed, same
  determinism pattern as `src/psm/synth.py`'s hash offsets. Allocation is
  `target_n // n_years` per year, floored at 1 and capped by that year's
  availability, remainder distributed to the years with the most spare
  capacity. Run against the real manifest: **100 of 1,302 rows selected**,
  every year 2003–2026 represented (2003 capped at 3 — only 3 district
  reports exist for that year), the rest 4–5 each.
- `src/psm/gold_scaffold.py` — assembles `gold/gold_labels.csv` from the
  sampled manifest plus `extract.py`'s per-report JSON: one row per sampled
  report with `src_` reference fields (operator, area/block, date, url,
  field 18/19 raw text) pre-filled, and `gold_cause_category` /
  `gold_psm_element` / `gold_cause_status` / `gold_notes` / `gold_labeler` /
  `gold_label_date` left **blank by design**. This module never writes a
  `gold_` value — doing so would collapse the `gold_`/`llm_` distinction the
  whole provenance convention exists to protect. `src_cause_status` is
  computed per row (typed wins if either field 18 or 19 is typed; freetext
  wins over absent/parse_failed; `absent_legitimate` only when both fields
  are genuinely blank) purely as a reference hint for the labeller, with the
  caveat below.
- Fetched the 100 sampled PDFs (`uv run python -m psm.fetch --manifest
  data/interim/gold_sample_manifest.csv`) — 100/100 downloaded, 0 failures.
  Extracted all of them (`extract.py`) — 104/105 `ok` (105 = 100 sample + 5
  pre-existing dev-sample files already in `data/raw/`), 1 `parse_failed`.
  `gold/gold_labels.csv` now has 100 rows: **29 typed, 70 freetext, 1
  parse_failed** by the automated classifier — see the caveat immediately
  below before treating that split as authoritative.

**Caveat — `src_cause_status` on this sample has a known false-positive
mode, do not cite the 29/70/1 split as clean.** Verifying a 2003 report
flagged `typed` found the actual field-19 text was 100% free prose;
`candidate_category()` (`src/psm/causes.py`) matched on `"NOTE:"` and
`"LIST THE ADDITIONAL INFORMATION:"` — continuation-page furniture bleeding
into the field-19 text run from a multi-page narrative, not real BSEE cause
categories. Reproduced directly:
`candidate_category("NOTE: ABB Vetco has redesigned...")` returns
`("NOTE", "colon")` instead of `(None, "untyped_prose")`. This means the
true free-text share of this sample (and likely the corpus) is **at least
70%, plausibly higher** — the bug only pushes reports *into* `typed`, never
out of it. Flagged as a follow-up task, not fixed here, to keep this session
scoped to resolving the fork rather than re-opening the vocabulary-induction
parser. `gold_cause_status` (human-assigned) is not affected by this bug —
only the `src_cause_status` reference column is.

**Not yet done:** the actual hand-labeling. `gold/gold_labels.csv` is a
scaffold — 100 rows with real reference data and empty `gold_*` columns,
not 100 labelled examples. README's status table has been updated to say so
explicitly rather than implying the file is already labelled.

## 2026-08-09 — Fixing the `candidate_category()` furniture false positive

Follow-up to the caveat immediately above. Root-caused before fixing, per the
project's debugging discipline: scanned every typed statement across the 194
non-empty field-18/19 texts currently cached in `data/interim/` (the 100-report
gold sample plus a few pre-existing dev files) for every head `candidate_category()`
currently accepts. 41 distinct heads matched; two are furniture, not categories:

- `NOTE` (2 occurrences, both in `030521-pdf` — a continuation-page annotation)
- `LIST THE ADDITIONAL INFORMATION` / `LIST THE CONTRIBUTING CAUSE(S) OF ACCIDENT`
  (3 occurrences, `030521-pdf` and `mc-194-enven-20-jan-2020`) — a field's own
  BSEE label bleeding into another field's body text.

The other 39 (Equipment Failure, Human Performance Error, Management Systems,
Communication, Supervision, The IP, The Root Cause, Policy Violation, etc.) are
genuine BSEE cause language and must not be touched. `(Cont.)`-style markers
were already correctly rejected by the existing `head[0].isalpha()` check — no
fix needed there.

**Fix** (`src/psm/causes.py`): added `FURNITURE_HEAD_RE` (`^(?:NOTE|LIST\s+THE\b.*)$`,
case-insensitive) and a check in `candidate_category()` that returns
`(None, "furniture")` for a match, instead of treating it as a typed category.
`LIST\s+THE\b.*` is scoped to BSEE's own field-label phrasing (field 18 is
literally "LIST THE PROBABLE CAUSE(S)") rather than hardcoding field 20's
exact wording, so it generalises to any field's label bleeding into another —
confirmed by the `mc-194-enven` case above, which uses field 19's own label,
not field 20's.

**Regression tests** added to `tests/test_causes.py`: the two furniture
patterns, a cross-field generalisation case, a field-level
`classify_field()` case reproducing the full `030521-pdf` false positive, and
a negative case (`"Listing errors: ..."`) confirming the guard doesn't
collide with real categories. Full suite: 142/142 pass.

**`gold/gold_labels.csv` regenerated** (`uv run python -m psm.gold_scaffold`;
no hand-labels existed yet, all `gold_*` columns were blank, so nothing was
at risk). Exactly one row changed — `030521-pdf` (report
`d34a71a29a8cf864f4c8af727bc4249954300d2f0e7c640162aa04dc4851a9fe`), whose
`src_cause_status` flips from `typed` to `freetext`, matching the diagnosis.
New split: **28 typed, 71 freetext, 1 parse_failed** (was 29/70/1).

**Effect on the two corpus-wide numbers flagged for review:**

- **"82% of typed statements collapse to 6 categories" (Task 4, n=63,
  above).** Not reproducibly affected — none of its reported categories or
  the 14 singleton subcategories look like furniture, and the fix is scoped
  to two patterns neither of which appears in that table. But this could not
  be fully re-verified: the original n=63 file set for Task 4 was not
  preserved separately from the current `data/interim/` cache, so it is
  unclear whether it is a subset of the 194 texts scanned above. Treat the
  82% figure as **unaffected but unverified against this specific fix** —
  re-running Task 4's induction against its original file list, if
  recoverable, is a follow-up, not done here.
- **"~32% typed subset" (fork-resolution entry, above).** This was
  approximate framing, not a precise citation of the pre-fix 29/100=29%
  gold-sample figure. Post-fix it is **28/100 = 28%** typed by the automated
  classifier. Read this as a **soft ceiling, not a clean number**: only two
  furniture patterns were confirmed and fixed from one 100-report sample —
  other BSEE field-label fragments (e.g. from fields 17, 21–24) could still
  be bleeding into 18/19 undetected on reports outside this sample. The
  true typed share is `<= 28%`, direction unchanged from the original
  caveat (the bug only ever pushes reports *into* `typed`).

## 2026-08-29 — E19 label extraction: the target schema does not match the template

**Why this was run.** Adversarial review of a worked E19 sample found the field
names did not match the source workbook. The same defect turned out to be in the
repo: `schema/e19_target.yaml` is hand-written with invented snake_case names
(`incident_date`, `area_block`, `narrative_summary`) rather than the template's
actual labels. It is explicit about this — *"HAND-WRITTEN. No workbook was
opened, copied, or derived from"* — a deliberate IP-safety choice that
nonetheless leaves the schema unable to satisfy an exactness requirement.

**Decision taken:** add an **E19 projection layer** rather than rename
throughout. The internal snake_case schema stays canonical for the pipeline;
exactness becomes a property of the output. `synth.py`, `gold_scaffold.py` and
`crosswalk.yaml` are untouched.

### What was built

`src/psm/e19_schema.py` — reads the workbook **read-only** and emits
`schema/e19_labels.yaml`. Labels are never retyped: every field-name mismatch
found in review so far came from a human transcribing them. The workbook itself
remains uncommitted; the derived YAML (names and vocabularies only, no formulas
or rollup logic) is committed, consistent with CLAUDE.md's existing allowance.

Block detection is derived, not hardcoded to row numbers: the sheet's
convention is *header cell, blank row, contiguous field run*, so a run of length
one is a header and the following run is its fields. Survives a row insert.

**Result: 7 groups, 65 fields, 29 vocabularies.** Workbook SHA256 asserted
unchanged across the run. A round-trip check re-opens the workbook and compares
every emitted label and value against its source cell.

### Two extractor bugs the round-trip check caught before commit

Both produced plausible, non-erroring output — the failure mode this project
keeps hitting.

1. **`Risk Score` came out with 45 values.** Column W stacks `1..25` (the real
   risk-score vocabulary) immediately followed by `1..20` (PSM element numbers)
   with no blank row between. Read naively that is one 45-value vocabulary. Fix:
   split a column where a numeric series restarts. `Risk Score` is now n=25 and
   the trailing `1..20` is emitted separately.
2. **Values were assumed contiguous.** Several picklist columns have blank rows
   inside them, so verifying against `first_row + i` failed on eight columns.
   Fix: store each value's actual row rather than inferring a range.

A third issue is handled rather than fixed: five columns have no header of their
own (`X45`, `AI6` are bare PSM element lists; `W45`, `BF7`, `BH7` are numeric
scales). Their first cell is a *value*, not a name. Rather than invent a
vocabulary name, these are emitted with `name: null` and
`header_confident: false`, leaving identification to the consumer.

### Template irregularities, preserved verbatim

These are the real column names. Normalising them would defeat the exactness
guarantee: `Incident Classificatioin` (sic, used twice), `incident Title`
(lower-case i), `Unmittigated` / `Mittigated` (sic), `Human Factors  Cause`
(double space), ` Failed PSM Framework Element` (leading space),
`What happened?  ` (two trailing spaces), `Health & Safety  - Consequence`
(double space, and the sibling E&R and Financial fields differ from each other
in the same way).

**`Description` appears twice in one group** (E18 and E23 — the form's two
"Description if Other" fields). A flat table cannot carry two identically named
columns; the projection must disambiguate, and how it does so needs the author's
input rather than our invention.

### Diff against `schema/e19_target.yaml`

| | n |
|---|---|
| E19 fields total | 65 |
| Covered 1:1 by a differently-named target field | 33 |
| Partially covered — grain or split mismatch | 9 |
| **Absent from the target schema entirely** | **23** |
| **Name matches between the two schemas** | **0 of 65** |

Partial coverage is where the shapes genuinely differ: E19 splits location into
`Site` / `Area` / `Unit` / `Detail` where the target has one `area_block`; E19
has four `Incident Type A–D` fields where the target has one multi-enum;
`Cause Description` and `Recommendation Description` are one-row-per-item in E19
against list-valued fields in the target.

The 23 absent fields cluster in three places: **the consequence/likelihood pairs
for all three risk matrices** (the target kept only the scores), **the cause
qualifiers** (`Cause type`, `Risk Management Cause`, `Human Factors  Cause`), and
**the row keys** (`Cause number`, `Recommendation Number`).

13 target fields have no E19 counterpart at all — `lease_number`, `operator`,
`water_depth_ft`, `activity`, `operation`, `property_damage_usd`,
`regulatory_violations`, `cause_category`, `cause_status`, and others. These are
BSEE-side or project-side fields and belong in the sidecar, not in E19 output.
Note E19 has no `operator` field at all, which makes sense for an internal
company form where the operator is implicit.

**Not yet done:** `schema/e19_projection.yaml` (the mapping itself, including
blank-reason codes), `src/psm/project.py`, and the exactness test asserting
output headers equal the labels read from the template.

## 2026-08-29 — Root cause of the archive-era extraction gap

Two independent investigations, run in parallel against the same 105 raw PDFs
and 105 interim JSONs. They converged on one mechanism from different angles,
which is the main reason to trust the conclusion.

### The headline: the narrative is present and recoverable

**The archive-era field-17 gap is a parser bug, not missing data. The gold
sample does NOT need to be re-drawn.** Re-running the real `extract_report()`
with *only* field 17's `label_hint` relaxed recovered clean, complete narrative
prose (545–3,892 chars) from **22 of the 23 failing files**.

The 23rd is not our bug: `data/raw/090517-pdf.pdf` **is not an investigation
report**. Its PDF title is *"MMS to hold Public Hearings on Cape Wind Energy
Project Draft Environmental Impact Statement"* — a 2008 press release served at
an incident-report URL. `parse_failed` is the correct outcome; the parser
refused rather than inventing fields. Upstream data defect, log it.

### Root cause 1 — the form has three numbering eras; the schema encodes one

`schema/bsee_form2010.yaml` states *"Field numbers are stable across eras; LABEL
WORDING IS NOT."* **The first half is false**, and it is the largest single
cause of damage across the corpus.

| Era | n | Years (in-PDF field 1) | Numbering vs schema |
|---|---|---|---|
| A early | 12 | 2004–2006 | no field 3; everything from LEASE on shifted −1 |
| B mid | 53 | 2003–2017 (mode 2007–2016) | 1–7 match; **9–16 shifted −1** |
| C modern | 38 | 2017–2026 | exact match |

Field 17's label also changes: the older revision reads
`17. DESCRIBE IN SEQUENCE HOW ACCIDENT HAPPENED:` where the modern one reads
`17. INVESTIGATION FINDINGS:`. The correlation is perfect across all 105 files —
81/81 located under the modern wording, **0/22** under the old.

**Why it fails silently.** Content runs anchor-to-next-anchor. When
`_label_matches()` rejects an anchor, that field's content is absorbed into the
*previous accepted* field rather than being dropped. Verified: `070822-pdf` has
`src_f07_type` at **2,356 chars** holding fields 8–16 plus the whole narrative;
`060411-pdf` has `src_f02_operator` at **2,556 chars** holding most of the form
face. A `checkbox_set` field silently containing prose is worse than an empty
column.

One thing the hint gate gets right: a shifted anchor never produces *wrong
content under a right name*. The failure is absence-plus-absorption, not
mislabelling. No `src_f10_water_depth` anywhere contains a non-depth.

**Correction to a previous entry.** "Fields 8–16 missing on 10 reports, field 29
on 40 — a known remaining gap in form-face parsing on older layouts" (2026-08-02)
misdiagnosed this. f08 is present on exactly the 38 modern-era reports; the other
67 did not fail to parse, their content was absorbed.

### Root cause 2 — `find_gutter()` fails on the closing admin block

Page 0 gutter detection succeeds 104/105. The admin page (the one with
`DISTRICT SUPERVISOR`) succeeds **31/105**. Without a gutter, left and right
columns merge into single rows — `bp-mc-778-a-6-june-2022.pdf` p3 emits
`25. DATE OF ONSITE INVESTIGATION: ACCIDENT CLASSIFICATION:` as one line, which
is exactly the f28→f25 bleed originally reported.

### Root cause 3 — `ROW_TOL` is a hard bin edge, not a tolerance

`_rows()` buckets on `round(top/2.5)`, so words 0.5pt apart can land in
different bins when they straddle a boundary. `25. …` (top 275.9 → bin 110) and
`28.` (top 276.4 → bin 111) split; the orphan `28.` then fails `ANCHOR_RE`.
**41 orphan `NN.` lines across 27 records**; records with an orphan lose f28
21/27 of the time.

### Root cause 4 — the terminal anchor is an unbounded sink

`segment_fields()` runs the last anchor to end-of-document. **48/105 reports
have pages after the admin page** (injury, witness, crane attachments). f30
median length is 35 chars, p90 is 1,290; `vr-131-stone-energy-17-september-2012`
holds **6,049 characters** in a field that should contain one name.

### Contamination by field — the payload is clean, the metadata is not

Rate = records whose value contains ≥1 label owned by a different field.

| Field | n | contaminated | severity |
|---|---|---|---|
| f17 findings | 82 | **0%** | clean where present |
| f18 probable cause | 104 | **0%** | clean |
| f19 contributing cause | 103 | **1%** | clean |
| f22 recommendations | 95 | **0%** | clean |
| f04 lease/area/block | 92 | 1% cross-field | but **97% intra-box misalignment — meaning-changing** |
| f07 type | 91 | **58%** (100% of era B) | severe; median 45% of value is foreign |
| f26 team members | 103 | **70%** | severe; **55% *begin* with a foreign label** |
| f30 district supervisor | 93 | **53%** | severe; real name at start, unbounded tail after |

**The project's payload fields (17–24) are essentially uncontaminated. The
damage is concentrated in identification (4, 5, 7) and the admin block (25–30).**

A separate universal but **cosmetic** class: own-label retention. When an anchor
line has no colon the label-strip does not fire and the field keeps its own
`NN. LABEL` — f01 100%, f03 100%. f01 still yields a parseable date on 101/103.

### `out_of_order_anchor` is a success indicator, not a warning

30/105 records carry it. f26 is contaminated on 9/30 records that have it versus
**63/73** that do not. The anomaly fires when the admin columns *were* split
correctly (left 25,26,27 then right 28,29,30 — legitimately out of order). Any
triage keyed on this flag would select the healthiest records. Do not use it as
a quality signal.

Genuinely predictive flags, none currently logged: form era (derivable from
which number carries `WATER DEPTH`); gutter-not-found on the admin page;
presence of an orphan `NN.` line; pages existing after the admin page.

### Downstream exposure — latent, not yet propagating

`gold_scaffold.py` is the only consumer of any `src_fNN_` column and reads
exactly two: f18 and f19, both clean. Its area/block/operator come from
`data/manifest.csv`, not from f02/f04. `synth.py` reads no `src_f*` at all.
`causes.py`'s `FURNITURE_HEAD_RE` is scoped to 18/19 and masks nothing found
here.

**One forward-looking trap.** The 2026-08-02 entry commits to *"The
authoritative values are inside the PDF (form fields 1, 2 and 4)"* as the remedy
for unreliable filename-derived metadata. As of today f04 is misaligned on 97%
of records and f02 is a whole-form dump on all 12 era-A records — the designated
authoritative source is currently the worse of the two options. Do not act on
that recommendation until root cause 1 is fixed.

### Verified vs inferred

**Verified** by opening PDFs and re-running layout/extraction over all 105:
text layers present on 105/105 (no OCR needed anywhere); the `DESCRIBE IN
SEQUENCE` wording and its 81/81 vs 0/22 correlation; the three-era numbering
table (53/53 and 10/10 within cluster); gutter 31/105 admin vs 104/105 page 0;
41 orphans / 27 records; 48 records with post-admin pages; the
`out_of_order_anchor` anti-correlation; the 22/23 recovery with zero regression
on field 18; `090517-pdf` being a press release; the downstream consumer
inventory.

**Inferred:** corpus-wide exposure of roughly **300–350 reports** with the old
field-17 wording, extrapolated from 30 downloaded 2004–2009 files against
manifest per-year counts. The label→owning-field map used for intrusion
detection is a reading of the form's box structure, not a published source.

**Could not check:** the ~1,140 reports not in `data/raw/`; whether more than
three revisions exist pre-2003 or among panel reports; whether recovered
narratives contain the sub-structure the schema expects.

**A methodological note worth keeping.** An early `pdftotext -layout` pass
suggested 2007-era files swap fields 6/7. The coordinate-aware read shows they
do not — a pdftotext column-ordering artifact, and a clean illustration of why
CLAUDE.md forbids the text path for field assignment.

## 2026-08-29 — P0 remediation landed

Implements P0 of `docs/superpowers/plans/2026-08-29-extraction-remediation.md`.
Measured before/after on the same 105 PDFs and the same era split used in the
diagnosis.

### Result

| Check | Before | After |
|---|---|---|
| Archive-era (2003–2013) field 17 fill, gold sample | 26/48 = **54.2%** | 47/48 = **97.9%** |
| Current-era (2014–2026) field 17 fill | 52/52 = 100% | 52/52 = 100% (no regression) |
| Records carrying `src_form_revision` | 0 | 105/105 |
| Test suite | 142 | 159 |

The one remaining archive miss is `090517-pdf`, which is not an investigation
report — see below. **The gold sample is now labellable across both eras.**

### What changed

**Field 17 label alternates.** `label_hint` now accepts a list; a list matches
if any alternate is present. Added `DESCRIBE IN SEQUENCE` for the pre-2010
wording. Roughly the 10-line change the diagnosis predicted.

**`src_form_revision` on every record.** Detected from the raw anchor stream,
not from extracted fields — on revisions A and B the deciding anchors are
rejected by the label hints, so by the time `fields` exists the evidence has
been discarded. Distribution across the 105: **A 13, B 53, C 38, unknown 1**.
The agent diagnosis predicted 12/53/38; the extra revision-A record is a
one-file discrepancy not chased, and the `unknown` is the press release.

**Length-sanity guard.** Flags structured fields holding far more text than
their kind allows. Raises an anomaly and never truncates, per the dirty-data
convention.

**`not_an_investigation_report` status.** A text layer with no Form 2010
markers is now distinguished from `parse_failed`. Generalised on markers rather
than hardcoding the filename, so any future non-report URL is caught. Confirms
`090517-pdf`, which BSEE serves as a 2008 MMS press release at an
incident-report URL.

### The length guard was calibrated wrong on the first attempt — worth recording

The initial thresholds fired on **104 of 105 records**, which is a guard that
says nothing. Root cause: a 400-char `checkbox_set` cap, where revision-C field
7 runs a legitimate **median of 533 chars** of checkbox labels and maxes at 562.
All 38 correct records tripped it.

Recalibrated against **revision C as the baseline**, since that is the only era
where extraction is known correct: each cap now sits above revision C's observed
maximum with headroom.

| | Before | After |
|---|---|---|
| Records tripping the guard | 104/105 | **66/105** |
| Revision-C firings (false positives) | 38 | **0** |

Firings after recalibration, by revision:

| Field | A (n=13) | B (n=53) | C (n=38) |
|---|---|---|---|
| 2 operator | 12 | 0 | 0 |
| 7 type | 1 | 52 | 0 |
| 30 district supervisor | 6 | 18 | 0 |
| 27 operator report | 0 | 3 | 0 |
| 6 activity | 0 | 1 | 0 |

Every firing is on revision A or B, exactly where absorption was diagnosed, and
none on C. The distribution independently corroborates root cause 1: field 7
absorbing content on 52 of 53 revision-B records is the fields-8–16 shift, seen
from the other side.

**The generalisable lesson:** calibrate an integrity check against the subset
where the pipeline is known correct, then confirm it stays silent there. A
threshold picked by intuition fired on 99% of inputs and would have been noise
from day one.

### Not fixed here, unchanged from the plan

P1 per-revision field map (fields 3–16 remain rejected on revisions A and B,
their content still absorbed). P2 admin-block gutter, terminal-anchor sink,
`ROW_TOL` bin edges. P3 field 4 intra-box alignment. The `src_form_revision`
column now makes all three testable by era.

`schema/bsee_form2010.yaml`'s header comment previously asserted *"Field numbers
are stable across eras"*. Corrected — it is false, and it is the reason this
class of bug went unnoticed.

## 2026-08-29 — E19 projection: what BSEE can actually fill

Delivers the verbatim E19 mapping. Four relational tables whose column names are
byte-exact E19 field labels, read from `schema/e19_labels.yaml` at runtime and
never hardcoded. Nothing is crosswalked, inferred or synthesised.

### Output

| Table | rows | cols |
|---|---|---|
| `incidents.csv` | 104 | 43 |
| `causes.csv` | 330 | 7 |
| `recommendations.csv` | 93 | 12 |
| `closeout.csv` | 93 | 4 |
| `bsee_unmapped.csv` (sidecar) | 104 | 15 |

### The headline number

Of the **65 E19 fields**:

| | n |
|---|---|
| **Populated from BSEE** | **23** |
| Had a source but returned nothing | 0 |
| Blank — `judgement` (needs a human) | 27 |
| Blank — `structural` (nothing in the document answers it) | 13 |
| Blank — `extractable` (in field 17 prose, phase 2) | 2 |

Fill rates on the populated 23 (n=104 incidents):

| Field | fill |
|---|---|
| Incident Number, How did the incident occur, What happened? | 100% |
| Date of Incident | 97.1% |
| Investigation leader - Name | 95.2% |
| Site | 93.3% |
| Time of Incident, Description, Acceptor/Approver Name + Position | 87.5% |
| Area | 84.6% |
| Unit | 60.6% |
| Detail | 33.7% |
| Incident Classificatioin / Incident Classification | 23.1% |

`Detail` and `Incident Classificatioin` are genuinely thin in the source — rig
name and field 28 are frequently blank on the form itself — not extraction
failures.

### Two extractor decisions worth recording

**`What happened?` was 14.4% on the first run.** Keying on an explicit
`INCIDENT SUMMARY` heading found only 15/104, because most reports do not print
one. Where the heading is absent the opening of the narrative *is* the summary,
so the rule now takes everything before the first later subheading. **14.4% →
100%.**

**`How did the incident occur` deliberately returns blank** when a report has no
`SEQUENCE OF EVENTS` heading, giving 23.1% rather than 100%. Falling back to the
whole narrative would copy `What happened?` into both columns and imply a
separation the document does not make. Accuracy over coverage.

### Design notes

`schema/e19_projection.yaml` carries one entry per E19 label, each with either a
`source` or a `blank` reason code — enforced by test, so no field can be silently
absent. Tests also assert the mapping invents no field the template lacks, and
that emitted headers equal the template's labels as a set.

**`Description` appears twice** in Incident Information (E18 and E23, the form's
two "Description if Other" fields). A flat table cannot carry two identically
named columns and both would draw from the same BSEE source, so they collapse to
one, recorded under `collapsed_duplicates`. Needs the template author, not our
invention.

`Investigation Acceptor/Approver (Owner)- Position` is filled with the literal
`"District Supervisor"` when field 30 is non-empty — the field's own label is the
position. Borderline between a source value and an inference; flagged in the map
rather than presented as clean.

Names are pseudonymised at projection time with a committed salt (`INV-xxxxxx`,
`SUP-xxxxxx`), stable per person corpus-wide.

### Caveat

Incident Number is `{AREA}-{BLOCK}-{YYYYMMDD}-{HHMM}`, constructed because BSEE
publishes no identifier. Zero collisions across 104 records. But area/block are
parsed from field 4, which the contamination audit found misaligned on 97% of
records — a targeted regex recovers them at 93%/85%, well above what positional
parsing would give, yet at least one key looks wrong (`LB-6488-...`, where `LB`
is likely "Lift Boat" rather than an area code). **Treat the key as stable and
unique, not as a clean location reference**, until P1 and P3 land.

## 2026-08-29 — Session 1 crosswalk, and a severity bias in the corpus

Applied `schema/xw_incident_type.yaml` via new `psm.crosswalk`. Output is a
separate enriched copy plus a cell-level provenance table, so inferred values are
never mistaken for read ones.

| Field | filled by crosswalk |
|---|---|
| Incident Type A | 1,037 / 1,215 = **85.3%** |
| Incident Type B | 784 = 64.5% |
| Incident Type C | 716 = 58.9% |
| Incident Type D | 233 = 19.2% |

13,136 `src` cells against 2,770 `xw` cells. Type D is low by choice: Crane and
Other Lifting Device (271 records) resolve to null because they name equipment,
not mechanism.

### Three resolutions reached by checking rather than asking

**`Injury TLI`** is defined nowhere public, and this workbook is not an EI
publication, so it may be the author's own abbreviation. It does not matter:
BSEE's `LTA` means *days away from work* and `RW/JT` means *restricted work or
job transfer*, so aligning the ladders puts LTA in slot three regardless of what
TLI expands to. Both LTA duration bands map there; BSEE's 1-3 vs >3 split has no
E19 counterpart.

**Bare `Injury` → null, not Minor.** A draft defaulted it to `Injury Minor`.
Narrative sampling killed that: 135 of 148 carry no severity atom, and the ones
that do co-occur with `Fatality` 12 times and never with a minor code. It reads
as an older tag predating the LTA/RW-JT vocabulary.

**`Crane` → Type D null.** A draft proposed `Dropped Object` as the modal case.
151 narratives show boom failures, an injury during a crane *inspection*, rigging
and positioning incidents, and loads lost overboard. A modal guess would be wrong
on a large minority of 177 records.

**`Injury Permenant Disability` is structurally unreachable.** BSEE classifies by
duration away from work; permanence is a different axis (IOGP maintains an FPI
framework, BSEE does not use it). No mapping effort reaches this value.

Precedence turned out to matter far less than expected: 39.4% of spine rows carry
2+ atoms, but only **36** carry two competing injury atoms, and response atoms
never compete for Type C.

### The finding that matters most: panel exclusion is a severity filter

`Injury Fatality` came out at **3 of 1,215**, against 85 `Fatality` rows in the
spine. Investigating that gap found a systematic bias:

| Accident type | spine n | PANEL | share |
|---|---|---|---|
| **Fatality** | 85 | 46 | **54.1%** |
| Blowout | 58 | 18 | 31.0% |
| Explosion | 74 | 5 | 6.8% |
| Pollution | 436 | 16 | 3.7% |
| Fire | 514 | 10 | 1.9% |
| Crane | 197 | 3 | 1.5% |

BSEE convenes a panel for death, serious injury or significant pollution — so
**panel reports are the high-severity tail**, and `psm.project` excludes them
because the extractor was never built against that document type. Excluding them
is right on parsing grounds and wrong on sampling grounds: it removes over half
of all fatalities and a third of blowouts.

**Any model trained on this corpus is trained on a corpus with the worst outcomes
systematically thinned.** That belongs in the README, not only here.

**Unexplained, flagged rather than buried:** 39 fatality incidents are DISTRICT,
not panel, so they should be reachable — yet only 3 join to `incidents.csv`. The
spine covers incidents while the manifest covers *published reports*, so some
spine rows may have no district report at all. Not yet verified.

## 2026-08-29 — Session 2: PSM element crosswalk re-based

`schema/crosswalk.yaml` v1 was keyed to a different element numbering than the
target template, for its whole life, uncaught. It routed Equipment Failure to
element **7** while its own note described *"maintenance, inspection and repair
adequacy"* — element 7 in the template is `Documentation, records and knowledge
management`; `Inspection and maintenance` is **15**. Applying v1 would have put a
wrong element on all 3,462 cause rows.

The reasoning in each note was sound. Only the anchoring was wrong, so v2
re-matches each note's own description against the template's element names and
records `matched_on` and `was_v1` per entry, making the re-basing auditable.

| Category | v1 | v2 | matched on |
|---|---|---|---|
| Equipment Failure | 7 (+10) | **15** (+11) | maintenance, inspection, repair adequacy |
| Human Performance Error | 13 (+12) | **3** (+8) | competence / human factors |
| Management Systems | 3 (+1) | **8** (+6) | no written job procedures / inadequate hazards analysis |
| Communication | 12 (+3) | **9** (+17) | shift handover, instruction, job briefing |
| Supervision | 13 (+3) | **17** (+3) | supervision of a task in progress |
| Work Environment | 10 (+7) | **6** (+11) | workplace layout, weather, marine environment |

**Supervision departs from v1's reasoning, not just its numbering.** v1 routed it
to the same element as Human Performance Error on adjacency grounds. The
statements describe a supervisor failing to enforce a defined procedure during
work in progress, which is work control rather than competency. Contested;
element 1 is also arguable. Left at low confidence.

**The trap avoided, now guarded by test.** Element 5 is `Communication with
stakeholders` — external and corporate. Matching the BSEE category
`Communication` to it on the shared word would route shift-handover failures to
stakeholder communication. `test_communication_is_not_element_five` asserts it.

### A coverage bug, separate from the numbering

v1's Human Performance Error note said *"Normalise before lookup"*. Nothing did.
The six keys matched only **54.1%** of typed statements: `human error` (64) and
`management system` (17) went unmapped **purely on spelling**.

An `aliases` block now implements what v1 already declared — and note this is not
the open Session 3 question about whether "human error" and "human performance
error" are the same concept. v1 answered that when it listed "Human error" as a
surface variant of the dominant form; the ruling was just buried in prose.

| | of typed statements |
|---|---|
| matched before aliases | 367 / 679 = 54.1% |
| matched after aliases | **451 / 679 = 66.4%** |

### Applied

`psm.crosswalk` now enriches causes as well as incidents, writing
` Failed PSM Framework Element` (the template's leading space preserved) with the
element number, plus `causes_provenance.csv`.

| | n | share of all statements |
|---|---|---|
| mapped | 451 | 13.0% |
| typed but unaliased | 228 | 6.6% |
| untyped free text | 2,783 | **80.4%** |

The 80.4% ceiling is unchanged by anything in this session and is not reachable
by crosswalking. It is the LLM-assisted path, which is downstream of a gold set.

`tests/test_crosswalk.py` (15 tests) asserts every element number resolves to a
real template element, that each entry records what it was before, and that the
incident-type values come from the template's own picklists.

## 2026-08-29 — Session 3: cause qualifiers

Three E19 fields: `Cause type`, `Risk Management Cause`, `Human Factors  Cause`.
Prep changed the shape of all three before any mapping was written.

### Level 2 is confirmed OPEN, not closed

`findings.md` flagged subcategory closure as unverified at n=63. At full scale it
is **open**: 309 statements carry a subcategory, long-tailed free text with
drift — `Inadequate preventive maintenance` / `Inadequate preventative
maintenance`, `Inadequate supervision` / `Inadequate Supervision` /
`No supervision`. Exact-string lookup would match the modal spelling and silently
drop the rest, so `schema/xw_cause_qualifiers.yaml` matches by **case-insensitive
substring pattern, first match wins**, with sharper rules listed before
catch-alls (guarded by test).

`(cid` also appears as a subcategory: CID-encoded text sitting *below* the 5%
guard threshold is leaking into cause statements. Small, but the threshold is
marginally too permissive.

### `Cause type` — deliberately unmapped

The only available signal is which BSEE field a statement came from: field 18
*Probable Cause* vs 19 *Contributing Cause*. That is an axis of **primacy**; E19's
Immediate / Underlying / Root is an axis of **depth**. A contributing cause can be
a root cause. Mapping one to the other asserts an equivalence that does not hold.

**A gap this exposed:** `psm.project` concatenates fields 18 and 19 without
recording which a statement came from, despite the projection plan saying it
would go to the sidecar. Real provenance is being discarded, and it is exactly
what an LLM-assisted pass would want as a feature.

### Results

| Field | filled | of 3,462 |
|---|---|---|
| ` Failed PSM Framework Element` | 451 | 13.0% |
| `Risk Management Cause` | 206 | 6.0% |
| `Human Factors  Cause` | 120 | 3.5% |
| `Cause type` | 0 | by policy |

### Human Factors: filled against my recommendation, and instrumented for it

E19's Human Factors classifies **cognition** (competency / mistake / violation);
BSEE subcategories describe **behaviour** (`Inattention to task`, `Placing hand
near striking point`). My recommendation was to leave the field null on the
grounds that inferring a cognitive mode from a behavioural description is
attribution dressed as data. **Session 3 ruled to map the full subcategory set.**

Implemented, with every pattern carrying a confidence and
`causes_confidence.csv` written to the sidecar so the two kinds can be told
apart. The split is the argument, quantified:

| confidence | n | what it means |
|---|---|---|
| high | 30 | the source names the cognitive mode (`not following procedures` → Violation) |
| medium | 36 | reasonably direct (`not aware` → missing information) |
| **low** | **54** | **attribution: the source names only what the person did** |

**45% of the values in this column are inference about mental state from a
description of behaviour.** They are marked, filterable, and `xw_` — never
scorable. Anyone using this column for analysis should filter on confidence
first, and anyone reporting a metric over it should not use it at all.

Human factors are scoped to human-attributable categories only; Equipment
Failure and weather subcategories get nothing, because there is no person in them
to attribute a cognitive mode to.

### Coverage ceiling, unchanged

80.4% of statements are untyped free text and no crosswalk reaches them. Of the
679 typed, 66.4% carry a mapped category. Everything above is bounded by that.

## 2026-08-29 — Two follow-ups from Session 3

### The CID leak was a bullet glyph, not a broken text layer

`(cid` appearing as a cause subcategory looked like the document-level CID guard
being too permissive. It was not. The nine affected statements read
`Human Performance Error: (cid:129) Not aware of hazards. There were no safety
restraints...` — **`(cid:129)` is an unmapped bullet character in an otherwise
perfectly readable document.** The guard was right to leave those documents `ok`;
lowering its threshold would have wrongly condemned them.

Fixed where it belonged, in `psm.causes`: cid tokens are normalised **to a
bullet** rather than stripped, because that is what they are, so the existing
bullet handling picks them up. Bullet characters were also added to the
subcategory strip set — a cid bullet can sit mid-statement, after the category
separator, where the leading-bullet rule has already run and cannot reach it.

Effect: categories recovered on statements that previously produced `(cid`, and a
few merged statements correctly split.

| | before | after |
|---|---|---|
| cause statements | 3,462 | 3,468 |
| Equipment Failure | 111 | 114 |
| Human Performance Error | 177 | 179 |
| Management Systems | 72 | 76 |

### `src_cause_field` recorded

`psm.project` concatenated fields 18 and 19 without recording which a statement
came from, discarding real provenance. Now written to
`data/processed/e19/causes_source_field.csv`, keyed on incident and cause number.

It is deliberately **not** crosswalked to `Cause type` — probable/contributing is
an axis of primacy, Immediate/Underlying/Root an axis of depth. But it is the
obvious feature for a later LLM-assisted pass, and it should not have been thrown
away.

## 2026-08-29 — Session 4: Section 3 from hazard energy

E19 Section 3 asks for the worst outcome that could **reasonably be expected**.
BSEE records what **did** happen. Bridging that is the whole session, and two
approaches failed before one worked.

### Measured: actual-outcome-only does not work

| Method | A | B | C | D | E | blank |
|---|---|---|---|---|---|---|
| Actual outcome only | 15 | 185 | 219 | **0** | 3 | **666 (61%)** |
| Hazard energy | 11 | 138 | 318 | 325 | 189 | 107 (10%) |

**559 incidents receive a consequence from hazard energy where actual-outcome
records nothing** — every fire, dropped load and explosion that happened to hurt
nobody. Zero records reach consequence D under the actual method. This is the
near-miss burial quantified, and it is why consequence is derived from what an
event *could* do. The approach follows the EEI Safety Classification and Learning
model, whose categories are High-Energy SIF and *Potential* SIF.

### Failure 1: the exposure proxy was circular

An "event with people present is worse" bump initially used
`Required Evacuation` / `Required Muster`. **84% of the most severe rating came
from that flag, not from hazard energy** — E fell from 172 to 27 without it. And
it is circular: an evacuation is ordered *because* something was serious.

Replaced with positional checkbox marks `DRILLING` / `WORKOVER` / `COMPLETION`,
which describe what work was underway rather than what happened. Better coverage
(196 vs 162 of 622) and **independently validated**: a rig name appears in field 5
on **45%** of crewed-flagged records against **4%** of production-only ones —
12.8× more likely, from a different part of the form extracted by a different
mechanism.

Known limit: it identifies definitely-crewed records but cannot identify
definitely-unmanned ones, since `PRODUCTION` covers both manned platforms and
unmanned satellites. The bias is toward under-rating, which is the safer
direction.

### Failure 2: likelihood from the actual-vs-potential gap

Deriving likelihood from how close the actual came to the potential gave **70% of
records likelihood 1**, and collapsed every near miss straight back into
"Incident" — reintroducing the exact burial the consequence work had just fixed.

The error was conceptual, not a tuning problem: that formula measures
**realisation** (did it happen this time), where likelihood means **how likely
the outcome is when the scenario recurs**. Recorded in the rule file so it is not
retried.

### What worked: likelihood measured from the corpus

P(serious injury | mechanism), across 2,014 spine rows. **The result is the most
interesting finding of the session:**

| Mechanism | n | severe-injury rate | likelihood |
|---|---|---|---|
| Other Lifting Device | 94 | **24.5%** | 5 |
| Crane | 177 | **23.7%** | 5 |
| Explosion | 73 | 12.3% | 4 |
| Structural Damage | 40 | 7.5% | 3 |
| Fire | 514 | 4.7% | 2 |
| Blowout | 58 | 3.4% | 2 |
| Pollution | 435 | 1.1% | 2 |
| Collision | 48 | 0.0% | 1 |

**Lifting operations are 5× more likely to seriously injure someone than fire, and
7× more than a blowout.** The dramatic hazards rarely hurt people; the routine
ones do. Consequently **every Very Serious Incident in the output is a lifting
incident** — 55 Other Lifting Device, 38 Crane, zero fires — which the model
arrived at independently of the classification bands.

A first banding at ≥40% → likelihood 5 left the VSI class **empty across the
entire corpus**, which said more about the threshold than the data. Rebanded at
≥20%, on the reasoning that a one-in-five chance of serious injury given the event
is genuinely high.

### Result

| | verbatim | enriched |
|---|---|---|
| Incident columns with any value | 15 / 43 | **25 / 43** |

| Section 3 field | filled | src / xw |
|---|---|---|
| Incident Classification | 62.6% | 234 / 527 |
| Health & Safety Consequence, Likelihood, Risk Score, Classification | 55.6% each | 0 / 676 |
| Financial Cost Consequence | 39.3% | 0 / 478 |
| Environment & Reputation Consequence | 15.1% | 0 / 184 |

Distribution: Incident 378, Serious 196, Very Serious 102.

**The Risk Score formula is assumed, not sourced.** The template lists scores 1-25
but not the Consequence × Likelihood matrix producing them, and it was not
recoverable from the workbook. A plain 5×5 product reproduces the range. Replace
when the author supplies the real matrix; nothing else changes.

## 2026-08-29 — Adversarial review: five independent agents

Five agents, each attacking a different surface, none sharing context. Their
findings are recorded here by **root cause**, because one three-line defect
explains four of the symptoms and that was not visible from any single report.

Every headline claim below was reproduced directly before being recorded.

---

### R0 — `_rows()` quantises instead of clustering. Root cause of four defects.

`src/psm/layout.py`:

```python
buckets.setdefault(round(w["top"] / tol), []).append(w)
```

This is a **fixed bin edge, not a tolerance**. Two words on the same visual
baseline land in different rows whenever the bin edge falls between them —
`BLOCK:` at `top=308.8` (bin 124) and its value `25` at `top=308.3` (bin 123),
0.5pt apart.

**Measured across all 1,289 PDFs: 23,400 of 237,714 true visual rows (9.84%) are
shattered, affecting 1,274 of 1,289 documents.** The docstring's claimed
behaviour holds only when a pair happens to straddle no bin edge.

It explains, in descending order of harm:

**(a) `src_form_revision` is wrong on ≥45 of 1,219 records (3.7%)**, mostly 32
revision-B documents recorded as A. `detect_form_revision` treats the *absence*
of a field-3 anchor as evidence for revision A, and the shattering manufactures
exactly that absence: `3.` and `OPERATOR/CONTRACTOR` fall in adjacent bins so
`ANCHOR_RE` never fires.

**This is the most dangerous defect in the repository.** It is the
stratification key — findings.md, the schema comments and the P1 plan all scope
work "by revision" — so it launders errors into the instrument built to detect
them, and any per-revision field remap applied to those 32 files would convert
missing fields into confidently wrong ones.

**(b) D2 — block number reads as the next field's ordinal.** `RE_BLOCK`'s `\s*`
crosses a newline into `5. A-Hoover Spar`. **41 of 42 `Area == "5"` records are
wrong** (one genuinely is block 5). Verified against page geometry on 12 PDFs:
true blocks are 25, 857, 50, 364, 757, 602 — all matching their filenames.
Corpus-wide block accuracy: 985 exact, 130 empty, **58 confidently wrong**.
Area *letters* are clean: 1,151 exact, **0 wrong**.

Fixing only the regex would turn 41 confident wrong answers into 41 blanks,
because the value *precedes* its label. Fixing `_rows` fixes them at source.

**(c) D3 — `Incident Classificatioin` is 230 of 234 label bleed.** Field 28's
true content *is* MAJOR/MINOR and is recoverable — an independent band-aware
reconstruction recovers it cleanly. `find_gutter` succeeds on only **127 of 434
admin pages (29.3%)** because it is a whole-page test applied to a page whose
upper two-thirds is single-column narrative: **column detection is per-page, the
layout is per-region.**

**(d) Field 5 is blank on 124 of 127 revision-A records** — its content sits
inside `src_f04`. Indistinguishable downstream from a form that left the box
empty.

### Extraction reliability, measured against page geometry (n=29 PDFs)

| Field | rev A | rev B | rev C |
|---|---|---|---|
| f17 findings | 9/9 | 9/9 | 9/9 |
| f18 probable cause | 9/9 | 9/9 | 8/9 |
| f22 recommendations | 8/9 | 8/9 | 8/9 |
| f04 lease/area/block | **1/9** | 9/9 | 8/9 |
| f05 platform | **1/9** | 9/9 | 8/9 |

Approximate field error rate: **rev A ~27%, rev B ~6%, rev C ~5%**, concentrated
in f01/f04/f05. **The narrative fields are the reliable ones.**

**The field-17 recovery holds and exceeds its claim: non-empty on 1,219/1,219,
100% in every revision**, content verified on all 28 sampled documents, character
counts matching an independent reconstruction to within ~25 chars — no silent
truncation. The two label alternates were the right fix.

---

### R1 — `Incident Classification` ships 234 illegal values that suppress 149 valid ones

BSEE field 28 is MAJOR/MINOR; the E19 picklist is VSI/SI/Incident. Disjoint
vocabularies, mapped as raw text in `e19_projection.yaml`. **234 of 234 verbatim
values are illegal**, and because verbatim-wins they **block 149 rows that had a
valid crosswalk classification available**.

`e19_projection.yaml` has no concept of a vocabulary constraint, and
`test_projection.py` checks headers but never values.

---

### R2 — the recommendations table has a false grain

Declared "one row per recommendation"; delivers **exactly one row per incident on
all 1,079**. The blank-line splitter never fires — no `src_f22` in 1,128 records
contains a blank line. 72 cells hold multiple enumerated recommendations
concatenated. 38 rows record `none` / `N/A` as a recommendation.

Downstream: `closeout.csv` inherits the false grain. Any per-recommendation count
or closure rate is wrong.

---

### R3 — the headline statistic fails, and the failure propagates into the risk scores

**BSEE's vocabulary is not stationary.** `LTA` codes begin 2006; `Other Lifting
Device` begins 2007; `Blowout` ends 2013. Pre-2006 records sit in the denominator
while being structurally incapable of entering the numerator (the coarse `Injury`
atom, extinct after 2012, is excluded). **Lifting and Blowout never coexist.**

Restricted to 2007–2026, where every code is active:

| | pooled (claimed) | 2007+ (correct) |
|---|---|---|
| Lifting vs Fire | 5.2× | **2.53×** [1.44, 4.45] |
| Lifting vs Explosion | — | **0.94** [0.45, 1.96] |
| Lifting vs Blowout | 7× | **undefined**, n=2 |

Explosion at 25.9% is nominally the *highest* rate in the corpus. **"The dramatic
hazards damage plant; the routine ones hurt people" is contradicted by the only
comparable explosion data.**

Direction survives: leave-one-year-out on lifting vs fire within 2007+ gives RR
between 2.26 and 2.82 across all 20 years. Only the magnitude was an artifact.

**This propagates.** `xw_consequence_tiers.yaml` hard-codes the pooled rates as
likelihood bands. Re-banding on 2007+ rates moves Explosion 4→5 and Fire 2→3, and
leaves Blowout and Collision with no estimable rate. The finding "every Very
Serious Incident is a lifting incident" is **not independent corroboration — it
is the same artifact propagating through the banding.** Under corrected rates
every explosion joins the VSI class.

Selection bias was investigated and is *not* the killer: 30 CFR 250.188 requires
reporting of all fires and explosions **and** all crane/material-handling
incidents unconditionally, so there is no regulatory injury threshold that would
admit fires while excluding uninjurious lifts.

---

### R4 — the test suite does not protect what it claims to

**Coverage measured:** `crosswalk.py` 243 statements **0%**, `evidence.py` 190
**0%**, `e19_schema.py` 145 **0%**, `spine.py` 122 **0%**, `fetch.py` 99 **0%**.
Total 30%. **The five modules that produce every committed table have no test
importing them.** `tests/test_crosswalk.py` tests `schema/crosswalk.yaml` — a
different artifact with a confusingly similar name, which likely explains why
nobody noticed.

**13 of 28 tests in `test_crosswalk.py` cannot fail from any defect.** They assert
that English words appear in YAML: `assert "ASSUMED" in tiers[...]`,
`assert "70%" in rej["why"]`, `assert crosswalk["version"] >= 2`. Swapping any two
categories' element numbers leaves all 28 green — in a file whose docstring claims
to prevent exactly that.

`test_bullet_endash_form` asserts the parser handles U+2022. The corpus contains
U+0081. The test passes while 12 real rows are corrupted.

`tests/test_conventions.py` — named in CLAUDE.md as the enforcer of the
provenance-prefix rule — is 30 lines, tests only `synth.py`, and its docstring
still says `crosswalk.py` "does not exist yet". **186 of 187 columns across the
eleven committed tables carry no provenance prefix.** The deviation is defensible
(E19 columns must be byte-exact, so provenance moved to a parallel file) but it is
undocumented, and CLAUDE.md, README and `crosswalk.yaml` all still assert the
prefix rule.

---

### R5 — nothing in this repository can currently be scored

`gold/gold_labels.csv`: 100 rows, **all six `gold_*` columns empty**. By the
project's own rule — score against `gold_` only — there is no reportable number.

Three further problems, all measured:

- **The join does not exist.** Gold keys on `report_id` = sha256; the tables key
  on `Incident Number`. **Direct join: 0 of 100.** A two-hop via
  `bsee_unmapped.csv` recovers 99, but it is undocumented and untested.
- **Stratification is year-uniform, not corpus-proportional.** 2003 (3 reports)
  and 2007 (97 reports) get equal weight. Any accuracy computed is a year-balanced
  macro-average, and nothing says so.
- **n=100 cannot carry the metric anyone wants.** `gold_psm_element` has 20
  classes — ~5 rows per class. Per-element accuracy is out by a factor of ten.

**Train/test leak is already baked in at four sites**, all self-documented: the
cause vocabulary was induced on all 3,462 statements; the likelihood rates were
measured on the same 2,014 spine rows they label; the likelihood banding was
chosen *by inspecting the resulting label distribution* ("an earlier absolute
banding left the VSI class empty"); the qualifier patterns were fit to the 309
observed subcategories.

---

### R6 — the README contradicts the shipped data

- It lists risk scores as **`syn_`**; `provenance.csv` labels all 676 **`xw`**.
- `findings.md` says the panel severity bias "belongs in the README". **It is
  still not there.** A reader is warned about `llm_` columns and not told half the
  fatalities are missing.
- Only **3 `Injury Fatality`** records reach the output against 86 in the spine.
  Panel exclusion explains 46. **The remaining ~37 are still unexplained.**

---

### Where an agent overstated, and it matters

One agent concluded the hazard-energy method "rates zero near misses". Technically
true, materially misleading: it conflates E19's Type A `Near Hit` (nothing
happened — **24 records**, all correctly showing no Section 3, a real structural
gap) with the colloquial sense of a near miss (something happened, nobody hurt).
There are **584** of the latter and they *are* rated. The gap is 24 records, not
the method's purpose.

Recorded because the difference decides whether the method is broken or merely
incomplete. It is incomplete.

## 2026-08-29 — R0 applied: `_rows` clusters instead of quantising

### The fix

`round(top / tol)` replaced with single linkage on the gap, **plus a span cap**.
Both parts were necessary and the second was found by a test rather than by
inspection.

**The tolerance had to shrink with the algorithm.** As a bin width, 2.5 meant
±1.25 from a centre; as a gap it means "chain anything within 2.5pt", which is
far looser. Measured on a sampled form face, single linkage at tol 2.0 produced a
within-row spread of 3.36pt — two distinct lines merged. The observed gap
distribution is bimodal: **146 of 222 consecutive gaps under 1pt** (same-baseline
jitter), **62 above 2.5pt** (genuine line breaks), only 14 between. `ROW_TOL` is
now **1.5**, sitting in the empty middle.

**A test I wrote caught a weakness in the fix I wrote.** Single linkage alone
chains: six words stepping 1.4pt apart each pass the tolerance and merge across
7pt. Real pages do not show that ladder, but nothing prevented it, so a row is
now also capped at `ROW_SPAN_MAX = 2.0` from its first word.

Baseline before the change, measured over 120 sampled PDFs: **5,112 excess rows
against 10,734 true rows — 47.6% more rows than the pages have, affecting 119 of
120 documents.**

### Measured outcome — two fixed, one unchanged, one deferred

| | before | after |
|---|---|---|
| **`Area == "5"`** (next field's ordinal) | 42 | **2** |
| `src_form_revision` A / B / C / unknown (ok records) | 127 / 701 / 377 / 14 | **94 / 743 / 377 / 5** |
| `Unit` populated | 691 | **764** |
| UNKEYED incident numbers | 80 | 76 |
| field 28 label bleed | 230 | **228** |
| field 5 → `Unit` on revision A | 3/127 | 0/94 |

**D2 is 95% resolved.** 33 revision-B documents were reclassified out of A —
matching the 32 predicted — and 9 unknowns resolved. A collision key that read
`261-20050225-1043` now reads `EI-261-...`: the missing area letter recovered
itself, which is the clearest single demonstration that the row reconstruction
was the cause.

**D3 did not move, and that is expected.** Its root cause is `find_gutter` being
a whole-page test applied to a page whose upper two-thirds is single-column
narrative — R0.1 in the remediation plan, independent of `_rows`. The remediation
plan predicted this; recording it because a fix that improves one symptom and not
another is exactly where wishful reading creeps in.

**Field 5 on revision A went from ~0 to 0.** On revision A the form numbering is
shifted, so anchor 5 is `ACTIVITY`, not `PLATFORM`, and the label hint correctly
refuses it. That is the P1 per-revision field map's job, not R0's. The previous
3/127 were spurious matches; 0/94 is the more honest number.

### Note on re-extraction

The sandbox caps a single command at ~3 minutes, and a full 1,289-document
extraction exceeds that. It was completed in two passes (1,169 then the
remaining 120), and `anomalies.jsonl` was regenerated from the per-record
anomaly lists afterwards, because the interrupted run had truncated it in `w`
mode. Anyone re-running this should do it locally in one pass.

## 2026-08-29 — R0.1 applied: column detection per band, not per page

### The fix, in three parts — the second and third were found by being wrong

**Part 1: band the page.** `find_gutter` asks whether *the page* is two-column.
Wrong question: the admin block sits at the BOTTOM of a page whose upper
two-thirds is single-column narrative, so the prose crosses every candidate x and
the page-wide test can never fire (127 of 434 admin pages, 29.3%). Replaced with
`find_column_bands`, which finds contiguous runs of rows sharing a gutter.

**Part 2: judge the band, not the row.** A first version tested each row for a
clear span with content on both sides. That fragmented the block into runs of
one, because a long field-26 value legitimately spills across the gutter and
`30. DISTRICT SUPERVISOR:` sits entirely in the right column. Both the
clear-fraction tolerance and the content-on-both-sides test now apply to the
band.

**Part 3: require form structure, not just whitespace.** Part 2 worked on the
admin block and **shredded narrative prose** — three consecutive ragged lines
happened to share a gap, and `iv) Stress concentration areas` /
`relieved by some means to prevent surface crack` came out as two "columns".
That is exactly what the page-wide clear-fraction test used to prevent; a local
test loses the protection and has to replace it with positive evidence. A band
now also requires at least two rows carrying a form anchor (`NN. Label`). Prose
does not.

### A metric that hid a working fix

After part 3 the measure said clean MAJOR/MINOR had fallen from 10 to 2, and the
fix was one step from being reverted. The metric was `value.upper() in
('MAJOR','MINOR')` — an exact match. The actual extracted value was
`'MAJOR\n29. ACCIDENT INVESTIGATION\nPANEL FORMED:\nNO'`: **the classification was
correct and leading**, with field 29's content trailing it. Measured as
"starts with MAJOR/MINOR", the true figure was **62**, not 2.

Recorded because the near-miss is the lesson: a too-strict metric scored a
correct extraction as a regression, and the response to a regression is usually
to revert.

### The residue had a familiar shape

Field 29's label wraps across two rows — `29. ACCIDENT INVESTIGATION` /
`PANEL FORMED:` — so a hint of `PANEL FORMED` never matched the anchor line,
anchor 29 was rejected, and field 28 ran on into its content. Identical in shape
to field 17's two wordings, and fixed the same way: a `label_hint` alternate in
YAML, no code change.

### Measured outcome

| | original | now |
|---|---|---|
| field 28 **clean MAJOR/MINOR** | 4 | **58** |
| field 28 total non-empty (i.e. how much was bleed) | 234 | **119** |
| field 29 located | ~460 | **1,006** / 1,219 |
| `Area == "5"` | 42 | **2** |
| `Unit` populated | 691 | **757** |
| revision A / B / C / unknown | 127/701/377/14 | **94/743/377/5** |

Field 28 non-empty *falling* is the point: field 29 now claims its own content
instead of it being absorbed. The bleed collapsed from 230 to ~57, and the column
carries 58 clean classifications where it carried 4.

Field 17 fill holds at 99.7% of ok records. 226 tests pass. Enriched incident
columns with any value remain 25/43 — R0 and R0.1 corrected values rather than
adding columns, which was their purpose.

**Still open from the review:** R1 vocabulary constraints (the 234 illegal
classifications are now 119, but the column still mixes BSEE MAJOR/MINOR with
E19's VSI/SI/Incident and still suppresses crosswalk values), R2 recommendation
grain, R3 the retracted statistic and re-banded likelihood, R4 test honesty,
R5 gold set, R6 README, R7 the ~37 unexplained missing fatalities.

## 2026-08-29 — R1 and R2 applied

### R1 — vocabulary constraints, and field 28 moved to the sidecar

BSEE field 28 is `MAJOR`/`MINOR`. The E19 `Incident Classification` picklist is
`Very Serious Incident` / `Serious Incident` / `Incident`. Disjoint vocabularies,
mapped as raw text — so 234 illegal values shipped, and because verbatim wins
they **suppressed 149 rows that had a valid crosswalked classification**.

Field 28 now goes to the sidecar as `bsee_accident_classification` (with field 29
alongside); the E19 column is filled by the crosswalk from the risk score.

| | before | after |
|---|---|---|
| illegal values, **all committed tables** | 234 | **0** |
| `Incident Classification` legitimate | 527 | **660** |
| `Incident Classification` junk | 234 | **0** |

Three things beyond the immediate fix:

**A `vocabularies:` block** declaring which E19 columns are picklist-backed,
enforced in `psm.project`: an illegal value is blanked and counted, never
written. Blank beats wrong in a controlled column.

**A `vocabulary_exempt:` block** for `Site` / `Area` / `Unit`. The template ships
those as placeholder facility names (`Alpha`/`Beta`, `One`/`Two`) and this project
repurposes them for BSEE geography deliberately; a strict validator would
otherwise flag 2,237 cells. The exemption is now a recorded decision with a
stated reason per column, and a test requires the reason.

**A value-legality test** across all four tables and both directories. The point
the review made was that header tests passed throughout while 234 illegal values
shipped: nothing checked values.

### R2 — recommendation grain

The splitter used a blank line. **Zero of 1,077 non-empty field-22 values contain
one**, so it never fired and every incident got exactly one row — the declared
grain, "one row per recommendation", was false for the whole table.

Recommendations are *enumerated*, not paragraph-separated. Measured across the
corpus: 51 values carry `\n<digit>[.)]`, 24 use `2)` style, 9 use bullets, 7 use
`b)`. Splitting on those, and treating nil returns (`None`, `N/A`) as
`absent_legitimate` per the repo's existing convention rather than as
recommendation text:

| | before | after |
|---|---|---|
| rows | 1,079 | **1,244** |
| incidents with 2+ recommendations | **0** | **56** |
| max per incident | 1 | **12** |
| distinct `Recommendation Number` values | 1 | **12** |
| nil returns counted as recommendations | 38 | **0** |

Worth stating plainly: the false grain was real but **narrower than the audit
implied**. Only ~56 of 1,079 incidents genuinely hold multiple recommendations;
the rest were correctly one row. The defect was that the number was meaningless,
not that a thousand rows were wrong.

A test now asserts the shipped table has a real grain — `max(per_incident) > 1`
and `Recommendation Number` takes more than one value. That is the check that
would have caught it, and it did not exist.

**A test caught a lossy behaviour in the fix.** The first splitter stripped
trailing full stops as separator debris. A single prose recommendation came back
without its final period — against this project's verbatim principle. Only
leading separator characters are stripped now.

Tests 235 → 243, 2 skipped.

## 2026-08-29 — R3 applied: likelihood re-banded, headline claim retracted

### The claim is withdrawn

> ~~"Lifting operations are 5x more likely to seriously injure someone than fire,
> and 7x more than a blowout. The dramatic hazards damage plant; the routine ones
> hurt people."~~

**Do not present this.** BSEE's accident-type vocabulary is not stationary, and
the rates were pooled across 1995–2026 as though it were.

| code | first used | last used |
|---|---|---|
| Blowout | 1996 | **2013** |
| Other Lifting Device | **2007** | 2026 |
| `LTA (>3 days)` / `LTA (1-3) days` | **2006** | 2026 |
| `Injury` (coarse, excluded from the numerator) | 1995 | 2012 |

Two independent breaks, either fatal on its own. Pre-2006 records sit in the
denominator while being **structurally incapable** of entering the numerator,
because their injuries carry the coarse `Injury` atom the metric excludes. And
**Blowout and Other Lifting Device never coexist in the data at all** — the 7x
compared a 2007–2026 mechanism against one whose code was retired in 2013.

Restricted to 2007–2026, where every code is in use:

| mechanism | n | rate | band | was |
|---|---|---|---|---|
| Explosion | 27 | **0.259** | **5** | 4 |
| Other Lifting Device | 94 | 0.245 | 5 | 5 |
| Crane | 170 | 0.241 | 5 | 5 |
| Fire | 186 | **0.097** | **3** | 2 |
| Structural Damage | 36 | 0.083 | 3 | 3 |
| Pollution | 176 | 0.017 | 2 | 2 |
| Blowout | **2** | — | **unestimable** | 2 |
| Collision | **5** | — | **unestimable** | 1 |

Lifting vs fire falls **5.2x → 2.5x**. Lifting vs explosion is **0.94** —
explosion is nominally the highest rate in the corpus. The rhetorical half of the
claim is contradicted by the only explosion data comparable to the only lifting
data.

**The defensible wording**, if the finding is kept:

> Among BSEE investigations 2007–2026 — the period in which both the lifting and
> lost-time-injury codes were in use — 24% of investigations tagged Crane or Other
> Lifting Device also record a fatality or lost-time injury (n=264), against 10%
> of those tagged Fire (n=186): a rate ratio of 2.5 (95% CI 1.4–4.5). Explosion is
> indistinguishable from lifting at 26% (n=27). Blowout and Collision cannot be
> compared — their codes were retired before the lifting code came into use. These
> are per-investigated-incident conditional rates, not per-lift or per-exposure
> risks, over incidents BSEE chose to investigate.

The *direction* survives: leave-one-year-out within the window gives a lifting/fire
ratio between 2.26 and 2.82 across all 20 years. Only the magnitude was artifact.

### It propagated, exactly as predicted

The rates are not just a slide — they are the likelihood bands. Re-banding moved
every Section 3 score:

| | before | after |
|---|---|---|
| Likelihood distribution | 1:16 2:362 3:30 4:31 5:237 | 1:10 2:193 **3:177** 5:265 |
| Incident | 378 | **203** |
| Serious Incident | 196 | **310** |
| Very Serious Incident | 102 | **132** |

And the claim that looked like independent corroboration was the same artifact:

| Very Serious Incident composition | before | after |
|---|---|---|
| Other Lifting Device | 55 | 59 |
| Crane | 38 | 41 |
| **Explosion** | **0** | **32** |
| **Fire** | **0** | **14** |

*"Every Very Serious Incident is a lifting incident — zero fires"* was true of the
output and false about the world. It was the era artifact reappearing downstream,
and it read as confirmation.

### Unestimable is now a first-class outcome

A mechanism whose code was retired before the outcome codes existed gets **no
likelihood, and therefore no risk score and no classification** — but it keeps its
consequence. Borrowing a rate from the pooled series would reinstate precisely the
artifact this correction removes. 15 records lose a score this way (660
consequence, 645 scored).

A minimum of n=20 in-window is required for a rate; `Blowout` (2), `Collision` (5)
and `Damaged/Disabled Safety Sys.` (15) fall below it and are listed with their
in-window counts.

Tests 243 → 249, including guards that the rates declare their window, that no
unestimable mechanism carries a rate, that every rate meets the n floor, and that
explosion is not banded below lifting.

## 2026-08-29 — R4 applied: the test suite can now fail

### The name collision that hid the gap

`tests/test_crosswalk.py` tested `schema/crosswalk.yaml`. **Nothing tested
`psm.crosswalk`** — 244 statements, 0%, the module that writes every enriched
table. The near-identical names are the likely reason nobody noticed 28 passing
tests sitting beside an untested module. Renamed to `test_crosswalk_schema.py`,
and a new `test_crosswalk_module.py` tests the module.

| module | before | after |
|---|---|---|
| `crosswalk.py` | **0%** | **48%** |
| total | 30% | 35% |
| tests | 249 | **281** |

The 24 new module tests target defects that actually occurred, not happy paths:
a mechanism alone must be a Loss Event (a record tagged only `Fire` previously
got no Type A); a deliberate null must not backfill from a lower-precedence atom;
an unestimable mechanism gets consequence but no score; verbatim always wins.

### The test the file's own docstring promised and did not have

`test_crosswalk_schema.py` opens by saying it exists so the v1 numbering bug
"cannot recur silently" — v1 routed Equipment Failure to element 7 while its own
note described element 15's subject matter. **Nothing compared the two.** Swapping
any two categories' element numbers left all 28 tests green.

Replaced `test_version_is_two_or_later` (a constant asserting a constant) with
`test_every_element_matches_its_own_stated_reasoning`, which checks each entry's
`matched_on` phrase against the element *name*.

**It failed on first run, on exactly the two entries marked `confidence: low`** —
`Supervision` (fixed by removing "task" from the stopword list, since element 17
is "Work control, permit to work and **task** risk management") and
`Work Environment`, whose "workplace layout, weather, marine environment" shares
nothing with "Hazard identification and risk assessment". That is the file's own
admission, so the test now permits a low-confidence entry to share no vocabulary
**provided it declares low confidence and explains** — and requires agreement
everywhere else.

### The provenance convention: documented deviation, now enforced

CLAUDE.md says every column in every processed table carries a
`src_`/`xw_`/`llm_`/`gold_`/`syn_` prefix and names `test_conventions.py` as the
enforcer. That file was 30 lines, tested only `synth.py`, and its docstring still
said `crosswalk.py` "does not exist yet". **186 of 187 shipped columns carry no
prefix.**

The deviation is correct and was simply never written down: E19 columns must be
byte-exact template labels, so prefixing them would break the exactness guarantee
the projection layer exists to provide. Provenance moved to a **parallel file** —
and that is a *stronger* guarantee than a prefix, because a prefix labels a whole
column while the parallel file labels every cell, and the same E19 column is
read-verbatim on one row and inferred on another.

`test_conventions.py` now enforces what ships: prefixes on `synth.py` output and
the sidecar, where the exactness constraint does not apply; and for the E19
tables, that a provenance file exists with matching shape, that its tokens come
from a closed set, that no non-empty cell lacks a provenance, that no provenance
mark lacks a value, and that **`xw` never overwrote a verbatim value**.

That last one is the enrichment step's central invariant and had no test at all.

**CLAUDE.md still describes the prefix rule as universal.** It is not, and the
deviation is deliberate. Left for the repo owner rather than amended unilaterally.

### Still outstanding from the review

R5 gold set (0/100 labelled, joins 0/100 directly — nothing scoreable), R6 README
contradictions, R7 the ~37 unexplained missing fatalities. `e19_schema.py`,
`evidence.py`, `fetch.py` and `spine.py` remain at 0%; they are one-shot
generators rather than pipeline stages, which is a reason but not a defence.

---

## 2026-08-29 — S1: two silent cause-parser defects, found by adversarial review

Both were **coverage** bugs, not correctness bugs: they withheld mappings rather
than inventing wrong ones, so nothing downstream ever complained. That is why
they survived 284 passing tests.

### S1a — `Category - Subcategory` was never a separator

`SEP_CLASS`'s ASCII-hyphen alternative was `(?<=[a-zA-Z])-(?=\s)`, which requires
the hyphen to touch the preceding word. The equally common spaced form was not a
separator at all, so the parser ran on to the next qualifying separator and
produced a head too long for `MAX_CATEGORY_WORDS`:

    Equipment Failure - Inadequate preventative maintenance/Inadequate
    equipment repair- the crane's aux hoist system ...
                    ^ not a separator          ^ separator; head is 11 words

Report `BM 3 Cantium 5-Aug-2025` names four of the six canonical categories in
its own text and mapped to none of them.

Added a third alternative, `(?<=\s)-(?=\s)`. "Flexi-Coil" is unaffected — it has
no space after the hyphen, which is what the original narrowing was for.

Widening the separator opened one hole: a mid-sentence prose dash could yield a
head ("a well-known issue - the valve stuck - ..."). Closed by requiring
`head[0].isupper()` in `candidate_category`, which `unwrap` had always required
to *begin* a statement. Measured cost of that guard: 2 statements corpus-wide,
both junk (`construction`, `of this incident include`).

### S1b — a wrapped field label became the corpus's third most common category

`FURNITURE_HEAD_RE` catches `LIST THE ...` only while the label is intact. In
two-column soup BSEE's own label wraps and the tail lands alone, carrying the
colon:

    19. LIST THE CONTRIBUTING CAUSE(S) OF
    ACCIDENT:

`ACCIDENT` is short, title-ish and colon-separated — every test for a cause
category. 24 statements corpus-wide. `tests/test_causes.py` asserted only that
the *unsplit* label is rejected, so the split form shipped untested.

**A general rule was tried and rejected on evidence.** "An ALL-CAPS head is
furniture" is wrong: of the corpus's 11 all-caps heads, **6 are legitimate
categories** — HUMAN ERROR, COMMUNICATION, SUPERVISION, EQUIPMENT FAILURE,
MANAGEMENT SYSTEM, WORK ENVIRONMENT — covering 13 statements. A blanket guard
would have deleted them silently. Fragments are therefore listed as data in
`schema/bsee_form2010.yaml:cause_field_furniture`, matched only when ALL CAPS.

### Measured effect (full re-run of `psm.project` + `psm.crosswalk`)

| | before | after | |
|---|---|---|---|
| cause statements | 3,587 | 3,609 | +22 |
| mapped to a PSM element | 460 (12.8%) | **521 (14.4%)** | +13.3% |
| `Risk Management Cause` | 218 (6.1%) | **276 (7.6%)** | +27% |
| `Human Factors Cause` | 125 (3.5%) | **152 (4.2%)** | +22% |
| typed but unaliased (junk diagnostic) | 255 | **238** | −17 |
| gold typed rows | 29 | **30** | |
| gold rows the crosswalk can score | 19 | **22** | |

The two derived cause fields improved more, proportionally, than the element
field did — they read the subcategory, which is exactly what the spaced-hyphen
bug was hiding.

### Verification

5 new tests. Checked that they **fail against the pre-fix code**: 2 of the 5 do
(the other 3 are guards against regressions the old code did not have). Full
suite 284 → 291 passing, 2 skipped; `test_conventions.py` and
`test_projection.py` clean after regeneration, so the parallel provenance files
still match shape and `xw` still never overwrote a verbatim value.

### Negative result worth recording

`src_cause_status` was suspected of being conflated with crosswalk-mappability.
It is not used **anywhere** outside `gold_scaffold.py` and `gold_sample.py` — no
production module reads or branches on it, and no processed table carries it. The
conflation is a documentation defect (CLAUDE.md defines `typed` as
"controlled-vocabulary category present", while the code implements a *shape*
test that consults no vocabulary), not a data defect.

---

## 2026-08-29 — S2: "What was the outcome?" 0% → 89.1%, in two provenance tiers

The column was coded `blank: extractable`, noted as *"stated within the field 17
narrative but not separable as a field"*. Half true, and the half that was wrong
had left the column empty for the life of the project.

### Tier 1 — verbatim sentence (`src`), 434/1,215 = 35.7%

`psm.project` takes the **last** sentence in field 17 matching a consequence
cue. Last, not first: a narrative states the injury twice, once in the opening
summary and once at the close, and the later statement is the settled one — the
opening says "a rigger was injured", the closing says which bone and how many
days.

**Two obvious cues were tried and rejected.** `resulting in` and `as a result`
are *causal connectors*, not outcome markers, and fire constantly mid-narrative
on cause statements ("A failed FSV allowed gas to migrate to the hot exhaust
resulting in the fire"). They lifted recall 36% → 56% and took precision with
them; on a 12-sample eyeball, 4 of 12 hits were causes, headings or opening
summaries. `resulting in` is retained only when followed by an injury noun.

Recall is deliberately the lesser goal. This tier writes `src`, so a wrong
sentence is a false claim that BSEE said it — the one error the provenance
design exists to prevent.

### Tier 2 — composition from spine atoms (`xw`), 649 more = 53.4%

`schema/xw_outcome.yaml` renders BSEE's own accident-type codes into English:
`LTA (>3 days)` → "a lost-time accident with more than 3 days lost". This is
**translation, not inference** — same granularity, nothing added — which is why
it is `xw` and not `syn_`. Contrast `xw_consequence_tiers.yaml`, which decides
which band a record falls into and is a real opinion.

Three refusals are written into the rule file and tested:

* **No negative claims.** Absence of an injury atom is *not* rendered "no
  injuries". BSEE coding omissions are common and the spine's silence is not a
  claim. Reports that genuinely say so are caught by tier 1, whose cue list
  leads with that phrasing.
* **No severity language.** "Serious", "significant", "severe", "minor" appear
  nowhere and must not be added; that is the line between naming and judging.
* **No sentence without atoms.** 12% of incidents do not join the spine and get
  nothing. A sentence assembled from no outcome data would be fabrication with
  an `xw` label on it.

Response atoms (`Required Evacuation`, `Required Muster`) render as their own
clause so an evacuation does not read as though it were the harm.

### Result

| | before | after |
|---|---|---|
| `What was the outcome?` | 0 (0.0%) | **1,083 (89.1%)** — 434 `src`, 649 `xw` |
| `extractable` blanks remaining | 2 | **1** (`Work Group`) |

### Verification, including a test that was itself wrong

10 new tests. Rather than a source-copy revert (which broke schema path
resolution and produced errors rather than failures — an invalid check), each
guard was mutation-tested by replacing `outcome_text` in the loaded module:
atom-order rendering, a "No injuries reported." default, a severity adjective,
a non-empty return for no atoms, and a threshold atom rendered as a figure.

**Four of five mutations were caught; one was missed.**
`test_phrase_order_follows_the_rule_file_not_the_atom_string` used one atom per
group, where the fixed group order hid the defect — the test asserted a property
it could not observe. Rewritten to use atoms within a single group, plus a
second test for the injury group. Both now catch the mutation.

Recorded because it is the failure mode the project's own standard warns about:
a test that cannot fail is worse than no test, and only the mutation check found
it. Suite 291 → 300 passing, 2 skipped.

---

## 2026-08-29 — S3: `Work Group` re-coded `extractable` → `structural`

`extractable` means "present in field 17 prose, not yet pulled out" — a to-do.
This one could never be discharged, so it was a standing false promise. The
`extractable` count is now 0; every remaining blank is `structural` (17) or
`judgement` (27).

**The picklist decides it.** The template vocabulary (named `Shift` in the
workbook, bound to the Work Group cell) is: A-F Process Ops, Maintenance,
Projects, Technical, Facilities Management, Admin, Other. **Six of the twelve
values are one company's named shift crews.** No public federal document can say
which of an operator's process-ops shifts was on tour.

**The six functional values were measured, not dismissed.** A cue list over
field 17 prose classifies 233 records (19.1%), 201 (16.5%) unambiguously. That
looked worth having until the hits were read. Sampling 10 `Maintenance` matches:

* ~4 name a **post-incident actor** — "a mechanic placed the crane out of
  service for repair", "the crane mechanic found the boom cable stretched"
  during a post-event inspection.
* ~3 name the **injured person's trade** — "a Crane Mechanic received a puncture
  wound", "a contract Mechanic fell through grating".
* ~3 arguably name the crew doing the work.

Roughly **30% precision for the question actually being asked**. Filling 16% of
a column at 30% precision, under a provenance mark implying better, is worse
than a blank — and nothing downstream reads this column.

**Why this is not the Site/Area/Unit case.** Those three are `vocabulary_exempt`
because the template ships placeholder identifiers (Alpha/Beta/Gamma/Delta,
One/Two/Three/Four, A/B/C/D) for a concept BSEE *does* publish — so the
substitution swaps vocabulary while keeping the concept. Work Group has no BSEE
counterpart at all. Substituting field 6 ACTIVITY (a lifecycle phase) or field 8
OPERATION (a work type) would swap the *concept*, which the exempt mechanism was
not built to license.

**Left open for the template author, not decided here.** If the picklist were
extended with BSEE's own coarse work context — Drilling / Workover / Completion
/ Production — the column becomes fillable at ~87% from field 6 (`src_f06`
carries a value on 87.4% of records). That is a change to his template's
semantics and is his call. Recorded in the projection entry and to be raised in
the memo.

### Negative result

No code changed. `blank-by-reason` moved from
`{structural: 16, extractable: 1, judgement: 27}` to
`{structural: 17, judgement: 27}`; suite unchanged at 300 passing, 2 skipped.

---

## 2026-08-29 — S4: the field disposition ledger

**37 of 57 obtainable fields carry data (65%).** All 20 unfilled obtainable
fields are `synthetic` — the generator exists in `synth.py` and is not yet wired
into the projection, so the honest reading is *65% now, 100% of obtainable once
step 5 lands*, with 8 columns that will stay blank for stated reasons.

Raw fill was 38%/46%/25%/50% across the four tables and meant nothing. Most
empty cells are empty because a federal investigation report structurally cannot
record an operator's internal close-out approver. Those are not gaps; they are
the shape of the source. Mixed among them were a handful of genuinely fillable
columns nobody had reached, and the two kinds of blank were indistinguishable.

| disposition | n | in the denominator? |
|---|---|---|
| `filled` | 37 | yes |
| `synthetic` | 20 | yes |
| `deliberate_blank` | 7 | no — a decision, with the reason in a schema file |
| `needs_human` | 1 | no — the labelling backlog, tracked in `gold/` |
| `not_obtainable` | 1 | no — `Work Group` |

`needs_human` and `deliberate_blank` are outside the denominator deliberately.
Inside it, the headline would *rise* whenever we declined to do labelling work,
which is the wrong incentive to build into a metric.

Both numbers are reported because they answer different questions: the field
count says whether a column was attempted, the cell count (39,063 / 84,083 =
46.5%) says how far a typical BSEE report gets.

### The ledger is self-policing, and that is the point

`schema/e19_disposition.yaml` is not documentation — every entry is a claim
about the world, and a claim nobody checks decays into decoration. A stale audit
is worse than none, because it reads as authority while describing a table that
no longer exists.

`tests/test_ledger.py` (13 tests) checks each claim against the data:
`not_obtainable` and `deliberate_blank` columns must be empty; `filled` columns
must not be; `synthetic` columns must be empty *until the synth layer is wired*,
with the failure message instructing that the test be rewritten to assert a
`syn` provenance mark rather than deleted; every column in the data must be
declared and every declaration must match a real column; every
`deliberate_blank` must name a file that exists; every named generator must
appear in `synth.SYN_COLUMN_MANIFEST`.

**Mutation-checked, not assumed.** Six false claims were injected — calling a
filled column `not_obtainable`, calling an empty one `filled`, calling a filled
one `deliberate_blank` and `synthetic`, dropping a column, inventing one. All
six were caught.

One test exists only to stop the metric being gamed:
`test_the_headline_is_not_vacuously_perfect` fails if every obtainable field is
filled, on the grounds that a denominator whittled down to the columns that
happen to be full would report 100% and mean nothing. It must be deleted
deliberately, not allowed to pass by accident.

### What this buys

The memo to the template's author can now say *"we filled 65% of what a BSEE
report can supply, rising to 100% once the synthetic scaffold is wired, and here
are the 8 fields only your organisation's records can fill"* — a request he can
act on, rather than a raw percentage that invites him to think the project
failed. Suite 300 → 313.

---

## 2026-08-29 — S4b: CORRECTION. There is no template author, and no organisation

Entries above this line — including today's S3 and S4 — were written on a
premise that is false. They refer to "the template author", "his organisation's
records", and a memo asking him to fill the columns BSEE cannot supply. **There
is no author and no organisation.** This is a self-contained public dataset
built from a public corpus for a hackathon. Nobody else is coming to fill
anything.

The premise came from an early framing in the project and was never re-checked;
it then propagated into schema files, where it was shaping design decisions.
`findings.md` is append-only, so the earlier entries stand as written and this
is the correction of record. The schema files themselves were fixed.

### What was actually wrong, not just mis-worded

Three of the five dispositions in `e19_disposition.yaml` encoded *"somebody
else fills this, or nobody does"*:

* `not_obtainable` — `Work Group`. Deferred to an organisation that does not
  exist. It is now a `synthetic_column`: nothing real can go there, and an
  openly `syn` value beats a blank.
* `deliberate_blank` — the seven risk columns our method declined to estimate.
  The methodological reasons remain true and are kept as notes, but "leave it
  blank" stops being an option when the sheet must be dense.
* `needs_human` — `Cause type`. There is no separate human. 100% `syn`.

Reduced to two dispositions (`real`, `synthetic_column`) plus a `gap_policy` on
every real column. The headline metric changed with them: **"percent of
obtainable fields filled" is meaningless for a dataset that is dense by
construction** — it would read 100% and say nothing.

### The number that replaces it

**40.1% of this dataset is real.** 39,063 of 97,412 cells carry `src` or `xw`;
the projected 58,349 remainder is fabricated under `syn`.

That split is the fact a stranger most needs, and it decomposes in a way that
decides how the fabrication should be done:

| | cells | what filling it means |
|---|---|---|
| Wholly synthetic columns — approvers, workflow dates, action tracking, risk components | 37,948 (65% of the gap) | Uniform fabrication. Safe **because** it is uniform; nothing here is confusable with a fact about a real incident. |
| Gaps **inside** real columns | 20,401 (35%) | A `syn` value in the same column as `src` values, describing the **same real incident**. |

The second row is the hazard. `Incident Type D` is 18.4% real, so four cells in
five will assert a mechanism for a named incident at a named block on a named
date that BSEE never asserted. That is defensible for a synthetic dataset and
indefensible the moment the marking is lost.

### Guarding it

`modelling_target: true` now flags the 16 columns an entrant would plausibly try
to *predict*, and `psm.ledger --real-only` (to be built with the synth wiring)
reduces them to their `src`/`xw` cells. The causes table is the sharpest case:
one real prose input, `Cause Description` at 100% `src`, and four labels over it
of which the best is 14.4% real. Training on the fabricated 85.6% is learning
`schema/synth_rules.yaml`.

`tests/test_ledger.py` was rewritten (13 → 15 tests) around the new vocabulary,
and two new guards were added that can only fail on a real drift:
`test_the_primary_input_feature_is_not_fabricated` pins `Cause Description` at
100% real with `gap_policy: none`, and `test_a_meaningful_share_is_real` fails
if the real share ever drops below 25% — a dataset that drifted to almost
entirely fabricated would otherwise pass every other test while being useless.

Suite 313 → 315.

---

## 2026-08-29 — P0-0: the 2010–14 label trough is REAL, not an artifact

Diagnosed before starting Phase 0, because the spec's risk table said that if
the trough turned out to be another form-revision artifact it belonged inside
Phase 0's scope. **It is not.** Phase 0 proceeds as specced, and the trough is
Phase 3's problem.

### The revision hypothesis is refuted

| era | n | rev A | rev B | rev C | mapped |
|---|---|---|---|---|---|
| 2000–04 | 19 | 9 | 10 | 0 | 0.0% |
| 2005–09 | 402 | 85 | 316 | 0 | 9.0% |
| **2010–14** | **288** | **0** | **284** | **0** | **1.7%** |
| 2015–19 | 239 | 0 | 133 | 106 | 11.7% |
| 2020–24 | 217 | 0 | 0 | 217 | 56.2% |
| 2025–29 | 54 | 0 | 0 | 54 | 72.2% |

2010–14 is 100% revision B. So is most of 2005–09, which maps at 9.0%. Same
form, five times the mapping rate. The form is not the variable.

### What is actually happening: four labelling regimes, not a ramp

Per-year, with `Human Error` counted separately from the crosswalk's other five
categories:

| year | n | mapped | `Human Error` | modern six |
|---|---|---|---|---|
| 2003–06 | 162 | 0% | 0 | 0 |
| 2007 | 96 | 12% | 12 | 0 |
| 2008 | 88 | 22% | 17 | 2 |
| 2009 | 75 | 7% | 3 | 2 |
| 2010–2014 | 288 | 0–4% | 0–2/yr | 0–1/yr |
| 2015–2018 | 189 | 3–13% | 0–1/yr | 1–5/yr |
| **2019** | 50 | **34%** | 2 | **17** |
| 2020–2026 | 271 | 31–77% | 0–5/yr | 17–29/yr |

Four regimes with sharp edges:

1. **2003–2006** — free prose. No controlled vocabulary at all.
2. **2007–2009** — a brief `Human Error` era. Almost every mapped statement in
   this window is that one head.
3. **2010–2018** — the trough. `Human Error` falls out of use before the modern
   vocabulary arrives. Investigators write **ad-hoc heads of their own**: 68
   distinct ones across 105 occurrences in 477 records, e.g. `Poor Body
   Placement` (6), `Failure to follow company policy` (5), `Inadequate Hazard
   Analysis` (3), `Poor Communication` (2), `Inadequate JSA` (2). Real
   categories, not in anyone's controlled list.
4. **2019 onward** — the modern six. Adoption jumps from 5 occurrences in 2018
   to 17 in 2019 and never falls back.

### Consequences, which are larger than the trough itself

**`schema/crosswalk.yaml`'s six categories are a 2019+ vocabulary.** 948 of
1,219 records — 78% of the corpus — predate it. That is not a defect in the
crosswalk; it is a fact about BSEE that the crosswalk cannot fix and that
nothing in the repo currently states.

* **Era-stratified splits must use these four regimes, not 5-year bins.** A bin
  boundary at 2015 or 2020 cuts through the middle of a regime.
* **The gold set is a regime-4 sample.** Its 30 typed rows are drawn almost
  entirely from post-2019 reports, so any crosswalk accuracy measured on it
  describes the modern regime only and must say so.
* **Weak-supervision labelling functions built on the modern vocabulary will
  have near-zero coverage on regimes 1–3.** That is 78% of the corpus, and it is
  the strongest argument yet for the clustering pass: the only route to labels
  before 2019 is inference from prose, because there is nothing to extract.
* **The trough is not recoverable by better extraction.** 105 ad-hoc head
  occurrences across 477 records is thin, and the rest is genuinely free prose.
  No parser fix reaches it.

### Correction

The completion plan called the trough "probably a form-revision artifact, not a
real change in reporting practice". Wrong on both counts — it is not the
revision, and it *is* a real change in reporting practice.

---

## 2026-08-29 — P0-A: anchors resolved by label, not by number

`Recommendation Description` label bleed **30.4% → 1.5%**; records carrying
fields 8–16 **30.9% → 99.7%**.

### The spec's fix was the wrong one

The spec proposed a per-revision *number* map. Dumping the raw anchor stream of
a revision-B report showed why that would not have worked:

```
REJ  6. 'OPERATION:'            hint='ACTIVITY'            -> really field 8
REJ  8. 'CAUSE:'                hint='OPERATION'           -> really field 9
REJ  9. 'WATER DEPTH: 23 FT.'   hint='CAUSE'               -> really field 10
REJ 10. 'DISTANCE FROM SHORE'   hint='WATER DEPTH'         -> really field 11
REJ  3. 'SEA STATE: FT.'        hint='OPERATOR/CONTRACTOR' -> really field 14
```

Revision B renumbers the form face **and** two-column linearisation drops
digits, so "13. SEA STATE" arrives as "3. SEA STATE". A number map handles the
first and not the second. The label is reliable; the number is not.

`field_for_label()` resolves each anchor by matching its tail against the label
hints already in `bsee_form2010.yaml`, longest hint first (so "OPERATOR" cannot
claim an "OPERATOR/CONTRACTOR" anchor), anchored at the start of the tail (so a
hint inside prose does not open a field). Fired **6,881 times**, and needs no
per-revision map at all — it fixes A, B and future revisions identically.

### The second defect was not the one diagnosed

The spec attributed field 22's contamination to the terminal-anchor sink. **It
is not.** On 322 of the 369 affected records field 30 is correctly located. The
real mechanism, visible in the raw text:

```
22. RECOMMENDATIONS TO PREVENT RECURRANCE | NATURE OF DAMAGE: N/A $ | NARRATIVE: | <body>
```

Field 22's label spans two visual lines with field 21's block linearising
between them, and the label-stripper only cuts to the first colon **on the first
line** — which has no colon. Fixed by `label_bleed_patterns` in the form spec,
removing label fragments **in place**: cutting to `NARRATIVE:` would delete real
text, because the body is split around the interleaved block ("The Houma
District has no recommendation | NATURE OF DAMAGE: Ruptured, melted |
NARRATIVE: | for the Regional Office."). Fired 3,632 times.

### A regression I introduced and caught

The first version normalised whitespace with `" ".join(body.split())`, which
flattens newlines. `psm.causes.unwrap` segments fields 18/19 **by line**, so a
bullet or category head that no longer starts a line stops starting a statement:
cause statements fell **3,607 → 2,298**, a 36% loss, with no error anywhere.
Fixed to normalise within lines only. This is exactly the silent-plausible-wrong
failure the repo keeps meeting, and it was caught only because the count was
being watched.

### Acceptance criteria

| # | criterion | before | after | target | |
|---|---|---|---|---|---|
| A1 | records with f08–f16 | 30.9% | **99.7%** | ≥90% | PASS |
| A2 | field 7 over length | 743 | **0** | ≤100 | PASS |
| A3 | field 30 not located | 169 | 145 | ≤40 | **FAIL** |
| A4 | `Recommendation Description` bleed | 30.4% | **1.5%** | ≤5% | PASS |
| A5 | `Cause Description` unusable | 7.6% | **5.4%** | ≤3% | **FAIL** |
| A6 | records with any over-length field | 899 | 426 | ≤200 | **FAIL** |
| A7 | longest single field | 280,537 | 267,928 | ≤20,000 | **FAIL** |
| A8 | E19 columns losing fill | — | **0** | 0 | PASS |

A3, A6 and A7 are **P0-B's** targets, not P0-A's — they are the terminal-anchor
sink, untouched so far. A7 barely moved because one report still has 267,928
characters in field 8. A5 is close and the residue is now short fragments rather
than form furniture.

A8 passes with four columns *gaining*: `Unit` +7.7pp (62.3→70.0),
`Description` +2.1pp, both Acceptor fields +2.0pp. Nothing lost.

### Row-count changes, and why they are not losses

Cause statements 3,607 → 3,172; recommendations 1,244 → 1,186. Both fell because
stripped label text was previously being split into spurious statements. The
mapped *rate* rose 14.4% → **15.3%** and `typed_but_unaliased` fell 238 → 203,
which is the direction that indicates junk removal rather than data loss.

Suite unchanged at 315 passing, 2 skipped. **No new tests yet — P0-A's tests
land with P0-B so both fixes are covered by one re-extraction.**

---

## 2026-08-29 — P0-B: the terminal anchor bounded

**Records with any over-length field: 899 → 119.** The two records holding an
entire document in one field are gone: the worst is now 700 characters with
267,228 in `src_unassigned_tail`.

### Bounding by page furniture does not work

The spec proposed stopping at the first furniture line after the terminal
anchor. `kept_lines` has already **dropped** every furniture line by the time
`segment_fields` runs, so there is nothing left to stop at. Bounded instead by
`max_length_by_kind`, which is data already in the form spec, with a separate
`terminal_prose_cap` for the two kinds that deliberately declare no limit.

Overflow goes to `src_unassigned_tail`, never discarded. 351 records now carry
one. Without it, the bound would be indistinguishable from data loss.

### Acceptance criteria, final

| # | criterion | before | after | target | |
|---|---|---|---|---|---|
| A1 | records with f08–f16 | 30.9% | **99.7%** | ≥90% | PASS |
| A2 | field 7 over length | 743 | **0** | ≤100 | PASS |
| A3 | field 30 not located | 169 | 145 | ≤40 | **FAIL** |
| A4 | `Recommendation Description` bleed | 30.4% | **1.5%** | ≤5% | PASS |
| A5 | `Cause Description` unusable | 7.6% | **5.4%** | ≤3% | **FAIL** |
| A6 | records with any over-length field | 899 | **119** | ≤200 | PASS |
| A7 | longest single field | 280,537 | 37,050 | ≤20,000 | **FAIL** |
| A8 | E19 columns losing fill | — | **0** | 0 | PASS |

### A7's target was wrong, not the code

All five fields still over 20,000 characters are **field 17 narratives**, and
they are legitimate. The largest, 37,050 characters in
`31-MAY-2023_GC468_EV2010R-2.pdf`, is an 11-page Hess TLP investigation reading
cleanly from `"Incident Summary: On May 31, 2023, Hess Corporation notified
BSEE..."` to a coherent closing sentence about the IP's fall.

The 20,000 figure was set before anyone had measured what a legitimate field 17
looks like. **The criterion should have excluded prose kinds**, and is restated:
*longest non-prose field ≤ 20,000*, which passes at 700.

### A3 is a different defect, now contained

145 records still lack field 30, and the cause is visible in what field 27
absorbs on them:

    'INDIRECTLY CONTRIBUTING. ACCIDENT CLASSIFICATION: 28. ACCIDENT INVESTIGATION
     29. PANEL FORMED: NO DISTRICT SUP...'

Column linearisation **transposes label and number**: `ACCIDENT CLASSIFICATION:`
(field 28's label) arrives before the digits `28.`, which are then followed by
field 29's label. And field 30's label appears with no number at all, so
`ANCHOR_RE` — which requires `\d+\.` — cannot see it.

Fixing that needs label-without-number detection, which is a third mechanism and
out of Phase 0's scope. The terminal bound has made it **harmless**: A6 passes,
and the absorbed text is capped at 150 characters instead of running to
end-of-document. Deferred, with the evidence recorded.

### Verification

`tests/test_extract_anchors.py`, 17 tests, using verbatim strings from named
reports. Mutation-checked against five plausible wrong implementations —
trusting the number, shortest-hint-first, unanchored hint matching, a tidied-down
prose cap, and the cut-to-`NARRATIVE:` strip that would have deleted half a
sentence. All five caught.

Suite 315 → 332. A8 passes with four columns gaining and none losing.

---

## 2026-08-29 — P0-C: `real` stops meaning `non-empty`

The ledger now reports a third number: **94.3% of checked cells pass their shape
check** (10,245 of 10,870). Separate from the 40.3% real / 59.7% fabricated
split, and separate on purpose — a cell can be present and still be form
furniture, a fragment, or truncated.

### Checks are opt-in, and the reason is measured

A global rule was the obvious design and is wrong. Tested before implementing:
"at least four words" fails **100%** of `Incident Number`, `Date of Incident`,
`Incident Type A`, and every risk band — every code, key and picklist value in
the dataset. A validity layer that fires everywhere reports nothing. Eight
columns declare checks; the rest declare none because none would distinguish
good from bad.

`no_form_label` uses `form_label_tokens` in `e19_disposition.yaml`, deliberately
a **different list in a different file** from `label_bleed_patterns` in
`bsee_form2010.yaml`, which does the stripping. A detector sharing its patterns
with the thing it checks can only ever report success. A test asserts the two
lists differ.

### The check found something on its first run

`Incident Number` came back **80.6% valid, 236 failures** — and the pattern was
mine, not the data's. The key is documented as
`{AREA}-{BLOCK}-{YYYYMMDD}-{HHMM}`. It is not: it is **variable arity**, because
the generator drops components the source did not supply.

| components | keys |
|---|---|
| 4 | 1,002 |
| 3 | 129 |
| 2 | 79 |
| 5 | 4 (content-hash suffix on colliding groups) |

162 carry no time at all, and `UNKEYED-<hash>` appears where neither area nor
date is available. I had written the check without knowing the shape of the
primary join key.

The pattern was rewritten to admit every legitimate variant and **still fails 38
keys shaped `AREA-BLOCK-HHMM`** (`SM-6636-1100`) — a key carrying a time but no
date is ambiguous, and this joins all four tables. All 1,214 are currently
unique, so nothing is broken today. The check exists so that stops being luck.

### Current validity, per column

| valid | column | failures |
|---|---|---|
| 69.1% | `Recommendation Description` | truncated 355, form_label 18, too_short 7 |
| 94.6% | `Cause Description` | too_short 186, form_label 6 |
| 96.9% | `Incident Number` | bad_pattern 38 |
| 99.2% | `What was the outcome?` | truncated 4, too_short 5 |
| 99.2% | `How did the incident occur` | form_label 2 |
| 99.7% | `What happened?  ` | form_label 4 |

**Truncation is named separately from contamination** because they are different
problems: one lost text, the other gained furniture. Collapsing them into a
boolean would hide which. `Recommendation Description` is now only 1.5%
contaminated but 28.9% truncated — the remaining defect there is loss, not
pollution, and it is the P0-B residue plus BSEE's own two-column wrapping.

### Verification

9 new tests. One of them, `test_checks_are_declared_where_they_can_fail`, asserts
that at least one declared check currently fails somewhere — a validity layer
that passes everywhere is decoration, and this forces a deliberate decision when
a column reaches 100% rather than letting the check quietly stop earning its
place.

Mutation-checked against three plausible wrong implementations: disabling
`no_form_label`, counting empty cells as invalid (which would double-count
coverage and make the two headline numbers move together), and folding
truncation into a generic boolean. All three caught.

Suite 332 → 340. **Phase 0 is complete.**

---

## 2026-08-29 — D1: the gap-fill split, at 50% real

**14,276 cells (14.7%) will be deliberately left blank.** Projected composition
is now 40.3% real / 45.0% fabricated / 14.7% honest blank, against 40.3% / 59.7%
under fill-everything.

### The rule

A `real` column's empty cells are fabricated when the column is already
**majority real**, and left blank when fabrication would dominate. The 50% line
is where a glance at a column gives the right general impression without
checking provenance: above it, "mostly real with some fill"; below it, "mostly
invented" — which is precisely what a dense column would hide.

This reverses the earlier fill-everything decision for eight columns. That
decision was taken before three things were measured: that all labelled cause
data is post-2019, that the cause-label columns sit at 4–15% real, and that the
missingness is strongly non-random by era. Fabricating `Human Factors Cause`
means inventing 3,418 labels around 152 real ones, all of which sit in a single
reporting era.

| left blank | real | gap |
|---|---|---|
| `Human Factors  Cause` | 4.3% | 3,418 |
| `Risk Management Cause` | 7.8% | 3,294 |
| ` Failed PSM Framework Element` | 14.7% | 3,048 |
| `Environment & Reputation  - Consequence` | 15.3% | 1,028 |
| `Incident Type D` | 18.4% | 991 |
| `Financial Cost & Business Interruption  - Consequence` | 37.0% | 765 |
| `How did the incident occur` | 19.5% | 977 |
| `Detail` | 37.8% | 755 |

The blank is not an absence of work. It says BSEE recorded nothing, and that
silence is one of the more interesting properties of this corpus — 0.6% of
cause statements mapped in 2010–14 against 64.2% in 2025+. Fabricating over it
would erase the phenomenon the dataset is partly about.

### The test found two columns I had not considered

The rule was drafted for the 16 modelling targets. `test_leave_blank_columns_are_
the_minority_real_ones` applies it universally, and failed immediately on two
non-target columns:

* **`How did the incident occur`, 19.5% real.** The lowest of any narrative
  column and, on reflection, the strongest case on the entire list: filling it
  means inventing a prose account of how a real, named, dated incident unfolded.
  Not a modelling target and still the most misleading thing that could go in
  this dataset.
* **`Detail`, 37.8% real.** A fabricated location detail still asserts something
  about a real incident that BSEE never said.

Both moved to `leave_blank`, and the rule is now universal rather than scoped to
targets — which needs no exception clause and is easier to defend.

Recorded because the test was written to encode a rule and instead corrected it.
It also fails in the other direction: if a `leave_blank` column's real share ever
rises past 50%, the policy must be revisited deliberately rather than drifting.

`honest_blanks` is tracked separately from `fabricated_cells` in the ledger.
Counting deliberate blanks as fabrication would misreport the dataset as more
invented than it is, and would make choosing honesty look worse in the headline.

Suite 340 → 343.

---

## 2026-08-29 — D2: single-label kept; secondary elements move to a sidecar

### The question I was going to ask was mostly wrong

I had been citing "48.3% of incidents carry multiple cause categories" as the
case for a multi-label schema. Measured properly, at both grains:

* **Incident level:** 112 of 231 (48.5%) do carry multiple categories — and the
  causes table's grain is already *one row per cause statement*, so this is
  represented today as multiple rows. Nothing to change.
* **Statement level:** **0 of 3,572** statements carry more than one category.

The multi-label case was an artifact of measuring at the wrong grain. The
existing schema already handles it.

### What actually remained

Whether one statement's `Failed PSM Framework Element` should hold one element
or several. `crosswalk.yaml` has declared an `also_touches` for all six
categories since v1, and **it was emitted by nothing** — the only reference
anywhere in `src/` was a print statement in `evidence.py`.

It is not hedging. Equipment Failure → 15 (inspection and maintenance) vs 11
(standards and practices) is the difference between a maintenance finding that
was not actioned and a design that was wrong the day it was fitted, and the
cause text usually says which. The 29-row labelling exercise split Equipment
Failure between exactly those two on exactly that basis.

### Decision: sidecar, not a multi-valued cell

`data/processed/e19/enriched/causes_secondary_element.csv`, keyed on
`Incident Number` + `Cause number` — the same pattern `causes_confidence.csv`
and `causes_source_field.csv` already use.

The E19 cell stays single-valued because the template's picklist takes one
element per cause, and multi-valuing it would break the byte-exact projection
guarantee the whole layer exists to provide. The sidecar gives anyone doing
multi-label work the data without forcing multi-label on anyone who wants the
template.

    primary -> secondary        n
      3 -> 8                  207
     15 -> 11                 136
      8 -> 6                   83
      9 -> 17                  34
     17 -> 3                   34
      6 -> 11                  30

### The measurable payoff, and the ceiling it exposes

Elements reachable from primaries alone: **6 of 20** (3, 6, 8, 9, 15, 17). With
secondaries: **7** — element 11 joins.

That is a small gain and a large finding. **13 of the Energy Institute's 20
elements are unreachable from this crosswalk**, no matter how the data is
labelled, because BSEE's six cause categories do not span the framework.
Leadership (1), legislation (2), workforce involvement (4), MoC (12), emergency
preparedness (14), contractor management (18) and the rest can never appear.
Anyone evaluating a model on "PSM element" is evaluating on a 7-class problem
wearing a 20-class label, and that should be stated wherever the column is
described.

### Verification

6 new tests. Mutation-checked against four plausible failures: dropping sidecar
rows, writing the secondary into the E19 cell, echoing the primary as its own
secondary, and emitting a secondary where no primary exists. All four caught.

Suite 343 → 348. **Phase 1's two decisions are closed; Phase 2 (synth wiring)
is unblocked.**

---

## 2026-08-29 — P2: synth wired. 17,583 synthetic cells, all marked `syn`

`synth.py` was written and tested on 2026-08-09 and imported by nothing in
production for three weeks. The incidents table now reads:

| provenance | cells | |
|---|---|---|
| `syn` | 17,583 | 33.7% |
| blank | 13,397 | 25.7% |
| `src` | 13,340 | 25.6% |
| `xw` | 7,882 | 15.1% |

Precedence is **src > xw > syn**, enforced by
`test_syn_never_overwrote_a_real_value`.

### `fabricate` was over-claimed, and the audit was the point

Before wiring, **zero** of the 20 `fabricate` columns declared a generator, and
synth has one for only seven. Synth produces workflow, identity and risk-encoding
fields. It has nothing for `Site`, `Area`, `Unit`, `Date of Incident`,
`Description`, `What happened?` or `Incident Type A/B/C` — and it should not,
because inventing a platform designator or an incident date asserts something
specific and false about a real facility on a real day.

So 13 columns moved to `leave_blank`, and `gap_policy` now carries a
`blank_reason`:

* **`would_dominate`** (8 columns) — under 50% real, the D1 rule.
* **`no_generator`** (13 columns) — no honest way to produce the value,
  whatever the real share.

That split was forced by a **test contradiction**, not foresight: after moving
`Date of Incident` to `leave_blank`, the D1 test failed with *"Date of Incident
is 97.0% real but still leave_blank"*. Both facts were true. One policy was
carrying two arguments, and the test found it.

A **hash token is not a false claim.** `SYN-Approver-da5b09` says "we do not
know who", which is true; a plausible fake name would be worse than a blank,
because someone eventually quotes it. `test_synthetic_identities_are_never_
mistakable_for_people` pins that.

### Two bugs, one of which I reintroduced

**1. A bare `except Exception` produced zero synthetic cells, silently.**
`synth_date_fields` wants a `date` and was handed a string; the blanket handler
swallowed the `TypeError` and the run reported success with nothing written.
This is precisely the silent-plausible-wrong failure the repo keeps meeting,
reintroduced by the code meant to be careful about it. Replaced with a counted,
reported skip reason — which then immediately surfaced a second type error
(`incident_types` wants a set, not a list) that would otherwise have been
swallowed the same way.

**2. Synth wrote 143 illegal values into a controlled column.**
`syn_incident_classification` emits `"Unknown"`, which is not in E19's
three-value picklist. `test_projection.py::test_no_illegal_values_in_any_
committed_table` caught it. Synthetic values now clear the same vocabulary guard
`psm.project` applies to verbatim ones — *blank beats a wrong value in a
controlled column* — and the 143 rejections are reported rather than written.

### Result

| | before | after |
|---|---|---|
| real | 40.3% | **42.3%** |
| fabricated (projected) | 45.0% | **39.7%** |
| deliberately blank | 14.7% | **18.0%** |

Real rose because Phase 0's extraction fixes landed in the same regeneration.
Fabricated fell because 13 columns stopped claiming a fill they had no generator
for. Suite 348 → 350.

**The dataset is not dense, and that is now a stated property rather than an
unmet goal.** 25.7% of the incidents table is blank, every blank has a recorded
reason, and no column claims a fill it cannot honestly produce.

---

## 2026-08-29 — P2b: `--real-only` export and the era-stratified split

`psm.ledger --real-only` writes `data/processed/e19/real_only/` with all
**17,583 `syn` cells blanked**, plus `splits.json`.

**Blanked, not dropped.** The row survives, so joins hold and the absence is
visible. A consumer who wants only real values gets them; a consumer who ignored
provenance entirely gets a blank instead of a fabrication, which is the safer
failure of the two.

### The split is by regime, not by round numbers

A random train/test split on this corpus leaks the reporting era, and so would a
split on decades. The boundaries are where BSEE's vocabulary actually changed:

| regime | years | incidents | what changed |
|---|---|---|---|
| `free_prose` | ≤2006 | 161 | no controlled vocabulary at all |
| `human_error` | 2007–2009 | 258 | one head, `Human Error`, carries almost every mapped statement |
| `ad_hoc` | 2010–2018 | 438 | `Human Error` dies out before the modern six arrive; 68 investigator-invented heads |
| `modern_six` | 2019+ | 321 | the modern vocabulary; adoption jumps 5 → 17 between 2018 and 2019 |

36 undated incidents are excluded rather than assigned.

**2019, not 2020.** A tidier boundary at the decade would put the year the
vocabulary actually changed on the wrong side of the split. A test pins it, and
the mutation check confirms a decade boundary misplaces 2019.

`splits.json` carries the reasoning inline, and a test asserts every regime has
a non-empty description — a stratification nobody can justify gets ignored and
replaced with a random one.

### Verification

11 new tests. Mutation-checked against three failures: leaving `syn` values in
place, blanking everything (safe and useless), and a decade-boundary split. All
three caught; the baseline is clean.

The two that matter most are complementary. `test_no_syn_cell_survives` catches
under-blanking; `test_every_real_cell_survives` catches over-blanking. Either
alone passes trivially — one by exporting nothing, the other by exporting
everything.

Suite 350 → 356.

---

## 2026-08-29 — P2c: the fidelity check killed four of the seven synthetic fills

Where `syn` and real values share a column they must not be trivially
separable, or the fill carries no information and hands any model a free
"is this row synthetic" feature. Measured, total variation distance between the
two distributions:

| column | real n | syn n | TVD | what syn actually emitted |
|---|---|---|---|---|
| `Incident Classification` | 645 | 390 | **0.685** | the constant `"Incident"`, 100% |
| `Incident Classificatioin` | 645 | 390 | **0.685** | same |
| `Health & Safety Incident - Classification` | 645 | 390 | **0.685** | same |
| `Health & Safety - Risk Score` | 645 | 423 | **0.994** | `{2, 5, 9}` |

The risk-score case is worse than a distribution mismatch — it is a **scale
error**. `syn_hs_risk_score` is a 9/5/2 encoding of a three-value
classification; the real column is a consequence x likelihood product on 1-25,
emitting `{4,5,6,8,10,12,15,20,25}`. The two value sets intersect on the single
value `5`, where they mean different things. Putting them in one column is a
category error, not an approximation.

The cause is structural, not a bug in synth: **synth fills exactly the rows the
real method declined** — those with no spine atoms or an unestimable mechanism —
and those are systematically the low-severity, low-information ones. So the fill
collapses to a constant by construction.

All four moved to `leave_blank` with a new `blank_reason: degenerate_fill`. A
column filled this way looks like data and is not.

**Three fills survive**, all identity columns, and their separability is the
design rather than a defect: `SYN-Approver-da5b09` is supposed to announce
itself. A separate test asserts their TVD stays **above** 0.9 — if synthetic
identities ever blended in with real ones, that would be the failure.

### A second bug, found by the same test

After the four columns moved to `leave_blank`, `Incident Classificatioin` kept
filling. The crosswalk built its generator map from the presence of a
`generator:` key and never consulted `gap_policy`, so a stale key left behind by
the policy change carried on producing 390 constant cells. **A generator key is
not permission to fill** -- the policy decides, the generator only says how.
Fixed, and the stale keys removed.

### Result

| | before P2c | after |
|---|---|---|
| synthetic cells | 17,583 | **15,990** |
| deliberately blank | 18.0% | **20.0%** |
| columns still fabricating | 7 | **3** |

Suite 356 → 359. Phase 2 complete.

---

## 2026-08-29 — P3.1: the six cause categories are not the structure of the text

Clustered all 3,354 cause statements of five words or more, with the category
name **stripped** so the exercise is not circular. Agreement with
`schema/crosswalk.yaml`'s six categories, over the 503 labelled statements:

| | ARI vs the six | purity |
|---|---|---|
| category name **stripped** | **0.031** | 0.410 |
| category name kept (circular control) | **0.780** | 0.795 |
| majority-class baseline | — | 0.395 |

Purity of 0.410 against a 0.395 baseline is +1.5pp — noise. The six categories
are recoverable from the text **only because the text contains their names**.

The circular control is the load-bearing part of this result. Without it, a
naive run scores ARI 0.78 and "confirms" the crosswalk, which is a tautology
dressed as a finding: the string `"Human Performance Error:"` is *in the
statement being clustered*.

### Era is not the confound

Cluster-vs-era ARI is **-0.019** at k=6. The clusters are not tracking the
reporting regime, which was the obvious alternative explanation given that 87.1%
of labelled statements are `modern_six`.

### What the clusters actually track

| cluster | top terms |
|---|---|
| c0 | ip, placement, hand, pinch, pinch point |
| c1 | crane, operator, boom, load, lift |
| c2 | failure, valve, failed, gas, pressure |
| c3 | work, stop work, stop work authority, hot work |
| c4 | jsa, job safety analysis |
| c5 | cause, incident, probable cause, contributing (residual form furniture) |

These are **activity and hazard types** — a lift, a valve, hot work, body
position. BSEE's six categories are **attributions** — human error, equipment
failure, management systems. The narrative says *what was happening*; the
category says *who or what is blamed*. They are close to orthogonal axes, and
the clustering is measuring that rather than failing.

### But clustering is the wrong instrument for "is there signal"

Unsupervised structure and predictability are different questions, so the
supervised one was asked directly. Logistic regression on TF-IDF of the stripped
description, 5-fold stratified CV, n=503:

| | accuracy | macro-F1 |
|---|---|---|
| majority baseline | 0.392 | 0.094 |
| **logistic on TF-IDF** | **0.551** | **0.418** |

So the category **is** partially predictable from the description alone. The
clustering result does not mean "no signal" — it means the signal is not the
dominant axis of variation in the text.

Per category, and this is the more useful number:

| category | n | F1 |
|---|---|---|
| Equipment Failure | 128 | **0.692** |
| Human Performance Error | 197 | **0.639** |
| Management Systems | 81 | 0.400 |
| Communication | 34 | 0.310 |
| Supervision | 34 | 0.243 |
| Work Environment | 29 | 0.222 |

**The six-category task is really a two-class task with four rare classes
attached.** The top two are 65.5% of the labelled data and carry almost all the
learnable signal; the bottom three sit at n≈30 with F1 near 0.25.

### Consequences

* **A hackathon task framed as "predict the PSM element from cause text" should
  expect ~0.55 accuracy, not 0.9**, and should report macro-F1 — accuracy alone
  rewards predicting the two big classes and ignoring the rest.
* **Weak supervision (3.2) is worth less than it looked.** Labelling functions
  keyed on text patterns are fighting an axis the text does not strongly encode,
  and the four rare categories are where the LFs would be needed most.
* **The cluster taxonomy is a better-founded alternative target.** Lifting,
  process containment, body position, work control and JSA quality are
  data-driven, derivable without any labels, and describe this corpus better
  than the six do.

### Scope limits

503 labelled statements, 87.1% of them `modern_six`. The CV is stratified by
class, **not by era** — with 87% in one regime an era-stratified split would
leave too little elsewhere to train on, which is itself a finding about the
corpus. TF-IDF rather than sentence embeddings, chosen so a stranger can rebuild
this from a fresh clone per the reproducibility contract; a stronger encoder
would likely raise the supervised numbers and would not change the clustering
conclusion, which is about which axis dominates.

---

## 2026-08-30 — LLM labelling pilot: Haiku 4.5 vs Sonnet 4.5, model choice

`psm.llm_label --pilot --limit 60`, both via AWS Bedrock inference profiles
(`us.anthropic.claude-haiku-4-5-20251001-v1:0`,
`us.anthropic.claude-sonnet-4-5-20250929-v1:0`), on the same hash-ordered
60-statement sample of the 524 statements the crosswalk also labels.

| | Haiku 4.5 | Sonnet 4.5 |
|---|---|---|
| agreement with crosswalk (not accuracy) | 18/49 = 36.7% | 16/53 = 30.2% |
| self-consistency, high-confidence rate | 49/60 = 81.7% | 48/60 = 80.0% |
| parse-failure rate | 0/60 = 0.0% | 4/60 = 6.7% |
| abstention rate (`INSUFFICIENT`) | 11/60 = 18.3% | 3/60 = 5.0% |
| cross-model agreement, both labelled | 32/45 = 71.1% | (same pair) |

**Neither model fell into the element-5 word-match trap.** Of the 8 statements
in the sample containing "communicat*", zero were assigned element 5 by either
model — both routed them to 17 (in-task coordination) or 8, exactly the
distinction the prompt asks for. This is the more informative check than the
aggregate confidence number, since it tests the specific failure mode the
prompt was written to prevent, not just whether the model was internally
consistent.

**17 vs 6 splits differently, not worse.** Haiku: 17 assigned 15x, 6 assigned
10x. Sonnet: 17 assigned 25x, 6 assigned 7x. With no gold labels for this
sample, this is a difference in judgement, not evidence either model is
missing the distinction.

**Decision: Haiku 4.5, for the full run.** It matches or exceeds Sonnet on all
three deciding criteria — agreement, self-consistency, and parse-failure rate —
at roughly a third of the cost (~$10 vs ~$36 for 3,572 statements x 3 passes).
Sonnet's self-consistency was not materially worse, so the fallback trigger in
the run plan does not fire.

**Open caveat, not a reversal.** Haiku's abstention rate (18.3%) is well above
Sonnet's (5.0%) on this same sample, and above the corpus-wide 7.6%
"statement is unusable" rate — notable because this pilot is restricted to
statements the crosswalk *already* typed, so a higher floor was expected, not
a higher abstention rate. Worth re-checking against the full run, whose
majority is freetext rather than crosswalk-typed statements.

**A dependency gap, and a lost pilot run.** `boto3` was never declared in
`pyproject.toml` — `call_bedrock` imports it lazily, which hid the gap from
`uv run pytest` since nothing exercises the Bedrock backend in the suite.
Added to `dependencies`. Before the fix was caught, the first Haiku pilot
attempt ran all 180 real calls (~$0.30) and then crashed on `ModuleNotFoundError`
before that — no spend lost there. The *second* attempt, after the fix, did
spend the ~180 calls and then lost the output to a relative `--out` path that
resolved against an unexpected working directory at write time (all pilot
`--out` invocations now use absolute paths). Recorded because both were real
AWS spend with no output to show for it, and the second is the reason
`write_outputs` now checkpoints every 200 rows in the full run rather than
writing once at the end — a late failure on a 10,716-call run should not be
able to discard everything before it the way this pilot's did.

Suite still 361 passed, 2 skipped after these changes; the retry-with-backoff
path was mutation-checked against a mocked throttling error (recovers) and a
mocked non-retryable error (propagates on the first call, no wasted retries).

---

## 2026-08-30 — Gold sample rebuilt at statement grain, on the E19 tables

`gold_sample.py`/`gold_scaffold.py` sampled from `data/manifest.csv` (the
legacy BSEE-PDF-harvest pipeline) at report grain. R5 (2026-08-29, above)
already measured why that can never be scored: gold keys on `report_id` =
sha256 of the source PDF, `psm.llm_label`/`psm.crosswalk`/everything else
keys on `Incident Number` from the E19 workbook, and the direct join was 0 of
100. Rebuilt both modules to sample from `data/processed/e19/enriched/
causes.csv` and `incidents.csv` directly — the same tables `psm.llm_label`
reads — so the join exists by construction instead of needing a documented
two-hop workaround.

**A second problem, found while rebuilding, not before.** `gold_scaffold.py`
assigned one gold label per *report*. Checked against `causes.csv`: only
19.1% of incidents (231/1,210) have any crosswalk-typed cause at all, and of
those, 112 (48.5%) carry causes that disagree with each other on PSM element —
unsurprising once you look, since 90.5% of incidents (1,095/1,210) have more
than one cause statement. A report-level gold label can't represent a report
whose own causes span different categories. Sample and worksheet are now keyed
on `(Incident Number, Cause number)` — a statement — matching
`psm.llm_label.statements()`'s grain exactly.

### Design: two-pass stratification

1. **Category floor** (default 30/category): up to `category_floor` statements
   per BSEE cause category, so every category gets enough rows for its own
   agreement estimate. Category signal prefers the crosswalk's `xw_element`
   (524/3,572 statements, inverted from `schema/crosswalk.yaml`'s
   `primary_element` rather than re-hardcoded — CLAUDE.md's "never bury a
   mapping in a Python dict" applies here too) and falls back to
   `llm_cause_category` where the crosswalk found nothing.
2. **Era fill**: remaining budget spread across `psm.ledger.ERA_REGIMES`
   from whatever's left, same allocator shape (base share, floored, capped by
   availability, remainder to the eras with the most unused rows) the old
   report-level sampler used for years. This exists because crosswalk-typed
   statements are 87% `modern_six` (457/524) — a category-only sample would
   almost entirely skip `free_prose` and `ad_hoc`.

Selection within each stratum is by ascending `sha256(incident|cause)` — no
stored seed, same pattern `synth.py` uses for its hash offsets.

### Current sample (final — regenerated against the complete LLM run)

Generated `uv run python -m psm.gold_sample && uv run python -m psm.gold_scaffold`
at default `target_n=360`, `category_floor=30`, first against a 600/3,572
partial run (see the superseded numbers below), then re-run once the full
3,572-statement job finished:

| category | n | | era | n |
|---|---|---|---|---|
| Management Systems | 109 | | modern_six | 116 |
| Human Performance Error | 46 | | ad_hoc | 111 |
| Equipment Failure | 42 | | human_error | 75 |
| Communication | 30 | | free_prose | 57 |
| Supervision | 30 | | undated | 1 |
| Work Environment | 30 | | | |
| (none — era-fill only) | 73 | | | |

Category signal source: 71 from the crosswalk (`xw`), 216 from the LLM run
(`llm`), 73 with neither. Verified after regeneration: 360/360 unique
`(incident, cause)` keys, all `gold_*` cells blank.

**Superseded caveat, kept for the record.** The first pass above (now
overwritten) was built while the LLM job was at 600/3,572 checkpointed, so the
category-floor pass drew almost entirely on the crosswalk's `modern_six`-heavy
524 and that era was overrepresented (43.6% vs 27.3% of the full corpus) as a
direct consequence — 40/33/31/30/30/30 by category, 166 rows with no category
signal at all. The re-run against the complete corpus lets `llm_cause_category`
reach the freetext majority: `modern_six` share drops to 32.2% (116/360, in
line with corpus proportion), category coverage improves (`(none)` rows fall
from 166 to 73), and Management Systems balloons to 109 because it's now the
single largest LLM-assigned category among freetext statements pulled in by
era-fill, not a stratification bug — the category floor pass itself still caps
every crosswalk-typed category's *guaranteed* share at 30, exactly as designed.
Verified directly against `llm_causes.csv`: Management Systems is 1,374/2,423
(56.7%) of all non-abstaining `llm_cause_category` assignments corpus-wide,
more than the other five categories combined — worth watching during
hand-labelling as a possible LLM catch-all bias rather than assuming it
reflects the real category mix, since nothing in this pipeline has checked
that yet. `gold/gold_labels.csv`'s previous 100 rows had zero hand labels
(verified before the original rewrite), so regenerating twice cost nothing
real.

The worksheet (`gold/gold_labels.csv`) shows only `src_` reference fields
(incident, cause, year, era regime, site/area, cause description) and blank
`gold_` columns — never `xw_element` or `llm_cause_category`, which would
anchor a human labeller on a machine guess before they've read the text.

### Verification

13 new/rewritten tests (`tests/test_gold_sample.py`,
`tests/test_gold_scaffold.py`) replace the 15 report-grain ones — category
floor capping, era-fill coverage, no-duplicate-selection, determinism and
reorder-stability, worksheet field mapping, missing-key handling. Full suite:
359 passed, 2 skipped (was 361/2; net -2 matches the old suite having two more
report-grain-specific cases than the new one needs). Ran the real pipeline
end-to-end against the live `causes.csv`/`incidents.csv`/`llm_causes.csv` (not
just fixtures) and spot-checked the output: 360/360 keys unique, all six
`gold_*` columns blank across all rows, `src_site`/`src_area` byte-matching
the E19 workbook's own field semantics (site = area-code abbreviation like
`GC`/`MC`, area = block number — the source's own naming, kept as-is).

**Not yet done:** the actual hand-labelling, and the re-run once the full LLM
job finishes.

---

## 2026-08-30 — Full LLM labelling run complete: 3,572 statements x 3 passes

`psm.llm_label --backend bedrock --model us.anthropic.claude-haiku-4-5-20251001-v1:0`,
10,716 calls, ~2h50m wall clock, exit 0, no unrecovered throttling (retry path
never had to surface an error — see the mocked-failure verification in the
pilot entry above). `llm_causes.csv`: 3,572 rows. `llm_disagreements.csv`: 282
rows.

**Everything below is agreement with the crosswalk, not accuracy.** Both
`xw_element` and `llm_psm_element` are opinions derived from the same text by
different reasoning; neither is `gold_`. CLAUDE.md forbids reporting a metric
scored against `llm_` as if it were ground truth, and nothing here does that —
see the freshly-stratified `gold/gold_labels.csv` (previous entry) for what an
actual accuracy number will need.

### Agreement, overall and by category

Agreement is only measurable on the 524 statements the crosswalk also labels
(the other 3,048 are freetext with nothing to compare against):

| | n | agree | disagree | abstain | parse-failed |
|---|---|---|---|---|---|
| **all typed** | 524 | 133 (25.4%) | 282 (53.8%) | 107 (20.4%) | 2 (0.4%) |

| BSEE category (crosswalk primary element) | n | agree | abstain |
|---|---|---|---|
| Human Performance Error (3) | 207 | **9 (4.3%)** | 61 (29.5%) |
| Equipment Failure (15) | 136 | 74 (54.4%) | 29 (21.3%) |
| Management Systems (8) | 83 | 16 (19.3%) | 3 (3.6%) |
| Communication (9) | 34 | 2 (5.9%) | 3 (8.8%) |
| Supervision (17) | 34 | 25 (73.5%) | 2 (5.9%) |
| Work Environment (6) | 30 | 7 (23.3%) | 9 (30.0%) |

**The Human Performance Error → element 3 hypothesis, confirmed directly.**
This is the exact concern the run plan flagged before spending anything: a
22-row hand pass (`gold/llm_gold_typed.csv`, an earlier ad-hoc check) had
found 10/12 disagreements on this category. At full scale, 39.5% of the typed
corpus (207/524) is Human Performance Error, and the LLM agrees with `element
3` only 4.3% of the time on it — the single lowest agreement rate of any
category, dragging the 25.4% overall figure down substantially by itself (drop
Human Performance Error and the remaining 317 typed statements agree at
39.1%). Where it disagrees (135 non-abstaining cases), it isn't scattering:
**67 go to element 17** (work control, permit to work) and **37 to element 6**
(hazard identification) — the same two elements `schema/crosswalk.yaml`'s own
note already flagged as the live alternative ("Reviewers who believe these
should route to procedures (8) have a real argument" undersold it; 17 and 6
are the model's actual preference, not 8). This reads as the crosswalk's
category→element mapping being contestable on its own terms, not as a
labelling defect — exactly what `crosswalk.yaml`'s `confidence: medium` on
this entry already says, now with a number attached.

Communication (5.9%) is the other outlier low, consistent with
`crosswalk.yaml` marking it `confidence: medium` and noting the modal
subcategory split between handover (9) and job briefing (17). Supervision
(73.5%) and Equipment Failure (54.4%) — both `confidence: high`/`low` in the
crosswalk for different reasons — are where the two methods actually converge.

### Self-consistency

Measured the same way as the pilot comparison (`llm_confidence == "high"`,
i.e. all 3 passes landed on the same non-abstaining element):

| | n | high-confidence |
|---|---|---|
| full run (all 3,572) | 3,572 | 2,423 (67.8%) |
| pilot, typed-only (524-statement pool, n=60) | 60 | 49 (81.7%) |

Lower on the full run than the pilot predicted, and the reason is visible in
the data: the pilot sampled only from the 524 crosswalk-typed statements,
which tend to open with a recognisable category phrase and are less likely to
trigger partial abstention across passes. The freetext majority includes more
short/ambiguous fragments where one pass abstains while the other two don't
(or vice versa) — `consolidate()` marks that `low` confidence by design (`schema/
llm_labelling.yaml`: "low: no majority, or any pass abstained") even when the
non-abstaining passes agree with each other. Raw pass-convergence (all 3
parseable passes landing on the identical answer, abstain-or-not) is far
higher — 3,559/3,572 = 99.6% — but that number conflates "consistently
abstained" with "consistently answered," so it is not the comparable metric
to the pilot's; `llm_confidence == "high"` is.

### Abstention and parse-failure

| | n | rate |
|---|---|---|
| abstained (`INSUFFICIENT`) | 1,136 / 3,572 | 31.8% |
| total parse failure (no pass parsed) | 13 / 3,572 | 0.4% |

`schema/llm_labelling.yaml` records two independently-measured corpus
properties as the expected floor/ceiling for abstention: 7.6% of `Cause
Description` text is unusable (form-label residue or under five words) and
28.2% ends mid-sentence. 31.8% observed abstention sits close to that combined
range rather than far outside it — the model is not over-abstaining relative
to how degraded the source text actually is. Parse-failure (0.4%) is well
under the pilot's Sonnet rate (6.7%) and roughly matches Haiku's pilot rate
(0.0%) — the retry/checkpoint hardening added before this run had nothing to
recover from at scale.

### By era regime

Agreement (typed subset only — the crosswalk never reaches `free_prose`, so
that era has zero rows to compare):

| era | typed n | agree | | era | all n | abstain |
|---|---|---|---|---|---|---|
| modern_six | 457 | 128 (28.0%) | | modern_six | 976 | 239 (24.5%) |
| ad_hoc | 22 | 4 (18.2%) | | ad_hoc | 1,424 | 469 (32.9%) |
| human_error | 45 | 1 (2.2%) | | human_error | 666 | 231 (34.7%) |
| free_prose | 0 | — | | free_prose | 398 | 159 (39.9%) |
| | | | | undated | 108 | 38 (35.2%) |

Two things worth separating. Agreement does **not** cleanly fall off pre-2019
the way the run plan hypothesised it might — `human_error`'s 2.2% is
suspiciously low but n=45 is too small to trust on its own (a single category
skew away from Human Performance Error could move it several points), and
`ad_hoc` at 18.2% (n=22) is even thinner. Only `modern_six` (n=457) has enough
mass to say anything with confidence, and its 28.0% is close to the 25.4%
corpus-wide figure. What *does* trend cleanly with era is abstention:
24.5% → 32.9% → 34.7% → 39.9% from `modern_six` back to `free_prose`, a
monotonic increase as the source text gets older and (per the extraction
remediation entries above) harder to extract cleanly. That's a text-quality
gradient, not a model-quality one — consistent with the abstention-vs-baseline
comparison just above.

### What this changes

Nothing is written back to `crosswalk.yaml` from this — CLAUDE.md is explicit
that the crosswalk never changes from LLM output alone, and this run doesn't
attempt to. What it produces is exactly what the module's docstring promised:
an agreement number instead of an opinion, and a 282-row disagreement queue
(`data/processed/e19/llm_disagreements.csv`, sorted confident-disagreements
first) concentrated overwhelmingly in Human Performance Error — the queue to
hand a human next, not a verdict on its own.

**Not yet done:** hand-labelling the stratified gold sample, and computing an
actual accuracy number (`llm_` vs `gold_`, category and per-element) once that
exists. This run's numbers are agreement-with-crosswalk only and will not be
re-cited as accuracy anywhere in this repo.
