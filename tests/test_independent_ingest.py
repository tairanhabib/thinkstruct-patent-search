"""Independent test pass, Stage 2: ingest and cleaning, on small hand-built records.

Written by a test agent that did not write src/. A failing test here is a finding for
TEST_REPORT.md, not something to patch around. Uses the offline fakes from conftest.py.
"""
import json
import re

import numpy as np
import pytest

from src import embed, ingest, search
from src.ingest import normalize, parse_claims

from conftest import COMPLETE, OTHER, without

FILE = "patents_ipa240215.json"


def passages(index, doc, kind=None):
    sql = ("SELECT s.* FROM passages s JOIN patents p ON p.id = s.patent_id WHERE p.doc_number = ?"
           + (" AND s.kind = ?" if kind else "") + " ORDER BY s.kind, s.ord, s.id")
    return index.con.execute(sql, (doc, kind) if kind else (doc,)).fetchall()


# --- empty paragraphs ---------------------------------------------------------------------------

def test_empty_and_whitespace_description_paragraphs_are_dropped(build_index):
    record = without(COMPLETE, detailed_description=["", "First real paragraph about the hub and its bore.", "   ",
                                                     "\n\t", "Second real paragraph about the sensor battery."])
    index, _ = build_index([record])
    texts = [row["text"] for row in passages(index, "D-COMPLETE", "description")]
    assert texts == ["First real paragraph about the hub and its bore.", "Second real paragraph about the sensor battery."]


# --- cancelled claims ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw", ["1 - 5 . (canceled)", "1-5. (canceled)", "3 . (canceled)", "3 . (cancelled)",
                                 "1 - 5 . (Canceled)", "1 - 5 . (CANCELED)", "1 - 5 . canceled", "(canceled)",
                                 "1 - 5 . (canceled).", "1 .- 15 . (canceled)", "1 - 15 : (canceled)", "1 - 9 (canceled)"])
def test_cancelled_claim_is_dropped(raw):
    claims = parse_claims([raw, "6 . A wheel comprising a rim and a hub"])
    assert [c["number"] for c in claims] == [6]
    assert not any("cancel" in c["text"].lower() for c in claims)


def test_a_real_claim_that_mentions_cancelling_is_not_dropped():
    [claim] = parse_claims(["1 . A noise canceling tire comprising a resonator that has canceled the cavity tone"])
    assert claim["number"] == 1 and "canceling" in claim["text"]


@pytest.mark.parametrize("raw", ["2 . (withdrawn)", "2 . (Withdrawn) The wheel of claim 1", "1 - 3 . (not entered)"])
def test_other_status_markers_are_reported(raw):
    """Not in the documented policy. Records what happens to withdrawn claims: they are kept as claim text."""
    claims = parse_claims([raw])
    assert len(claims) == 1  # kept; documents current behaviour


# --- claim numbers ------------------------------------------------------------------------------

def test_first_claim_without_a_number_is_claim_1():
    claims = parse_claims(["an axle body, having a middle segment and two end segments",
                           "2 . The spoke according to claim 1 , wherein the axle body is steel"])
    assert [(c["number"], c["inferred"]) for c in claims] == [(1, 1), (2, 0)]


@pytest.mark.parametrize("raw, number, start", [
    ("1 . A wheel", 1, "A wheel"), ("12 . The wheel", 12, "The wheel"), ("3.The wheel", 3, "The wheel"),
    ("  7 .  The wheel", 7, "The wheel"), ("101 . The wheel", 101, "The wheel"),
    ("4 ． The wheel", 4, "The wheel"), ("5、轮辋", 5, "轮辋"),
])
def test_claim_number_formats(raw, number, start):
    [claim] = parse_claims([raw])
    assert claim["number"] == number and claim["inferred"] == 0 and claim["text"].startswith(start)


@pytest.mark.parametrize("raw", ["0.5 mm to 1.5 mm thick rubber layer on the rim",
                                 "1,2-polybutadiene rubber in the tread compound",
                                 "100 parts by mass of a diene rubber"])
