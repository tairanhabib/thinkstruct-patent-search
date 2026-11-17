"""M3: can the tool tell that a query has no match in the index?

    python scripts/testing/offtopic_check.py INDEX_WITH_ONLY_THE_ENGLISH_PATENTS

For the 30 queries of forward_queries.json (5 of them about bread, aircraft engines, phone cameras, a drug and
blockchain) this prints the similarity of the best result, and how far it stands above the per-query background
sample that `Index.calibration` already scores (in units of that sample's spread). If the 5 off-topic queries stood
apart from the other 25 on either number, a warning could be printed below that level.
"""
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from src import embed  # noqa: E402
from src.search import Index, rank_patents  # noqa: E402

index = Index(sys.argv[1])
rows = []
for query in json.load(open(os.path.join(ROOT, "scripts/testing/forward_queries.json"), encoding="utf-8"))["queries"]:
    vector = embed.encode([query["text"]], "query: ")[0]
    mean, spread = index.calibration(np.stack([vector] * (len(index.languages) + 1)))
    best = rank_patents(index.vectors, index.vector_patent, vector, index.vector_language == 0)[2]
    rows.append((query["category"], query["id"], best[0], (best[0] - mean[0]) / spread[0], mean[0], spread[0], query["text"][:60]))
print(f"{'category':10s} id   best   above background   background mean, spread   query")
for row in sorted(rows, key=lambda r: r[3]):
    print(f"{row[0]:10s} {row[1]}  {row[2]:.3f}  {row[3]:5.2f} spreads        {row[4]:.3f}, {row[5]:.4f}            {row[6]}")
off, on = [r for r in rows if r[0] == "no_match"], [r for r in rows if r[0] != "no_match"]
for name, column in (("similarity of the best result", 2), ("spreads above the background sample", 3)):
    a, b = [r[column] for r in off], [r[column] for r in on]
    print(f"\n{name}: off-topic {min(a):.3f} to {max(a):.3f}, the other 25 {min(b):.3f} to {max(b):.3f}. "
          f"Real queries at or below the highest off-topic one: {sum(x <= max(a) for x in b)} of {len(b)}. "
          f"Off-topic queries at or above the lowest real one: {sum(x >= min(b) for x in a)} of {len(a)}.")
