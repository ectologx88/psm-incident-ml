"""psm.provenance is the single source of truth for provenance tokens.

Before this module existed the closed set was hardcoded in three places
(test_conventions, test_fill_outputs, export_e19) which could drift apart
silently -- src/key/pseud are all "valid" set members, so no closed-set
test catches a site that never learned about a new token.
"""
from psm import provenance as pv


def test_token_set_is_exactly_the_documented_closed_set():
    assert pv.TOKENS == frozenset(
        {"", "src", "xw", "llm", "gold", "syn", "key", "pseud"}
    )


def test_fill_colors_and_unshaded_are_disjoint_and_inside_the_closed_set():
    assert set(pv.FILL_COLORS) <= pv.TOKENS
    assert pv.UNSHADED == frozenset({"", "src"})
    assert not (set(pv.FILL_COLORS) & pv.UNSHADED)


def test_provenance_row_classifies_by_column_not_by_value():
    row = {
        "Incident Number": "GC-478-20240502-1620",       # constructed -> key
        "Investigation leader - Name": "INV-a1b2c3",      # pseudonym -> pseud
        "What happened?  ": "a real narrative",           # verbatim -> src
        "Work Group": "",                                 # empty -> ""
    }
    cols = list(row)
    p = pv.provenance_row(row, cols)
    assert p["Incident Number"] == "key"
    assert p["Investigation leader - Name"] == "pseud"
    assert p["What happened?  "] == "src"
    assert p["Work Group"] == ""


def test_provenance_row_key_wins_even_for_values_with_no_hash_marker():
    # THE defect Phase 0 exists to fix: composite IDs like AREA-BLOCK-DATE-TIME
    # carry no INV-/SUP-/UNKEYED- substring but are still constructed.
    p = pv.provenance_row({"Incident Number": "EI-259-20230101-0900"},
                          ["Incident Number"])
    assert p["Incident Number"] == "key"


def test_export_and_convention_tests_import_from_here():
    # the three call sites must not re-hardcode the set. tests/ is not a
    # package (no __init__.py), so load the test modules by file path.
    import importlib.util
    from pathlib import Path

    import psm.export_e19 as ex
    assert ex.PROVENANCE_FILLS is pv.FILL_COLORS

    def load(name):
        path = Path(__file__).parent / f"{name}.py"
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    assert load("test_conventions").PROVENANCE_TOKENS == pv.TOKENS
    assert load("test_fill_outputs").TOKENS == pv.TOKENS
