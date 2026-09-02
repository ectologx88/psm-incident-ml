"""The disposition ledger, made self-policing.

`schema/e19_disposition.yaml` is not documentation. Each entry is a **claim
about the world** -- that no BSEE report can supply this column, that this other
one carries real values, that fabricating a third one's gaps is acceptable. A
claim nobody checks decays into decoration, and a stale audit is worse than none
because it reads as authority while describing a table that no longer exists.

This matters more here than in most projects. The dataset is dense by
construction: every cell the source cannot supply is fabricated. The only thing
separating a real value from an invented one is the provenance marking, and the
only thing guaranteeing the marking means what it says is this file plus these
tests.
"""

from __future__ import annotations

import pytest

from psm.ledger import (
    ALL_DISPOSITIONS,
    DEFAULT_OUT,
    GAP_POLICIES,
    REPO,
    load_disposition,
    measure,
    measure_provenance,
    reconcile,
    render,
    tally,
    validity,
)

pytestmark = pytest.mark.skipif(
    not measure(), reason="run `python -m psm.project` and `python -m psm.crosswalk` first")


@pytest.fixture(scope="module")
def spec() -> dict:
    return load_disposition()


@pytest.fixture(scope="module")
def seen() -> dict:
    return measure()


@pytest.fixture(scope="module")
def prov() -> dict:
    return measure_provenance()


def _entries(spec):
    for table, cols in spec["fields"].items():
        for col, entry in cols.items():
            yield table, col, entry


class TestTheFileDescribesTheData:
    def test_no_column_lacks_a_disposition(self, spec, seen):
        """An undeclared column is a cell of unknown provenance in a dataset
        whose entire value proposition is known provenance."""
        missing, _ = reconcile(spec, seen)
        assert missing == [], f"columns with no disposition: {missing}"

    def test_no_disposition_describes_a_column_that_is_gone(self, spec, seen):
        _, orphan = reconcile(spec, seen)
        assert orphan == [], f"dispositions for columns not in the data: {orphan}"

    def test_every_disposition_is_from_the_closed_set(self, spec):
        for table, col, entry in _entries(spec):
            assert entry["disposition"] in ALL_DISPOSITIONS, \
                f"{table}.{col!r}: unknown disposition {entry['disposition']!r}"

    def test_every_real_column_declares_a_gap_policy(self, spec):
        """What happens in a real column's empty cells is the whole question.
        Leaving it implicit is how a `syn` value ends up unremarked beside a
        `src` one."""
        for table, col, entry in _entries(spec):
            if entry["disposition"] != "real":
                continue
            assert entry.get("gap_policy") in GAP_POLICIES, \
                f"{table}.{col!r}: real column with gap_policy {entry.get('gap_policy')!r}"


class TestTheRenderedFileMatchesItsSource:
    """README.md says this file 'fails the build if any claim in it stops
    being true' -- but every other test in this module checks a *claim*
    (a number, a policy) against the data, not the *rendered markdown*
    against its own generator. A `generator:` name can change in
    schema/e19_disposition.yaml, `psm.ledger` regenerate correctly when run
    by hand, and the committed docs/e19_field_ledger.md still say the old
    thing, because nothing here ever re-ran the render and diffed it. This
    closes that gap: it is the render step itself, so it cannot drift from
    what `uv run python -m psm.ledger` would produce."""

    def test_committed_ledger_is_freshly_regenerated(self, spec, seen, prov):
        stats = tally(spec, seen, prov)
        val = validity(spec)
        rendered = render(spec, seen, stats, val, prov)
        committed = DEFAULT_OUT.read_text(encoding="utf-8")
        assert rendered == committed, (
            "docs/e19_field_ledger.md does not match schema/e19_disposition.yaml "
            "-- run `uv run python -m psm.ledger` and commit the result")


