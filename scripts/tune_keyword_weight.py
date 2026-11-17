"""Measure hybrid search against keyword-only and semantic-only search, for a range of keyword weights.

    python scripts/tune_keyword_weight.py --index COPY_OF_AN_INDEX_WITH_ONLY_THE_640_ENGLISH_PATENTS

Uses the four known-answer tests of scripts/testing/backtest.py (200 queries each, seed 42) unchanged:
  A  claim 1 finds its own patent (its own claims are not candidates)
  B  abstract finds its own claims (the abstract is taken out of the keyword table for the query)
  C  title finds the patent
  D  dependent claim finds the patent that holds its parent
The weight is KEYWORD_WEIGHT in src/search.py: the vote of the keyword list in the fusion, against 1 for
the semantic list. Point --index at a copy: Test B edits the keyword table inside a transaction it rolls back.
"""
import argparse
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts", "testing"))
import backtest  # noqa: E402
from src import embed, search as engine  # noqa: E402

WEIGHTS = (1.0, 0.5, 0.2, 0.1, 0.05, 0.02, 0.01, 0.005, 0.002)
TESTS = ("A", "B", "C", "D")


def run(index, mode, samples):
    docs_a, docs_b, docs_c, items = samples
    return {"A": backtest.test_a(index, docs_a, mode), "B": backtest.test_b(index, docs_b, mode, True),
            "C": backtest.test_c(index, docs_c, mode), "D": backtest.test_d(index, items)[f"patent_{mode}"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", required=True)
    args = parser.parse_args()
    index = engine.Index(args.index)
    assert not index.languages, "needs an index with only the English patents"
    encode, cache = embed.encode, {}
    embed.encode = lambda texts, prefix: cache.setdefault((tuple(texts), prefix), encode(texts, prefix))  # same queries every round

    claims = backtest.first_claims(index)
    pool = backtest.dependent_claims(index)
    samples = (
        backtest.sample([doc for doc, claim in claims.items() if len(claim[2]) >= 40]),
        backtest.sample([row[0] for row in index.con.execute(
            "SELECT doc_number FROM patents p WHERE abstract IS NOT NULL AND EXISTS (SELECT 1 FROM passages s "
            "WHERE s.patent_id = p.id AND s.kind = 'claim' AND length(s.text) >= 40)")]),
        backtest.sample(list(index.patent_ids)),
        random.Random(backtest.SEED).sample(sorted(pool), min(backtest.SAMPLE, len(pool))))

    single = {mode: run(index, mode, samples) for mode in ("keyword", "semantic")}
    mrr = {mode: {test: backtest.metrics(ranks)["mrr"] for test, ranks in single[mode].items()} for mode in single}
    better = {test: max(single, key=lambda mode: mrr[mode][test]) for test in TESTS}
    print(f"Mean reciprocal rank, {backtest.SAMPLE} queries per test, {len(index.patent_ids)} patents. "
          f"Weight in src/search.py now: {engine.KEYWORD_WEIGHT}.\n")
    print("| Search | A: claim 1 to patent | B: abstract to claims | C: title to patent | D: dependent claim to patent | Worst gap to the better single mode |")
    print("| --- | --- | --- | --- | --- | --- |")
    for mode in single:
        print(f"| {mode} only | " + " | ".join(f"{mrr[mode][test]:.3f}" for test in TESTS) + " | |")
    for weight in WEIGHTS:
        engine.KEYWORD_WEIGHT = weight
        hybrid = run(index, "hybrid", samples)
        gaps = {test: backtest.gap(hybrid[test], single[better[test]][test]) for test in TESTS}
        worst = min(TESTS, key=lambda test: gaps[test]["mrr"])
        low, high = gaps[worst]["mrr_ci"]
        print(f"| hybrid, keyword weight {weight} | "
              + " | ".join(f"{backtest.metrics(hybrid[test])['mrr']:.3f} ({gaps[test]['mrr']:+.3f})" for test in TESTS)
              + f" | {gaps[worst]['mrr']:+.3f} on {worst} ({low:+.3f} to {high:+.3f}) |", flush=True)
    print("\nIn brackets: hybrid minus the better single mode on that test (" +
          ", ".join(f"{test}: {better[test]}" for test in TESTS) + "). The last column gives its 95% interval.")


if __name__ == "__main__":
    main()
