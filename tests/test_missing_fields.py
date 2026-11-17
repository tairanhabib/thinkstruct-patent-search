"""The missing field policy, proven on synthetic records.

Policy: a patent is never dropped. A missing field is stored as NULL, listed in
`missing_fields`, shown as "Unknown", and makes the patent fail a filter on that field
only when that filter is used, unless include_unknown is set.
"""
import pytest

import cli
from conftest import COMPLETE, OTHER, without
from src.search import search

FIELDS = ["title", "abstract", "detailed_description", "claims", "classification", "bibtex", "filename"]
EMPTY_VALUES = {"deleted": None, "null": [None], "empty string": [""], "whitespace": ["   "], "empty list": [[]],
                "list of empty strings": [["", " "]]}


def docs(results):
    return [result["doc_number"] for result in results]


def broken(field, how):
    """COMPLETE with one field deleted or emptied."""
    if how == "deleted":
        return without(COMPLETE, field)
    return without(COMPLETE, **{field: EMPTY_VALUES[how][0]})


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("how", EMPTY_VALUES)
def test_patent_with_a_missing_field_is_ingested_searched_and_shown_as_unknown(build_index, field, how):
    index, stats = build_index([broken(field, how), OTHER])
    assert stats["patents"] == 2  # not dropped

    row = index.con.execute("SELECT missing_fields FROM patents WHERE doc_number = 'D-COMPLETE'").fetchone()
    if field != "filename":  # filename is not shown to the user; its absence is covered by filing_week below
        assert field in row["missing_fields"].split(",")
        assert stats[f"missing_{field}"] == 1

    results = search("hub bore pressure sensor battery", mode="semantic", index=index)
    assert docs(results)[0] == "D-COMPLETE"  # still found through the text that remains

    shown = cli.format_patent(index, "D-COMPLETE")
    label = {"detailed_description": "Description", "bibtex": "Citation", "filename": "Source file"}.get(field, field.capitalize())
    assert f"{label}: Unknown" in shown


def test_patent_with_no_abstract_still_appears_in_results(build_index):
    index, _ = build_index([without(COMPLETE, "abstract"), OTHER])
    for mode in ("semantic", "hybrid"):
        results = search("tire pressure sensor in a hub bore", mode=mode, index=index)
        assert docs(results)[0] == "D-COMPLETE" and results[0]["passage"]["kind"] in ("claim", "description")
    assert "None" not in cli.format_results(results)


def test_missing_classification_fails_a_classification_filter_unless_unknown_is_included(build_index):
    index, _ = build_index([without(COMPLETE, "classification"), OTHER])
    assert docs(search("pressure sensor", index=index))[0] == "D-COMPLETE"  # no filter: present
    assert search("pressure sensor", cpc_prefix="B60B", index=index) == []  # filter used: excluded
    assert docs(search("pressure sensor", cpc_prefix="B60B", include_unknown=True, index=index)) == ["D-COMPLETE"]
    for strategy in ("auto", "filter_first", "filter_after"):
        assert search("pressure sensor", cpc_prefix="B60B", strategy=strategy, index=index) == []


def test_missing_title_fails_a_title_filter_unless_unknown_is_included(build_index):
    index, _ = build_index([without(COMPLETE, "title"), OTHER])
    assert search("pressure sensor", title="wheel hub", index=index) == []
    assert docs(search("pressure sensor", title="wheel hub", include_unknown=True, index=index)) == ["D-COMPLETE"]


def test_missing_abstract_and_a_keyword_filter(build_index):
    index, _ = build_index([without(COMPLETE, "abstract"), OTHER])
    assert docs(search("sensor", keywords="hub", index=index)) == ["D-COMPLETE"]  # the title still matches
    assert search("sensor", keywords="inflation", index=index) == []  # the word was only in the lost abstract
    assert docs(search("sensor", keywords="inflation", include_unknown=True, index=index)) == ["D-COMPLETE"]


def test_missing_date_fails_a_date_filter_unless_unknown_is_included(build_index):
    index, stats = build_index([without(COMPLETE, "filename"), OTHER], file_name="no_date_in_this_name.json")
    assert stats["missing_filing_week"] == 1
    assert docs(search("tire", date_from="2024-01-01", index=index)) == ["D-OTHER"]
    assert set(docs(search("tire", date_from="2024-01-01", include_unknown=True, index=index))) == {"D-COMPLETE", "D-OTHER"}


def test_undetectable_language_fails_a_language_filter_unless_unknown_is_included(build_index):
    formula_only = {"doc_number": "D-FORMULA", "claims": ["1.1 ≤ b/C ≤ 1.4 (1) 0.5 ≤ D/E ≤ 0.9 (2) 3 ≤ F/G ≤ 4 (3) 12 ≥ 7"]}
    index, stats = build_index([formula_only, OTHER])
    assert stats["language_unknown"] == 1
    assert docs(search("b/C", language="en", index=index)) == ["D-OTHER"]
    assert "D-FORMULA" in docs(search("b/C", language="en", include_unknown=True, index=index))
    assert "Language: Unknown" in cli.format_patent(index, "D-FORMULA")


def test_patent_with_no_claims_can_still_be_the_source_of_a_similarity_search(build_index):
    index, _ = build_index([without(COMPLETE, "claims"), OTHER])
    info = {}
    results = search(doc_number="D-COMPLETE", claim_number=1, index=index, info=info)
    assert docs(results) == ["D-OTHER"] and info["query_source"] == "abstract"  # fell back, and says so


def test_patent_with_only_a_title_is_kept_and_found_by_keyword(build_index):
    index, stats = build_index([{"doc_number": "D-TITLE", "title": "Magnetic levitation wheel"}, OTHER])
    assert stats["patents"] == 2 and stats.get("no_searchable_text", 0) == 0
    for mode in ("keyword", "hybrid"):
        results = search("levitation wheel", mode=mode, index=index)
        assert "D-TITLE" in docs(results)
    title_only = next(r for r in results if r["doc_number"] == "D-TITLE")
    assert title_only["passage"] is None and "Evidence: Unknown" not in cli.format_results([title_only])


def test_patent_with_nothing_but_a_number_is_stored_and_counted(build_index):
    index, stats = build_index([{"doc_number": "D-EMPTY"}, OTHER])
    assert stats["patents"] == 2 and stats["no_searchable_text"] == 1
    shown = cli.format_patent(index, "D-EMPTY")
    assert shown.count("Unknown") >= 6 and "D-EMPTY" in shown
    assert docs(search("anything at all", index=index)) == ["D-OTHER"]  # it cannot match, and it breaks nothing


def test_patent_without_a_document_number_gets_a_labelled_placeholder(build_index):
    index, stats = build_index([without(COMPLETE, "doc_number"), OTHER])
    assert stats["missing_doc_number"] == 1
    results = search("hub bore pressure sensor", mode="semantic", index=index)
    assert docs(results)[0].startswith("NO-NUMBER-")


def test_a_broken_file_and_a_broken_record_do_not_stop_the_batch(build_index, tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "patents_ipa240101.json").write_text("{ this is not json", encoding="utf-8")
    index, stats = build_index([COMPLETE, "not a dictionary", OTHER])
    assert stats["files_failed"] == 1 and stats["records_not_a_dictionary"] == 1 and stats["patents"] == 2
