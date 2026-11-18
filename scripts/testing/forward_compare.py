"""Paired comparison of two forward-test runs, query by query, with a bootstrap interval.

    python scripts/testing/forward_compare.py BASE_TAG OTHER_TAG [OTHER_TAG ...] [--languages de es zh ja] [--category general]

Reads results/forward_results_<tag>.json and results/forward_judgments_builder.json: every item of every run,
the tester's 365 included, scored by one second set of blind judges, so runs can be compared with each other. The
tags `mixed` and `english` are the tester's own runs at commit de3fe99 (hybrid search with equal votes, the default
then). The `after_*` tags were run after the fixes. (results/forward_report_before_*.json are the tester's two runs
re-scored with these judgments by `forward_test.py report`.) Prints, for each other tag, the mean relevance of the top 5 (0 to 2), the number of queries with a result
scored 2, and the difference to the base tag with a 95% interval from 4,000 resamples of the queries.
"""
import argparse
import json
import os

import numpy as np

RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def per_query(tag, judged, languages, category):
    out = {}
    for run in json.load(open(os.path.join(RESULTS, f"forward_results_{tag}.json"), encoding="utf-8")):
        if run["query_language"] in languages and category in (None, run["category"]):
            scores = [judged[row["item"]] for row in run["results"][:5]]
            out[(run["id"], run["query_language"])] = (float(np.mean(scores + [0] * (5 - len(scores)))), max(scores, default=0) == 2)
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("base")
    parser.add_argument("others", nargs="+")
    parser.add_argument("--languages", nargs="+", default=["de", "es", "zh", "ja"])
    parser.add_argument("--category")
    args = parser.parse_args()
    judged = json.load(open(os.path.join(RESULTS, "forward_judgments_builder.json")))
    base = per_query(args.base, judged, args.languages, args.category)
    rng = np.random.default_rng(0)
    print(f"{len(base)} queries ({', '.join(args.languages)}{', ' + args.category if args.category else ''})")
    print(f"{args.base}: mean {np.mean([v[0] for v in base.values()]):.3f}, a result scored 2 for {sum(v[1] for v in base.values())} queries")
    for tag in args.others:
        other = per_query(tag, judged, args.languages, args.category)
        diff = np.array([other[key][0] - base[key][0] for key in base])
        means = diff[rng.integers(0, len(diff), (4000, len(diff)))].mean(axis=1)
        print(f"{tag}: mean {np.mean([v[0] for v in other.values()]):.3f}, a result scored 2 for {sum(v[1] for v in other.values())} queries, "
              f"difference {diff.mean():+.3f} (95% interval {np.percentile(means, 2.5):+.3f} to {np.percentile(means, 97.5):+.3f}), "
              f"better on {int((diff > 0).sum())} queries, worse on {int((diff < 0).sum())}")
