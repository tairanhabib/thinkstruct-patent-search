import numpy as np
import pytest

from conftest import COMPLETE, OTHER, without
from src.search import Index, rank_patents, search


def docs(results):
    return [result["doc_number"] for result in results]


def test_semantic_search_returns_the_best_passage_as_evidence(build_index):
    index, _ = build_index([COMPLETE, OTHER])
    results = search("circumferential grooves and sipes in the tread", mode="semantic", index=index)
    assert docs(results)[0] == "D-OTHER"
    assert "grooves" in results[0]["passage"]["text"] and results[0]["similarity"] > 0.5


def test_filter_first_and_filter_after_give_the_same_ranking():
    rng = np.random.default_rng(0)
    vectors = rng.normal(size=(500, 16)).astype(np.float32)
    vectors[250:] = vectors[:250]  # the real data has patents that share identical text, so scores tie exactly
    owner = np.sort(np.concatenate([rng.integers(0, 40, 250), rng.integers(40, 80, 250)]))  # grouped, as Index keeps them
    query = rng.normal(size=16).astype(np.float32)
    keep = owner % 3 == 0
    first = rank_patents(vectors, owner, query, keep, "filter_first")
    after = rank_patents(vectors, owner, query, keep, "filter_after")
    assert all(float(vectors[row] @ query) == pytest.approx(score, abs=1e-5) and owner[row] == patent
               for patent, row, score in zip(*first))  # the row returned really is that patent's best
    assert all(score >= float((vectors[(owner == patent) & keep] @ query).max()) - 1e-5 for patent, _, score in zip(*first))
    assert first[0].tolist() == after[0].tolist() and first[1].tolist() == after[1].tolist()
    assert np.allclose(first[2], after[2], atol=1e-5)
    assert set(first[0].tolist()) == set(owner[keep].tolist())
    everything = rank_patents(vectors, owner, query)
    assert [p for p in everything[0].tolist() if p % 3 == 0] == first[0].tolist()


def test_classification_prefix_filter_accepts_spaces_and_slashes(build_index):
    index, _ = build_index([COMPLETE, OTHER])
    assert docs(search("tire", cpc_prefix="B60B", index=index)) == ["D-COMPLETE"]
    assert docs(search("tire", cpc_prefix="b60c 11/03", index=index)) == ["D-OTHER"]
    assert docs(search("tire", cpc_prefix="B60", index=index, top_k=5)) != []
    assert search("tire", cpc_prefix="H01L", index=index) == []


def test_keyword_filter_needs_every_keyword_and_uses_word_stems(build_index):
    index, _ = build_index([COMPLETE, OTHER])
    assert docs(search("vehicle part", keywords="sensors pressure", index=index)) == ["D-COMPLETE"]
    assert search("vehicle part", keywords="pressure grooves", index=index) == []


def test_title_and_date_filters(build_index):
    index, _ = build_index([COMPLETE, OTHER])
    assert docs(search(title="pneumatic tire", index=index)) == ["D-OTHER"]
    index.con.execute("UPDATE patents SET filing_week = '2025-01-02' WHERE doc_number = 'D-OTHER'")
    assert docs(search("tire", date_from="2025-01-01", index=index)) == ["D-OTHER"]
    assert docs(search("tire", date_to="2024-12-31", index=index)) == ["D-COMPLETE"]


def test_passage_type_filter_limits_the_evidence(build_index):
    index, _ = build_index([COMPLETE, OTHER])
    for kind in ("claim", "abstract", "description"):
        results = search("pressure sensor battery", passage_types=[kind], index=index)
        assert results and all(result["passage"]["kind"] == kind for result in results)


def test_similar_excludes_the_source_patent_and_names_the_claim_used(build_index):
    index, _ = build_index([COMPLETE, OTHER])
    info = {}
    results = search(doc_number="D-COMPLETE", claim_number=2, index=index, info=info)
    assert docs(results) == ["D-OTHER"] and info["query_source"] == "claim 2"
    with pytest.raises(ValueError):
        search(doc_number="NOT-THERE", index=index)


def test_hybrid_fusion_rewards_agreement_between_keyword_and_semantic(build_index):
    index, _ = build_index([COMPLETE, OTHER])
    results = search("tire pressure sensor", mode="hybrid", index=index)
    assert docs(results)[0] == "D-COMPLETE" and results[0]["keyword_rank"] == 1
    assert results[0]["score"] == pytest.approx(2 / 61)  # first in both rankings


def test_filters_only_lists_matches_and_a_bare_call_is_refused(build_index):
    index, _ = build_index([COMPLETE, OTHER])
    assert docs(search(cpc_prefix="B60C", index=index)) == ["D-OTHER"]
    assert docs(search(keywords="sensor", index=index)) == ["D-COMPLETE"]
    with pytest.raises(ValueError):
        search(index=index)


def test_foreign_patent_is_searchable_by_english_keywords_and_shown_in_english(build_index):
    german = without(COMPLETE, doc_number="D-GERMAN", title="Radnabe mit Drucksensor",
                     abstract="Eine Radnabe mit einem Reifendrucksensor, der den Fülldruck des Reifens an den Fahrer meldet.",
                     claims=["eine Radnabe mit einer Bohrung und einem Reifendrucksensor, der in der Bohrung sitzt"],
                     detailed_description=["Die Nabe hat eine Bohrung, in der der Drucksensor und seine Batterie festsitzen."])
    index, stats = build_index([german, OTHER])
    assert stats["language_de"] == 1
    row = index.con.execute("SELECT language, title_en FROM patents WHERE doc_number = 'D-GERMAN'").fetchone()
    assert row["language"] == "de" and row["title_en"] == "[de to en] Radnabe mit Drucksensor"
    [result] = search("Radnabe Drucksensor Bohrung", language="de", index=index)
    assert result["passage"]["text_en"].startswith("[de to en] ") and result["passage"]["text"].startswith(("eine", "Die", "Eine"))
    assert docs(search(keywords="Drucksensor", index=index)) == ["D-GERMAN"]  # the fake keeps the German words
    assert index.con.execute("SELECT COUNT(*) FROM translations").fetchone()[0] >= 3  # title, abstract, passage cached


def test_ingest_twice_adds_nothing(build_index):
    index, first = build_index([COMPLETE, OTHER])
    _, second = build_index([COMPLETE, OTHER])
    assert first["patents"] == 2 and second == {"files": 1, "already_indexed": 2}


def test_index_regroups_vectors_that_were_saved_out_of_patent_order(build_index, tmp_path):
    index, _ = build_index([COMPLETE, OTHER])
    expected = [(r["doc_number"], r["passage"]["text"]) for r in search("pressure sensor battery", mode="semantic", index=index)]
    order = np.random.default_rng(1).permutation(len(index.vectors))
    np.save(tmp_path / "index" / "embeddings.npy", index.vectors[order])
    np.save(tmp_path / "index" / "vector_passage_ids.npy", index.vector_passage[order])
    shuffled = Index(str(tmp_path / "index"))
    assert np.all(np.diff(shuffled.vector_patent) >= 0)
    assert [(r["doc_number"], r["passage"]["text"]) for r in search("pressure sensor battery", mode="semantic", index=shuffled)] == expected
