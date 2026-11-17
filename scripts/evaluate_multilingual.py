"""Does search work as well on foreign patents as on English ones? Writes eval_results.md.

Usage: python scripts/evaluate_multilingual.py [--index index]

Needs the parallel set in the index (scripts/make_parallel_set.py, then
`python cli.py ingest data/parallel`). The same inventions then exist in English, German
and Chinese.

Main test: for each of those patents, take its first claim in English and search for it.
The claims themselves are not candidates, so the right answer is the same patent's
abstract or description. A patent counts as found at the rank where it appears.

Three ways of handling languages are compared:
- shared: one query vector for every language (the original plan).
- uncalibrated: the query is translated into each language and each passage is scored
  against the query in its own language; the raw scores are merged.
- translate_query: the same, with each language's scores put on one scale before merging
  (what the search does by default).

Finding a foreign patent is only half of "comparable". The other half is not letting
foreign patents push out better English ones. Sections 3 and 4 cover that half.
"""
import argparse
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from benchmark import QUERIES as SHORT_QUERIES  # noqa: E402
from src import embed, translate  # noqa: E402
from src.search import QUERY_BEAMS, Index, query_language, search  # noqa: E402

NAMES = {"en": "English", "de": "German", "zh": "Chinese"}
METHODS = (
    ("keyword", "shared", "keyword only"),
    ("semantic", "shared", "semantic, shared space"),
    ("semantic", "uncalibrated", "semantic, query translated, raw scores"),
    ("semantic", "translate_query", "semantic, query translated, calibrated"),
    ("hybrid", "shared", "hybrid, shared space"),
    ("hybrid", "uncalibrated", "hybrid, query translated, raw scores"),
    ("hybrid", "translate_query", "hybrid, query translated, calibrated (default)"),
)
ONE_LANGUAGE = [m for m in METHODS if m[1] != "uncalibrated"]  # with one language in play, calibration changes nothing


def first_claim(index, doc_number):
    row = index.con.execute(
        "SELECT s.text FROM passages s JOIN patents p ON p.id = s.patent_id "
        "WHERE p.doc_number = ? AND s.kind = 'claim' ORDER BY s.ord LIMIT 1", (doc_number,)).fetchone()
    return row[0] if row else None


def reciprocal_ranks(index, queries, targets, candidates, mode, method, timings=None, ignore=None):
    """1 / rank of the target patent for each query (0 when it is not returned at all).
    `ignore[i]` is a patent that is neither right nor wrong for query i and is left out of the count."""
    out = []
    for position, (query, target) in enumerate(zip(queries, targets)):
        info = {}
        # Keyword search reads only title and abstract, so it needs no passage type to keep the claims out.
        results = search(query, mode=mode, cross_lingual=method,
                         passage_types=None if mode == "keyword" else ["abstract", "description"],
                         restrict_docs=candidates, top_k=len(candidates), translate_results=False, index=index, info=info)
        ranked = [r["doc_number"] for r in results if ignore is None or r["doc_number"] != ignore[position]]
        out.append(1.0 / (ranked.index(target) + 1) if target in ranked else 0.0)
        if timings is not None:
            timings.append(info["ms"]["translate_query"])
    return np.array(out)


def summarize(rr):
    return {"recall@1": float((rr == 1).mean()), "recall@10": float((rr >= 0.1).mean()), "mrr": float(rr.mean())}


def gap_interval(rr, baseline, rounds=2000):
    """95% paired bootstrap interval for the difference in mean reciprocal rank (this row minus the baseline row)."""
    rng = np.random.default_rng(0)
    difference = rr - baseline
    samples = rng.choice(difference, (rounds, len(difference))).mean(axis=1)
    return float(np.percentile(samples, 2.5)), float(np.percentile(samples, 97.5))


def row(label, name, rr, baseline):
    s = summarize(rr)
    gap = "" if baseline is None else f"{s['mrr'] - baseline.mean():+.3f}"
    interval = "" if baseline is None else "{:+.3f} to {:+.3f}".format(*gap_interval(rr, baseline))
    return f"| {label} | {name} | {s['recall@1']:.2f} | {s['recall@10']:.2f} | {s['mrr']:.3f} | {gap} | {interval} |"


