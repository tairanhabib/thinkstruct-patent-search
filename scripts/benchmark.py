"""Time the search with and without hybrid search and filters. Writes benchmarks.md.

Usage: python scripts/benchmark.py [--index index] [--repeat 5] [--scale 30] [--times 10]

Part 1 runs the real `search()` on the real index: 20 fixed queries, each repeated.
Part 2 repeats the scoring step alone on the same vectors copied `--scale` times, to see
what happens to filter first and filter after as the corpus grows.
Part 3 runs the real `search()` again on a real index `--times` times the size, built in a
temporary directory, so the SQL filter, the keyword ranking and the fetch grow too.
"""
import argparse
import os
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "testing"))
import perf  # noqa: E402  (the tester's script: `scale` writes a real index several times the size)
from src import db, embed  # noqa: E402
from src.search import Index, filter_patents, rank_patents, search  # noqa: E402

QUERIES = [
    "wheel hub with integrated pressure sensor",
    "pneumatic tire tread pattern that reduces road noise",
    "run flat tire with reinforced sidewall",
    "airless tire with flexible spokes",
    "tire pressure monitoring system that transmits wirelessly",
    "bicycle wheel rim made of carbon fiber",
    "trailer hitch coupling with automatic locking",
    "rubber composition containing silica for low rolling resistance",
    "wheel bearing unit with a sealing device",
    "method of retreading a truck tire",
    "caster wheel with a swivel lock for carts",
    "tire with sound absorbing foam attached to the inner liner",
    "central tire inflation system for off road vehicles",
    "tread groove shape that improves drainage on wet roads",
    "wheel cover that improves aerodynamics of an electric vehicle",
    "bead core structure that improves rim seating",
    "studded winter tire with improved ice grip",
    "self sealing tire with a sealant layer",
    "omnidirectional wheel with rollers for a robot",
    "tow bar with a sensor detecting trailer angle",
]
# name, filters. Chosen to cover a wide range of selectivity.
FILTERS = [
    ("classification B60 (all)", {"cpc_prefix": "B60"}),
    ("classification B60C (tires)", {"cpc_prefix": "B60C"}),
    ("classification B60B (wheels)", {"cpc_prefix": "B60B"}),
    ("keyword: rubber", {"keywords": "rubber"}),
    ("classification B60C11 (treads)", {"cpc_prefix": "B60C11"}),
    ("filing weeks 2024-06 to 2024-08", {"date_from": "2024-06-01", "date_to": "2024-08-31"}),
    ("keyword: sensor", {"keywords": "sensor"}),
    ("classification B60D (hitches)", {"cpc_prefix": "B60D"}),
    ("B60C + keywords: noise", {"cpc_prefix": "B60C", "keywords": "noise"}),
    ("title contains: wheel bearing", {"title": "wheel bearing"}),
]


def median_p95(values):
    values = np.sort(np.asarray(values))
    return float(np.median(values)), float(values[min(len(values) - 1, int(np.ceil(0.95 * len(values))) - 1)])


def time_search(index, repeat, **options):
    """Median and 95th percentile of the whole call, and of the call without the query encoding."""
    total, without_encoding, stages = [], [], {}
    info = {}
    for _ in range(repeat):
        for query in QUERIES:
            search(query, index=index, info=info, translate_results=False, **options)
            total.append(info["ms"]["total"])
            without_encoding.append(info["ms"]["total"] - info["ms"]["encode_query"])
            for name, value in info["ms"].items():
                stages.setdefault(name, []).append(value)
    return median_p95(total), median_p95(without_encoding), {k: float(np.median(v)) for k, v in stages.items()}, dict(info)


def part_one(index, repeat, out, heading="## Part 1: the real search on the real index\n"):
    out.append(heading)
    out.append(f"{len(index.patent_ids)} patents, {len(index.vectors)} vectors of {index.vectors.shape[1]} dimensions. "
               f"{len(QUERIES)} queries, each run {repeat} times ({len(QUERIES) * repeat} timings per row). "
               "Times in milliseconds, median / 95th percentile. Result translation is switched off.\n")

    out.append("### The three search modes, no filters\n")
    out.append("| Mode | Whole call | Without encoding the query | Encode query | Score vectors | Keyword ranking | Fuse and fetch |")
    out.append("| --- | --- | --- | --- | --- | --- | --- |")
    for label, mode in (("semantic (default)", "semantic"), ("keyword only", "keyword"), ("hybrid (semantic and keyword fused)", "hybrid")):
        total, rest, stage, _ = time_search(index, repeat, mode=mode)
        out.append(f"| {label} | {total[0]:.1f} / {total[1]:.1f} | {rest[0]:.2f} / {rest[1]:.2f} | {stage['encode_query']:.1f} "
                   f"| {stage['score']:.2f} | {stage['keyword']:.2f} | {stage['fuse'] + stage['fetch']:.2f} |")

    out.append("\n### Search with filters (default mode): filter first, filter after, and auto\n")
    out.append("All three strategies return the same results (checked for every row). \"Vectors kept\" is the share of all "
               "vectors that belong to patents passing the filter. \"SQL filter\" is the median time of the filter query alone. "
               "The three strategy columns are the median time of the filter and scoring steps together, so they include it. "
               "The last column is the whole call with the default strategy (auto), "
               "without encoding the query, median / 95th percentile.\n")
    out.append("| Filter | Patents passing | Vectors kept | SQL filter | Filter first | Filter after | Auto (default) | "
               "First against after | Whole call, auto |")
    out.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    _, base_rest, base_stage, _ = time_search(index, repeat)
    base = base_stage["filter"] + base_stage["score"]
    out.append(f"| none | {len(index.patent_ids)} | 100% | none | {base:.2f} | same | same | | {base_rest[0]:.2f} / {base_rest[1]:.2f} |")
    for label, filters in FILTERS:
        runs = {name: time_search(index, repeat, strategy=name, **filters)
                for name in ("filter_first", "filter_after", "auto")}
        for query in QUERIES[:5]:
            answers = [[(r["doc_number"], r["passage"] and r["passage"]["text"]) for r in
                        search(query, index=index, translate_results=False, strategy=name, **filters)] for name in runs]
            assert answers[0] == answers[1] == answers[2], (label, query)
        core = {name: run[2]["filter"] + run[2]["score"] for name, run in runs.items()}
        info = runs["auto"][3]
        out.append(f"| {label} | {info['patents_passing_filters']} | {info.get('vectors_kept', 0) / len(index.vectors):.1%} "
                   f"| {runs['auto'][2]['filter']:.2f} | {core['filter_first']:.2f} | {core['filter_after']:.2f} | {core['auto']:.2f} "
                   f"| {core['filter_after'] / core['filter_first']:.1f}x | {runs['auto'][1][0]:.2f} / {runs['auto'][1][1]:.2f} |")
    out.append("")


