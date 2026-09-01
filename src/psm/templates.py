"""Action-template registry loader + exact match-back classifier."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
REGISTRY = REPO / "schema" / "action_templates.yaml"

TAGS = ("elimination", "engineering", "admin", "ppe")


@lru_cache(maxsize=None)
def load_templates() -> tuple[dict, ...]:
    data = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    ts = tuple(data["templates"])
    for t in ts:
        assert set(t) == {"id", "tag", "text"}, t
        assert t["tag"] in TAGS, t["id"]
    return ts


@lru_cache(maxsize=None)
def templates_by_tag() -> dict[str, tuple[dict, ...]]:
    out: dict[str, list[dict]] = {tag: [] for tag in TAGS}
    for t in load_templates():
        out[t["tag"]].append(t)
    return {k: tuple(v) for k, v in out.items()}


@lru_cache(maxsize=None)
def _text_to_tag() -> dict[str, str]:
    return {t["text"]: t["tag"] for t in load_templates()}


def classify_action(text: str) -> str:
    """Exact registry lookup. KeyError on unknown text is a FEATURE: company
    registers must contain no recommendation text outside the registry."""
    return _text_to_tag()[text]
