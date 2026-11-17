"""Load patent JSON files into SQLite: normalize fields, split claims, detect language.

Missing field policy: a patent is never dropped. A field with no usable content is
stored as NULL (or as no passages) and listed in `missing_fields`.
"""
import collections
import datetime
import glob
import json
import os
import re

from . import db, embed, translate

# The task sheet and the real files name the fields differently. Accept both.
ALIASES = {
    "document_number": "doc_number",
    "bibtext_citation": "bibtex",
    "bibtex_citation": "bibtex",
    "classification_code": "classification",
    "classification_codes": "classification",
    "description": "detailed_description",
}
# "12 . text", "1 - 5 . text", "3.text". Not "0.5 mm": a digit may not follow the dot.
CLAIM_NUMBER = re.compile(r"\s*(\d{1,3})\s*(?:[-–]\s*(\d{1,3})\s*)?[.．、]\s*(?!\d)(.*)", re.S)
# "1 - 5 . (canceled)", "3 . (canceled)", "1 .- 15 . (canceled)", "1 - 15 : (canceled)", "1 - 9 (canceled)"
CANCELLED = re.compile(r"[\d\s.,:;()\-–]*cancel+ed[\s.)]*", re.I)
CLAIM_REFERENCE = re.compile(
    r"(?:claims?|anspr[uü]ch\w*|权利要求|請求項|请求项|reivindicaci[oó]n(?:es)?|revendications?)\s*(\d+)", re.I)


def _text(value):
    """A usable string, or None when there is no content."""
    if isinstance(value, (list, tuple)):
        value = " ".join(str(v) for v in value if v)
    value = "" if value is None else str(value).strip()
    return value or None


def _items(value):
    """Non-empty strings from a list, or from a newline separated string."""
    if isinstance(value, str):
        value = value.splitlines()
    if not isinstance(value, (list, tuple)):
        return []
    return [s.strip() for s in value if isinstance(s, str) and s.strip()]


def parse_claims(items):
    """Number each claim, drop cancelled ones, and note the parent of dependent claims.

    An item without a number is a claim that lost its number and opening words in the
    source. It gets the previous number plus one, flagged as inferred.
    """
    claims, previous = [], 0
    for raw in items:
        if CANCELLED.fullmatch(raw):
            stated = re.findall(r"\d+", raw)
            previous = int(stated[-1]) if stated else previous + 1  # the numbers are used up
            continue
        match = CLAIM_NUMBER.match(raw)
        if match:
            previous, body, inferred = int(match.group(2) or match.group(1)), match.group(3).strip(), 0
            if not body:
                continue
        else:
            previous, body, inferred = previous + 1, raw.strip(), 1
        reference = CLAIM_REFERENCE.search(body)
        parent = int(reference.group(1)) if reference and int(reference.group(1)) != previous else None
        claims.append({"number": previous, "inferred": inferred, "parent": parent, "text": body})
    return claims


def _filing_week(file_name, inner_filename):
    """ISO date from `patents_ipaYYMMDD.json`, else from `...-YYYYMMDD.XML`, else None."""
    for pattern, prefix, text in ((r"(\d{6})\.json$", "20", file_name), (r"-(\d{8})\.", "", inner_filename or "")):
        found = re.search(pattern, text)
        if found:
            try:
                return datetime.datetime.strptime(prefix + found.group(1), "%Y%m%d").date().isoformat()
            except ValueError:
                pass
    return None


def normalize(raw, file_name):
    """One raw dictionary to the internal shape. Never raises on a missing or odd field."""
    row = {}
    for key, value in raw.items():
        key = re.sub(r"\W+", "_", str(key).strip().lower())
        row[ALIASES.get(key, key)] = value
    codes = row.get("classification")
    if isinstance(codes, str):
        codes = re.split(r"[,;|]", codes)
    if not isinstance(codes, (list, tuple)):
        codes = []
    patent = {
        "doc_number": _text(row.get("doc_number")),
        "title": _text(row.get("title")),
        "abstract": _text(row.get("abstract")),
        "bibtex": _text(row.get("bibtex")),
        "filename": _text(row.get("filename")),
        "claims": parse_claims(_items(row.get("claims"))),
        "description": _items(row.get("detailed_description")),
        "codes": [c for c in (re.sub(r"[^A-Z0-9]", "", str(c).upper()) for c in codes) if c],
        "raw_classification": _text(row.get("classification")),
    }
    patent["filing_week"] = _filing_week(file_name, patent["filename"])
    checks = (("title", patent["title"]), ("doc_number", patent["doc_number"]), ("abstract", patent["abstract"]),
              ("detailed_description", patent["description"]), ("claims", patent["claims"]),
              ("classification", patent["codes"]), ("bibtex", patent["bibtex"]),
              ("filing_week", patent["filing_week"]))
    patent["missing"] = [name for name, value in checks if not value]
    return patent


