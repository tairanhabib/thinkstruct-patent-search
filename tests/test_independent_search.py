"""Independent test pass, Stage 3: search invariants that need no model (random vectors and the offline fakes).

The same invariants are checked against the real index and the real model in scripts/testing/test_functional_real.py.
A failing test is a finding for TEST_REPORT.md.
"""
import numpy as np
import pytest

from conftest import COMPLETE, OTHER, without
from src.search import rank_patents, search


def random_index(rng, patents=60, dims=24, duplicate_rows=True):
    sizes = rng.integers(1, 9, patents)
    owner = np.repeat(np.arange(1, patents + 1), sizes)
    vectors = rng.normal(size=(len(owner), dims)).astype(np.float32)
    if duplicate_rows:  # identical passages in different patents: exact ties, which real data has
        vectors[rng.integers(0, len(owner), 12)] = vectors[rng.integers(0, len(owner), 12)]
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors, owner


@pytest.mark.parametrize("seed", range(25))
@pytest.mark.parametrize("share", [0.01, 0.05, 0.14, 0.16, 0.5, 0.99, 1.0])
def test_every_strategy_returns_the_same_patents_in_the_same_order(seed, share):
    rng = np.random.default_rng(seed)
    vectors, owner = random_index(rng)
    query = vectors[rng.integers(len(vectors))] + rng.normal(scale=0.1, size=vectors.shape[1]).astype(np.float32)
    allowed = rng.random(owner.max() + 1) < share
    keep = allowed[owner]
    runs = [rank_patents(vectors, owner, query, keep, strategy) for strategy in ("filter_first", "filter_after", "auto")]
    for other in runs[1:]:
        assert runs[0][0].tolist() == other[0].tolist()  # same patents, same order
        assert runs[0][1].tolist() == other[1].tolist()  # same evidence row
        assert np.allclose(runs[0][2], other[2], atol=1e-6)
    patents, rows, scores = runs[0]
    assert set(patents.tolist()) == set(owner[keep].tolist())  # every patent that passes, and no other
    assert len(set(patents.tolist())) == len(patents)
    assert np.all(np.diff(scores) <= 1e-7)  # best first
    assert all(keep[row] and owner[row] == patent for patent, row in zip(patents.tolist(), rows.tolist()))
    brute = {p: float((vectors[(owner == p) & keep] @ query).max()) for p in set(owner[keep].tolist())}
    assert np.allclose(scores, [brute[p] for p in patents.tolist()], atol=1e-6)  # the score is the best passage's


@pytest.mark.parametrize("seed", range(10))
def test_strategies_agree_with_several_languages_and_calibration(seed):
    rng = np.random.default_rng(seed)
    vectors, owner = random_index(rng)
    language_of_patent = rng.integers(0, 3, owner.max() + 1)
    version = language_of_patent[owner]
    queries = rng.normal(size=(3, vectors.shape[1])).astype(np.float32)
    calibration = (np.array([0.0, 0.05, 0.1]), np.array([1.0, 0.8, 1.2]))
    keep = (rng.random(owner.max() + 1) < 0.4)[owner]
    a = rank_patents(vectors, owner, queries, keep, "filter_first", version, calibration)
    b = rank_patents(vectors, owner, queries, keep, "filter_after", version, calibration)
    assert a[0].tolist() == b[0].tolist() and a[1].tolist() == b[1].tolist()


def test_a_filter_that_keeps_nothing_returns_nothing():
    vectors, owner = random_index(np.random.default_rng(0))
    for strategy in ("filter_first", "filter_after", "auto"):
        patents, rows, scores = rank_patents(vectors, owner, vectors[0], np.zeros(len(owner), bool), strategy)
        assert len(patents) == 0 and len(rows) == 0


RECORDS = [
    COMPLETE, OTHER,
    {"title": "Trailer hitch coupling", "doc_number": "D-HITCH", "filename": "US0000003A1-20240229.XML",
     "abstract": "A coupling for a trailer hitch that locks by itself when the ball enters the socket.",
     "detailed_description": ["The socket holds a spring loaded latch that closes around the ball of the towing vehicle."],
     "claims": ["1 . A trailer coupling comprising a socket and a spring loaded latch"], "classification": "B60D106FI",
     "bibtex": "@patent{D-HITCH}"},
    {"title": "Zirconium bracket", "doc_number": "D-KEYWORD", "filename": "US0000004A1-20240307.XML",
     "abstract": "A zirconium bracket.", "detailed_description": [], "claims": [], "classification": "B60B2700FI", "bibtex": "@patent{D-KEYWORD}"},
    {"title": "Assembly", "doc_number": "D-SEMANTIC", "filename": "US0000005A1-20240314.XML",
     "abstract": "An assembly for vehicles that is described only in its claims and nowhere else at all.",
     "detailed_description": ["The fastener holder of zirconium alloy carries the bracket of the brake line on the axle housing."],
     "claims": ["1 . A holder made of a zirconium alloy that carries a bracket for a brake line on an axle housing"],
     "classification": "B60B2700FI", "bibtex": "@patent{D-SEMANTIC}"},
]


def docs(results):
    return [r["doc_number"] for r in results]


