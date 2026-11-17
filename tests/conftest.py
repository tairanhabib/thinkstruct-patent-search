"""Test fixtures. The embedding and translation models are replaced by small fakes so
the tests run offline in a second. The fake embedding is a hashed bag of words: texts
that share words get similar vectors, which is all these tests need."""
import json
import re
import zlib

import numpy as np
import pytest

from src import embed, ingest, search, translate

# A complete synthetic patent. Tests delete fields from copies of it.
COMPLETE = {
    "title": "Wheel hub with pressure sensor",
    "doc_number": "D-COMPLETE",
    "filename": "US0000001A1-20240215.XML",
    "abstract": "A wheel hub carrying a tire pressure sensor that reports the inflation state to the driver.",
    "detailed_description": ["The hub has a bore that holds the pressure sensor and its battery firmly in place.",
                             "", "FIG. 1"],
    "claims": ["a hub body with a bore and a tire pressure sensor mounted inside the bore",
               "2 . The hub of claim 1 , wherein the pressure sensor is powered by a battery"],
    "bibtex": "@patent{D-COMPLETE}",
    "classification": "B60B2700FI",
}
OTHER = {
    "title": "Pneumatic tire tread",
    "doc_number": "D-OTHER",
    "filename": "US0000002A1-20240222.XML",
    "abstract": "A pneumatic tire with a tread pattern of circumferential grooves that drain water quickly.",
    "detailed_description": ["The tread has four circumferential grooves and sipes cut across every rib of rubber."],
    "claims": ["1 . A pneumatic tire comprising a tread with circumferential grooves and sipes"],
    "bibtex": "@patent{D-OTHER}",
    "classification": "B60C1103FI",
}


def fake_encode(texts, prefix):
    vectors = np.zeros((len(texts), 64), np.float32)
    for row, text in enumerate(texts):
        for word in re.findall(r"\w+", text.lower()):
            vectors[row, zlib.crc32(word.encode()) % 64] += 1
        vectors[row, 0] += 1e-3  # never a zero vector
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


@pytest.fixture(autouse=True)
def offline_models(monkeypatch):
    monkeypatch.setattr(embed, "encode", fake_encode)
    monkeypatch.setattr(embed, "count_truncated", lambda texts, prefix: 0)
    monkeypatch.setattr(translate, "translate_texts",
                        lambda texts, source, target="en", beams=4: [f"[{source} to {target}] {text}" for text in texts])


@pytest.fixture
def build_index(tmp_path):
    """build_index(records) ingests them and returns (Index, ingest statistics)."""
    def build(records, file_name="patents_ipa240215.json"):
        data_dir = tmp_path / "data"
        data_dir.mkdir(exist_ok=True)
        (data_dir / file_name).write_text(json.dumps(records), encoding="utf-8")
        stats = ingest.ingest_dir(str(data_dir), str(tmp_path / "index"))
        return search.Index(str(tmp_path / "index")), stats
    return build


def without(record, *fields, **changes):
    """Copy of a record with some fields removed and others replaced."""
    copy = {key: value for key, value in record.items() if key not in fields}
    copy.update(changes)
    return copy
