"""Does BSEE's cause text actually partition into the crosswalk's six categories?

`schema/crosswalk.yaml` asserts six cause categories and maps each to a PSM
element. Nothing has ever checked whether those six describe real structure in
the text or are just the labels BSEE happened to print. This is that check, and
it needs **no hand labels** -- which makes it the cheapest thing in Phase 3 and
the one most likely to change what the others are worth doing.

THE CIRCULARITY TRAP, AND HOW IT IS AVOIDED
-------------------------------------------
A cause statement reads "Human Performance Error: Not following proper
procedures- Danos crew members did not follow ...". Cluster that text and you
will recover the six categories perfectly, because the category name is *in the
string*. The result would be a tautology dressed as a finding.

So the category head and its subcategory are **stripped** before vectorising,
and only the free-text description is clustered. `--keep-heads` runs the
circular version deliberately, as a control: if the stripped run scores far
lower than the control, that gap is the honest measure of how much the six
categories are doing beyond naming themselves.

THE ERA CONFOUND
----------------
Labelled statements are overwhelmingly post-2019 (docs/findings.md: four
reporting regimes). Clusters that track the *regime* rather than the category
would look like structure and be an artifact. Cluster-vs-era agreement is
reported alongside cluster-vs-category so the two can be compared.

Run::

    uv run python -m psm.cluster
    uv run python -m psm.cluster --keep-heads     # the circular control
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
E19 = REPO / "data" / "processed" / "e19"
CROSSWALK = REPO / "schema" / "crosswalk.yaml"
DEFAULT_OUT = REPO / "docs" / "cause_clustering.md"

SEED = 20260829          # frozen; this is a reproducible dataset
K_RANGE = range(2, 13)


def load_statements() -> list[dict]:
    """Every cause statement, with its category, era regime and stripped text."""
    from psm.causes import candidate_category, normalise_category, parse_statement
    from psm.ledger import regime_for

    csv.field_size_limit(10 ** 9)
    spec = yaml.safe_load(CROSSWALK.read_text(encoding="utf-8"))
    aliases = {k.lower(): v for k, v in spec["aliases"].items()}

    with (E19 / "enriched" / "causes.csv").open(encoding="utf-8", newline="") as fh:
        causes = list(csv.DictReader(fh))
    with (E19 / "incidents.csv").open(encoding="utf-8", newline="") as fh:
        years = {r["Incident Number"]: (r.get("Date of Incident") or "")[:4]
                 for r in csv.DictReader(fh)}

    out = []
    for r in causes:
        raw = r["Cause Description"] or ""
        st = parse_statement(raw)
        head = getattr(st, "category", None)
        cat = aliases.get(normalise_category(head)) if head else None

        # Strip the head AND the subcategory: both name the category, and
        # leaving either in makes the clustering circular.
        body = getattr(st, "description", None) or raw
        if head:
            body = re.sub(re.escape(head), " ", body, flags=re.IGNORECASE)
        y = years.get(r["Incident Number"], "")
        out.append({
            "id": f'{r["Incident Number"]}#{r["Cause number"]}',
            "raw": " ".join(raw.split()),
            "text": " ".join(body.split()),
            "category": cat,
            "year": int(y) if y.isdigit() else None,
            "regime": regime_for(int(y)) if y.isdigit() else None,
        })
    return out


def cluster(texts: list[str], k: int):
    from sklearn.cluster import KMeans
    from sklearn.feature_extraction.text import TfidfVectorizer

    # TF-IDF rather than a downloaded sentence model: the reproducibility
    # contract in CLAUDE.md says a stranger must be able to rebuild this from a
    # fresh clone, and a pinned vectoriser over committed text does that where a
    # model checkpoint does not.
    vec = TfidfVectorizer(min_df=3, max_df=0.5, stop_words="english",
                          ngram_range=(1, 2), sublinear_tf=True)
    X = vec.fit_transform(texts)
    km = KMeans(n_clusters=k, random_state=SEED, n_init=10)
    return km.fit_predict(X), X, vec


def top_terms(vec, X, labels, k: int, n: int = 6) -> dict[int, list[str]]:
    import numpy as np
    names = np.array(vec.get_feature_names_out())
    out = {}
    for c in range(k):
        rows = X[labels == c]
        if rows.shape[0] == 0:
            out[c] = []
            continue
        mean = np.asarray(rows.mean(axis=0)).ravel()
        out[c] = list(names[mean.argsort()[::-1][:n]])
    return out


def agreement(labels, truth) -> dict:
    """ARI and purity against a reference partition, over the labelled subset."""
    from sklearn.metrics import adjusted_rand_score
    pairs = [(l, t) for l, t in zip(labels, truth) if t]
    if len(pairs) < 20:
        return {"n": len(pairs), "ari": None, "purity": None}
    L = [p[0] for p in pairs]
    T = [p[1] for p in pairs]
    by_cluster: dict[int, Counter] = {}
    for l, t in pairs:
        by_cluster.setdefault(l, Counter())[t] += 1
    purity = sum(c.most_common(1)[0][1] for c in by_cluster.values()) / len(pairs)
    return {"n": len(pairs), "ari": adjusted_rand_score(T, L), "purity": purity}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--keep-heads", action="store_true",
                    help="the circular control: cluster WITH the category name in the text")
    args = ap.parse_args(argv)

    rows = load_statements()
    field = "raw" if args.keep_heads else "text"
    usable = [r for r in rows if len(r[field].split()) >= 5]
    texts = [r[field] for r in usable]
    cats = [r["category"] for r in usable]
    regimes = [r["regime"] for r in usable]
    n_lab = sum(1 for c in cats if c)

    print(f"statements: {len(rows)}, usable (>=5 words): {len(usable)}, "
          f"with a mapped category: {n_lab}")
    print(f"mode: {'CIRCULAR CONTROL (heads kept)' if args.keep_heads else 'heads stripped'}\n")
    print(f"{'k':>3}{'ARI vs 6 cats':>15}{'purity':>9}{'ARI vs era':>12}{'silhouette':>12}")

    from sklearn.metrics import silhouette_score
    results = []
    for k in K_RANGE:
        labels, X, vec = cluster(texts, k)
        a = agreement(labels, cats)
        e = agreement(labels, regimes)
        sil = silhouette_score(X, labels, sample_size=min(2000, X.shape[0]),
                               random_state=SEED)
        results.append({"k": k, "cat": a, "era": e, "sil": sil,
                        "terms": top_terms(vec, X, labels, k)})
        print(f"{k:>3}{a['ari']:>15.3f}{a['purity']:>9.3f}"
              f"{e['ari']:>12.3f}{sil:>12.3f}")

    best = max(results, key=lambda r: r["cat"]["ari"])
    print(f"\nbest agreement with the six categories: k={best['k']}, "
          f"ARI={best['cat']['ari']:.3f}, purity={best['cat']['purity']:.3f} "
          f"(n={best['cat']['n']})")
    six = next(r for r in results if r["k"] == 6)
    print(f"at k=6 specifically: ARI={six['cat']['ari']:.3f}, "
          f"purity={six['cat']['purity']:.3f}, era-ARI={six['era']['ari']:.3f}")
    print("\nk=6 cluster terms:")
    for c, terms in sorted(six["terms"].items()):
        print(f"   c{c}: {', '.join(terms)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
