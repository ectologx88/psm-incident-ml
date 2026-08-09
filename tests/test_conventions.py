"""Column-provenance convention checks for src/psm/synth.py's output.

Scope note: this only covers synth.py's own syn_-prefixed output. No module
yet assembles the full src_/xw_/llm_/gold_/syn_ table — data/processed/
incidents.csv and src/psm/crosswalk.py do not exist yet (see
docs/superpowers/plans/2026-08-09-synth-fields-implementation.md, Scope
Boundary). Extend this file to check the assembled table's columns once that
module exists.
"""
from __future__ import annotations

from psm.synth import load_rules, synthesize_row

VALID_PREFIXES = ("src_", "xw_", "llm_", "gold_", "syn_")


def test_every_synth_output_column_has_a_valid_prefix(make_row):
    rules = load_rules()
    out = synthesize_row(make_row(), rules)
    data_keys = set(out) - {"anomalies"}
    for key in data_keys:
        assert key.startswith(VALID_PREFIXES), f"{key!r} carries no provenance prefix"


def test_synth_never_emits_xw_columns(make_row):
    rules = load_rules()
    out = synthesize_row(make_row(), rules)
    assert not any(k.startswith("xw_") for k in out), (
        "synth.py must never emit xw_ — see the xw_/syn_ boundary rule in CLAUDE.md"
    )