class TestTheClaimsAreTrue:
    def test_real_columns_carry_data(self, spec, seen):
        """The regression guard. A column that quietly empties -- an extractor
        keying on a heading that vanished, a join that stopped joining -- is a
        failure mode this repo has already hit twice, and once the synth layer
        is wired it would be invisible: the column would still look full."""
        empty = [f"{t}.{c!r}" for t, c, e in _entries(spec)
                 if e["disposition"] == "real" and seen[t][c][0] == 0]
        assert empty == [], f"marked real but carrying nothing: {empty}"

    def test_gap_policy_none_means_the_column_really_is_complete(self, spec, seen):
        """`none` asserts there is nothing to fill. If such a column has holes,
        those holes will silently stay empty in a dataset that promises density."""
        for table, col, entry in _entries(spec):
            if entry.get("gap_policy") != "none":
                continue
            n, total = seen[table][col]
            assert n == total, (
                f"{table}.{col!r} claims gap_policy: none but is {n}/{total}")

    def test_synthetic_columns_carry_syn_provenance(self, spec):
        """Rewritten 2026-08-29 when synth was wired, as its predecessor's
        failure message instructed. It previously asserted these columns were
        EMPTY; it now asserts every value in them is marked `syn`.

        An unmarked fabricated column is the single worst outcome available to
        this project, so the assertion moved rather than being deleted."""
        import csv as _csv
        from psm.ledger import E19
        _csv.field_size_limit(10 ** 9)
        with (E19 / "enriched" / "incidents.csv").open(encoding="utf-8", newline="") as fh:
            data = list(_csv.DictReader(fh))
        with (E19 / "enriched" / "provenance.csv").open(encoding="utf-8", newline="") as fh:
            prov = list(_csv.DictReader(fh))
        checked = 0
        for col, entry in spec["fields"]["incidents"].items():
            if entry["disposition"] != "synthetic_column" or not entry.get("generator"):
                continue
            for d, p in zip(data, prov):
                if (d[col] or "").strip():
                    checked += 1
                    assert p[col] == "syn", f"{col!r}: value marked {p[col]!r}, not syn"
        assert checked > 0, "no synthetic column carries any value -- synth is not wired"


class TestTheGeneratorPromisesAreKeepable:
    def test_named_generators_exist(self, spec):
        """A generator name is a promise. `null` is an honest admission and is
        allowed; a name that does not exist is a to-do disguised as a plan.

        Rewritten 2026-08-30 when fill.py was wired. The check previously
        assumed synth.py was the only generator module and looked up names
        in SYN_COLUMN_MANIFEST alone; this branch introduces fill.py as a
        second producer (the filled/ layer's Work Group, gated Likelihoods,
        and Cause type), so the lookup now checks the union of
        synth.SYN_COLUMN_MANIFEST and fill.FILL_COLUMN_MANIFEST. The
        promise-checking intent -- every named generator must actually
        exist somewhere -- is unchanged."""
        from psm.fill import FILL_COLUMN_MANIFEST
        from psm.synth import SYN_COLUMN_MANIFEST
        known = set(SYN_COLUMN_MANIFEST) | set(FILL_COLUMN_MANIFEST)
        for table, col, entry in _entries(spec):
            gen = entry.get("generator")
            if entry["disposition"] != "synthetic_column" or gen is None:
                continue
            assert gen in known, (
                f"{table}.{col!r} names generator {gen!r}, which neither "
                f"synth.py nor fill.py produces")

    def test_every_synthetic_column_declares_its_generator_key(self, spec):
        """Including as `null`. Omitting the key hides the columns with no
        generator behind an absence rather than naming them."""
        for table, col, entry in _entries(spec):
            if entry["disposition"] == "synthetic_column":
                assert "generator" in entry, \
                    f"{table}.{col!r}: synthetic_column with no generator key"

    def test_reason_files_named_for_declined_judgements_exist(self, spec):
        """Several synthetic columns are synthetic because our method declined
        to estimate, not because the source is silent. That distinction is only
        meaningful while the reasoning is readable."""
        for table, col, entry in _entries(spec):
            where = entry.get("reason_recorded_in")
            if where:
                assert (REPO / where).exists(), f"{table}.{col!r}: {where} does not exist"