def part_two(index, scale, repeat, out):
    """Scoring step only, on the vectors copied `scale` times with a little noise."""
    rng = np.random.default_rng(0)
    n = len(index.vectors)
    vectors = np.tile(index.vectors, (scale, 1))
    for k in range(scale):  # one copy at a time keeps the temporary noise array small
        vectors[k * n:(k + 1) * n] += 0.01 * rng.standard_normal(index.vectors.shape, dtype=np.float32)
    # copy k of patent p becomes patent p + k * table_size, so every copy is a distinct patent
    owner = np.concatenate([index.vector_patent + k * index.table_size for k in range(scale)])
    queries = embed.encode(QUERIES, "query: ")
    out.append(f"## Part 2: the scoring step alone at {scale} times the size\n")
    out.append(f"The {n} real vectors copied {scale} times with small random noise: {len(vectors):,} vectors, "
               f"{vectors.nbytes / 1e9:.2f} GB in memory, {len(index.patent_ids) * scale:,} synthetic patents. Only the vector "
               "scoring step is timed (mask, matrix product, best passage per patent, sort of the patents). The SQL filter, keyword ranking "
               f"and query encoding are not included. {len(QUERIES)} queries, {repeat} runs each. Milliseconds, median / 95th percentile.\n")
    out.append("| Filter | Vectors kept | Filter first | Filter after | Auto (default) | First against after |")
    out.append("| --- | --- | --- | --- | --- | --- |")

    def run(keep, strategy):
        times = []
        for _ in range(repeat):
            for query in queries:
                start = time.perf_counter()
                rank_patents(vectors, owner, query, keep, strategy)
                times.append((time.perf_counter() - start) * 1000)
        return median_p95(times)

    full = run(None, "filter_first")
    out.append(f"| none | 100% | {full[0]:.1f} / {full[1]:.1f} | same | same | |")
    for label, filters in FILTERS:
        allowed = filter_patents(index, **filters)
        keep = np.tile(allowed[index.vector_patent], scale)
        first, after, auto = run(keep, "filter_first"), run(keep, "filter_after"), run(keep, "auto")
        out.append(f"| {label} | {keep.mean():.1%} | {first[0]:.1f} / {first[1]:.1f} | {after[0]:.1f} / {after[1]:.1f} "
                   f"| {auto[0]:.1f} / {auto[1]:.1f} | {after[0] / first[0]:.1f}x |")
    out.append("")


def part_three(index_dir, times, repeat, out):
    """Part 1 again, on a real index `times` times the size. Every patent, passage, classification and full text
    row is copied (document numbers get a suffix) and the vectors get a little noise, so nothing is an exact tie."""
    with tempfile.TemporaryDirectory() as directory:
        perf.scale(argparse.Namespace(index=index_dir, dest=os.path.join(directory, "index"), times=times))
        big = Index(os.path.join(directory, "index"))
        for query in QUERIES:
            search(query, index=big, translate_results=False)  # warm the SQLite page cache
        part_one(big, repeat, out, f"## Part 3: the real search on a real index {times} times the size\n\n"
                 "Unlike Part 2 this includes the SQL filter, the keyword ranking and the fetch. "
                 f"The index is the real one with every row copied {times} times.\n")
        big.con.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--index")
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--scale", type=int, default=30, help="copies of the vectors for part 2 (0 to skip)")
    parser.add_argument("--times", type=int, default=10, help="size of the real index built for part 3 (0 to skip)")
    parser.add_argument("--out", default="benchmarks.md")
    args = parser.parse_args()

    index = Index(args.index)
    embed.encode(QUERIES[:2], "query: ")  # load and warm the model before timing anything
    for query in QUERIES:
        search(query, index=index, translate_results=False)  # warm the SQLite page cache
    import platform
    out = ["# Search timing\n",
           f"Generated by `python scripts/benchmark.py`. Machine: {platform.processor() or platform.machine()}, "
           f"{os.cpu_count()} cores, Python {platform.python_version()}, NumPy {np.__version__}.\n"]
    part_one(index, args.repeat, out)
    if args.scale:
        part_two(index, args.scale, max(1, args.repeat // 2), out)
    if args.times:
        part_three(db.index_dir(args.index), args.times, max(1, args.repeat // 2), out)
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write("\n".join(out))
    print("\n".join(out))


if __name__ == "__main__":
    main()