def test_hybrid_brings_in_what_only_keywords_and_what_only_meaning_found(build_index):
    index, _ = build_index(RECORDS)
    query = "zirconium alloy holder that carries a bracket for a brake line on an axle housing"
    keyword = docs(search(query, mode="keyword", top_k=1, index=index))
    semantic = docs(search(query, mode="semantic", top_k=1, index=index))
    assert keyword == ["D-KEYWORD"] and semantic == ["D-SEMANTIC"]  # the two lists clearly differ at the top
    # Rank 1 in one list only is worth 1/61. D-COMPLETE is second in BOTH lists (2/62), so it leads the fused list:
    # that is how reciprocal rank fusion works, and it is why the top 3 is checked here, not the top 2.
    fused = docs(search(query, mode="hybrid", top_k=3, index=index))
    assert {"D-KEYWORD", "D-SEMANTIC"} <= set(fused)


def test_results_are_sorted_unique_and_repeatable(build_index):
    index, _ = build_index(RECORDS)
    for mode in ("hybrid", "semantic", "keyword"):
        first = search("pressure sensor in a wheel hub", mode=mode, index=index)
        second = search("pressure sensor in a wheel hub", mode=mode, index=index)
        assert [(r["doc_number"], r["score"]) for r in first] == [(r["doc_number"], r["score"]) for r in second]
        assert [r["score"] for r in first] == sorted((r["score"] for r in first), reverse=True)
        assert len(set(docs(first))) == len(first)


@pytest.mark.parametrize("top_k, expected", [(1, 1), (2, 2), (5, 5), (50, 5)])
def test_top_k_is_respected_even_when_fewer_exist(build_index, top_k, expected):
    index, _ = build_index(RECORDS)
    # hybrid, because D-KEYWORD has no passage long enough to embed: semantic search alone can never return it
    assert len(search("vehicle wheel tire trailer bracket", mode="hybrid", top_k=top_k, index=index)) == expected


@pytest.mark.parametrize("top_k", [0, -1, -5])
def test_top_k_of_zero_or_less_returns_nothing_or_is_refused(build_index, top_k):
    index, _ = build_index(RECORDS)
    try:
        results = search("vehicle wheel", top_k=top_k, index=index)
    except ValueError:
        return
    assert results == [], f"top_k={top_k} returned {len(results)} results"


def test_search_by_document_number_excludes_the_patent_in_every_mode(build_index):
    index, _ = build_index(RECORDS)
    for record in RECORDS:
        for mode in ("hybrid", "semantic", "keyword"):
            try:
                results = search(doc_number=record["doc_number"], mode=mode, top_k=50, index=index)
            except ValueError:
                continue  # no text long enough to search with: refused with a message, which is fine
            assert record["doc_number"] not in docs(results)


def test_claim_number_that_does_not_exist_is_reported(build_index):
    """`similar --doc X --claim 99`: the patent has no claim 99. Answering with the abstract is only acceptable if the
    caller is told the claim was not there."""
    index, _ = build_index(RECORDS)
    info = {}
    try:
        search(doc_number="D-COMPLETE", claim_number=99, index=index, info=info)
    except ValueError as error:
        assert "99" in str(error)
        return
    assert "99" in str(info.get("query_source", "")) or "not" in str(info.get("query_source", "")), info.get("query_source")


@pytest.mark.parametrize("query", ["", None])
def test_empty_query_without_filters_is_refused(build_index, query):
    index, _ = build_index(RECORDS)
    with pytest.raises(ValueError):
        search(query, index=index)


@pytest.mark.parametrize("query", ["   ", "\n\t", "?!.,;:", "---", "()[]{}"])
def test_query_with_no_words_is_refused_or_returns_nothing(build_index, query):
    index, _ = build_index(RECORDS)
    try:
        results = search(query, index=index)
    except ValueError:
        return
    assert results == [], f"{query!r} returned {len(results)} ranked results as if it meant something"


@pytest.mark.parametrize("keywords", ["?!", "--", '""'])
def test_keyword_filter_with_no_usable_word_is_not_silently_dropped(build_index, keywords):
    index, _ = build_index(RECORDS)
    try:
        results = search("vehicle", keywords=keywords, top_k=50, index=index)
    except ValueError:
        return
    unfiltered = search("vehicle", top_k=50, index=index)
    assert docs(results) != docs(unfiltered), "the keyword filter was ignored: same results as with no filter at all"


@pytest.mark.parametrize("text", ["'; DROP TABLE patents; --", '" OR 1=1 --', "NEAR(a b) AND * OR NOT", "title_en:hub", "a\x00b", "100% _ \\ %"])
def test_quotes_and_sql_in_every_text_input_do_no_harm(build_index, text):
    index, _ = build_index(RECORDS)
    for options in ({"query": text}, {"keywords": text}, {"title": text}, {"cpc_prefix": text}, {"query": "wheel", "keywords": text},
                    {"query": "wheel", "title": text}, {"query": "wheel", "language": text}):
        try:
            search(index=index, **options)
        except ValueError:
            pass
    assert index.con.execute("SELECT COUNT(*) FROM patents").fetchone()[0] == len(RECORDS)


def test_inverted_date_range_returns_nothing(build_index):
    index, _ = build_index(RECORDS)
    assert search(date_from="2025-01-01", date_to="2024-01-01", index=index) == []
