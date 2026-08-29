# E19 completion — walkthrough plan

Phase 1 populated 23 of 65 E19 fields verbatim. This plan covers the other 42,
by converting domain knowledge into **versioned rule files** that a module can
apply across all 1,215 incidents and 3,462 cause statements.

## The operating principle

**Every question put to a human must be one that could not have been answered by
looking at the data.** So each session is preceded by prep work — pull the
distinct values, compute the distribution, count the coverage — and the human is
only ever asked to make the call that genuinely needs judgement.

Corollary: a session that asks "what should `Incident Type C` be?" has failed.
The right question is "here are the 31 distinct `ACCIDENT_TYPE` values BSEE
publishes, with counts — which E19 picklist value does each become?"

## What this produces, and what it does not

Each session emits a rule file under `schema/`, applied by one module, with
output columns carrying the **`xw_` prefix**. That prefix is load-bearing:

> **Nothing this walkthrough produces is ground truth.** A crosswalk is an
> opinion applied consistently. `gold_` remains reserved for a human labelling
> individual records, and metrics are still scored against `gold_` only. This
> exercise makes the dataset *complete*; it does not make it *validated*.

---

## Session 0 — Evidence pack (no input needed)

Prep for everything below. For each of the 42 unfilled fields, assemble: the
candidate BSEE source, its coverage, and its distinct values or distribution.

Output: `docs/e19_evidence_pack.md`. One table per field group. This is what
makes the later sessions fast — without it, each question turns into an
investigation.

---

## Session 1 — Incident Type A/B/C/D  *(4 fields, 1,215 records)*

**Why first:** the biggest coverage win for the least judgement, and it exercises
the whole rules-file pipeline on something low-risk.

**Prep:** distinct values of the spine's `ACCIDENT_TYPE` with counts. It is
already a controlled vocabulary from BSEE's own database — `Fire` 515,
`Required Evacuation` 452, `Pollution` 440, `LTA (>3 days)` 264, `Crane` 177,
`Fatality` 85, `Blowout` 58. Roughly 30 distinct values covering every record.

**The ask:** for each BSEE value, the E19 Type A (Loss Event / Near Hit), B
(H&S / Env & Reputation / BI & Cost), C (13 values) and D (15 values).

**Watch for:** `ACCIDENT_TYPE` is multi-valued (`Fire - Injury - Required
Evacuation`). E19 Type C and D are single-valued. The precedence rule — which
wins when a record is both a Fire and an Injury — is a decision, not a detail.

**Output:** `schema/xw_incident_type.yaml` · applied by `psm.crosswalk`
**Validates by:** every record receives a Type A and B; zero `ACCIDENT_TYPE`
values fall through unmapped; the fall-through list is empty or explicitly
accepted.

---

## Session 2 — Re-base the PSM element crosswalk  *(1 field, 3,462 cause rows)*

**Why early:** `schema/crosswalk.yaml` already exists and is **keyed to the wrong
numbering**. It routes Equipment Failure to element 7, describing it as
"maintenance, inspection and repair adequacy" — but element 7 in the template is
`Documentation, records and knowledge management`; `Inspection and maintenance`
is element 15. It was written deliberately blind (energyinst.org returns 403), so
this is not a defect in the reasoning, only in the numbering it was anchored to.

Applying it as-is would put a systematically wrong element on every cause row.

**Prep:** the 6 induced categories against the 20 element names now in
`schema/e19_labels.yaml`.

**The ask:** confirm or correct the element number for each of the 6 categories,
keeping the existing `confidence` and `note` fields — the notes are good and
should survive the re-basing.

**Output:** `schema/crosswalk.yaml` v2, `target_element_reference` naming the
template as the authority.
**Validates by:** every element number resolves to a name in `e19_labels.yaml`;
a regression test asserting the two files agree, so this cannot silently drift
again.

---

## Session 3 — Cause qualifiers  *(3 fields, 3,462 cause rows)*

`Cause type`, `Risk Management Cause`, `Human Factors  Cause`.

**Prep:** the induced cause vocabulary — 6 categories, plus subcategories and
the field they came from. **Field 18 (probable) vs 19 (contributing) is adjacent
to Root vs Immediate/Underlying but is not the same axis**; whether it is a
usable proxy is exactly the judgement needed.

**The ask:** map each category/subcategory to the three E19 picklists. Some will
be one-to-many or genuinely undecidable from the category alone — mark those
`null` rather than guessing, so they surface as gaps rather than as confident
errors.

**Watch for:** ~28% of cause statements are typed; the rest are free prose with
no category. Those get nothing from this session and stay blank pending the
LLM-assisted path.

**Output:** `schema/xw_cause_qualifiers.yaml`
**Validates by:** typed statements receive all three qualifiers or an explicit
`null`; the untyped share is reported, not hidden.

