"""Independent test pass, Stage 7: performance.

    python scripts/testing/perf.py latency --index INDEX --out results/perf_1x.json   # 50 queries, filters at three selectivities
    python scripts/testing/perf.py cold    --index INDEX                              # first query after process start, prints JSON
    python scripts/testing/perf.py scale   --index INDEX --dest DIR --times 10        # write a 10 times larger index into DIR

`scale` copies every patent, passage, classification and full text row `times` times (document numbers get a
suffix) and tiles the vectors, with small noise on the copies so they are not exact ties. Unlike part 2 of
scripts/benchmark.py, the result is a real index: the SQL filter, the keyword ranking and the fetch are measured
at the larger size too, not only the matrix product.
"""
import argparse
import json
import os
import platform
import resource
import shutil
import sqlite3
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

# name, share of vectors kept on the 640 patent index (from benchmarks.md), filter
SELECTIVITIES = [("broad: classification B60C", {"cpc_prefix": "B60C"}),
                 ("medium: keyword rubber", {"keywords": "rubber"}),
                 ("narrow: title contains wheel bearing", {"title": "wheel bearing"})]


def fifty():
    from benchmark import QUERIES
    forward = json.load(open(os.path.join(ROOT, "scripts/testing/forward_queries.json")))["queries"]
    return QUERIES + [q["text"] for q in forward]


def med_p95(values):
    values = np.sort(np.asarray(values, float))
    return [round(float(np.median(values)), 3), round(float(values[min(len(values) - 1, int(np.ceil(0.95 * len(values))) - 1)]), 3)]


def measure(index, queries, repeat, **options):
    from src.search import search
    total, rest, stages, info = [], [], {}, {}
    for _ in range(repeat):
        for query in queries:
            search(query, index=index, info=info, translate_results=False, **options)
            total.append(info["ms"]["total"])
            rest.append(info["ms"]["total"] - info["ms"]["encode_query"])
            for name, value in info["ms"].items():
                stages.setdefault(name, []).append(value)
            stages.setdefault("filter_and_score", []).append(info["ms"]["filter"] + info["ms"]["score"])
    return {"whole_call": med_p95(total), "without_encoding": med_p95(rest), "timings": len(total),
            "median_stage_ms": {name: round(float(np.median(v)), 3) for name, v in stages.items()},
            "patents_passing": info.get("patents_passing_filters"), "vectors_kept": info.get("vectors_kept")}