def test_body_that_starts_with_a_quantity_is_not_read_as_a_claim_number(raw):
    [claim] = parse_claims([raw])
    assert (claim["number"], claim["inferred"]) == (1, 1) and claim["text"] == raw


def test_claim_numbers_are_unique_within_a_patent_for_a_clean_sequence():
    claims = parse_claims(["a rim", "2 . The rim of claim 1", "a hub", "a spoke", "5 . The spoke of claim 4"])
    numbers = [c["number"] for c in claims]
    assert numbers == [1, 2, 3, 4, 5] and len(set(numbers)) == len(numbers)


def test_unnumbered_run_longer_than_the_gap_gives_a_duplicate_number():
    """The documented weak spot (35 places in the real data): two unnumbered claims where the numbering has room
    for one. Recorded as behaviour: the second inferred number collides with the stated one."""
    claims = parse_claims(["1 . A rim", "a hub body", "a spoke body", "3 . The spoke of claim 1"])
    assert [c["number"] for c in claims] == [1, 2, 3, 3]


# --- dependent claims ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw, parent", [
    ("2 . The spoke according to claim 1 , wherein the hub is steel", 1),
    ("3 . The wheel of claim 2 , further comprising a sensor", 2),
    ("4 . The tire as claimed in claim 3 , in which the tread is rubber", 3),
    ("5 . The tire as recited in Claim 4", 4),
    ("6 . The tire according to any one of claims 1 to 5", 1),
    ("7 . A vehicle comprising the wheel of claim 6", 6),
    ("12 . The wheel according to claim 11 , wherein the rim of claim 1 is used", 11),
])
def test_dependent_claim_is_linked_to_its_parent(raw, parent):
    [claim] = parse_claims([raw])
    assert claim["parent"] == parent


@pytest.mark.parametrize("raw", ["1 . A wheel comprising a rim and a hub", "9 . A method of making a tire",
                                 "2 . The wheel of any preceding claim"])
def test_independent_or_unresolvable_claim_has_no_parent(raw):
    [claim] = parse_claims([raw])
    assert claim["parent"] is None


def test_a_claim_is_never_its_own_parent():
    [claim] = parse_claims(["2 . The wheel of claim 2 , wherein the rim is aluminium"])
    assert claim["parent"] is None


def test_parent_is_stored_and_points_at_an_existing_claim(build_index):
    record = without(COMPLETE, claims=["a hub body with a bore and a tire pressure sensor mounted inside the bore",
                                       "2 . The hub of claim 1 , wherein the pressure sensor is powered by a battery",
                                       "3 . The hub of claim 2 , wherein the battery is rechargeable through the bore"])
    index, _ = build_index([record])
    rows = {row["ord"]: row for row in passages(index, "D-COMPLETE", "claim")}
    assert rows[1]["parent_claim"] is None and rows[2]["parent_claim"] == 1 and rows[3]["parent_claim"] == 2
    assert all(row["parent_claim"] in rows for row in rows.values() if row["parent_claim"])


# --- long paragraphs ----------------------------------------------------------------------------

def long_paragraph(characters=25000):
    words, sentence = [], 0
    while sum(len(w) + 1 for w in words) < characters:
        sentence += 1
        words += f"Sentence {sentence} describes the bead seat {sentence * 7} of the rim flange {sentence * 13} in detail.".split()
    return " ".join(words)


def test_long_paragraph_is_stored_whole_and_split_into_windows_that_lose_nothing(build_index):
    text = long_paragraph()
    assert len(text) > 20000
    index, _ = build_index([without(COMPLETE, detailed_description=[text])])
    [stored] = passages(index, "D-COMPLETE", "description")
    assert stored["text"] == text  # the stored text is the whole paragraph
    pieces = embed.windows(text, 1600)
    assert all(len(piece) <= 1600 for piece in pieces)
    assert " ".join(pieces).split() == text.split()  # every word, in order, exactly once
    rows = int((index.vector_passage == stored["id"]).sum())
    assert rows == len(pieces) and rows > 12  # one vector per window


