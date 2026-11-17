import re

from src.embed import windows
from src.ingest import normalize, parse_claims
from src.translate import detect_language


def numbers(claims):
    return [(c["number"], c["inferred"]) for c in claims]


def test_numbered_dependent_claim_keeps_number_and_parent():
    [claim] = parse_claims(["2 . The spoke according to claim 1 , wherein the hub is steel"])
    assert (claim["number"], claim["inferred"], claim["parent"]) == (2, 0, 1)
    assert claim["text"].startswith("The spoke")


def test_unnumbered_claim_is_previous_number_plus_one():
    claims = parse_claims(["an axle body", "2 . The spoke of claim 1", "a rim and a tire", "4 . The wheel of claim 3"])
    assert numbers(claims) == [(1, 1), (2, 0), (3, 1), (4, 0)]


def test_cancelled_range_is_dropped_but_uses_up_its_numbers():
    claims = parse_claims(["1 - 5 . (canceled)", "a body on the rim", "7 . The body of claim 6"])
    assert numbers(claims) == [(6, 1), (7, 0)]


def test_every_cancelled_format_in_the_data_is_dropped():
    for raw in ("1 - 5 . (canceled)", "3 . (canceled)", "1 .- 15 . (canceled)", "1 - 15 : (canceled)",
                "1 - 9 (canceled)", "(cancelled)"):
        claims = parse_claims([raw, "a rim with a flange and a bead seat"])
        assert len(claims) == 1 and claims[0]["number"] == int((re.findall(r"\d+", raw) or [1])[-1]) + 1


def test_decimal_at_the_start_is_not_a_claim_number():
    [claim] = parse_claims(["0.5 mm to 1.5 mm thick rubber layer"])
    assert numbers([claim]) == [(1, 1)] and claim["text"].startswith("0.5 mm")


def test_parent_claim_is_found_in_german_and_chinese():
    assert parse_claims(["2 . Die Speiche nach Anspruch 1"])[0]["parent"] == 1
    assert parse_claims(["2. 根据权利要求1所述的辐条"])[0]["parent"] == 1


def test_empty_content_counts_as_missing():
    p = normalize({"title": "  ", "doc_number": "X1", "detailed_description": [""], "claims": []},
                  "patents_ipa240215.json")
    assert p["title"] is None and p["description"] == [] and p["claims"] == []
    assert set(p["missing"]) == {"title", "abstract", "detailed_description", "claims", "classification", "bibtex"}
    assert p["filing_week"] == "2024-02-15"


def test_field_names_from_the_task_sheet_are_accepted():
    p = normalize({"Title": "Wheel", "Document Number": 123, "Classification Code": "B60B 1/04",
                   "Claims": "1. A wheel.\n2. The wheel of claim 1.", "Detailed Description": "One.\n\nTwo."},
                  "anything.json")
    assert p["doc_number"] == "123" and p["codes"] == ["B60B104"]
    assert numbers(p["claims"]) == [(1, 0), (2, 0)] and p["description"] == ["One.", "Two."]


def test_filing_week_falls_back_to_the_filename_field_then_to_missing():
    assert normalize({"filename": "US20240051333A1-20240215.XML"}, "foreign.json")["filing_week"] == "2024-02-15"
    p = normalize({"title": "T"}, "foreign.json")
    assert p["filing_week"] is None and "filing_week" in p["missing"]


def test_windows_cut_at_boundaries_and_lose_nothing():
    text = "First sentence here. " * 30
    pieces = windows(text, 100)
    assert all(len(piece) <= 100 for piece in pieces)
    assert all(piece.endswith(".") for piece in pieces)
    assert " ".join(pieces) == text.strip()


def test_language_detection_refuses_short_text():
    assert detect_language("A-B-C (I)") is None
    assert detect_language("The tire has a tread portion and two sidewall portions joined by a carcass.") == "en"
    assert detect_language("Der Reifen hat einen Laufstreifen und zwei Seitenwände, die durch eine Karkasse verbunden sind.") == "de"
    assert detect_language("一种充气轮胎，包括胎面部和一对胎侧部。") == "zh"
