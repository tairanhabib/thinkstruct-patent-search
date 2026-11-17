"""Independent test pass, Stage 3: functional tests of search on a REAL index with the REAL models.

Not collected by the default `python -m pytest` (pytest.ini points at tests/). Run it on purpose:

    PATENT_TEST_INDEX=/path/to/index python -m pytest scripts/testing/test_functional_real.py -q

The index is opened read-mostly (searches may add rows to its translation cache), so point it at a copy.
A failing test is a finding for TEST_REPORT.md.
"""
import json
import os
import random
import re
import subprocess
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from benchmark import FILTERS, QUERIES  # noqa: E402
from src.search import Index, keyword_rank, search  # noqa: E402

INDEX_DIR = os.environ.get("PATENT_TEST_INDEX", os.path.join(ROOT, "index"))
EVERYTHING = 100000
FORWARD = [q["text"] for q in json.load(open(os.path.join(ROOT, "scripts/testing/forward_queries.json")))["queries"]]
FIFTY = QUERIES + FORWARD


@pytest.fixture(scope="module")
def index():
    return Index(INDEX_DIR)


@pytest.fixture(scope="module")
def patents(index):
    return [dict(row) for row in index.con.execute("SELECT * FROM patents")]


def docs(results):
    return [r["doc_number"] for r in results]


