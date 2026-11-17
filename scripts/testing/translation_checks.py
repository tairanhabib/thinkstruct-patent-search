"""Independent test pass, Stage 6: translation and display. Needs the index with the German and Chinese copies.

    python scripts/testing/translation_checks.py --index COPY_OF_INDEX_WITH_840 --out scripts/testing/results/translation.json

Point --index at a copy: display translations are written to its cache.
"""
import argparse
import glob
import json
import os
import random
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cli  # noqa: E402
from src import translate  # noqa: E402
from src.search import Index, query_language, search  # noqa: E402

SEED = 42
CJK = re.compile(r"[぀-ヿ一-鿿가-힯]")
UMLAUT_WORDS = re.compile(r"\b(der|die|das|und|nach|mit|eine[rnms]?|wobei|gemäß|zwischen|für|wird|ist)\b", re.I)
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
UNIT = re.compile(r"(?<![A-Za-z])(mm|cm|kPa|MPa|GPa|kg|km/h|rpm|phr|°C|°|%|Hz|N/mm|nm|μm|dtex)(?![A-Za-z])")
TERMS = ("rim", "bead", "tread", "hub", "spoke", "sidewall", "carcass", "sipe", "belt", "groove")


def looks_english(text):
    """No East Asian characters, and the detector (when it has enough text to say) agrees it is English."""
    if CJK.search(text):
        return False
    detected = translate.detect_language(text)
    return detected in (None, "en")


def display(index, out):
    """Every non-English result shows an English title, abstract and matching passage; the original is labelled and retrievable."""
    rows = index.con.execute("SELECT doc_number, language, title, title_en, abstract, abstract_en FROM patents WHERE language != 'en'").fetchall()
    stored = {"foreign_patents": len(rows), "no_english_title": 0, "no_english_abstract": 0, "title_not_english": [], "abstract_not_english": [],
              "title_same_as_original": 0, "abstract_stuck_repeating": 0, "title_stuck_repeating": 0}
    for row in rows:
        stored["no_english_title"] += not row["title_en"]
        stored["no_english_abstract"] += not row["abstract_en"]
        if row["title_en"] and not looks_english(row["title_en"]):
            stored["title_not_english"].append(row["doc_number"])
        if row["abstract_en"] and not looks_english(row["abstract_en"]):
            stored["abstract_not_english"].append(row["doc_number"])
        stored["title_same_as_original"] += row["title_en"] == row["title"]
        stored["abstract_stuck_repeating"] += bool(row["abstract_en"] and translate.looping(row["abstract_en"]))
        stored["title_stuck_repeating"] += bool(row["title_en"] and translate.looping(row["title_en"]))
    out["stored_english_title_and_abstract"] = stored

    queries = [q["text"] for q in json.load(open(os.path.join(ROOT, "scripts/testing/forward_queries.json"), encoding="utf-8"))["queries"]
               if q["category"] in ("general", "specific")]
    shown = {"results_checked": 0, "passage_not_translated": 0, "passage_not_english": [], "passage_stuck_repeating": [], "label_missing": 0,
             "original_missing_with_show_original": 0, "title_unknown_or_foreign": 0, "evidence_kinds": {}}
    for language in ("de", "zh"):
        for query in queries:
            results = search(query, language=language, top_k=5, index=index)
            text = cli.format_results(results, show_original=True)
            for r in results:
                shown["results_checked"] += 1
                passage = r["passage"]
                shown["evidence_kinds"][passage["kind"]] = shown["evidence_kinds"].get(passage["kind"], 0) + 1
                shown["passage_not_translated"] += not passage["translated"] or passage["text_en"] == passage["text"]
                if not looks_english(passage["text_en"]):
                    shown["passage_not_english"].append([r["doc_number"], passage["text_en"][:120]])
                if translate.looping(passage["text_en"]):
                    shown["passage_stuck_repeating"].append([r["doc_number"], passage["text_en"][:120]])
                shown["label_missing"] += f"{r['doc_number']} | {r['title_en']}  [translated from {language}]" not in text
                shown["original_missing_with_show_original"] += passage["text"][:40] not in re.sub(r"\s+", " ", text.replace("\n        ", " "))
                shown["title_unknown_or_foreign"] += not r["title_en"] or not looks_english(r["title_en"])
    out["displayed_results"] = shown
    # `show` on one patent per language: title, abstract and claims in English, original one flag away
    out["show"] = {}
    for language in ("de", "zh"):
        doc = index.con.execute("SELECT doc_number FROM patents WHERE language = ? ORDER BY doc_number LIMIT 1", (language,)).fetchone()[0]
        plain, both = cli.format_patent(index, doc), cli.format_patent(index, doc, show_original=True)
        out["show"][language] = {"doc": doc, "says_machine_translated": "shown in English, machine translated" in plain,
                                 "east_asian_characters_in_plain_output": len(CJK.findall(plain)),
                                 "original_lines_with_flag": both.count("original:"), "abstract_line": plain.split("Abstract:\n")[1][:160]}


