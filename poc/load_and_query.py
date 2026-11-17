"""Proof of concept: the hybrid patent search as ONE SQL statement in PostgreSQL with pgvector.

Copies the small index (SQLite plus the two .npy files) into Postgres, then runs a classification
prefix filter, a keyword match and a vector ordering in a single statement: exact, then with the
HNSW index, then compares with the Python search of Part 1.

    docker compose up -d --wait && .venv/bin/python poc/load_and_query.py
    .venv/bin/python poc/load_and_query.py --pgserver /some/empty/dir     # no Docker
"""
import argparse
import os
import re
import sqlite3
import statistics
import sys
import time

import numpy as np
import psycopg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src import embed  # noqa: E402
from src.search import Index, search  # noqa: E402

QUERY, CPC_PREFIX, KEYWORDS = "wheel hub with integrated pressure sensor", "B60B", "sensor"
# shortcut: the statement takes the 200 nearest surviving passages, then keeps the best one per patent.
# A patent that owns many near passages can crowd others out; raise this if fewer than 10 patents come back.
CANDIDATES = 200

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;
DROP TABLE IF EXISTS passage_vectors, classifications, patents;
CREATE TABLE patents (
    id integer PRIMARY KEY, doc_number text NOT NULL, title_en text, abstract_en text,
    tsv tsvector GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(title_en, '') || ' ' || coalesce(abstract_en, ''))) STORED);
CREATE TABLE classifications (patent_id integer NOT NULL, code text NOT NULL);
-- shortcut: the passage text sits on the vector row (repeated when a long passage owns several
-- vectors); at 10 million patents keep it in its own table and join the ten winners.
CREATE TABLE passage_vectors (
    patent_id integer NOT NULL, passage_id integer NOT NULL, kind text NOT NULL, ord integer NOT NULL,
    text text NOT NULL, embedding vector(384) NOT NULL);
