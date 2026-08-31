"""Tests for src/psm/fill.py — deterministic fill of the E19 filled/ layer."""
from __future__ import annotations

import csv  # noqa: F401
from pathlib import Path  # noqa: F401

from psm.fill import load_rules, weighted_pick


def test_weighted_pick_is_deterministic_and_in_vocab():
    weights = {"A": 1, "B": 3, "C": 6}
    first = weighted_pick("INC-1|1", "salt", weights)
    second = weighted_pick("INC-1|1", "salt", weights)
    assert first == second
    assert first in weights


def test_weighted_pick_varies_with_key_and_respects_weights():
    weights = {"A": 1, "B": 3, "C": 6}
    picks = [weighted_pick(f"INC-{i}|1", "salt", weights) for i in range(500)]
    counts = {v: picks.count(v) for v in weights}
    # C (weight 6/10) must dominate A (weight 1/10); loose bounds, no flake.
    assert counts["C"] > counts["A"]
    assert set(picks) == {"A", "B", "C"}


def test_weighted_pick_zero_weight_value_never_chosen():
    weights = {"A": 1, "B": 0}
    assert all(
        weighted_pick(f"k{i}", "s", weights) == "A" for i in range(50)
    )


def test_synth_rules_v2_keys_present():
    rules = load_rules()
    for key in (
        "work_group_weights", "work_group_salt",
        "cause_type_first_cause", "cause_type_weights", "cause_type_salt",
        "likelihood_weights", "er_likelihood_salt", "fin_likelihood_salt",
        "element_fallback_salt",
    ):
        assert key in rules, key
    assert rules["version"] == 2