def detection(index, out):
    rng = random.Random(SEED)
    result = {}
    for language in ("en", "de", "zh"):
        texts = [row[0] for row in index.con.execute(
            "SELECT s.text FROM passages s JOIN patents p ON p.id = s.patent_id WHERE p.language = ? AND length(s.text) >= 40 ORDER BY s.id", (language,))]
        picked = rng.sample(texts, 20)
        got = [translate.detect_language(text) for text in picked]
        result[f"20 {language} passages (40 characters or more)"] = {"correct": sum(g == language for g in got), "of": 20,
                                                                     "wrong": [[g, t[:60]] for g, t in zip(got, picked) if g != language]}
    queries = json.load(open(os.path.join(ROOT, "scripts/testing/forward_queries.json"), encoding="utf-8"))["queries"]
    for language in ("en", "de", "es", "zh", "ja"):
        texts = [q["text"] if language == "en" else q["translations"][language] for q in queries if "translations" in q]
        as_passage = [translate.detect_language(t) for t in texts]
        as_query = [query_language(t) for t in texts]
        result[f"10 {language} queries, passage rule (20 letters, 0.7)"] = {"correct": sum(g == language for g in as_passage), "of": 10, "got": as_passage}
        result[f"10 {language} queries, query rule (40 letters, 0.9)"] = {"correct": sum(g == language for g in as_query), "of": 10, "got": as_query}
    short = [row[0] for row in index.con.execute(
        "SELECT s.text FROM passages s JOIN patents p ON p.id = s.patent_id WHERE p.language = 'en' AND length(s.text) < 40 ORDER BY s.id")]
    picked = rng.sample(short, 40)
    got = [translate.detect_language(t) for t in picked]
    result["40 short English fragments (under 40 characters)"] = {"none": sum(g is None for g in got), "en": sum(g == "en" for g in got),
                                                                 "foreign": [[g, t] for g, t in zip(got, picked) if g not in (None, "en")]}
    synthetic = ["1.1≤b/C≤1.4 (1)", "0.05 ≤ tan δ ≤ 0.20", "12345 67890 2024", "FIG. 3", "A-B-C (I)", "SiO2 + C → Si + CO2", "Wr/Pw = 0.30",
                 "100 phr", "(25) (26) (27)", "", "   ", "θ1 < θ2 < θ3", "TIRE", "B60C 11/03", "…"]
    got = [translate.detect_language(t) for t in synthetic]
    result["15 numeric, formula and empty strings"] = {"none": sum(g is None for g in got), "detected": [[g, t] for g, t in zip(got, synthetic) if g]}
    # English text taken for a foreign language, at the three places the code detects language
    abstracts = [row[0] for row in index.con.execute("SELECT abstract FROM patents WHERE collection = 'small'")]
    first_claims = [row[0] for row in index.con.execute(
        "SELECT s.text FROM passages s JOIN patents p ON p.id = s.patent_id WHERE p.collection = 'small' AND s.kind = 'claim' GROUP BY p.id HAVING s.ord = MIN(s.ord)")]
    titles = [row[0] for row in index.con.execute("SELECT title FROM patents WHERE collection = 'small'")]
    passages = rng.sample([row[0] for row in index.con.execute(
        "SELECT s.text FROM passages s JOIN patents p ON p.id = s.patent_id WHERE p.collection = 'small' AND length(s.text) >= 40 ORDER BY s.id")], 2000)
    for name, texts in (("640 English abstracts (what ingest reads first)", abstracts), ("640 English first claims (ingest fallback)", first_claims),
                        ("640 English titles (last fallback)", titles), ("2,000 English passages", passages)):
        got = [translate.detect_language(t) for t in texts]
        result[f"{name}: taken for a foreign language"] = {"foreign": sum(g not in (None, "en") for g in got), "unknown": sum(g is None for g in got),
                                                           "of": len(texts), "examples": [[g, t[:70]] for g, t in zip(got, texts) if g not in (None, "en")][:8]}
    benchmark_like = [q["text"] for q in queries]
    got = [query_language(t) for t in benchmark_like]
    result["30 English forward queries, query rule"] = {"en": sum(g == "en" for g in got), "other": [[g, t] for g, t in zip(got, benchmark_like) if g != "en"]}
    out["language_detection"] = result