def insert_patent(con, patent, collection):
    sample = (patent["abstract"] or (patent["claims"][0]["text"] if patent["claims"] else None)
              or " ".join(patent["description"][:3]) or patent["title"])
    language = translate.detect_language(sample)
    title_en, abstract_en = patent["title"], patent["abstract"]
    if language and language != "en":
        # Only these two short fields are translated at ingest, so keyword search works in English.
        title_en = translate.translate(patent["title"], language, con) if patent["title"] else None
        abstract_en = translate.translate(patent["abstract"], language, con) if patent["abstract"] else None
    patent_id = con.execute(
        "INSERT INTO patents (doc_number, collection, title, title_en, abstract, abstract_en, classification,"
        " bibtex, filename, filing_week, language, missing_fields) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (patent["doc_number"], collection, patent["title"], title_en, patent["abstract"], abstract_en,
         patent["raw_classification"] if patent["codes"] else None, patent["bibtex"], patent["filename"],
         patent["filing_week"], language, ",".join(patent["missing"]))).lastrowid
    con.executemany("INSERT INTO classifications VALUES (?,?,?)", [(patent_id, c, c[:4]) for c in patent["codes"]])
    con.execute("INSERT INTO patents_fts (rowid, title_en, abstract_en) VALUES (?,?,?)",
                (patent_id, title_en or "", abstract_en or ""))
    rows = [(patent_id, "abstract", 0, 0, None, patent["abstract"])] if patent["abstract"] else []
    rows += [(patent_id, "claim", c["number"], c["inferred"], c["parent"], c["text"]) for c in patent["claims"]]
    rows += [(patent_id, "description", i + 1, 0, None, text) for i, text in enumerate(patent["description"])]
    con.executemany(
        "INSERT INTO passages (patent_id, kind, ord, number_inferred, parent_claim, text) VALUES (?,?,?,?,?,?)", rows)
    return language


def ingest_dir(data_dir, index_dir=None, collection=None):
    """Ingest every JSON file under `data_dir`, then embed what is new. Safe to run again:
    document numbers already in the index are skipped, and one bad file or record never
    stops the rest."""
    con = db.connect(index_dir)
    collection = collection or os.path.basename(os.path.normpath(data_dir))
    stats = collections.Counter()
    known = {row[0] for row in con.execute("SELECT doc_number FROM patents")}
    for path in sorted(glob.glob(os.path.join(data_dir, "**", "*.json"), recursive=True)):
        try:
            with open(path, encoding="utf-8") as handle:
                rows = json.load(handle)
        except (OSError, ValueError) as error:
            stats["files_failed"] += 1
            print(f"skipped file {path}: {error}")
            continue
        stats["files"] += 1
        for position, raw in enumerate(rows if isinstance(rows, list) else [rows]):
            if not isinstance(raw, dict):
                stats["records_not_a_dictionary"] += 1
                continue
            patent = normalize(raw, os.path.basename(path))
            if not patent["doc_number"]:
                # Keep it findable: a made-up, clearly labelled identifier.
                patent["doc_number"] = f"NO-NUMBER-{os.path.basename(path)}-{position}"
            if patent["doc_number"] in known:
                stats["already_indexed"] += 1
                continue
            known.add(patent["doc_number"])
            language = insert_patent(con, patent, collection)
            stats["patents"] += 1
            stats[f"language_{language or 'unknown'}"] += 1
            for name in patent["missing"]:
                stats[f"missing_{name}"] += 1
            if not (patent["title"] or patent["abstract"] or patent["claims"] or patent["description"]):
                stats["no_searchable_text"] += 1
        con.commit()
    stats.update(embed.embed_pending(con, index_dir))
    con.close()
    return dict(stats)