class TestModellingTargetsAreFlagged:
    def test_every_cause_label_column_is_a_modelling_target(self, spec):
        """The causes table is the dataset's point: one prose input and four
        labels over it. Forgetting to flag one means --real-only silently ships
        fabricated labels as ground truth."""
        for col, entry in spec["fields"]["causes"].items():
            if col in ("Incident Number", "Cause number", "Cause Description"):
                continue
            assert entry.get("modelling_target"), \
                f"causes.{col!r} is a label over Cause Description but is not flagged"

    def test_the_primary_input_feature_is_not_fabricated(self, spec, seen):
        """If Cause Description were ever fabricated or gap-filled, the dataset
        would have no real input left and nothing downstream would be worth
        modelling."""
        entry = spec["fields"]["causes"]["Cause Description"]
        assert entry["disposition"] == "real"
        assert entry["gap_policy"] == "none"
        n, total = seen["causes"]["Cause Description"]
        assert n == total


class TestTheHeadlineIsWellFormed:
    def test_the_cell_accounting_is_exhaustive(self, spec, seen, prov):
        s = tally(spec, seen, prov)
        assert s["real_cells"] + s["pseud_cells"] + s["fabricated_cells"] \
            + s["unfilled_cells"] == s["total_cells"]

    def test_the_dataset_is_not_claimed_to_be_all_real(self, spec, seen, prov):
        """A denominator quietly narrowed to the real columns would report 100%
        real and be worthless. If this ever passes vacuously, the ledger has
        stopped counting the fabricated majority."""
        s = tally(spec, seen, prov)
        assert s["fabricated_cells"] > 0
        assert s["real_cells"] < s["total_cells"]

    def test_a_meaningful_share_is_real(self, spec, seen, prov):
        """The other direction. A dataset that drifted to almost entirely
        fabricated would still pass every test above while being useless; this
        is the floor below which the corpus has stopped being the point."""
        s = tally(spec, seen, prov)
        assert s["real_cells"] / s["total_cells"] > 0.25, (
            f"only {100 * s['real_cells'] / s['total_cells']:.1f}% of cells are real")


class TestRealMeansProvenanceReal:
    """The 2026-09-01 adversarial review's data-quality finding.

    `measure()` counts presence, and the render labelled that count "real":
    a column of 1,147 pseudonyms and 67 synthetic fills read as "100.0%
    real", and syn gap-fill inside declared-real columns inflated the
    headline the same way. "Real" in this ledger means what the headline
    says it means -- src or xw per the cell's provenance token -- so the
    numbers must come from the provenance files wherever one exists.
    """

    def test_pseudonymised_cells_are_not_counted_real(self, prov):
        pc = prov["incidents"]["Investigation leader - Name"]
        assert pc["real"] == 0, pc
        assert pc["pseud"] > 1000, pc

    def test_syn_gap_fill_is_not_counted_real(self, seen, prov):
        """Owner-Position is 1,074 src + 138 syn; the old ledger reported
        99.8% real because the syn fills are non-empty."""
        pc = prov["incidents"]["Investigation Acceptor/Approver (Owner)- Position"]
        n, total = seen["incidents"]["Investigation Acceptor/Approver (Owner)- Position"]
        assert pc["real"] < n, "provenance-real should exclude the syn fills"
        assert pc["real"] + pc["fab"] == n, (pc, n)

    def test_the_rendered_row_tells_the_truth(self, spec, seen, prov):
        stats = tally(spec, seen, prov)
        rendered = render(spec, seen, stats, validity(spec), prov)
        row = next(l for l in rendered.splitlines()
                   if "`Investigation leader - Name`" in l)
        assert row.startswith("| 0.0% |"), row

    def test_headline_real_matches_the_token_files(self, spec, seen, prov):
        """The tally must equal a direct count over the provenance files for
        the provenanced tables, plus presence for declared-real columns of
        the tables that have none."""
        s = tally(spec, seen, prov)
        direct = sum(c["real"] for t in prov.values() for c in t.values()
                     if c is not None)
        unprov = sum(
            n for table, cols in seen.items() if table not in prov
            for col, (n, _) in cols.items()
            if (spec["fields"].get(table, {}).get(col) or {}).get("disposition") == "real"
        )
        assert s["real_cells"] == direct + unprov