def cache(index, out):
    translate.translate_texts(["热身"], "zh", "en")  # load the model outside the timing
    rows = index.con.execute("SELECT s.text FROM passages s JOIN patents p ON p.id = s.patent_id WHERE p.language = 'zh' AND s.kind = 'description' "
                             "AND length(s.text) BETWEEN 150 AND 250 ORDER BY s.id DESC").fetchall()
    timings = []
    for (text,) in rows:
        key_free = text + " "  # never asked for before in this exact form, so the first call cannot be a hit
        start = time.perf_counter()
        first = translate.translate(key_free, "zh", index.con)
        middle = time.perf_counter()
        second = translate.translate(key_free, "zh", index.con)
        end = time.perf_counter()
        timings.append([round((middle - start) * 1000, 1), round((end - middle) * 1000, 3), first == second])
        if len(timings) == 10:
            break
    firsts, seconds = sorted(t[0] for t in timings), sorted(t[1] for t in timings)
    out["translation_cache"] = {"passages": len(timings), "first_request_ms_median": firsts[len(firsts) // 2], "first_request_ms_range": [firsts[0], firsts[-1]],
                                "second_request_ms_median": seconds[len(seconds) // 2], "second_request_ms_range": [seconds[0], seconds[-1]],
                                "same_text_both_times": all(t[2] for t in timings)}


def round_trip(index, out):
    rng = random.Random(SEED)
    rows = [row[0] for row in index.con.execute(
        "SELECT s.text FROM passages s JOIN patents p ON p.id = s.patent_id WHERE p.collection = 'small' AND s.kind != 'abstract' "
        "AND length(s.text) BETWEEN 150 AND 320 ORDER BY s.id")]
    picked = []
    for term in TERMS:  # one passage per term, so each of the usual trouble words is covered once
        pool = [t for t in rows if re.search(rf"\b{term}\b", t, re.I) and t not in picked]
        picked.append(rng.choice(pool))
    trips = []
    for text in picked:
        entry = {"original": text}
        for language in ("de", "zh"):
            there = translate.translate_texts([text], "en", language, beams=1)[0]   # as the query and the test set are translated
            back = translate.translate_texts([there], language, "en", beams=4)[0]    # as a result is displayed
            entry[language], entry[f"{language}_back"] = there, back
            entry[f"{language}_terms_lost"] = [t for t in TERMS if re.search(rf"\b{t}s?\b", text, re.I) and not re.search(rf"\b{t}s?\b", back, re.I)]
            entry[f"{language}_numbers_kept"] = sorted(NUMBER.findall(text)) == sorted(NUMBER.findall(back))
        trips.append(entry)
    out["round_trip"] = trips


def numbers(index, out):
    """Numbers, reference numerals and units: English original against its machine-made copy (the test set), and a
    foreign passage against the English shown to the user."""
    originals = {p["doc_number"]: p for f in glob.glob(os.path.join(ROOT, "data/small/*.json")) for p in json.load(open(f, encoding="utf-8"))}
    result = {}
    for language in ("de", "zh"):
        pairs = []
        for path in glob.glob(os.path.join(ROOT, f"data/parallel/{language}/*.json")):
            for copy in json.load(open(path, encoding="utf-8")):
                source = originals[copy["doc_number"].rsplit("-", 1)[0]]
                for field in ("claims", "detailed_description"):
                    pairs += [(a, b) for a, b in zip(source[field], copy[field]) if len(a.strip()) >= 40 and a != b]
        same = sum(sorted(NUMBER.findall(a)) == sorted(NUMBER.findall(b)) for a, b in pairs)
        with_units = [(a, b) for a, b in pairs if UNIT.search(a)]
        units_same = sum(sorted(UNIT.findall(a)) == sorted(UNIT.findall(b)) for a, b in with_units)
        bad = [(a, b) for a, b in pairs if sorted(NUMBER.findall(a)) != sorted(NUMBER.findall(b))]
        random.Random(SEED).shuffle(bad)
        result[f"English to {language} (the test set, all translated passages)"] = {
            "passages": len(pairs), "numbers_identical": same, "share": round(same / len(pairs), 4),
            "passages_with_units": len(with_units), "units_identical": units_same,
            "examples_of_changed_numbers": [{"en": a[:160], language: b[:160], "en_numbers": NUMBER.findall(a)[:12], f"{language}_numbers": NUMBER.findall(b)[:12]} for a, b in bad[:3]]}
        rows = [row[0] for row in index.con.execute(
            "SELECT s.text FROM passages s JOIN patents p ON p.id = s.patent_id WHERE p.language = ? AND length(s.text) BETWEEN 100 AND 400 "
            "AND s.text GLOB '*[0-9]*' ORDER BY s.id", (language,))]
        picked = random.Random(SEED).sample(rows, 100)
        shown = translate.translate_many(picked, language, index.con)
        same = sum(sorted(NUMBER.findall(a)) == sorted(NUMBER.findall(b)) for a, b in zip(picked, shown))
        bad = [(a, b) for a, b in zip(picked, shown) if sorted(NUMBER.findall(a)) != sorted(NUMBER.findall(b))]
        result[f"{language} to English (what is displayed, 100 passages with a number)"] = {
            "numbers_identical": same, "of": 100, "stuck_repeating": sum(translate.looping(b) for b in shown),
            "examples_of_changed_numbers": [{language: a[:160], "en": b[:160]} for a, b in bad[:3]]}
    out["numbers_and_units"] = result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args()
    index, out = Index(args.index), {}
    for step in (display, detection, cache, round_trip, numbers):
        if not args.only or step.__name__ in args.only:
            print("==", step.__name__, flush=True)
            step(index, out)
            json.dump(out, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote", args.out)
