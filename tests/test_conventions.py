"""Provenance-convention checks.

CLAUDE.md states that every column in every processed table carries a
`src_`/`xw_`/`llm_`/`gold_`/`syn_` prefix, and names this file as the enforcer.
**The shipped tables deliberately deviate, and this file now tests what actually
ships.**

The deviation, and why it is correct: the E19 tables must carry the source
workbook's field labels *byte-exact* -- `Incident Classificatioin` (sic),
` Failed PSM Framework Element` (leading space), `What happened?  ` (trailing
spaces). Prefixing them would break the exactness guarantee that is the entire
point of the projection layer. So provenance moved to a **parallel file**: for
every table, a `provenance.csv` of identical shape whose every cell holds `src`,
`xw` or empty.

That is a stronger guarantee than a prefix, not a weaker one -- a prefix labels a
whole column, while the parallel file labels every cell, and the same E19 column
can be read verbatim on one row and inferred on another.

Prefixes still apply, and are still enforced here, everywhere the exactness
constraint does not: `synth.py`'s output, the sidecar, and the interim records.

An earlier version of this file tested only `synth.py` and its docstring said
`crosswalk.py` "does not exist yet". It does, and 186 of 187 shipped columns
carry no prefix -- a defensible design that nothing described and nothing tested.
"""

from __future__ import annotations

import csv

import pytest

from psm.project import DEFAULT_OUT
from psm.synth import load_rules, synthesize_row

VALID_PREFIXES = ("src_", "xw_", "llm_", "gold_", "syn_")
PROVENANCE_TOKENS = {"", "src", "xw", "llm", "gold", "syn"}   # `syn` live since 2026-08-29

E19_TABLES = ["incidents", "causes", "recommendations", "closeout"]


class TestSynthObeysThePrefixRule:
    def test_every_synth_output_column_has_a_valid_prefix(self, make_row):
        out = synthesize_row(make_row(), load_rules())
        for key in set(out) - {"anomalies"}:
            assert key.startswith(VALID_PREFIXES), f"{key!r} carries no provenance prefix"

    def test_synth_never_emits_xw_columns(self, make_row):
        out = synthesize_row(make_row(), load_rules())
        assert not any(k.startswith("xw_") for k in out), (
            "synth.py must never emit xw_ -- see the xw_/syn_ boundary rule in CLAUDE.md")


@pytest.mark.skipif(not (DEFAULT_OUT / "incidents.csv").exists(),
                    reason="run `python -m psm.project` first")
class TestSidecarObeysThePrefixRule:
    """The sidecar is ours, not the template's, so the exactness constraint does
    not apply and the prefix rule does."""

    def test_every_sidecar_column_is_prefixed(self):
        with (DEFAULT_OUT / "bsee_unmapped.csv").open(encoding="utf-8", newline="") as fh:
            header = next(csv.reader(fh))
        for col in header:
            if col == "Incident Number":      # the join key, an E19 label by design
                continue
            assert col.startswith("bsee_"), f"sidecar column {col!r} is unprefixed"


@pytest.mark.skipif(not (DEFAULT_OUT / "enriched" / "provenance.csv").exists(),
                    reason="run `python -m psm.crosswalk` first")