def abstract_vectors(index, docs):
    out = []
    for doc in docs:
        passage = index.con.execute("SELECT s.id FROM passages s JOIN patents p ON p.id = s.patent_id "
                                    "WHERE p.doc_number = ? AND s.kind = 'abstract'", (doc,)).fetchone()[0]
        vector = index.vectors[index.vector_passage == passage].mean(axis=0)
        out.append(vector / np.linalg.norm(vector))
    return np.array(out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--index")
    parser.add_argument("--out", default="eval_results.md")
    args = parser.parse_args()
    index = Index(args.index)

    copies = {}  # language -> {original document number: copy document number}
    for doc in index.patent_ids:
        base, _, suffix = doc.rpartition("-")
        if suffix in ("DE", "ZH") and base in index.patent_ids:
            copies.setdefault(suffix.lower(), {})[base] = doc
    if not copies:
        raise SystemExit("no parallel set in the index: run scripts/make_parallel_set.py and ingest data/parallel first")
    originals = sorted(set.intersection(*(set(c) for c in copies.values())))
    copies["en"] = {doc: doc for doc in originals}
    languages = ["en"] + sorted(k for k in copies if k != "en")
    all_copies = {copy for by_original in copies.values() for copy in by_original.values()}
    distractors = [doc for doc in index.patent_ids if doc not in all_copies]  # the other English patents
    queries = [first_claim(index, doc) for doc in originals]

    out = ["# Multilingual evaluation\n",
           "Generated by `python scripts/evaluate_multilingual.py`.\n",
           f"- {len(originals)} patents exist in English (original), German and Chinese (machine translated copies made by "
           "`scripts/make_parallel_set.py` with opus-mt, greedy decoding).",
           "- Query: the first claim of each patent, in English, as stored (not the title, not the abstract).",
           "- Candidates: abstracts and description paragraphs only. Claims are excluded, so a patent cannot be found through the query text itself.",
           f"- Embedding model: `{embed.MODEL_NAME}`. Recall at k is the share of queries whose patent is in the top k. MRR is mean reciprocal rank.",
           "- The interval is a 95% paired bootstrap interval on the difference in MRR against the first row of the same method.",
           "- \"Shared space\": one query vector for all languages. \"Query translated, raw scores\": each passage is scored against "
           "the query translated into its language, and raw scores are merged. \"Calibrated\": the same, with each language's "
           "scores put on one scale first (the default in `search()`).\n",
           "**Two things to keep in mind when reading the German and Chinese rows.** The copies were produced by the same opus-mt "
           "models that then translate the query, so query and document share wording more than they would with real foreign "
           "patents. And finding the right patent is only half the job: sections 3 and 4 measure whether foreign patents push out "
           "English ones, which is where the raw scores fail.\n"]

    # What one query costs when nothing is cached: 10 queries, one at a time, sent straight to the models
    # (never through the cache, so this is the same on a first run and on a repeat run).
    uncached, cached = [], []
    for language in index.languages:
        translate.translate_texts(["warm up"], "en", language, beams=QUERY_BEAMS)  # model loading is not part of the number
    for query in queries[:10]:
        start = time.perf_counter()
        for language in index.languages:
            translate.translate_texts([query], "en", language, beams=QUERY_BEAMS)
        uncached.append((time.perf_counter() - start) * 1000)
    # Then every query in bulk, so the searches below are cache hits. Same texts, same cache keys.
    start, before = time.perf_counter(), translate.usage["characters"]
    for language in index.languages:
        translate.translate_many(queries, "en", index.con, target=language, beams=QUERY_BEAMS)
        foreign = [first_claim(index, copies[language][doc]) for doc in originals] if language in copies else []
        translate.translate_many(foreign, language, index.con, beams=QUERY_BEAMS)
    bulk = (translate.usage["characters"] - before, time.perf_counter() - start)
    print(f"bulk query translation: {bulk[0]:,} characters in {bulk[1]:.0f} s", flush=True)

    header = ["| Method | Target language | Recall at 1 | Recall at 10 | MRR | Gap to English (MRR) | 95% interval |",
              "| --- | --- | --- | --- | --- | --- | --- |"]

    # 1. each language on its own
    out += ["## 1. Alone: can the right patent be found within one language?\n",
            f"Candidates are only the {len(originals)} test patents in one language. With one language in play there is nothing "
            "to calibrate, so the raw and calibrated rows would be identical and only one is shown.\n"] + header
    for mode, method, label in ONE_LANGUAGE:
        baseline = None
        for language in languages:
            rr = reciprocal_ranks(index, queries, [copies[language][doc] for doc in originals],
                                  list(copies[language].values()), mode, method, None if method == "shared" else cached)
            out.append(row(label.replace(", calibrated", ""), NAMES[language], rr, baseline))
            baseline = rr if baseline is None else baseline
            print("alone", out[-1], flush=True)

    # 2. a foreign target among English distractors
    english_baseline = {}
    out += ["\n## 2. Mixed: is a foreign patent found among English ones?\n",
            f"Candidates are the {len(originals)} test patents in one language plus the {len(distractors)} other English patents. "
            "This rewards any method that scores foreign patents high, deserved or not, so read it together with section 3.\n"] + header
    for mode, method, label in METHODS:
        baseline = None
        for language in languages:
            rr = reciprocal_ranks(index, queries, [copies[language][doc] for doc in originals],
                                  list(copies[language].values()) + distractors, mode, method,
                                  None if method == "shared" else cached)
            out.append(row(label, NAMES[language], rr, baseline))
            baseline = rr if baseline is None else baseline
            print("mixed", out[-1], flush=True)
        english_baseline[(mode, method)] = baseline

    # 3. an English target with foreign patents added to the corpus
    out += ["\n## 3. Does adding foreign patents hurt English search?\n",
            f"The target is the English original. Candidates are all {len(originals) + len(distractors)} English patents plus the "
            f"{len(originals)} copies in one foreign language. The target's own copy is left out of the count (it is the same "
            "invention, so it is not a wrong answer). The other 99 copies are wrong answers. A fair method loses nothing here.\n",
            "| Method | Foreign patents added | Recall at 1 | Recall at 10 | MRR | Change (MRR) | 95% interval |",
            "| --- | --- | --- | --- | --- | --- | --- |"]
    for mode, method, label in METHODS[1:]:
        baseline = english_baseline[(mode, method)]
        out.append(row(label, "none", baseline, None))
        for language in languages[1:]:
            rr = reciprocal_ranks(index, queries, originals, originals + distractors + list(copies[language].values()),
                                  mode, method, ignore=[copies[language][doc] for doc in originals])
            out.append(row(label, NAMES[language], rr, baseline))
            print("added", out[-1], flush=True)

    # 4. short queries: do the three versions of the same patents come back in equal numbers?
    groups = {language: set(copies[language].values()) for language in languages}
    out += ["\n## 4. Short queries: are the languages treated alike?\n",
            f"The {len(SHORT_QUERIES)} short English queries of the benchmark, top 10 results each, over all "
            f"{len(index.patent_ids)} patents. Each of the {len(originals)} test patents is in the index once per language with "
            "the same content, so a fair method returns its versions in roughly equal numbers. "
            f"Counts are out of {10 * len(SHORT_QUERIES)} result slots.\n",
            "| Method | " + " | ".join(f"{NAMES[language]} versions of the test patents" for language in languages)
            + " | Other English patents |",
            "| --- |" + " --- |" * (len(languages) + 1)]
    for mode, method, label in METHODS[1:]:
        counts = dict.fromkeys(languages + ["other"], 0)
        for query in SHORT_QUERIES:
            for result in search(query, mode=mode, cross_lingual=method, top_k=10, translate_results=False, index=index):
                counts[next((name for name, docs in groups.items() if result["doc_number"] in docs), "other")] += 1
        out.append(f"| {label} | " + " | ".join(str(counts[name]) for name in languages + ["other"]) + " |")
        print("short", out[-1], flush=True)

    # 5. the other direction: a foreign query against the original English patents
    english_pool = originals + distractors
    out += ["\n## 5. Foreign query, English patents\n",
            f"The query is the first claim of the translated copy. Candidates are all {len(english_pool)} original English "
            "patents (abstract and description), so calibration plays no part. With \"query translated\" the query language is "
            "detected, the query is translated to English by a different model than the one that made the copies, and it must "
            "match the original human-written English. It is still a round trip: the query is a machine translation of a claim "
            "of the very patent it is looking for.\n",
            "| Method | Query language | Recall at 1 | Recall at 10 | MRR | Gap to English (MRR) | 95% interval | Query language detected |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for mode, method, label in ONE_LANGUAGE[1:]:
        baseline = None
        for language in languages:
            foreign_queries = [first_claim(index, copies[language][doc]) for doc in originals]
            rr = reciprocal_ranks(index, foreign_queries, originals, english_pool, mode, method)
            detected = sum(query_language(q) == language for q in foreign_queries)
            out.append(row(label.replace(", calibrated", ""), NAMES[language], rr, baseline) + f" {detected} of {len(foreign_queries)} |")
            baseline = rr if baseline is None else baseline
            print("foreign query", out[-1], flush=True)

    out += ["\n## What query translation costs per query\n",
            f"Translating one claim-length query (median {int(np.median([len(q) for q in queries]))} characters) into "
            f"{len(index.languages)} languages ({', '.join(index.languages)}) with greedy decoding:\n",
            "| | Median | Slowest |", "| --- | --- | --- |",
            f"| Not cached, models already loaded (10 queries, one at a time) | {np.median(uncached):.0f} ms | {max(uncached):.0f} ms |",
            f"| Cache hit: the translation step inside `search()` in the tables above | {np.median(cached):.2f} ms | {max(cached):.2f} ms |",
            ("\nAll queries were translated in bulk before the tables above were computed: "
             + (f"{bulk[0]:,} characters in {bulk[1]:.0f} s ({bulk[0] / bulk[1]:,.0f} characters per second)." if bulk[0]
                else "they were already in the cache from an earlier run, so no bulk rate was measured this time."))]

    # why the shared space fails
    english = abstract_vectors(index, originals)
    others = abstract_vectors(index, distractors)
    out += ["\n## Why the shared space fails: language bias\n",
            "Cosine similarity between abstracts. If the space were truly shared, a patent and its own translation would be "
            "closer than two different patents.\n",
            "| Pair | Mean similarity | 99th percentile |", "| --- | --- | --- |"]
    between = english @ others.T
    out.append(f"| English abstract and a different English patent's abstract | {between.mean():.3f} | {np.percentile(between, 99):.3f} |")
    for language in languages[1:]:
        own = np.sum(english * abstract_vectors(index, [copies[language][doc] for doc in originals]), axis=1)
        out.append(f"| English abstract and the same patent in {NAMES[language]} | {own.mean():.3f} | {np.percentile(own, 99):.3f} |")
        out.append(f"| Share of different English abstracts that score above the patent's own {NAMES[language]} copy "
                   f"| {(between > own[:, None]).mean():.1%} | |")

    # why raw scores cannot be merged
    levels = np.zeros((2, len(index.languages) + 1))
    for group, texts in enumerate((SHORT_QUERIES, queries)):
        for text in texts:
            versions = [text] + [translate.translate(text, "en", index.con, target=language, beams=QUERY_BEAMS)
                                 for language in index.languages]
            levels[group] += index.calibration(embed.encode(versions, "query: "))[0] / len(texts)
    out += ["\n## Why raw scores cannot be merged: each language has its own score level\n",
            "Mean similarity between a query and a fixed random sample of passages in the same language, almost all of them "
            "unrelated to the query. This is the level a passage has to rise above. Calibration subtracts it and divides by "
            "the spread.\n",
            "| Queries | " + " | ".join(NAMES.get(language, language) for language in ["en"] + index.languages) + " |",
            "| --- |" + " --- |" * (len(index.languages) + 1),
            "| Short queries | " + " | ".join(f"{value:.3f}" for value in levels[0]) + " |",
            "| Claim-length queries | " + " | ".join(f"{value:.3f}" for value in levels[1]) + " |"]

    out += ["\n## Diagnostics\n",
            "| Language | Patents | Detected as that language | Vectors | Vectors longer than the model input (512 tokens) "
            "| Passages where the translation got stuck repeating itself |",
            "| --- | --- | --- | --- | --- | --- |"]
    tokenizer = embed.model().tokenizer
    for language in languages:
        docs = list(copies[language].values())
        marks = ",".join("?" * len(docs))
        detected = index.con.execute(f"SELECT COUNT(*) FROM patents WHERE language = ? AND doc_number IN ({marks})",
                                     [language] + docs).fetchone()[0]
        rows = index.con.execute(
            "SELECT s.id, s.kind, s.number_inferred, s.text, p.title FROM passages s JOIN patents p ON p.id = s.patent_id "
            f"WHERE p.doc_number IN ({marks})", docs).fetchall()
        shortest, window = embed.limits(language)
        pieces = []
        for passage in rows:
            if len(passage["text"]) >= shortest:
                text = (f"{passage['title']}: {passage['text']}" if passage["kind"] == "claim" and passage["number_inferred"]
                        else passage["text"])
                pieces += embed.windows(text, window)
        too_long = sum(len(ids) > embed.MAX_TOKENS
                       for ids in tokenizer(["passage: " + p for p in pieces], truncation=False, verbose=False)["input_ids"])
        stuck = sum(translate.looping(passage["text"]) for passage in rows)
        out.append(f"| {NAMES[language]} | {len(docs)} | {detected} | {len(pieces)} | {too_long} | {stuck} of {len(rows)} |")
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write("\n".join(out) + "\n")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
