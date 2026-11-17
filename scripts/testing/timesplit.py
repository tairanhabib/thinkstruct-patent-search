"""Independent test pass, Stage 5 part 2: time split, as if the 2025 weekly files arrived after the index was built.

    python scripts/testing/timesplit.py --data data/small --work WORKDIR --reference INDEX_BUILT_IN_ONE_PASS

1. Builds a fresh index from the files dated before 1 January 2025, through `cli.py ingest`.
2. Ingests the 2025 files through the same command. Records whether that needed a full rebuild, how long it took,
   whether anything was duplicated, and whether a 2025 patent is found straight away.
3. Runs `cli.py ingest` once more on the full folder (what a user does when new files land in data/small).
4. Compares the incrementally built index with one built in a single pass: same rows, same search results.
5. Runs Test A of the backtest separately on the 2025 patents and on the earlier ones.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def cli(index, *args):
    start = time.perf_counter()
    done = subprocess.run([sys.executable, "cli.py", "--index", index, *args], cwd=ROOT, capture_output=True, text=True)
    return done, round(time.perf_counter() - start, 1)


def counts(index):
    import sqlite3
    con = sqlite3.connect(os.path.join(index, "patents.db"))
    ids = np.load(os.path.join(index, "vector_passage_ids.npy"))
    return {"patents": con.execute("SELECT COUNT(*) FROM patents").fetchone()[0],
            "distinct_document_numbers": con.execute("SELECT COUNT(DISTINCT doc_number) FROM patents").fetchone()[0],
            "passages": con.execute("SELECT COUNT(*) FROM passages").fetchone()[0],
            "full_text_rows": con.execute("SELECT COUNT(*) FROM patents_fts").fetchone()[0],
            "classification_rows": con.execute("SELECT COUNT(*) FROM classifications").fetchone()[0],
            "vectors": int(len(ids)), "vectors_file_rows": int(len(np.load(os.path.join(index, "embeddings.npy"), mmap_mode="r"))),
            "passages_with_a_vector": int(len(set(ids.tolist())))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data/small")
    parser.add_argument("--work", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--out", default=os.path.join(ROOT, "scripts/testing/results/timesplit.json"))
    args = parser.parse_args()
    old_dir, new_dir, index = (os.path.join(args.work, name) for name in ("before_2025", "weekly_2025", "index"))
    for path in (old_dir, new_dir, index):
        shutil.rmtree(path, ignore_errors=True)
    os.makedirs(old_dir), os.makedirs(new_dir)
    for path in sorted(glob.glob(os.path.join(args.data, "*.json"))):
        year = re.search(r"ipa(\d\d)\d{4}\.json$", path).group(1)
        shutil.copy(path, old_dir if year < "25" else new_dir)
    out = {"files_before_2025": len(os.listdir(old_dir)), "files_2025": len(os.listdir(new_dir))}

    done, seconds = cli(index, "ingest", old_dir)
    out["step1_build_before_2025"] = {"exit": done.returncode, "seconds": seconds, "report": done.stdout[-900:], "counts": counts(index)}
    probe = json.load(open(sorted(glob.glob(os.path.join(new_dir, "*.json")))[0]))[0]
    done, _ = cli(index, "show", "--doc", probe["doc_number"])
    out["probe_2025_patent"] = {"doc": probe["doc_number"], "title": probe["title"], "present_before_its_week_is_ingested": "No patent" not in done.stdout}
    before_vectors = np.load(os.path.join(index, "embeddings.npy"))

    done, seconds = cli(index, "ingest", new_dir)
    after = counts(index)
    after_vectors = np.load(os.path.join(index, "embeddings.npy"))
    embedded = re.search(r"embedded (\d+) windows from (\d+) passages in ([\d.]+) s", done.stdout)
    out["step2_ingest_2025"] = {
        "exit": done.returncode, "seconds": seconds, "report": done.stdout[-900:], "counts": after,
        "windows_embedded_this_time": int(embedded.group(1)) if embedded else None,
        "old_vectors_untouched": bool(np.array_equal(after_vectors[: len(before_vectors)], before_vectors)),
        "full_rebuild_needed": not (embedded and int(embedded.group(1)) == after["vectors"] - len(before_vectors))}
    done, seconds_search = cli(index, "search", probe["title"], "--mode", "keyword", "--top", "10")
    out["probe_2025_patent"]["found_by_title_right_after_ingest"] = probe["doc_number"] in done.stdout
    done, _ = cli(index, "similar", "--doc", probe["doc_number"], "--top", "3")
    out["probe_2025_patent"]["usable_as_a_query_right_after_ingest"] = done.returncode == 0 and " 1. " in done.stdout

    done, seconds = cli(index, "ingest", args.data)
    out["step3_ingest_whole_folder_again"] = {"exit": done.returncode, "seconds": seconds, "report": done.stdout[-400:], "counts": counts(index)}
    out["duplicates"] = {key: out["step3_ingest_whole_folder_again"]["counts"][key] for key in ("patents", "distinct_document_numbers", "vectors", "passages_with_a_vector")}

    # 4. the same index as one built in a single pass?
    from perf import fifty
    from src.search import Index, search
    built, reference = Index(index), Index(args.reference)
    same_text = set(built.con.execute("SELECT p.doc_number, s.kind, s.ord, s.text FROM passages s JOIN patents p ON p.id = s.patent_id")) == \
        set(reference.con.execute("SELECT p.doc_number, s.kind, s.ord, s.text FROM passages s JOIN patents p ON p.id = s.patent_id"))
    different, worst = 0, 0.0
    for query in fifty():
        for options in ({}, {"cpc_prefix": "B60C"}, {"keywords": "rubber"}):
            a = search(query, top_k=10, translate_results=False, index=built, **options)
            b = search(query, top_k=10, translate_results=False, index=reference, **options)
            different += [r["doc_number"] for r in a] != [r["doc_number"] for r in b]
            worst = max([worst] + [abs(x["similarity"] - y["similarity"]) for x, y in zip(a, b) if x["doc_number"] == y["doc_number"] and x["similarity"]])
    out["step4_against_single_pass_index"] = {"same_passages": same_text, "searches_compared": 150, "top10_lists_that_differ": different,
                                              "largest_similarity_difference": worst}

    # 5. Test A on the new patents against the old ones
    import backtest
    claims = backtest.first_claims(built, collection=os.path.basename(new_dir)) | backtest.first_claims(built, collection=os.path.basename(old_dir))
    week = dict(built.con.execute("SELECT doc_number, filing_week FROM patents"))
    backtest.first_claims = lambda index_, collection="small": claims  # the two collections have other names here
    groups = {"2025": sorted(d for d, c in claims.items() if len(c[2]) >= 40 and week[d] >= "2025-01-01"),
              "before 2025": sorted(d for d, c in claims.items() if len(c[2]) >= 40 and week[d] < "2025-01-01")}
    out["step5_test_a"] = {}
    ranks = {}
    for name, docs in groups.items():
        for mode in backtest.MODES:
            ranks[name, mode] = backtest.test_a(built, docs, mode)
            out["step5_test_a"][f"{name} | {mode}"] = backtest.metrics(ranks[name, mode])
    rng = np.random.default_rng(42)
    for mode in backtest.MODES:
        new, old = (np.where(np.array(ranks[g, mode]) > 0, 1.0 / np.maximum(ranks[g, mode], 1), 0.0) for g in ("2025", "before 2025"))
        diffs = [rng.choice(new, len(new)).mean() - rng.choice(old, len(old)).mean() for _ in range(1000)]
        out["step5_test_a"][f"MRR, 2025 minus before | {mode}"] = {"difference": round(float(new.mean() - old.mean()), 4),
                                                                  "ci": [round(float(np.percentile(diffs, 2.5)), 4), round(float(np.percentile(diffs, 97.5)), 4)]}
    json.dump(out, open(args.out, "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
