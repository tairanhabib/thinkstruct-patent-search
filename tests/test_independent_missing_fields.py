"""Independent test pass, Stage 2: missing fields, on synthetic records (the real data has only empty descriptions).

Each of six fields is removed in four ways: key deleted, null, empty string, empty list. In every case the patent
must ingest, stay findable through what is left, print "Unknown", and obey the filter rule.
A failing test here is a finding for TEST_REPORT.md.
"""
import re

import pytest

import cli
from conftest import COMPLETE, OTHER, without
from src.search import search

FIELDS = ["title", "abstract", "claims", "detailed_description", "classification", "bibtex"]
WAYS = {"deleted": "DELETE", "null": None, "empty string": "", "empty list": []}
LABEL = {"title": "Title", "abstract": "Abstract", "claims": "Claims", "detailed_description": "Description",
         "classification": "Classification", "bibtex": "Citation"}
# A query made only of words from one field of COMPLETE, to prove the patent is reachable through that field.
PROBE = {"title": "wheel hub with pressure sensor",
         "abstract": "reports the inflation state to the driver",
         "claims": "hub body with a bore and a tire pressure sensor mounted inside the bore",
         "detailed_description": "bore that holds the pressure sensor and its battery firmly in place"}


def broken(field, way):
    return without(COMPLETE, field) if WAYS[way] == "DELETE" else without(COMPLETE, **{field: WAYS[way]})


def docs(results):
    return [r["doc_number"] for r in results]


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("way", WAYS)
def test_patent_with_a_missing_field_ingests_without_error(build_index, field, way):
    index, stats = build_index([broken(field, way), OTHER])
    assert stats["patents"] == 2 and stats.get(f"missing_{field}") == 1
    stored = index.con.execute("SELECT missing_fields FROM patents WHERE doc_number = 'D-COMPLETE'").fetchone()[0]
    assert stored.split(",") == [field]  # exactly this field, nothing else flagged


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("way", WAYS)
def test_patent_is_still_findable_through_each_field_it_still_has(build_index, field, way):
    index, _ = build_index([broken(field, way), OTHER])
    for other, query in PROBE.items():
        if other == field:
            continue
        for mode in ("semantic", "hybrid"):
            assert docs(search(query, mode=mode, index=index))[0] == "D-COMPLETE", (other, mode)
    if field not in ("title", "abstract"):  # keyword search reads title and abstract
        assert "D-COMPLETE" in docs(search("inflation driver", mode="keyword", index=index))


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("way", WAYS)
def test_display_prints_unknown_and_never_none_null_or_a_blank_line(build_index, field, way):
    index, _ = build_index([broken(field, way), OTHER])
    shown = cli.format_patent(index, "D-COMPLETE", full=True)
    assert f"{LABEL[field]}: Unknown" in shown
    listing = cli.format_results(search("hub bore pressure sensor battery", index=index))
    for text in (shown, listing.rstrip("\n")):
        assert not re.search(r"\bNone\b|\bnull\b|\bnan\b", text), text
    assert all(line.strip() for line in shown.split("\n")), "show printed a blank line"
    # in a result listing a blank line separates results; no field line may be blank or end in a bare colon
    assert not re.search(r"(?m)^\s*(classification|filing week|language)\s*$", listing)
    if field == "title":
        assert "D-COMPLETE | Unknown" in listing
    if field == "classification":
        assert "classification Unknown" in listing


def test_display_of_a_patent_with_every_optional_field_missing(build_index):
    index, _ = build_index([{"doc_number": "D-BARE"}, OTHER])
    shown = cli.format_patent(index, "D-BARE")
    for label in ("Title", "Classification", "Citation", "Abstract", "Claims", "Description", "Source file"):
        assert f"{label}: Unknown" in shown
    assert "None" not in shown and all(line.strip() for line in shown.split("\n"))


# --- the filter rule: excluded by default, included with include_unknown --------------------------