@pytest.mark.parametrize("text", ["x" * 20500, "轮" * 20500, ("word" * 500 + " ") * 11, "a, " * 7000])
def test_windows_lose_no_character_on_text_without_convenient_boundaries(text):
    for limit in (400, 1600):
        pieces = embed.windows(text, limit)
        assert all(0 < len(piece) <= limit for piece in pieces)
        assert re.sub(r"\s", "", "".join(pieces)) == re.sub(r"\s", "", text)


def test_window_boundaries_have_no_overlap_and_no_gap():
    text = long_paragraph(6000)
    pieces = embed.windows(text, 1600)
    assert sum(len(piece.split()) for piece in pieces) == len(text.split())


# --- short fragments ----------------------------------------------------------------------------

def test_short_fragment_is_kept_for_display_and_not_embedded(build_index):
    fragment, long_enough = "1.1≤b/C≤1.4 (1)", "x" * 39 + "y"
    assert len(fragment) < 40 and len(long_enough) == 40
    index, _ = build_index([without(COMPLETE, detailed_description=[fragment, "z" * 39, long_enough])])
    rows = passages(index, "D-COMPLETE", "description")
    assert [row["text"] for row in rows] == [fragment, "z" * 39, long_enough]  # all three stored
    embedded = set(index.vector_passage.tolist())
    assert [row["id"] in embedded for row in rows] == [False, False, True]  # 39 is out, 40 is in


def test_short_fragment_is_printed_by_show(build_index):
    import cli
    index, _ = build_index([without(COMPLETE, detailed_description=["FIG. 1", "The hub has a bore for the sensor housing."])])
    assert "FIG. 1" in cli.format_patent(index, "D-COMPLETE")


# --- classification -----------------------------------------------------------------------------

def test_subclass_is_the_first_four_characters(build_index):
    index, _ = build_index([COMPLETE, OTHER])
    rows = dict(index.con.execute("SELECT p.doc_number, c.subclass FROM classifications c JOIN patents p ON p.id = c.patent_id"))
    assert rows == {"D-COMPLETE": "B60B", "D-OTHER": "B60C"}
    codes = dict(index.con.execute("SELECT p.doc_number, c.code FROM classifications c JOIN patents p ON p.id = c.patent_id"))
    assert codes == {"D-COMPLETE": "B60B2700FI", "D-OTHER": "B60C1103FI"}  # raw code kept, FI suffix included


@pytest.mark.parametrize("prefix, expected", [
    ("B60B", {"D-COMPLETE"}), ("B60C", {"D-OTHER"}), ("B60", {"D-COMPLETE", "D-OTHER"}), ("b60b", {"D-COMPLETE"}),
    ("B60B27", {"D-COMPLETE"}), ("B60B 27", {"D-COMPLETE"}), ("B60B2700FI", {"D-COMPLETE"}), ("B60B28", set()),
    ("B60D", set()), ("60B", set()), ("B60B2700FIX", set()),
])
def test_prefix_filter_works_on_the_raw_code(build_index, prefix, expected):
    index, _ = build_index([COMPLETE, OTHER])
    found = {r["doc_number"] for r in search.search(cpc_prefix=prefix, index=index)}
    assert found == expected


def test_a_null_inside_a_classification_list_does_not_become_a_code(build_index):
    index, _ = build_index([without(COMPLETE, classification=["B60B 27/00", None])])
    codes = [row[0] for row in index.con.execute("SELECT code FROM classifications")]
    assert codes == ["B60B2700"]


# --- filing week --------------------------------------------------------------------------------

@pytest.mark.parametrize("file_name, inner, expected", [
    ("patents_ipa240215.json", "US20240051333A1-20240215.XML", "2024-02-15"),
    ("patents_ipa250501.json", "US20250001333A1-20250501.XML", "2025-05-01"),
    ("patents_ipa241226.json", None, "2024-12-26"),
    ("anything.json", "US20240051333A1-20240215.XML", "2024-02-15"),
    ("anything.json", None, None),
    ("patents_ipa241345.json", None, None),  # not a real date
])
def test_filing_week_comes_from_the_file_name(file_name, inner, expected):
    patent = normalize({"doc_number": "X", "filename": inner}, file_name)
    assert patent["filing_week"] == expected
    assert ("filing_week" in patent["missing"]) == (expected is None)


