# Licence research notes — working file

Research log behind `DATA_SOURCES.md`. Records **what was actually fetched**, by
what method, and what could not be reached. Dead ends are kept deliberately:
a stranger checking our provenance claims needs to know where we hit a wall.

**All fetches in this log: 2026-08-02.** Not legal advice; see `DATA_SOURCES.md`.

---

## Method note — why some quotes are trusted and some are not

Two retrieval paths were used, and they are **not** equally reliable:

| Path | What it returns | Trust |
|---|---|---|
| `curl -sL` + local HTML→text strip | the literal bytes the server sent | **verbatim; quotable** |
| model-mediated page summariser (WebFetch) | a paraphrase of the page | **lead only; not quotable** |

Every quotation that reached `DATA_SOURCES.md` was re-fetched with `curl` and
grepped out of the raw HTML. Where a summariser produced a quote that `curl`
could not confirm, the quote was dropped rather than shipped. This distinction
is the whole reason this file exists.

---

## URLs checked

| URL | HTTP | Outcome |
|---|---|---|
| `https://www.bsee.gov/disclaimers` (plural — as originally briefed) | **404** | dead end; wrong path |
| `https://www.bsee.gov/disclaimer` (singular) | 200 | redirects → `bsee.gov/bsee.gov/privacy-disclaimer`; **primary licence evidence** |
| `https://www.bsee.gov/site-page/disclaimer` | 200 | same redirect target, byte-identical body |
| `https://www.data.bsee.gov/Main/Disclaimer.aspx` | 404 | dead end; guessed path, wrong |
| `https://www.data.bsee.gov/Main/HtmlPage.aspx?page=Disclaimer` | 200 | correct data-portal disclaimer |
| `https://www.data.bsee.gov/Other/DataTables/IncidentInvestigations.aspx` | 200 | 2,014 items / 101 pages; "last updated August 2, 2026 2:00 AM CST" |
| `https://www.data.bsee.gov/Other/DataTables/FieldDefinitions.aspx?page=incinv` | 200 | 7 field rows; **defect found, see below** |
| `https://www.data.bsee.gov/Main/RawData.aspx` | 200 | 39 `.zip` links; incinv → `/Other/Files/IncInvRawData.zip` |
| `https://www.bsee.gov/.../district-investigation-reports` | 200 | 581 PDF hrefs, 576 unique, 15 redacted-named |
| `https://www.bsee.gov/.../district-investigation-reports-archive` | 200 | 656 PDF hrefs, 0 redacted-named, years 2003–2013 |
| `https://www.bsee.gov/.../panel-investigation-reports` | 200 | **0 direct PDF hrefs** — landing pages, 3 pages of pagination |
| `https://www.doi.gov/copyright` | 200 | DOI third-party-content carve-out; verbatim confirmed |
| `https://catalog.data.gov/dataset/bsee-data-center-platform-rig-information` | 200 | JSON-LD `license` field — **best single artefact found** |
| `https://catalog.data.gov/api/3/action/package_search?...` | **404** | CKAN API not exposed at that path; used HTML + JSON-LD instead |
| `https://www.energyinst.org/terms` | **403** | blocked, browser UA too |
| `https://www.energyinst.org/technical/publications/topics/process-safety` | **403** | blocked |
| `https://publishing.energyinst.org/topics/.../element-20-...` | **403** | blocked |
| `https://www.energyinst.org/industry/publications/.../element-19-...` | **403** | blocked (WebFetch also 403) |

`energyinst.org` and `publishing.energyinst.org` returned 403 to **every**
attempt, including a full desktop-Chrome UA with `Accept`/`Accept-Language`
headers. This is bot protection, not a missing page — the pages exist and are
indexed. Consequence: **no EI text was verified first-hand.** See EI section.

---

## BSEE licence basis — what was actually found

### The operative sentence

From `https://www.bsee.gov/disclaimer` (→ `/bsee.gov/privacy-disclaimer`),
retrieved by `curl` and read out of the raw HTML:

> "Information presented on this website is considered public information and may be distributed or copied."

Immediately followed by:

> "Use of appropriate byline/photo/image credit is requested."

Read: "requested," not "required." An attribution *request* attached to a public
domain work is a courtesy norm, not a licence condition — but the repo should
honour it anyway, since honouring it costs nothing and refusing it looks bad.

### The independent corroboration — this is the strong one

The disclaimer page could be dismissed as a website footer rather than a data
licence. It cannot, because **BSEE itself nominates that page as the licence**
in its own machine-readable catalogue metadata. From the JSON-LD embedded in
BSEE's data.gov entry:

