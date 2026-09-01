"""The action template registry is the ONLY source of Recommendation
Description text in company registers, and the controls-hierarchy KPI reads
tags by exact match-back -- so the registry must be closed, clean of
regulator voice, and collision-free."""
import re

from psm import templates as tp

BANNED = re.compile(r"\b(MMS|OSM|BSEE|District|Regional Office)\b", re.I)


def test_registry_is_large_and_balanced():
    ts = tp.load_templates()
    assert len(ts) >= 40
    by = tp.templates_by_tag()
    assert set(by) == set(tp.TAGS)
    for tag in tp.TAGS:
        assert len(by[tag]) >= 8, f"{tag}: need >=8 templates"


def test_no_regulator_voice_anywhere():
    for t in tp.load_templates():
        assert not BANNED.search(t["text"]), t["id"]


def test_texts_and_ids_are_unique_and_match_back_round_trips():
    ts = tp.load_templates()
    assert len({t["id"] for t in ts}) == len(ts)
    assert len({t["text"] for t in ts}) == len(ts)
    for t in ts:
        assert tp.classify_action(t["text"]) == t["tag"]


def test_classify_action_raises_on_unknown_text():
    import pytest
    with pytest.raises(KeyError):
        tp.classify_action("this text is not in the registry")