"""
INDEXES = """
CREATE INDEX ON patents USING gin (tsv);
CREATE INDEX ON classifications (code text_pattern_ops, patent_id);  -- text_pattern_ops: LIKE 'B60B%' becomes a range scan
CREATE INDEX ON passage_vectors (patent_id);
CREATE INDEX passage_vectors_hnsw ON passage_vectors USING hnsw (embedding vector_ip_ops);  -- rows are unit length
ANALYZE;
"""
# The one statement. <#> is pgvector's negative inner product, so smaller is nearer.
SQL = """
WITH nearest AS (            -- passages of patents that pass both filters, nearest first
    SELECT v.patent_id, v.kind, v.ord, v.text, v.embedding <#> %(q)s::vector AS distance
    FROM passage_vectors v
    JOIN patents p ON p.id = v.patent_id
    WHERE p.tsv @@ plainto_tsquery('english', %(keywords)s)
      AND EXISTS (SELECT 1 FROM classifications c WHERE c.patent_id = p.id AND c.code LIKE %(prefix)s)
    ORDER BY v.embedding <#> %(q)s::vector
    LIMIT %(candidates)s
), best AS (                 -- the best passage of each patent
    SELECT DISTINCT ON (patent_id) * FROM nearest ORDER BY patent_id, distance
)
SELECT p.doc_number, -b.distance AS similarity, b.kind, b.ord, p.title_en, left(b.text, 100) AS passage
FROM best b JOIN patents p ON p.id = b.patent_id
ORDER BY b.distance, p.id
LIMIT 10
"""

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--dsn", default="postgresql://postgres:postgres@localhost:5433/postgres")
parser.add_argument("--index", default="index")
parser.add_argument("--pgserver", metavar="DIR", help="start an embedded Postgres (pip install pgserver) with its data in DIR")
args = parser.parse_args()
if args.pgserver:
    import pgserver
    server = pgserver.get_server(args.pgserver)  # stops when this process exits
    args.dsn = server.get_uri()

# prepare_threshold=None: plan every execution with the real values, so LIKE 'B60B%' can use its index
con = psycopg.connect(args.dsn, autocommit=True, prepare_threshold=None)
print(con.execute("SELECT version()").fetchone()[0].split(",")[0], end=", pgvector ")
con.execute(SCHEMA)
print(con.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()[0])


def literal(vector):
    return "[" + ",".join(map(repr, vector.tolist())) + "]"  # pgvector's text form; repr keeps every float32 exact


def copy_rows(table, rows):
    with con.cursor().copy(f"COPY {table} FROM STDIN") as copy:
        count = 0
        for count, row in enumerate(rows, 1):
            copy.write_row(row)
    return count


# 1. load
source = sqlite3.connect(os.path.join(args.index, "patents.db"))
vectors = np.load(os.path.join(args.index, "embeddings.npy"))
owners = np.load(os.path.join(args.index, "vector_passage_ids.npy")).tolist()
passages = {row[0]: row[1:] for row in source.execute("SELECT id, patent_id, id, kind, ord, text FROM passages")}
start = time.perf_counter()
loaded = [
    copy_rows("patents (id, doc_number, title_en, abstract_en)",
              source.execute("SELECT id, doc_number, title_en, abstract_en FROM patents")),
    copy_rows("classifications (patent_id, code)", source.execute("SELECT patent_id, code FROM classifications")),
    copy_rows("passage_vectors (patent_id, passage_id, kind, ord, text, embedding)",
              ((*passages[owner], literal(vector)) for owner, vector in zip(owners, vectors))),
]
copied = time.perf_counter()
con.execute(INDEXES)
print(f"loaded {loaded[0]} patents, {loaded[1]} classification codes, {loaded[2]} passage vectors: "
      f"COPY {copied - start:.1f} s, indexes and ANALYZE {time.perf_counter() - copied:.1f} s")
print("passage_vectors table %s, HNSW index %s" % con.execute(
    "SELECT pg_size_pretty(pg_table_size('passage_vectors')), pg_size_pretty(pg_relation_size('passage_vectors_hnsw'))").fetchone())

# 2. query
query_vector = embed.encode([QUERY], "query: ")[0]
params = {"q": literal(query_vector), "prefix": CPC_PREFIX + "%", "keywords": KEYWORDS, "candidates": CANDIDATES}
print(f"\nquery {QUERY!r}, classification prefix {CPC_PREFIX}, keyword {KEYWORDS!r}, {CANDIDATES} candidate passages")


def run(label, explain=False, repeat=15):
    """Time the statement under the current planner settings; return its rows."""
    con.execute(SQL, params).fetchall()  # warm the cache
    times = []
    for _ in range(repeat):
        clock = time.perf_counter()
        rows = con.execute(SQL, params).fetchall()
        times.append((time.perf_counter() - clock) * 1000)
    plan = [re.sub(r"'\[[^']*\]'", "'[query vector]'", line)
            for (line,) in con.execute("EXPLAIN (ANALYZE, BUFFERS) " + SQL, params)]
    print(f"\n{label}: {len(rows)} rows, median {statistics.median(times):.2f} ms of {repeat} runs "
          f"(fastest {min(times):.2f}, slowest {max(times):.2f}, measured from Python), "
          f"HNSW index used: {'yes' if any('passage_vectors_hnsw' in line for line in plan) else 'no'}")
    if explain:
        print("    " + "\n    ".join(plan))
    return rows


def show(rows):
    for rank, (doc_number, similarity, kind, number, title, passage) in enumerate(rows, 1):
        print(f"{rank:>3}. {similarity:.4f}  {doc_number:<16} {kind} {number}: {(title or '')[:60]}")
        print(f"       {' '.join(passage.split())}")


con.execute("SET enable_indexscan = off")  # HNSW can only be read by an index scan, so this forces exact scoring
exact = run("EXACT (index scans off, every surviving vector is scored)", explain=True)
show(exact)
con.execute("RESET enable_indexscan")
run("PLANNER'S OWN CHOICE (nothing forced)")

# Under a filter this selective the planner avoids HNSW, so push it there to see what the index returns.
con.execute("SET enable_seqscan = off; SET enable_bitmapscan = off; SET enable_sort = off")
hnsw = run("HNSW, hnsw.ef_search = 40 (the default)", explain=True)
con.execute("SET hnsw.ef_search = 1000")  # the largest value allowed
wide = run("HNSW, hnsw.ef_search = 1000 (the maximum)")
try:  # iterative scans arrived in pgvector 0.8.0: the index keeps going until the LIMIT is filled
    con.execute("SET hnsw.ef_search = 40; SET hnsw.iterative_scan = relaxed_order")
    iterative = run("HNSW, hnsw.ef_search = 40, hnsw.iterative_scan = relaxed_order", explain=True)
except psycopg.Error as error:
    iterative = None
    print(f"\nHNSW iterative scan: NOT RUN, this pgvector does not have it ({str(error).splitlines()[0]})")

# 3. the same query through the Python search of Part 1
index = Index(args.index)
python = search(QUERY, mode="semantic", cpc_prefix=CPC_PREFIX, keywords=KEYWORDS, top_k=10, translate_results=False,
                index=index)
same = [hit["doc_number"] for hit in python] == [row[0] for row in exact]
gap = max((abs(hit["similarity"] - row[1]) for hit, row in zip(python, exact)), default=0.0)
print(f"\nPython search returned {len(python)} patents. Same patents in the same order as exact SQL: {same}. "
      f"Largest similarity difference: {gap:.1e}")
# why HNSW loses rows: where the best passage of each exact result ranks among ALL vectors, before any filter
scores = index.vectors @ query_vector
print(f"rank of each exact result's best passage among all {len(scores)} vectors: "
      f"{[int((scores > row[1] + 1e-6).sum()) + 1 for row in exact]}")
exact_set = {row[0] for row in exact}
for label, rows in (("HNSW ef_search 40", hnsw), ("HNSW ef_search 1000", wide), ("HNSW iterative", iterative)):
    if rows is not None:
        print(f"{label}: {len(rows)} rows, {len(exact_set & {row[0] for row in rows})} of the {len(exact)} exact patents found")