```json
"license": "https://www.bsee.gov/bsee.gov/privacy-disclaimer",
"publisher": {"@type": "Organization",
              "name": "Bureau of Safety and Environmental Enforcement"}
```

with `Access Level: public`. That is BSEE, in a structured metadata field whose
entire purpose is to declare a licence, pointing at the exact page quoted above.
The chain closes on itself.

**Caveat worth stating plainly:** the data.gov record inspected is the
*Platform/Rig Information* dataset, not Incident Investigations. It was reached
via search because a dedicated Incident Investigations catalogue entry was not
located. So the metadata is *portal-wide BSEE practice*, not a per-dataset
declaration for our exact table. Strong evidence; not airtight for this table.

### What was NOT found

No page anywhere on `bsee.gov` or `data.bsee.gov` uses the words "public
domain", "17 U.S.C.", "§ 105", "CC0", or names any licence. The § 105 reasoning
is **our inference from the nature of the publisher**, not a BSEE assertion.
`DATA_SOURCES.md` labels it as inference. This distinction was the single most
important thing to get right in this task.

### Accuracy disclaimers — relevant to ML, quoted verbatim

`https://www.data.bsee.gov/Main/HtmlPage.aspx?page=Disclaimer`:

> "Some errors may exist in this data and we are constantly working to find and eliminate them."

> "This computer data is not intended as a legal document and should not be constructed as such."

(`constructed` is BSEE's own typo for `construed` — reproduced as-is because it
is a verbatim quote. Do not silently correct it; a stranger grepping for our
quote must find it.)

Same page states the database is derived from documents submitted by "oil
companies, other Government Agencies, and/or the public" — i.e. **BSEE is partly
a transcriber of third-party submissions**, which is exactly the mechanism by
which non-federal content enters a nominally federal dataset.

`https://www.data.bsee.gov/Main/RawData.aspx`, on the raw ZIP downloads we use:

> "we do not provide support for the downloadable raw data"

> "suggested only for those with advanced knowledge of the data involved"

BSEE is disclaiming support for precisely the artefact this project's pipeline
consumes. Worth surfacing to hackathon users.

---

## Field-definitions defect — verified, reproducible

`FieldDefinitions.aspx?page=incinv` lists 7 rows. Two of them are `AREA_BLOCK`;
the second has a blank definition. `ACCIDENT_TYPE` — a real column, present in
the raw file header — **has no definition on the page at all.**

Raw file header, from `data/raw/incinv/IncInvRawData/mv_acc_investigations.txt`:

```
"DATE_OCCURRED","MILITARY_TIME","LEASE_NUMBER","AREA_BLOCK","ACCIDENT_TYPE","PANEL_DISTRICT","STATUS"
```

Almost certainly the duplicated `AREA_BLOCK` row is a copy-paste error where
`ACCIDENT_TYPE` belongs.

Reproduce with the grid-markup match given in `DATA_SOURCES.md` §8, **not** a
bare `grep -c 'AREA_BLOCK'` — that returns 3, because the name also occurs
inside an inline JavaScript control block. Caught this only by running the
command I had already written into the doc; the claim (2 grid rows) was right,
the command published to prove it was wrong. Verify commands by running them.

Implication for us: **the single most semantically important
column for PSM crosswalking is the one column BSEE does not define.** Our
`schema/crosswalk.yaml` therefore maps a vocabulary we inferred from observed
values, not from a published definition. That is an honest limitation, not a bug.

Also noted: `MILITARY_TIME` is declared `VARCHAR2(321)` — 321 characters for a
`HH:MM` value. Harmless, but a sign the field definitions are loosely maintained.

---

## Row count — verified two independent ways

The brief said "~2,011 rows". Both checks today say **2,014**:

1. Live table page reports "2,014 items across 101 pages".
2. Local raw extract: `wc -l` = 2015 lines − 1 header = **2,014 data rows**.

Two independent paths agreeing is meaningful; a single number is not. The count
is live and grows, so `DATA_SOURCES.md` states it as a dated observation and
points at `spine.py` output as the authority.

Local ZIP as observed today (another agent owns `data/manifest.csv`; this is
recorded here only so the two can be compared, not as a competing claim):

```
sha256  70cc083f9a20a791889a2bff366894c81f1dde6b8ce958f79434457fa8882faf
        data/raw/IncInvRawData.zip
inner   IncInvRawData/mv_acc_investigations.txt  174,107 bytes  2026-08-02 04:49
```

The inner file's mtime (2026-08-02 04:49) is consistent with the portal's stated
refresh at 2026-08-02 02:00 CST. The ZIP *directory entry* still carries
`2021-05-13` — a stale container timestamp. Anyone hashing the ZIP will see it
change whenever BSEE regenerates it; **hash the inner `.txt`, not the ZIP**, if
a stable identity is wanted. Flagged for whoever owns the manifest.