FILTER_ON = {"title": {"title": "wheel hub"}, "classification": {"cpc_prefix": "B60B"},
             "abstract": {"keywords": "hub"}}  # the keyword filter reads title and abstract


@pytest.mark.parametrize("field", FILTER_ON)
@pytest.mark.parametrize("way", WAYS)
def test_filter_on_a_missing_field_excludes_by_default_and_includes_on_request(build_index, field, way):
    filters = FILTER_ON[field]
    record = broken(field, way)
    if field == "abstract":
        record["title"] = "Bearing assembly"  # so the keyword can only have come from the missing abstract
    index, _ = build_index([record, OTHER])
    assert "D-COMPLETE" not in docs(search(index=index, **filters))
    assert "D-COMPLETE" not in docs(search("pressure sensor in a bore", index=index, **filters))
    assert "D-COMPLETE" in docs(search(index=index, include_unknown=True, **filters))
    assert "D-COMPLETE" in docs(search("pressure sensor in a bore", index=index, include_unknown=True, **filters))
    # include_unknown must not let through a patent that HAS the field and fails the filter
    assert "D-OTHER" not in docs(search(index=index, include_unknown=True, **filters))


@pytest.mark.parametrize("field", ["claims", "detailed_description", "bibtex"])
def test_fields_with_no_filter_do_not_change_filtered_results(build_index, field):
    index, _ = build_index([without(COMPLETE, field), OTHER])
    assert docs(search(cpc_prefix="B60B", index=index)) == ["D-COMPLETE"]
    assert docs(search(keywords="hub", index=index)) == ["D-COMPLETE"]


def test_missing_date_and_the_date_filter(build_index):
    index, _ = build_index([without(COMPLETE, "filename"), OTHER], file_name="undated.json")
    assert "D-COMPLETE" not in docs(search(date_from="2024-01-01", index=index))
    assert "D-COMPLETE" in docs(search(date_from="2024-01-01", include_unknown=True, index=index))


def test_with_no_filter_a_patent_with_missing_fields_is_searched_like_any_other(build_index):
    index, _ = build_index([without(COMPLETE, "classification", "bibtex", "detailed_description"), OTHER])
    assert docs(search("tire pressure sensor in the hub bore", index=index))[0] == "D-COMPLETE"


# --- no searchable text at all -------------------------------------------------------------------

def test_patent_with_no_searchable_text_is_kept_counted_and_never_matches(build_index, capsys):
    bare = {"doc_number": "D-EMPTY", "classification": "B60B2700FI", "bibtex": "@patent{D-EMPTY}"}
    index, stats = build_index([bare, COMPLETE])
    assert stats["patents"] == 2 and stats["no_searchable_text"] == 1  # kept and counted, as documented
    assert "D-EMPTY" not in docs(search("hub bore pressure sensor", index=index))
    assert "D-EMPTY" not in docs(search("hub bore pressure sensor", mode="keyword", index=index))
    assert "D-EMPTY" in docs(search(cpc_prefix="B60B", index=index))  # still listed by a filter
    assert "Document number: D-EMPTY" in cli.format_patent(index, "D-EMPTY")


def test_ingest_names_the_patent_that_has_no_searchable_text(build_index, capsys):
    """The test plan asks for "a logged reason". A count alone does not say which patent, or why."""
    build_index([{"doc_number": "D-EMPTY", "classification": "B60B2700FI"}, COMPLETE])
    logged = capsys.readouterr().out
    assert "D-EMPTY" in logged


@pytest.mark.parametrize("value", [0, False, {}, [None], [[]], ["  ", ""], {"text": ""}, 3.5])
@pytest.mark.parametrize("field", FIELDS)
def test_odd_values_never_stop_an_ingest(build_index, field, value):
    index, stats = build_index([without(COMPLETE, **{field: value}), OTHER])
    assert stats["patents"] == 2
    shown = cli.format_patent(index, "D-COMPLETE")
    assert "Document number: D-COMPLETE" in shown and not re.search(r"\bNone\b", shown)
