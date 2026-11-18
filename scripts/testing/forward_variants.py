"""M2: three ways of handling a query that is not in English, scored with forward_test.py.

    python scripts/testing/forward_variants.py VARIANT --index COPY_OF_AN_INDEX --tag NAME

VARIANT:
  translate  the query is translated to English, then searched (what search() does by default)
  beam4      the same, with beam width 4 for the query translation instead of greedy decoding
  direct     the original query is embedded as it is, with the multilingual model, and never translated
  both       the rankings of `translate` and `direct` fused by reciprocal rank
Writes scripts/testing/results/forward_results_<tag>.json and the judging sheet, exactly as `forward_test.py run`.
On an index that holds English patents only, `direct` is search(cross_lingual="shared"): one query vector, no
translation. On a mixed index that option is known to bury the foreign patents, so compare on English only.
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts", "testing"))
import forward_test  # noqa: E402
from src import search as engine  # noqa: E402

search, EVERYTHING = engine.search, 100000


def direct(text, **options):
    return search(text, cross_lingual="shared", **options)


def both(text, top_k=10, **options):
    translated = search(text, top_k=EVERYTHING, **options)
    options.pop("info", None)
    original = search(text, top_k=EVERYTHING, cross_lingual="shared", **options)
    fused, by_doc = {}, {}
    for ranking in (translated, original):
        for rank, result in enumerate(ranking, 1):
            fused[result["doc_number"]] = fused.get(result["doc_number"], 0.0) + 1.0 / (engine.RRF_K + rank)
            by_doc.setdefault(result["doc_number"], result)  # evidence from the translated run when both have the patent
    return [dict(by_doc[doc], score=fused[doc]) for doc in sorted(fused, key=fused.get, reverse=True)[:top_k]]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("variant", choices=("translate", "beam4", "direct", "both"))
    parser.add_argument("--index", required=True)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    assert not engine.Index(args.index).languages, "needs an index with English patents only (see the note above)"
    if args.variant == "beam4":
        engine.QUERY_BEAMS = 4
    elif args.variant != "translate":
        engine.search = {"direct": direct, "both": both}[args.variant]  # forward_test.run looks the function up when it runs
    forward_test.run(args)
