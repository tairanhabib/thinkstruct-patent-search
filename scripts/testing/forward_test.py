"""Independent test pass, Stage 5 part 1: queries the system has never seen (scripts/testing/forward_queries.json).

    python scripts/testing/forward_test.py run    --index INDEX --tag mixed      # search everything, save results + a blind judging sheet
    python scripts/testing/forward_test.py report --tag mixed                    # needs results/forward_judgments_<tag>.json

`run` uses the default search (hybrid, top 10), with results translated for display exactly as the command line does.
The judging sheet lists each distinct (query meaning, displayed title, displayed passage) once, without saying which
language the query or the patent was in, so the judge cannot favour a language. Judgments are 0 (unrelated),
1 (same area) or 2 (directly relevant), saved as {item id: score}.
"""
import argparse
import hashlib
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
RESULTS = os.path.join(ROOT, "scripts/testing/results")
LANGUAGES = ("en", "de", "es", "zh", "ja")


def load_queries():
    return json.load(open(os.path.join(ROOT, "scripts/testing/forward_queries.json"), encoding="utf-8"))["queries"]


def item_id(query_id, title, passage):
    return hashlib.sha1(f"{query_id}\n{title}\n{passage}".encode("utf-8")).hexdigest()[:12]


def run(args):
    import cli
    from src.search import Index, query_language, search
    index = Index(args.index)
    runs, sheet = [], {}
    for query in load_queries():
        versions = {"en": query["text"], **query.get("translations", {})}
        for language, text in versions.items():
            info = {}
            results = search(text, top_k=10, index=index, info=info)
            rows = []
            for rank, r in enumerate(results, 1):
                foreign = r["language"] not in (None, "en")
                title = cli.shown((r["title_en"] or r["title"]) if foreign else r["title"])
                passage = r["passage"]
                shown_text = (passage["text_en"] if passage else "")[:600]
                row = {"rank": rank, "doc": r["doc_number"], "invention": r["doc_number"].removesuffix("-DE").removesuffix("-ZH"),
                       "language": r["language"], "title_shown": title, "score": r["score"], "similarity": r["similarity"],
                       "keyword_rank": r["keyword_rank"], "kind": passage["kind"] if passage else None,
                       "translated": bool(passage and passage["translated"]), "passage_shown": shown_text,
                       "passage_original": (passage["text"] if passage else "")[:600]}
                if rank <= 5:
                    row["item"] = item_id(query["id"], title, shown_text)
                    sheet[row["item"]] = {"item": row["item"], "query": query["text"], "title": title, "passage": shown_text}
                rows.append(row)
            runs.append({"id": query["id"], "category": query["category"], "query_language": language, "query": text,
                         "detected_language": query_language(text), "searched_in": info.get("query_languages"),
                         "ms": info["ms"], "results": rows})
            print(query["id"], language, "detected", runs[-1]["detected_language"], "| top:", rows[0]["doc"] if rows else None,
                  f"{rows[0]['similarity']:.3f}" if rows and rows[0]["similarity"] else "", flush=True)
    os.makedirs(RESULTS, exist_ok=True)
    json.dump(runs, open(os.path.join(RESULTS, f"forward_results_{args.tag}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    items = sorted(sheet.values(), key=lambda item: item["item"])  # order carries no information about rank or language
    json.dump(items, open(os.path.join(RESULTS, f"forward_judging_sheet_{args.tag}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(runs)} searches, {len(items)} distinct items to judge")


def report(args):
    runs = json.load(open(os.path.join(RESULTS, f"forward_results_{args.tag}.json"), encoding="utf-8"))
    judged = json.load(open(os.path.join(RESULTS, f"forward_judgments_{args.tag}.json"), encoding="utf-8"))
    out = {"missing_judgments": 0, "by_category_english": {}, "by_language_general": {}, "overlap_with_english_top10": {},
           "no_match": [], "similarity_top1_by_category": {}}

    def score(group):
        per_query, any2 = [], []
        for run_ in group:
            scores = []
            for row in run_["results"][:5]:
                if row["item"] not in judged:
                    out["missing_judgments"] += 1
                scores.append(judged.get(row["item"], 0))
            scores += [0] * (5 - len(scores))
            per_query.append(float(np.mean(scores)))
            any2.append(float(max(scores) == 2))
        return {"queries": len(group), "mean_score_at_5": round(float(np.mean(per_query)), 3), "share_with_a_2": round(float(np.mean(any2)), 3)}

    english = [r for r in runs if r["query_language"] == "en"]
    for category in ("general", "vague", "specific", "misspelled", "no_match"):
        group = [r for r in english if r["category"] == category]
        out["by_category_english"][category] = score(group)
        out["similarity_top1_by_category"][category] = [round(r["results"][0]["similarity"], 3) for r in group if r["results"] and r["results"][0]["similarity"]]
    out["by_category_english"]["all 30"] = score(english)
    out["by_category_english"]["25 that should match something"] = score([r for r in english if r["category"] != "no_match"])
    for language in LANGUAGES:
        group = [r for r in runs if r["category"] == "general" and r["query_language"] == language]
        out["by_language_general"][language] = score(group) | {
            "detected_as": sorted({r["detected_language"] for r in group}),
            "detected_correctly": sum(r["detected_language"] == language for r in group)}
    base = {r["id"]: [row["invention"] for row in r["results"]] for r in english}
    base_docs = {r["id"]: [row["doc"] for row in r["results"]] for r in english}
    for language in LANGUAGES[1:]:
        group = [r for r in runs if r["query_language"] == language]
        out["overlap_with_english_top10"][language] = {
            "mean_shared_inventions_of_10": round(float(np.mean([len(set(base[r["id"]]) & {row["invention"] for row in r["results"]}) for r in group])), 2),
            "mean_shared_documents_of_10": round(float(np.mean([len(set(base_docs[r["id"]]) & {row["doc"] for row in r["results"]}) for r in group])), 2),
            "same_top_1": sum(base[r["id"]][:1] == [row["invention"] for row in r["results"][:1]] for r in group)}
    for r in english:
        if r["category"] == "no_match":
            out["no_match"].append({"query": r["query"], "top_similarity": round(r["results"][0]["similarity"], 3), "results_returned": len(r["results"]),
                                    "top_score": round(r["results"][0]["score"], 4), "judged_top5": [judged.get(row["item"], 0) for row in r["results"][:5]]})
    languages_shown = {}
    for r in runs:
        for row in r["results"][:10]:
            languages_shown.setdefault(r["query_language"], {}).setdefault(row["language"] or "unknown", 0)
            languages_shown[r["query_language"]][row["language"] or "unknown"] += 1
    out["result_languages_by_query_language"] = languages_shown
    json.dump(out, open(os.path.join(RESULTS, f"forward_report_{args.tag}.json"), "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("what", choices=("run", "report"))
    parser.add_argument("--index")
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    {"run": run, "report": report}[args.what](args)