def test_file_name_date_wins_over_a_different_date_inside_filename():
    patent = normalize({"doc_number": "X", "filename": "US1A1-20240222.XML"}, "patents_ipa240215.json")
    assert patent["filing_week"] == "2024-02-15"


# --- uniqueness and repeat ingest ---------------------------------------------------------------

def test_ingesting_the_same_file_twice_creates_no_duplicates(build_index):
    index, first = build_index([COMPLETE, OTHER])
    counts = [index.con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
              for table in ("patents", "passages", "classifications", "patents_fts")]
    vectors = len(index.vectors)
    index2, second = build_index([COMPLETE, OTHER])
    assert first["patents"] == 2 and second.get("patents", 0) == 0 and second["already_indexed"] == 2
    assert counts == [index2.con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in ("patents", "passages", "classifications", "patents_fts")]
    assert len(index2.vectors) == vectors and len(index2.vector_passage) == vectors
    assert len(set(index2.vector_passage.tolist())) == len(index2.vector_passage)  # no passage embedded twice


def test_same_document_number_twice_in_one_file_and_across_files_is_kept_once(build_index, tmp_path):
    index, stats = build_index([COMPLETE, dict(COMPLETE)])
    assert stats["patents"] == 1 and stats["already_indexed"] == 1
    index, stats = build_index([COMPLETE], file_name="patents_ipa240222.json")
    assert stats["already_indexed"] >= 1
    numbers = [row[0] for row in index.con.execute("SELECT doc_number FROM patents")]
    assert numbers == ["D-COMPLETE"]


def test_document_number_as_integer_and_as_padded_string_is_one_patent(build_index):
    index, stats = build_index([without(COMPLETE, doc_number=20240051333), without(COMPLETE, doc_number=" 20240051333 ")])
    assert stats["patents"] == 1 and stats["already_indexed"] == 1


def test_a_new_file_is_added_without_touching_what_is_there(build_index):
    index, _ = build_index([COMPLETE])
    before = index.vectors.copy()
    index, stats = build_index([OTHER], file_name="patents_ipa250102.json")
    assert stats["patents"] == 1
    assert np.array_equal(index.vectors[: len(before)], before) or len(index.vectors) > len(before)
    assert {r["doc_number"] for r in search.search("pneumatic tire tread grooves", index=index)} >= {"D-OTHER"}
    assert index.con.execute("SELECT filing_week FROM patents WHERE doc_number = 'D-OTHER'").fetchone()[0] == "2025-01-02"


def test_interrupted_embedding_is_finished_by_the_next_ingest(build_index, tmp_path, monkeypatch):
    """Rows are committed before vectors are written. If the embedding step dies, a re-run must embed what is pending."""
    data = tmp_path / "data"
    data.mkdir()
    (data / FILE).write_text(json.dumps([COMPLETE, OTHER]), encoding="utf-8")
    monkeypatch.setattr(embed, "embed_pending", lambda con, index_dir=None: (_ for _ in ()).throw(RuntimeError("killed")))
    with pytest.raises(RuntimeError):
        ingest.ingest_dir(str(data), str(tmp_path / "index"))
    monkeypatch.undo()
    from conftest import fake_encode
    monkeypatch.setattr(embed, "encode", fake_encode)
    monkeypatch.setattr(embed, "count_truncated", lambda texts, prefix: 0)
    stats = ingest.ingest_dir(str(data), str(tmp_path / "index"))
    index = search.Index(str(tmp_path / "index"))
    assert stats["already_indexed"] == 2 and len(index.vectors) > 0
    assert {r["doc_number"] for r in search.search("pneumatic tire tread", mode="semantic", index=index)} == {"D-COMPLETE", "D-OTHER"}