def cli(*args):
    env = dict(os.environ, PATENT_INDEX=INDEX_DIR)
    return subprocess.run([sys.executable, "cli.py", *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)


# --- every input type in the README ---------------------------------------------------------------

@pytest.mark.parametrize("args", [
    ["search", "wheel hub with integrated pressure sensor", "--top", "5"],
    ["similar", "--doc", "20240051333", "--top", "5"],
    ["similar", "--doc", "20240051333", "--claim", "1", "--top", "5"],
    ["search", "--title", "pneumatic tire", "--top", "5"],
    ["search", "--cpc", "B60B", "--top", "5"],
    ["search", "--keywords", "rubber", "--top", "5"],
    ["show", "--doc", "20240051339"],
    ["stats"],
])
def test_every_readme_input_type_runs_and_prints_results(args):
    done = cli(*args)
    assert done.returncode == 0, done.stderr[-500:]
    assert "Traceback" not in done.stderr
    if args[0] in ("search", "similar"):
        assert re.search(r"(?m)^ 1\. \S+ \| ", done.stdout), done.stdout[:300]
        assert len(re.findall(r"(?m)^ ?\d+\. \S+ \| ", done.stdout)) == 5


def test_search_by_document_number_never_returns_that_patent(index, patents):
    sample = random.Random(42).sample([p["doc_number"] for p in patents], 40)
    for doc in sample:
        for mode in ("hybrid", "semantic", "keyword"):
            for claim in (None, 1):
                assert doc not in docs(search(doc_number=doc, claim_number=claim, mode=mode, top_k=EVERYTHING,
                                              translate_results=False, index=index)), (doc, mode, claim)


# --- each filter alone: every returned row is checked -----------------------------------------------

def truth(patents, test):
    return {p["doc_number"] for p in patents if test(p)}


@pytest.mark.parametrize("prefix", ["B60B", "B60C", "B60D", "B60C11", "B60B27", "B60"])
@pytest.mark.parametrize("query", [None, "wheel hub with integrated pressure sensor"])
def test_classification_prefix_returns_exactly_the_matching_patents(index, patents, prefix, query):
    results = search(query, cpc_prefix=prefix, top_k=EVERYTHING, translate_results=False, index=index)
    assert all((r["classification"] or "").startswith(prefix) for r in results)
    assert set(docs(results)) == truth(patents, lambda p: (p["classification"] or "").startswith(prefix))


def words(patent):
    return re.findall(r"\w+", f"{patent['title_en'] or ''} {patent['abstract_en'] or ''}".lower())


@pytest.mark.parametrize("keyword", ["rubber", "sensor", "noise", "bearing", "hitch"])
def test_keyword_filter_every_result_has_the_keyword_in_title_or_abstract(index, patents, keyword):
    by_doc = {p["doc_number"]: p for p in patents}
    results = search(keywords=keyword, top_k=EVERYTHING, index=index)
    assert results
    for r in results:  # the filter stems words, so "sensors" may stand for "sensor": the word must at least start with it
        assert any(w.startswith(keyword[:-1] if keyword.endswith("e") else keyword) for w in words(by_doc[r["doc_number"]])), r["doc_number"]
    exact = truth(patents, lambda p: keyword in words(p))
    assert exact <= set(docs(results))  # nothing with the exact word is left out


def test_keyword_filter_ignores_case(index):
    reference = docs(search(keywords="rubber", top_k=EVERYTHING, index=index))
    for variant in ("RUBBER", "Rubber", "rUbBeR"):
        assert docs(search(keywords=variant, top_k=EVERYTHING, index=index)) == reference


def test_multi_word_keyword_filter_needs_every_word(index, patents):
    by_doc = {p["doc_number"]: p for p in patents}
    results = search(keywords="tire pressure", top_k=EVERYTHING, index=index)
    assert results
    for r in results:
        found = words(by_doc[r["doc_number"]])
        assert any(w.startswith("tire") for w in found) and any(w.startswith("pressur") for w in found)
    both = set(docs(results))
    assert both == set(docs(search(keywords="tire", top_k=EVERYTHING, index=index))) & set(
        docs(search(keywords="pressure", top_k=EVERYTHING, index=index)))
    assert both == set(docs(search(keywords="pressure tire", top_k=EVERYTHING, index=index)))  # order does not matter


def test_multi_word_keyword_is_not_a_phrase_match(index, patents):
    """Recorded behaviour: 'tire pressure' means both words anywhere, not the phrase. Quoting changes nothing."""
    plain = set(docs(search(keywords="tire pressure", top_k=EVERYTHING, index=index)))
    quoted = set(docs(search(keywords='"tire pressure"', top_k=EVERYTHING, index=index)))
    phrase = truth(patents, lambda p: "tire pressure" in " ".join(words(p)))
    assert quoted == plain
    assert phrase < plain  # strictly more patents come back than contain the phrase


def test_title_filter_returns_every_patent_that_shares_a_title(index, patents):
    by_title = {}
    for p in patents:
        if p["collection"] == "small" and p["title"]:
            by_title.setdefault(p["title"], set()).add(p["doc_number"])
    shared = {title: group for title, group in by_title.items() if len(group) > 1}
    assert len(shared) == 43  # the number the notes give for this dataset
    for title, group in shared.items():
        results = search(title=title, top_k=EVERYTHING, index=index)
        assert group <= set(docs(results)), title
        assert all(title.lower() in (r["title"] or "").lower() or title.lower() in (r["title_en"] or "").lower() for r in results)


def test_title_filter_is_contains_not_exact(index, patents):
    """Recorded behaviour. The task asks for 'search for a specific title'; the filter is 'title contains'."""
    exact = truth(patents, lambda p: (p["title"] or "").strip().lower() == "tire")
    returned = set(docs(search(title="TIRE", top_k=EVERYTHING, index=index)))
    assert exact <= returned and len(returned) > len(exact)


def test_date_range_is_inclusive_at_both_ends(index, patents):
    week = truth(patents, lambda p: p["filing_week"] == "2024-06-06")
    assert len(week) >= 10
    assert set(docs(search(date_from="2024-06-06", date_to="2024-06-06", top_k=EVERYTHING, index=index))) == week
    two = truth(patents, lambda p: p["filing_week"] in ("2024-06-06", "2024-06-13"))
    assert set(docs(search(date_from="2024-06-06", date_to="2024-06-13", top_k=EVERYTHING, index=index))) == two
    assert set(docs(search(date_from="2024-06-07", date_to="2024-06-12", top_k=EVERYTHING, index=index))) == set()
    everything = set(docs(search(date_from="2024-02-15", date_to="2025-05-01", top_k=EVERYTHING, index=index)))
    assert everything == {p["doc_number"] for p in patents}


def test_combined_filters_return_the_intersection(index):
    query = "tire tread that reduces road noise"
    parts = [dict(cpc_prefix="B60C"), dict(keywords="noise"), dict(date_from="2024-06-01", date_to="2024-12-31"),
             dict(title="tire")]
    sets = [set(docs(search(query, top_k=EVERYTHING, translate_results=False, index=index, **part))) for part in parts]
    merged = {key: value for part in parts for key, value in part.items()}
    combined = set(docs(search(query, top_k=EVERYTHING, translate_results=False, index=index, **merged)))
    assert combined == set.intersection(*sets) and combined
    assert combined == set(docs(search(top_k=EVERYTHING, index=index, **merged)))  # the same without a query


# --- invariants ----------------------------------------------------------------------------------

CASES = [(name, options) for name, options in FILTERS] + [
    ("claims only", {"passage_types": ["claim"]}),
    ("B60C descriptions", {"cpc_prefix": "B60C", "passage_types": ["description"]}),
    ("english only", {"language": "en"}),
]


@pytest.mark.parametrize("name, options", CASES, ids=[name for name, _ in CASES])
def test_filter_first_and_filter_after_return_the_same_results_in_the_same_order(index, name, options):
    differences = []
    for query in FIFTY:
        for mode in ("hybrid", "semantic"):
            runs = {strategy: search(query, mode=mode, strategy=strategy, top_k=EVERYTHING, translate_results=False,
                                     index=index, **options) for strategy in ("filter_first", "filter_after", "auto")}
            first = runs["filter_first"]
            for strategy in ("filter_after", "auto"):
                other = runs[strategy]
                if docs(first) != docs(other):
                    at = next(i for i, (a, b) in enumerate(zip(docs(first), docs(other))) if a != b) if len(first) == len(other) else -1
                    differences.append((query[:40], mode, strategy, at, len(first), len(other)))
                elif [r["passage"]["text"] if r["passage"] else None for r in first] != [r["passage"]["text"] if r["passage"] else None for r in other]:
                    differences.append((query[:40], mode, strategy, "evidence differs"))
    assert not differences, f"{len(differences)} differences, first: {differences[:5]}"


def test_results_are_ordered_by_score_and_have_no_duplicates(index):
    for query in FIFTY:
        for mode in ("hybrid", "semantic", "keyword"):
            results = search(query, mode=mode, top_k=EVERYTHING, translate_results=False, index=index)
            scores = [r["score"] for r in results]
            assert scores == sorted(scores, reverse=True), (query, mode)
            assert len(set(docs(results))) == len(results), (query, mode)


def test_the_same_query_twice_returns_identical_results(index):
    for query in FIFTY[:20]:
        first = search(query, top_k=50, translate_results=False, index=index, cpc_prefix="B60")
        second = search(query, top_k=50, translate_results=False, index=index, cpc_prefix="B60")
        assert [(r["doc_number"], r["score"], r["similarity"]) for r in first] == [(r["doc_number"], r["score"], r["similarity"]) for r in second]


def test_a_second_index_object_gives_the_same_results(index):
    other = Index(INDEX_DIR)
    for query in FIFTY[:10]:
        assert docs(search(query, top_k=50, translate_results=False, index=index)) == docs(search(query, top_k=50, translate_results=False, index=other))


@pytest.mark.parametrize("top_k", [1, 3, 5, 10, 50])
def test_top_k_is_respected(index, top_k):
    assert len(search("wheel hub with integrated pressure sensor", top_k=top_k, translate_results=False, index=index)) == top_k


def test_top_k_larger_than_what_exists_returns_what_exists(index, patents):
    passing = truth(patents, lambda p: "wheel bearing" in (p["title"] or "").lower() or "wheel bearing" in (p["title_en"] or "").lower())
    assert 0 < len(passing) < 10
    for query in (None, "sealed bearing for a wheel hub"):
        results = search(query, title="wheel bearing", top_k=10, translate_results=False, index=index)
        assert set(docs(results)) == passing
    assert len(search("wheel", top_k=EVERYTHING, translate_results=False, index=index)) == len(patents)


def test_top_k_is_a_prefix_of_a_longer_list(index):
    long = docs(search("run flat tire sidewall", top_k=50, translate_results=False, index=index))
    assert docs(search("run flat tire sidewall", top_k=7, translate_results=False, index=index)) == long[:7]


# --- hybrid ----------------------------------------------------------------------------------------

def test_hybrid_contains_items_from_both_the_keyword_list_and_the_semantic_list(index):
    """Pick the query whose keyword top 10 and semantic top 10 differ most, then look at the fused top 10."""
    best = None
    for query in FIFTY:
        kw = docs(search(query, mode="keyword", top_k=10, translate_results=False, index=index))
        sem = docs(search(query, mode="semantic", top_k=10, translate_results=False, index=index))
        if len(kw) == 10 and (best is None or len(set(kw) & set(sem)) < best[0]):
            best = (len(set(kw) & set(sem)), query, kw, sem)
    overlap, query, kw, sem = best
    assert overlap <= 5, "no query separates the two lists clearly"
    fused = docs(search(query, mode="hybrid", top_k=10, translate_results=False, index=index))
    only_keyword, only_semantic = set(kw) - set(sem), set(sem) - set(kw)
    assert set(fused) & only_keyword, f"{query!r}: nothing from the keyword-only side reached the fused top 10"
    assert set(fused) & only_semantic, f"{query!r}: nothing from the semantic-only side reached the fused top 10"


def test_hybrid_score_is_reciprocal_rank_fusion_of_the_two_lists(index):
    for query in FIFTY[:20]:
        kw = docs(search(query, mode="keyword", top_k=EVERYTHING, translate_results=False, index=index))
        sem = docs(search(query, mode="semantic", top_k=EVERYTHING, translate_results=False, index=index))
        expected = {}
        for ranking in (sem, kw):
            for rank, doc in enumerate(ranking, 1):
                expected[doc] = expected.get(doc, 0.0) + 1.0 / (60 + rank)
        fused = search(query, mode="hybrid", top_k=30, translate_results=False, index=index)
        for r in fused:
            assert abs(r["score"] - expected[r["doc_number"]]) < 1e-12, (query, r["doc_number"])
        assert [round(r["score"], 12) for r in fused] == sorted((round(v, 12) for v in expected.values()), reverse=True)[:30]


# --- bad input: a clear message and no crash --------------------------------------------------------

LONG = ("a wheel comprising a rim, a hub and spokes wherein the rim has a bead seat " * 140)[:10000]
BAD = {
    "empty query": (["search", ""], "error"),
    "no arguments": (["search"], "error"),
    "unknown document number": (["similar", "--doc", "99999999999"], "error"),
    "unknown document number in show": (["show", "--doc", "99999999999"], "message"),
    "claim number that does not exist": (["similar", "--doc", "20240051333", "--claim", "999"], "says so"),
    "filter that matches nothing": (["search", "wheel", "--cpc", "Z99Z"], "message"),
    "keyword that matches nothing": (["search", "wheel", "--keywords", "xyzzyplugh"], "message"),
    "query of 10,000 characters": (["search", LONG, "--top", "3"], "results"),
    "query of only punctuation": (["search", "?!...,;:--()", "--top", "3"], "any"),
    "query of only spaces": (["search", "    ", "--top", "3"], "any"),
    "query with quotes and SQL": (["search", "'; DROP TABLE patents; -- \" OR 1=1 \"", "--top", "3"], "results"),
    "full text operators in the query": (["search", 'NEAR(wheel tire) AND "rim* OR title_en:hub ^ {x}', "--top", "3"], "results"),
    "SQL in the keyword filter": (["search", "wheel", "--keywords", "rubber\" OR \"1\"=\"1'; DROP TABLE patents;--"], "any"),
    "wildcards in the title filter": (["search", "--title", "%_'\"\\", "--top", "3"], "message"),
    "SQL in the classification filter": (["search", "--cpc", "B60B' OR '1'='1", "--top", "3"], "message"),
    "bad date": (["search", "wheel", "--from", "2024-13-45"], "error"),
    "date in another format": (["search", "wheel", "--from", "06/01/2024"], "error"),
    "unknown passage type": (["search", "wheel", "--types", "figure"], "error"),
    "unknown language": (["search", "wheel", "--language", "xx", "--top", "3"], "message"),
    "top of zero": (["search", "wheel", "--top", "0"], "any"),
    "negative top": (["search", "wheel", "--top", "-1"], "any"),
}


@pytest.mark.parametrize("name", BAD)
def test_bad_input_gives_a_clear_message_and_does_not_crash(name):
    args, expect = BAD[name]
    done = cli(*args)
    output = done.stdout + done.stderr
    assert "Traceback" not in output, output[-800:]
    assert done.returncode in (0, 1, 2), done.returncode
    listed = len(re.findall(r"(?m)^ ?\d+\. \S+ \| ", done.stdout))
    if expect == "error":
        assert done.returncode != 0 and re.search(r"error", output, re.I), output[-300:]
    if expect == "message":
        assert "No patent" in output, output[-300:]
    if expect == "results":
        assert done.returncode == 0 and listed >= 1, output[-300:]
    if expect == "says so":  # the user asked for a claim that is not there: the output must say that, not just answer
        assert re.search(r"no claim 999|claim 999 (does not exist|not found|is not)|has no claim", output, re.I), output[:300]
    print(f"\n[{name}] exit {done.returncode}, {listed} results listed; first line: {output.strip().splitlines()[0][:150] if output.strip() else ''}")


def test_the_tables_survive_the_injection_attempts(index):
    assert index.con.execute("SELECT COUNT(*) FROM patents").fetchone()[0] == len(index.patent_ids) > 0


def test_negative_top_is_rejected_or_empty(index):
    results = search("wheel", top_k=-1, translate_results=False, index=index)
    assert len(results) == 0, f"top_k=-1 returned {len(results)} results"


def test_punctuation_only_keyword_filter_is_not_silently_dropped(index, patents):
    results = search("wheel", keywords="!!! ???", top_k=EVERYTHING, translate_results=False, index=index)
    assert len(results) < len(patents), "a keyword filter with no usable word was ignored and the search ran unfiltered"


def test_search_before_any_ingest_gives_a_message_not_a_crash(tmp_path):
    env = dict(os.environ, PATENT_INDEX=str(tmp_path / "empty-index"))
    done = subprocess.run([sys.executable, "cli.py", "search", "wheel hub"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    assert "Traceback" not in done.stderr, done.stderr[-600:]