@pytest.fixture(scope="module")
def tokens(spec) -> list[str]:
    return [t.upper() for t in spec["form_label_tokens"]]


class TestValidityIsSeparateFromCoverage:
    """`real` must not mean `non-empty`.

    Under the old definition `Recommendation Description` read 100% real while
    30.4% of its values were BSEE stationery. Presence and correctness are two
    different claims and the ledger now makes both.
    """


    def test_form_furniture_fails(self, spec, tokens):
        from psm.ledger import check_value
        raw = ("RECOMMENDATIONS TO PREVENT RECURRANCE NATURE OF DAMAGE: none $ "
               "NARRATIVE: The New Orleans District makes no recommendations.")
        assert check_value(raw, {"no_form_label": True}, tokens) == "form_label"

    def test_real_prose_passes(self, spec, tokens):
        from psm.ledger import check_value
        raw = "The district recommends the operator revise its lift plan."
        rules = {"no_form_label": True, "min_words": 4, "terminal_punctuation": True}
        assert check_value(raw, rules, tokens) is None

    def test_truncation_is_named_separately_from_contamination(self, spec, tokens):
        """Different problems: one lost text, the other gained furniture.
        Collapsing them into a boolean would hide which."""
        from psm.ledger import check_value
        rules = {"no_form_label": True, "terminal_punctuation": True}
        assert check_value("The IP was transported to", rules, tokens) == "truncated"

    def test_an_empty_cell_is_not_invalid(self, spec, tokens):
        """Emptiness is coverage. Counting it as a validity failure would double
        count it and make the two numbers move together."""
        from psm.ledger import check_value
        assert check_value("", {"min_words": 5}, tokens) is None

    def test_every_declared_check_is_from_the_closed_set(self, spec):
        from psm.ledger import VALIDITY_CHECKS
        for table, col, entry in _entries(spec):
            for k in (entry.get("validity") or {}):
                assert k in VALIDITY_CHECKS, f"{table}.{col!r}: unknown check {k!r}"

    def test_checks_are_declared_where_they_can_fail(self, spec, seen):
        """A check that passes on 100% of a column tells nobody anything. This
        does not demand failures forever -- it demands that when a column reaches
        100% valid, someone decides deliberately whether the check still earns
        its place."""
        from psm.ledger import validity
        val = validity(spec)
        assert val, "no column declares a validity check"
        useful = [c for tb in val.values() for c in tb.values() if c["fails"]]
        assert useful, "every validity check passes everywhere -- they are decoration"

    def test_the_primary_join_key_is_checked(self, spec):
        """`Incident Number` joins all four tables. Its shape is variable-arity
        and 38 keys carry a time with no date; the check keeps that visible."""
        assert spec["fields"]["incidents"]["Incident Number"]["validity"]["pattern"]

    def test_form_label_tokens_are_not_the_same_list_that_strips_them(self, spec):
        """A detector sharing patterns with the thing it checks can only report
        success. These are deliberately two lists in two files."""
        import yaml
        from psm.ledger import REPO
        form = yaml.safe_load((REPO / "schema" / "bsee_form2010.yaml")
                              .read_text(encoding="utf-8"))
        assert set(spec["form_label_tokens"]) != set(form["label_bleed_patterns"])