class TestE19TablesCarryParallelProvenance:
    """The deviation, enforced. If the E19 columns cannot carry a prefix, the
    provenance file is the only thing standing between a read value and an
    inferred one -- so its integrity matters more, not less."""

    @staticmethod
    def _read(path):
        import csv as _csv
        _csv.field_size_limit(10 ** 9)
        with path.open(encoding="utf-8", newline="") as fh:
            return list(_csv.DictReader(fh))

    @pytest.mark.parametrize("table", ["incidents", "causes"])
    def test_a_provenance_file_exists_and_matches_shape(self, table):
        name = "provenance.csv" if table == "incidents" else "causes_provenance.csv"
        data = self._read(DEFAULT_OUT / "enriched" / f"{table}.csv")
        prov = self._read(DEFAULT_OUT / "enriched" / name)
        assert len(data) == len(prov), f"{table}: provenance row count differs"
        assert list(data[0]) == list(prov[0]), f"{table}: provenance columns differ"

    @pytest.mark.parametrize("name", ["provenance.csv", "causes_provenance.csv"])
    def test_provenance_tokens_are_from_the_closed_set(self, name):
        for row in self._read(DEFAULT_OUT / "enriched" / name):
            bad = {v for v in row.values() if v not in PROVENANCE_TOKENS}
            assert not bad, f"{name}: unknown provenance tokens {bad}"

    def test_every_non_empty_cell_has_a_provenance(self):
        """A value with no provenance is exactly what the prefix rule prevents
        elsewhere. Here the parallel file has to do that job."""
        data = self._read(DEFAULT_OUT / "enriched" / "incidents.csv")
        prov = self._read(DEFAULT_OUT / "enriched" / "provenance.csv")
        missing = sum(1 for d, p in zip(data, prov) for c in d
                      if (d[c] or "").strip() and not p[c])
        assert missing == 0, f"{missing} non-empty cells carry no provenance"

    def test_no_provenance_without_a_value(self):
        data = self._read(DEFAULT_OUT / "enriched" / "incidents.csv")
        prov = self._read(DEFAULT_OUT / "enriched" / "provenance.csv")
        orphan = sum(1 for d, p in zip(data, prov) for c in d
                     if p[c] and not (d[c] or "").strip())
        assert orphan == 0, f"{orphan} provenance marks with no value"

    def test_syn_never_overwrote_a_real_value(self):
        """Precedence is src > xw > syn, and it is the whole guarantee.

        A `syn` cell sitting where a `src` or `xw` value belonged would be a
        fabricated value wearing a real one's place -- the single worst outcome
        available to this project, and invisible without this check.
        """
        base = self._read(DEFAULT_OUT / "incidents.csv")
        data = self._read(DEFAULT_OUT / "enriched" / "incidents.csv")
        prov = self._read(DEFAULT_OUT / "enriched" / "provenance.csv")
        for b, d, p in zip(base, data, prov):
            for c in d:
                if p[c] == "syn":
                    assert not (b.get(c) or "").strip(), (
                        f"{c!r}: syn wrote over a verbatim value")

    def test_synthetic_identities_are_never_mistakable_for_people(self):
        """Hash tokens, not plausible names. A realistic fake name in a public
        dataset is worse than an obvious placeholder, because someone will
        eventually quote it as a real investigator."""
        data = self._read(DEFAULT_OUT / "enriched" / "incidents.csv")
        prov = self._read(DEFAULT_OUT / "enriched" / "provenance.csv")
        cols = [c for c in data[0] if "Name" in c or "Position" in c]
        for d, p in zip(data, prov):
            for c in cols:
                if p[c] == "syn" and (d[c] or "").strip():
                    assert d[c].startswith(("SYN-", "Synthetic Role")), \
                        f"{c!r}: synthetic identity {d[c]!r} does not announce itself"

    def test_xw_never_overwrote_a_verbatim_value(self):
        """The stated invariant of the enrichment step: verbatim always wins."""
        base = self._read(DEFAULT_OUT / "incidents.csv")
        data = self._read(DEFAULT_OUT / "enriched" / "incidents.csv")
        prov = self._read(DEFAULT_OUT / "enriched" / "provenance.csv")
        for b, d, p in zip(base, data, prov):
            for c in d:
                if p[c] == "src":
                    assert d[c] == b[c], f"{c!r}: enriched value differs from verbatim"
                if p[c] == "xw":
                    assert not (b[c] or "").strip(), f"{c!r}: xw wrote over a verbatim value"


class TestReadmeMatchesTheData:
    """The README stated risk scores were `syn_` while provenance.csv said `xw`,
    and omitted the panel severity bias entirely. Both were true for weeks.

    These are documentation tests, and named so. But they are tied to computed
    values rather than asserting that prose exists, so they fail when the data
    moves and the README does not."""

    @staticmethod
    def _readme() -> str:
        return (DEFAULT_OUT.parents[2] / "README.md").read_text(encoding="utf-8")

    def test_panel_fatality_share_matches_the_spine(self):
        """The headline bias figure must be the one the data actually shows."""
        import csv as _csv
        spine = DEFAULT_OUT.parents[0] / "investigations_index.csv"
        if not spine.exists():
            pytest.skip("spine not built")
        with spine.open(encoding="utf-8", newline="") as fh:
            rows = [r for r in _csv.DictReader(fh) if "Fatality" in (r["src_accident_type"] or "")]
        share = 100 * sum(1 for r in rows if r["src_panel_district"] == "PANEL") / len(rows)
        assert f"{share:.1f}%" in self._readme(), (
            f"README does not state the measured panel share of fatalities ({share:.1f}%)")

    def test_readme_does_not_call_risk_scores_synthetic(self):
        """They are computed from real BSEE fields through a versioned rule file."""
        text = self._readme().lower()
        i = text.find("risk-matrix fields")
        assert i > 0, "README no longer describes the risk-matrix fields"
        assert "not synthetic" in text[i:i + 400]

    def test_readme_documents_the_provenance_file(self):
        assert "provenance.csv" in self._readme()