def latency(args):
    from src import embed
    from src.search import Index
    index, queries = Index(args.index), fifty()
    embed.encode(["warm up"], "query: ")
    measure(index, queries[:10], 1)  # warm the caches; not recorded
    out = {"machine": f"{platform.machine()}, {os.cpu_count()} cores, Python {platform.python_version()}",
           "patents": len(index.patent_ids), "vectors": int(len(index.vectors)), "queries": len(queries), "repeat": args.repeat, "rows": {}}
    for mode in ("semantic", "keyword", "hybrid"):
        out["rows"][f"no filter, {mode}"] = measure(index, queries, args.repeat, mode=mode)
    for name, options in SELECTIVITIES:
        for strategy in ("filter_first", "filter_after", "auto"):
            out["rows"][f"{name}, {strategy}"] = measure(index, queries, args.repeat, strategy=strategy, **options)
            out["rows"][f"{name}, {strategy}"]["share_of_vectors_kept"] = round(out["rows"][f"{name}, {strategy}"]["vectors_kept"] / len(index.vectors), 4)
    for name, row in out["rows"].items():
        print(f"{name:55s} whole {row['whole_call']}  no-encode {row['without_encoding']}  filter+score {row['median_stage_ms']['filter_and_score']}"
              f"  keyword {row['median_stage_ms']['keyword']}  fetch {row['median_stage_ms']['fetch']}", flush=True)
    out["peak_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576)
    if args.out:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        json.dump(out, open(args.out, "w"), indent=1)


def cold(args):
    """Run in a fresh process: what the first query costs, piece by piece, against later ones."""
    start = time.perf_counter()
    from src import embed
    from src.search import Index, search
    imported = time.perf_counter()
    index = Index(args.index)
    loaded = time.perf_counter()
    queries, times = fifty()[:6], []
    for query in queries:
        t = time.perf_counter()
        search(query, index=index, translate_results=False)
        times.append(round((time.perf_counter() - t) * 1000, 1))
    print(json.dumps({"import_s": round(imported - start, 2), "load_index_s": round(loaded - imported, 2),
                      "first_query_ms": times[0], "later_queries_ms": times[1:],
                      "process_start_to_first_result_s": round(loaded - start + times[0] / 1000, 2),
                      "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576)}))


def scale(args):
    if os.path.exists(args.dest):
        shutil.rmtree(args.dest)
    os.makedirs(args.dest)
    shutil.copy(os.path.join(args.index, "patents.db"), os.path.join(args.dest, "patents.db"))
    con = sqlite3.connect(os.path.join(args.dest, "patents.db"))
    patents = con.execute("SELECT MAX(id) FROM patents").fetchone()[0] + 1
    passages = con.execute("SELECT MAX(id) FROM passages").fetchone()[0] + 1
    for k in range(1, args.times):
        p, s = k * patents, k * passages
        con.execute("INSERT INTO patents SELECT id + ?, doc_number || '-x' || ?, collection, title, title_en, abstract, abstract_en, "
                    "classification, bibtex, filename, filing_week, language, missing_fields FROM patents WHERE id < ?", (p, k, patents))
        con.execute("INSERT INTO classifications SELECT patent_id + ?, code, subclass FROM classifications WHERE patent_id < ?", (p, patents))
        con.execute("INSERT INTO passages SELECT id + ?, patent_id + ?, kind, ord, number_inferred, parent_claim, text FROM passages WHERE id < ?",
                    (s, p, passages))
        con.execute("INSERT INTO patents_fts (rowid, title_en, abstract_en) SELECT rowid + ?, title_en, abstract_en FROM patents_fts WHERE rowid < ?",
                    (p, patents))
    con.commit()
    con.execute("ANALYZE")
    con.commit()
    vectors = np.load(os.path.join(args.index, "embeddings.npy"))
    ids = np.load(os.path.join(args.index, "vector_passage_ids.npy"))
    rng = np.random.default_rng(42)
    blocks, id_blocks = [vectors], [ids]
    for k in range(1, args.times):
        noisy = vectors + rng.normal(0, 0.01, vectors.shape).astype(np.float32)
        blocks.append(noisy / np.linalg.norm(noisy, axis=1, keepdims=True))
        id_blocks.append(ids + k * passages)
    np.save(os.path.join(args.dest, "embeddings.npy"), np.vstack(blocks))
    np.save(os.path.join(args.dest, "vector_passage_ids.npy"), np.concatenate(id_blocks))
    print(json.dumps({"patents": con.execute("SELECT COUNT(*) FROM patents").fetchone()[0],
                      "passages": con.execute("SELECT COUNT(*) FROM passages").fetchone()[0],
                      "vectors": int(len(vectors) * args.times),
                      "db_mb": round(os.path.getsize(os.path.join(args.dest, "patents.db")) / 1e6, 1),
                      "vectors_mb": round(os.path.getsize(os.path.join(args.dest, "embeddings.npy")) / 1e6, 1)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("what", choices=("latency", "cold", "scale"))
    parser.add_argument("--index", required=True)
    parser.add_argument("--out")
    parser.add_argument("--dest")
    parser.add_argument("--times", type=int, default=10)
    parser.add_argument("--repeat", type=int, default=2)
    args = parser.parse_args()
    {"latency": latency, "cold": cold, "scale": scale}[args.what](args)