class TestTheGapFillSplit:
    """Six columns keep their blanks; the rest get filled.

    The line is 50% real -- the point where a glance at a column gives the right
    general impression without checking provenance. Above it, "mostly real with
    some fill"; below it, "mostly invented", which a dense column would hide.
    """

    def test_leave_blank_columns_are_the_minority_real_ones(self, spec, seen):
        """The policy must follow the data, not a preference. If a column's real
        share crosses 50%, its policy should be revisited deliberately rather
        than left to drift."""
        for table, col, entry in _entries(spec):
            if entry["disposition"] != "real":
                continue
            n, total = seen[table][col]
            share = n / total
            if entry.get("gap_policy") == "leave_blank":
                # Two reasons, one policy. The 50% rule is only about the
                # `would_dominate` case; `no_generator` applies at any share --
                # `Date of Incident` is 97.0% real and still unfillable, because
                # inventing a date asserts when a real incident happened.
                assert entry.get("blank_reason") in (
                    "would_dominate", "no_generator", "degenerate_fill"), \
                    f"{table}.{col!r}: leave_blank with no blank_reason"
                if entry["blank_reason"] == "would_dominate":
                    assert share < 0.5, (
                        f"{table}.{col!r} is {100 * share:.1f}% real but still "
                        "leave_blank/would_dominate -- it crossed the line; "
                        "decide deliberately")
            elif entry.get("gap_policy") == "fabricate":
                assert share >= 0.5 or total == n, (
                    f"{table}.{col!r} is only {100 * share:.1f}% real but marked "
                    "fabricate -- fabrication would dominate the column")

    def test_the_cause_labels_are_all_left_blank(self, spec):
        """These four ARE the modelling task. Filling `Human Factors Cause`
        would invent 3,418 labels around 152 real ones, all from one era."""
        for col in (" Failed PSM Framework Element", "Risk Management Cause",
                    "Human Factors  Cause"):
            assert spec["fields"]["causes"][col]["gap_policy"] == "leave_blank", col

    def test_honest_blanks_are_not_counted_as_fabrication(self, spec, seen):
        """Counting them as fabricated would misreport the dataset as more
        invented than it is, and would make choosing honesty look worse."""
        s = tally(spec, seen)
        assert s["honest_blanks"] > 0
        assert s["real_cells"] + s["fabricated_cells"] + s["unfilled_cells"] \
            == s["total_cells"]
        assert s["honest_blanks"] <= s["unfilled_cells"]


@pytest.fixture(scope="module")
def exported():
    from psm.ledger import E19, real_only
    return E19 / "real_only", real_only(E19 / "real_only")


class TestRealOnlyExport:
    """The escape hatch for anyone who wants to train rather than demo.

    Without it, the only artifact is one where 33.7% of the incidents table is
    fabricated and "filter on provenance first" is a footnote nobody reads.
    """


    @staticmethod
    def _rows(path):
        import csv as _csv
        _csv.field_size_limit(10 ** 9)
        with path.open(encoding="utf-8", newline="") as fh:
            return list(_csv.DictReader(fh))

    def test_no_syn_cell_survives(self, exported):
        from psm.ledger import E19
        out, _ = exported
        data = self._rows(out / "incidents.csv")
        prov = self._rows(E19 / "enriched" / "provenance.csv")
        for d, p in zip(data, prov):
            for c in d:
                if p.get(c) == "syn":
                    assert not (d[c] or "").strip(), f"{c!r}: syn value survived the export"

    def test_every_real_cell_survives(self, exported):
        """Blanking must be surgical. An export that also dropped `src` values
        would be safe and useless."""
        from psm.ledger import E19
        out, _ = exported
        data = self._rows(out / "incidents.csv")
        base = self._rows(E19 / "enriched" / "incidents.csv")
        prov = self._rows(E19 / "enriched" / "provenance.csv")
        for d, b, p in zip(data, base, prov):
            for c in d:
                if p.get(c) in ("src", "xw"):
                    assert d[c] == b[c], f"{c!r}: real value lost in the export"

    def test_rows_are_blanked_not_dropped(self, exported):
        """Dropping rows would break the joins and hide the absence. A blank is
        visible; a missing row is not."""
        from psm.ledger import E19
        out, _ = exported
        assert len(self._rows(out / "incidents.csv")) == \
               len(self._rows(E19 / "enriched" / "incidents.csv"))

    def test_the_split_is_by_regime_not_by_round_numbers(self):
        """A random split leaks the reporting era; so does a split on decades.
        The boundaries are where BSEE's vocabulary actually changed."""
        from psm.ledger import ERA_REGIMES, regime_for
        assert regime_for(2006) == "free_prose"
        assert regime_for(2007) == "human_error"
        assert regime_for(2009) == "human_error"
        assert regime_for(2010) == "ad_hoc"
        assert regime_for(2018) == "ad_hoc"
        assert regime_for(2019) == "modern_six"   # the jump, not 2020
        assert regime_for(None) is None
        assert len(ERA_REGIMES) == 4

    def test_every_regime_has_incidents(self, exported):
        """A split with an empty stratum is not a split."""
        _, res = exported
        for name, n in res["split"].items():
            assert n > 0, f"regime {name} is empty"

    def test_the_split_records_why_it_exists(self, exported):
        """A stratification nobody can justify gets ignored and replaced with a
        random one."""
        import json
        out, _ = exported
        spec = json.loads((out / "splits.json").read_text(encoding="utf-8"))
        assert "why" in spec and spec["why"].strip()
        for name, meta in spec["regimes"].items():
            assert meta["what"].strip(), f"{name} has no description"