---

## Session 4 — Consequence tiers  *(3 fields, plus 3 Risk Scores)*

**The session where domain knowledge does the most work.**

**Prep:** real distributions, not categories —
- Financial: `ESTIMATED AMOUNT (TOTAL)` parsed from `bsee_property_damaged`, present on **99.8%** of records. Histogram plus the extremes.
- H&S: counts of Fatality / LTA(>3d) / LTA(1-3d) / RW-JT / Other Injury / no injury.
- Environment: pollution volumes where stated in narrative, and `Pollution` flag counts.

**The ask:** the A–E boundary on each scale. *"Is a 17,098-gallon glycol release
a B or a C on your Environment scale"* is a question only you can answer, and
answering it once fills 440 records.

**Watch for:** these tiers describe the **actual** outcome. E19 Section 3 asks
for the **worst reasonably expected** outcome. Deriving potential from actual is
a real methodological choice — it will systematically under-rate near misses,
which is the class E19 exists to catch. **Record that limitation in the rule file
itself**, so nobody downstream mistakes these for assessed severities.

**Output:** `schema/xw_consequence_tiers.yaml`
**Validates by:** every tier boundary is exercised by at least one real record;
the distribution across A–E is reported for a sanity check rather than assumed.

---

## Session 5 — Questions for the template author  *(batch, async)*

Nothing here needs Seth in the room; it needs the workbook's author. Batched so
it goes out once.

1. **The Consequence × Likelihood → Risk Score matrix.** Not recoverable from the
   workbook — the picklist lists scores 1–25 but not the mapping. **Blocks all
   three Risk Score fields and all three per-matrix Classifications.**
2. Data model or form canonical, where the four field names disagree.
3. Should `Accepted` exist, given it is on the form but absent from
   `Database Fields`.
4. How to disambiguate `Description` at E18 vs E23.
5. Does every cause need a PSM element, including environmental preconditions
   like saltwater corrosion?

---

## Session 6 — The residue: decide policy, do not elicit rules

Fields where no rule will help. The output is a **decision**, not a mapping.

| Group | n | Options |
|---|---|---|
| `What was the worst outcome...` | 1 | LLM-assisted from narrative, human, or leave blank |
| Likelihood ×3 | 3 | Needs the org's own frequency model — probably leave blank |
| Unmitigated / Mitigated risk ×6 | 6 | No BSEE analogue at all; synthesise or leave blank |
| Workflow fields — owners, agreed dates, close-out, schedule status | ~21 | `synth.py` already exists for exactly this |

**Recommendation going in:** leave Likelihood blank. Deriving it would be
inventing an actuarial judgement and dressing it as data — and Section 3's
credibility is the thing most worth protecting.

---

## Then: the automation

Every session above produces `schema/xw_*.yaml`. The code is one thin module per
rule file plus a runner, because the design work is in the YAML:

```
psm.crosswalk  --  applies xw_incident_type, xw_cause_qualifiers,
                   xw_consequence_tiers, crosswalk (PSM elements)
psm.synth      --  already exists; extend to the workflow fields
psm.project    --  gains xw_ columns alongside src_
```

**One rule holds throughout: `src_` never changes.** Crosswalked values land in
`xw_` columns beside the source, so any mapping can be audited, re-run or
reversed without re-extraction. Re-running the whole crosswalk after an argument
about Session 4's boundaries should cost minutes.

## Sequencing

```
Session 0  evidence pack ─┬─ S1 incident type ──┐
                          ├─ S2 PSM re-base ────┤
                          ├─ S3 cause qualifiers┼─ psm.crosswalk ─ re-project
                          └─ S4 consequence ────┘
Session 5  author questions ── (unblocks Risk Scores + Classifications)
Session 6  residue policy   ── psm.synth
```

S1–S4 are independent and can run in any order or in one sitting. S5 is async
and blocks 6 fields. S6 can happen any time.

## Expected end state

| | now | after S1–S4 | after S5 | after S6 |
|---|---|---|---|---|
| Populated | 23 | ~31 | ~37 | ~58 |
| Genuinely blank | 42 | 34 | 28 | ~7 |

Roughly. The point of Session 0 is to replace these estimates with counts before
anyone spends time on the sessions themselves.

## What this does not fix

- **The ~28% typed-cause ceiling.** Sessions 2 and 3 only reach cause statements
  that carry a category. The other 72% need the LLM-assisted path, which is
  downstream of a gold set.
- **Revision A/B field absorption** (P1) — `Unit` at 1.6% on revision A is an
  extraction bug, not a mapping gap. No rule file helps.
- **Ground truth.** Everything here is `xw_`. Scoring still requires `gold_`.