---

## Redactions — counted, not assumed

Current district index: **15 of 576** unique PDFs carry a redaction marker in the
filename. Naming is inconsistent, which matters for anyone writing a detector:

```
W&T 7Mar2026 GB 783_Redacted.pdf          → _Redacted
GC 584 25-Dec-2024 signed 2010 redacted.pdf → lowercase, space-separated
MC 127 Anadarko 21-Oct-2023 Redacted.pdf   → capitalised, space-separated
SM 130 04Feb23 Redacted 2010.pdf           → mid-filename
```

A naive `endswith("_Redacted.pdf")` catches roughly a third of them. Case-
insensitive substring `redact` is the correct test.

Archive page (2003–2013): **0 of 656** filenames marked. Two readings, and we
cannot distinguish them from filenames alone: either older reports were never
redaction-reviewed, or they were redacted without the filename convention. The
second is more worrying for a public corpus. Treat the archive as **unverified
for PII**, not as "clean".

Inference recorded as inference: filename-level redaction implies BSEE removed
material — names, and plausibly operator commercial detail — from *some*
documents. It says nothing about the other 561, which were either reviewed and
found clean, or not reviewed. We do not know which.

---

## Panel vs district — structural difference that breaks naive scraping

- **District** index: direct `.pdf` hrefs under `/sites/bsee.gov/files/YYYY-MM/`.
  One fetch of the index yields every URL.
- **Panel** index: **zero** `.pdf` hrefs. Rows link to per-report landing pages
  ("Please click into each report to find associated documents"), paginated
  across 3 pages. Requires two-level crawl.

Anyone who writes one scraper for both silently gets zero panel reports and
never notices. Recorded because it is the kind of thing that produces a quietly
wrong dataset.

---

## Energy Institute — the genuinely unresolved one

### Verified

Element 19's name is **"Incident reporting and investigation"**. Confirmed from
EI's own publication title as indexed at `energyinst.org` — the URL slug
`...framework-element-19-incident-reporting-and-investigation` is EI's own
wording, on EI's own domain. The *page body* was never retrieved (403). So: the
element name is corroborated from an EI-controlled URL, not from EI page text
read first-hand. Element 20 ("Audit, assurance, management review and
intervention") appears the same way, which shows the pattern is EI's, not ours.

Framework structure — 2010 publication, 4 focus areas, 20 elements — is
consistently reported across independent third-party sources. Treated as
established fact about the framework's *shape*.

### NOT verified — and this is the load-bearing gap

EI's terms of use were **never retrieved**. Search-engine snippets indicate
energyinst.org asserts ownership of IP in its published material, reserves all
rights, and forbids reproduction beyond private use without written permission.
That is entirely consistent with a UK professional body that sells its
publications — but it is **a snippet, not a page we read**. It is not quoted in
`DATA_SOURCES.md`, because quoting an unverified snippet as if it were verified
terms is exactly the failure mode this repo is supposed to avoid.

### Reasoning to the recommendation

Three things pull in the same direction:

1. **Names vs text.** Element names are short factual labels. EI publishes them
   openly as publication titles, course descriptions, and marketing copy —
   naming a framework's parts is how a framework gets adopted. Short titles are
   generally weak candidates for copyright protection, and referencing a
   published standard by name with attribution is ordinary scholarly practice.
2. **But we could not read the terms.** So the confident version of that argument
   rests on unverified ground.
3. **And we lose nothing by being careful.** The ML task keys on *element number*.
   Element names are labelling convenience. The cost of dropping to numbers-only
   is near zero; the cost of being wrong on a public repo is not.

When an argument is probably fine but unverifiable, and the conservative option
is nearly free, take the conservative option. Hence: **numbers-only in the
machine-readable schema, names only in prose where attribution is adjacent.**

The workbook `E19 Investigation Report - Rev2.xlsx` was **not located, not
opened, not downloaded, and not referenced** at any point. Out of scope by
instruction and left that way.

---

## Open items for whoever picks this up

1. Retrieve `https://www.energyinst.org/terms` through a real browser and record
   the verbatim clause. Upgrades the EI section from inferred to verified.
2. Find a per-dataset data.gov entry for Incident Investigations, if one exists.
   Would tighten the licence chain from portal-wide to table-specific.
3. Sample redacted vs non-redacted PDFs to see what was actually removed. Would
   replace inference about PII/CBI with observation.
4. Determine whether 2003–2013 archive reports were redaction-reviewed at all.
   Currently unknown and flagged as such.