def _tvd(a: dict, b: dict) -> float:
    """Total variation distance between two value distributions. 0 = identical,
    1 = disjoint."""
    na, nb = sum(a.values()), sum(b.values())
    return 0.5 * sum(abs(a.get(k, 0) / na - b.get(k, 0) / nb) for k in set(a) | set(b))


class TestSyntheticFidelity:
    """Where `syn` and real values share a column, they must not be trivially
    separable -- otherwise the fill carries no information and any model gets a
    free "is this row synthetic" feature.

    This check found and killed four fills. `Incident Classification` was 100%
    the constant "Incident" against a real 31.5/48.1/20.5 spread; `Health &
    Safety - Risk Score` was a 9/5/2 encoding against a real 1-25 product, with
    almost disjoint value sets.
    """

    MAX_TVD = 0.60

    @staticmethod
    def _cols():
        import collections
        import csv as _csv
        from psm.ledger import E19
        _csv.field_size_limit(10 ** 9)
        with (E19 / "enriched" / "incidents.csv").open(encoding="utf-8", newline="") as fh:
            data = list(_csv.DictReader(fh))
        with (E19 / "enriched" / "provenance.csv").open(encoding="utf-8", newline="") as fh:
            prov = list(_csv.DictReader(fh))
        out = {}
        for c in data[0]:
            real = collections.Counter(d[c] for d, p in zip(data, prov)
                                       if p[c] in ("src", "xw") and (d[c] or "").strip())
            syn = collections.Counter(d[c] for d, p in zip(data, prov)
                                      if p[c] == "syn" and (d[c] or "").strip())
            if real and syn:
                out[c] = (real, syn)
        return out

    def test_shared_columns_are_not_trivially_separable(self, spec):
        """Identity columns are exempt and must be: a hash token is SUPPOSED to
        announce itself. Everything else has to overlap the real distribution or
        it should not be filled at all."""
        bad = []
        for c, (real, syn) in self._cols().items():
            if "Name" in c or "Position" in c:
                continue
            d = _tvd(real, syn)
            if d > self.MAX_TVD:
                bad.append(f"{c!r} TVD={d:.3f} (syn={dict(syn)})")
        assert not bad, "synthetic fill is separable from real values: " + "; ".join(bad)

    def test_shared_columns_share_a_value_scale(self, spec):
        """TVD alone would pass a fill that used the right values in the wrong
        proportions AND fail one that used a different scale -- but only this
        catches the scale error, which is the worse defect. `syn_hs_risk_score`
        emitted {2,5,9} where the real column emits {4,5,6,8,10,12,15,20,25}."""
        for c, (real, syn) in self._cols().items():
            if "Name" in c or "Position" in c:
                continue
            shared = set(real) & set(syn)
            assert len(shared) >= max(1, len(set(syn)) // 2), (
                f"{c!r}: syn values {sorted(set(syn))} barely intersect "
                f"real values {sorted(set(real))} -- different scales")

    def test_identity_columns_are_deliberately_separable(self):
        """The exemption above, made explicit rather than implied. If these ever
        became indistinguishable from real names, that would be the defect."""
        cols = self._cols()
        idc = [c for c in cols if "Name" in c or "Position" in c]
        assert idc, "no identity column carries synthetic fill"
        for c in idc:
            real, syn = cols[c]
            assert _tvd(real, syn) > 0.9, f"{c!r}: synthetic identities blend in"
