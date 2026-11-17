# Proof of concept: the hybrid search as one SQL statement

Part 1 searches in Python. SQLite does the filters and the keywords. NumPy scores the vectors.

The plan for 10 million patents is one PostgreSQL database with the pgvector extension. There, the whole query is one statement in Structured Query Language (SQL). This folder shows that statement working on the real small dataset: 640 patents and 32,772 passage vectors.

This is a proof of concept. The code is short and blunt on purpose.

## What it demonstrates

`poc/load_and_query.py` does six things, in order.

1. It creates three tables: `patents`, `classifications` and `passage_vectors`.
2. It bulk loads them with `COPY` from `index/patents.db` and the two `.npy` files.
3. It builds the indexes. A Generalized Inverted Index (GIN) for keywords. A `text_pattern_ops` index for classification code prefixes. A Hierarchical Navigable Small World (HNSW) index for the vectors.
4. It runs one statement that filters by classification prefix (`B60B`), filters by keyword (`sensor`), orders by vector distance to the query "wheel hub with integrated pressure sensor", and returns the ten best patents, each with its best passage.
5. It times that statement exact, then with the HNSW index, and prints the query plans.
6. It runs the same query through the Part 1 Python search and prints whether the results agree.

## How to run it

Run everything from the repository root. Both ways need the Part 1 index in `index/` and the Part 1 virtual environment in `.venv`.

### With Docker (the intended way)

```
docker compose up -d --wait
.venv/bin/pip install -r poc/requirements.txt
.venv/bin/python poc/load_and_query.py
docker compose down
```

`docker-compose.yml` starts PostgreSQL 16 with pgvector 0.8.7 on host port 5433. The password is fixed. It is for development only. The script connects to `postgresql://postgres:postgres@localhost:5433/postgres`. Pass `--dsn` (data source name, the connection string) to use another database.

### Without Docker (how it was run here)

```
.venv/bin/pip install -r poc/requirements.txt
.venv/bin/python poc/load_and_query.py --pgserver /tmp/patent-poc-pgdata
```

`pgserver` is a package from the Python Package Index (PyPI). Its wheel contains PostgreSQL 16.2 with pgvector 0.6.2. It needs no administrator rights. `--pgserver DIR` starts that server with its data files in `DIR` and stops it when the script ends. The folder that contains `DIR` must exist. Keep `DIR` outside the repository.

The script drops and recreates its three tables on every run. It is safe to run again.

## The one statement

```sql
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
```

How to read it:

- `%(q)s` is the query vector. `%(keywords)s` is `sensor`. `%(prefix)s` is `B60B%`. `%(candidates)s` is 200.
- `<#>` is the pgvector operator for negative inner product. Smaller means nearer. The vectors have length 1, so the inner product is the cosine similarity.
- `nearest` takes the 200 nearest passages among the patents that pass both filters.
- `best` keeps the nearest passage of each patent.
- The last part returns the ten nearest patents.

The search is over passages, but the answer is patents. So the statement must fetch more passages than it returns. 200 is a guess that worked here. See "Shortcuts" below.

## Measured output

The machine is an Apple M2 with 10 cores. It was running other heavy jobs at the same time. The load average was between 6 and 14 during these runs. **The timings are noisy.** Read them as "about one millisecond" or "about ten milliseconds". They are not a benchmark.

All times are in milliseconds (ms), measured from Python, so they include the round trip to the database. Each is the median of 15 runs. These numbers are from one run of the script. Its full output is pasted under "What was verified".

| Step | Result |
| --- | --- |
| `COPY` of 640 patents, 640 classification codes, 32,772 vectors | 8.3 seconds |
| Building all indexes, plus `ANALYZE` | 6.2 seconds |
| Size of the `passage_vectors` table | 68 megabytes (MB) |
| Size of the HNSW index | 59 MB |

| How the statement ran | Rows returned | Median time | Used the HNSW index |
| --- | --- | --- | --- |
| Exact (index scans switched off) | 10 | 1.15 ms | no |
| Planner left alone | 10 | 1.14 ms | no |
| Forced onto HNSW, `hnsw.ef_search = 40` (the default) | **6** | 1.04 ms | yes |
| Forced onto HNSW, `hnsw.ef_search = 1000` (the maximum) | **8** | 11.10 ms | yes |
| HNSW with iterative scan | not run | not run | not run |

Across four runs of the script the exact median was between 1.15 and 1.60 ms. The `ef_search = 1000` median was between 10.7 and 12.0 ms. The row counts were the same every time.

### What the output shows

1. **The exact statement agrees with Part 1.** It returns the same ten patents in the same order as the Python search. The largest difference in similarity is 1.2e-07. That is rounding in 32 bit floating point numbers.
2. **Left alone, the planner does not use the HNSW index for this query.** It expects the two filters to leave about 15 patents. The true number is 12. So it fetches the 469 vectors of those patents through the plain index on `patent_id` and scores all of them. This is the "filter first" strategy of Part 1. Here the database picks it by itself.
3. **Forced onto the HNSW index, the statement returns 6 patents instead of 10.** The HNSW scan hands over at most `hnsw.ef_search` rows, 40 by default. The filters run after that. Of those 40 rows, 21 passed the filters. They belong to 6 patents. The `LIMIT 200` is never reached.
4. **Raising `hnsw.ef_search` to its maximum does not fix it.** With 1000 the statement returns 8 patents. It takes about 11 ms, which is about ten times slower than exact. It is slower and still incomplete.
5. **The loss is not caused by the approximation. It is caused by filtering after a capped scan.** The script prints where the best passage of each correct patent ranks among all 32,772 vectors: 1, 20, 21, 23, 24, 37, 74, 219, 1130 and 2214. Six are inside the first 40. Eight are inside the first 1000. That matches the 6 and 8 rows exactly.
6. **The HNSW index is almost as large as the table.** 59 MB for 32,772 vectors is roughly 1.9 kilobytes per vector. Here a patent has about 51 vectors. At that ratio, 10 million patents would need an index close to one terabyte. That is a rough extrapolation, not a measurement.

What this means at scale: a selective filter combined with an approximate index silently returns too few rows. The fix has to be chosen per query. Either score exactly when the filter is selective, as the planner did here. Or use iterative index scans, which arrived in pgvector 0.8.0. Or partition the vectors so the filter is applied before the index. This proof of concept shows the problem. It does not show the fix. See "What was verified".

## What was verified

### (a) What was actually run here

Date: 16 November 2026. Python 3.11.15, psycopg 3.3.9, pgserver 0.1.4. The embedded server reported PostgreSQL 16.2 and pgvector 0.6.2.

1. `.venv/bin/pip install "psycopg[binary]" pgserver` installed psycopg 3.3.9 and pgserver 0.1.4, plus four packages they depend on.
2. `.venv/bin/python poc/load_and_query.py --pgserver <a directory outside the repository>` ran to the end with exit code 0. Its complete standard output is pasted below, unedited. The script itself replaces the 384 numbers of the query vector with `[query vector]` in the plans and cuts each passage to 100 characters. Three lines of warnings and progress on standard error, from the embedding model library, are left out.
3. The same script with `--dsn` ran against an embedded server that a separate process had started. Exit code 0. Same row counts (10, 10, 6, 8) and the same agreement with Python. This shows the `--dsn` path works when the script does not start the server itself.
4. The script with no options and no server running failed with "Connection refused" on `localhost` port 5433. That is expected. It shows the default points at the Docker port.
5. A separate count in SQLite confirmed the filter sizes: 32 patents match `sensor`, 298 patents have a `B60B` code, 12 patents pass both. The PostgreSQL plan shows the same 32, 298 and 12. So the two keyword engines agree for this keyword.

<details>
<summary>Complete output of step 2 (145 lines)</summary>

```text
PostgreSQL 16.2 on aarch64-apple-darwin23.5.0, pgvector 0.6.2
loaded 640 patents, 640 classification codes, 32772 passage vectors: COPY 8.3 s, indexes and ANALYZE 6.2 s
passage_vectors table 68 MB, HNSW index 59 MB

query 'wheel hub with integrated pressure sensor', classification prefix B60B, keyword 'sensor', 200 candidate passages

EXACT (index scans off, every surviving vector is scored): 10 rows, median 1.15 ms of 15 runs (fastest 1.10, slowest 1.64, measured from Python), HNSW index used: no
    Limit  (cost=1649.55..1649.57 rows=10 width=120) (actual time=0.779..0.781 rows=10 loops=1)
      Buffers: shared hit=791
      ->  Sort  (cost=1649.55..1650.05 rows=200 width=120) (actual time=0.778..0.780 rows=10 loops=1)
            Sort Key: b.distance, p.id
            Sort Method: quicksort  Memory: 28kB
            Buffers: shared hit=791
            ->  Hash Join  (cost=1508.14..1645.23 rows=200 width=120) (actual time=0.708..0.776 rows=11 loops=1)
                  Hash Cond: (p.id = b.patent_id)
                  Buffers: shared hit=791
                  ->  Seq Scan on patents p  (cost=0.00..134.40 rows=640 width=58) (actual time=0.001..0.041 rows=640 loops=1)
                        Buffers: shared hit=128
                  ->  Hash  (cost=1505.64..1505.64 rows=200 width=383) (actual time=0.689..0.690 rows=11 loops=1)
                        Buckets: 1024  Batches: 1  Memory Usage: 13kB
                        Buffers: shared hit=663
                        ->  Subquery Scan on b  (cost=1502.64..1505.64 rows=200 width=383) (actual time=0.671..0.687 rows=11 loops=1)
                              Buffers: shared hit=663
                              ->  Unique  (cost=1502.64..1503.64 rows=200 width=383) (actual time=0.671..0.686 rows=11 loops=1)
                                    Buffers: shared hit=663
                                    ->  Sort  (cost=1502.64..1503.14 rows=200 width=383) (actual time=0.671..0.678 rows=200 loops=1)
                                          Sort Key: v.patent_id, ((v.embedding <#> '[query vector]'::vector))
                                          Sort Method: quicksort  Memory: 99kB
                                          Buffers: shared hit=663
                                          ->  Limit  (cost=1494.49..1494.99 rows=200 width=383) (actual time=0.572..0.588 rows=200 loops=1)
                                                Buffers: shared hit=663
                                                ->  Sort  (cost=1494.49..1496.40 rows=763 width=383) (actual time=0.571..0.578 rows=200 loops=1)
                                                      Sort Key: ((v.embedding <#> '[query vector]'::vector))
                                                      Sort Method: top-N heapsort  Memory: 199kB
                                                      Buffers: shared hit=663
                                                      ->  Nested Loop  (cost=29.81..1461.52 rows=763 width=383) (actual time=0.081..0.459 rows=469 loops=1)
                                                            Join Filter: (v.patent_id = p_1.id)
                                                            Buffers: shared hit=663
                                                            ->  Hash Semi Join  (cost=28.71..103.95 rows=15 width=8) (actual time=0.072..0.081 rows=12 loops=1)
                                                                  Hash Cond: (p_1.id = c.patent_id)
                                                                  Buffers: shared hit=30
                                                                  ->  Bitmap Heap Scan on patents p_1  (cost=12.98..87.97 rows=32 width=4) (actual time=0.005..0.011 rows=32 loops=1)
                                                                        Recheck Cond: (tsv @@ '''sensor'''::tsquery)
                                                                        Heap Blocks: exact=23
                                                                        Buffers: shared hit=26
                                                                        ->  Bitmap Index Scan on patents_tsv_idx  (cost=0.00..12.97 rows=32 width=0) (actual time=0.004..0.004 rows=32 loops=1)
                                                                              Index Cond: (tsv @@ '''sensor'''::tsquery)
                                                                              Buffers: shared hit=3
                                                                  ->  Hash  (cost=12.00..12.00 rows=298 width=4) (actual time=0.064..0.064 rows=298 loops=1)
                                                                        Buckets: 1024  Batches: 1  Memory Usage: 19kB
                                                                        Buffers: shared hit=4
                                                                        ->  Seq Scan on classifications c  (cost=0.00..12.00 rows=298 width=4) (actual time=0.003..0.047 rows=298 loops=1)
                                                                              Filter: (code ~~ 'B60B%'::text)
                                                                              Rows Removed by Filter: 342
                                                                              Buffers: shared hit=4
                                                            ->  Bitmap Heap Scan on passage_vectors v  (cost=1.10..89.74 rows=51 width=1504) (actual time=0.003..0.006 rows=39 loops=12)
                                                                  Recheck Cond: (patent_id = c.patent_id)
                                                                  Heap Blocks: exact=108
                                                                  Buffers: shared hit=132
                                                                  ->  Bitmap Index Scan on passage_vectors_patent_id_idx  (cost=0.00..1.09 rows=51 width=0) (actual time=0.002..0.002 rows=39 loops=12)
                                                                        Index Cond: (patent_id = c.patent_id)
                                                                        Buffers: shared hit=24
    Planning:
      Buffers: shared hit=26
    Planning Time: 0.274 ms
    Execution Time: 0.802 ms
  1. 0.8874  20240278598      claim 24: WHEEL HUB
       The wheel hub of claim 17 wherein the sensor node is mounted to the housing outboard of the wheel mo
  2. 0.8726  20240351371      claim 11: WHEEL UNIT FOR A PEDELEC AND PEDELEC
       a hub which is rotatable about a rotational axis; a rim which is rotatable about the rotational axis
  3. 0.8706  20250100325      claim 7: VEHICLE WHEEL SUPPORT APPARATUS
       wherein the sensor is fixed to a fixing portion of the hub carrier in a state in which a detection p
  4. 0.8702  20250100326      claim 14: VEHICLE WHEEL SUPPORT DEVICE
       wherein the hub bearing includes a rotary body connected to the wheel, wherein the hub carrier inclu
  5. 0.8697  20240343065      claim 6: SENSOR HOLDER AND BEARING DEVICE FOR VEHICLE WHEEL
       an outer member having a double row of outer raceway surfaces on an inner circumference; an inner me
  6. 0.8671  20250100324      abstract 0: VEHICLE WHEEL SUPPORTING DEVICE
       A vehicle wheel supporting device includes a hub bearing rotatably supporting a wheel, a hub carrier
  7. 0.8635  20240157727      claim 4: RIM ACCESSORY FOR WHEEL POSITIONING ANGLE DETECTION, WARNING
       The rim accessory for the wheel positioning angle detection of claim 1 , wherein the housing body ha
  8. 0.8558  20240383279      claim 1: TOOL DEVICE AND STEERABLE-WHEEL ASSEMBLY
       a frame comprising a support arm; a walking element coupled to the frame; a drive motor selectively
  9. 0.8410  20240198727      description 9: CONTROLLER AND METHOD FOR CONTROLLING CASTERS ATTACHED TO A 
       In detail, locking device6in the exemplary embodiment shown has an interaction surface7which interac
 10. 0.8328  20240208266      abstract 0: Magnetic Apparatus for Centering Caster Wheels
       An autonomous delivery vehicle having one or more caster wheels that may be held off the ground for

PLANNER'S OWN CHOICE (nothing forced): 10 rows, median 1.14 ms of 15 runs (fastest 1.10, slowest 1.78, measured from Python), HNSW index used: no

HNSW, hnsw.ef_search = 40 (the default): 6 rows, median 1.04 ms of 15 runs (fastest 1.01, slowest 1.22, measured from Python), HNSW index used: yes
    Limit  (cost=20000009521.72..20000009521.75 rows=10 width=120) (actual time=0.666..0.667 rows=6 loops=1)
      Buffers: shared hit=1170
      ->  Sort  (cost=20000009521.72..20000009522.22 rows=200 width=120) (actual time=0.665..0.666 rows=6 loops=1)
            Sort Key: ((v.embedding <#> '[query vector]'::vector)), p.id
            Sort Method: quicksort  Memory: 26kB
            Buffers: shared hit=1170
            ->  Merge Join  (cost=10000009347.94..10000009517.40 rows=200 width=120) (actual time=0.614..0.664 rows=6 loops=1)
                  Merge Cond: (v.patent_id = p.id)
                  Buffers: shared hit=1170
                  ->  Unique  (cost=10000009347.66..10000009348.66 rows=200 width=383) (actual time=0.578..0.581 rows=6 loops=1)
                        Buffers: shared hit=1056
                        ->  Sort  (cost=10000009347.66..10000009348.16 rows=200 width=383) (actual time=0.578..0.579 rows=21 loops=1)
                              Sort Key: v.patent_id, ((v.embedding <#> '[query vector]'::vector))
                              Sort Method: quicksort  Memory: 32kB
                              Buffers: shared hit=1056
                              ->  Limit  (cost=77.16..9340.02 rows=200 width=383) (actual time=0.244..0.572 rows=21 loops=1)
                                    Buffers: shared hit=1056
                                    ->  Nested Loop Semi Join  (cost=77.16..35414.96 rows=763 width=383) (actual time=0.244..0.571 rows=21 loops=1)
                                          Join Filter: (p_1.id = c.patent_id)
                                          Buffers: shared hit=1056
                                          ->  Nested Loop  (cost=76.88..28814.28 rows=1639 width=1508) (actual time=0.227..0.258 rows=21 loops=1)
                                                Buffers: shared hit=984
                                                ->  Index Scan using passage_vectors_hnsw on passage_vectors v  (cost=76.60..27796.32 rows=32772 width=1504) (actual time=0.224..0.232 rows=40 loops=1)
                                                      Order By: (embedding <#> '[query vector]'::vector)
                                                      Buffers: shared hit=945
                                                ->  Memoize  (cost=0.29..0.32 rows=1 width=4) (actual time=0.000..0.000 rows=1 loops=40)
                                                      Cache Key: v.patent_id
                                                      Cache Mode: logical
                                                      Hits: 27  Misses: 13  Evictions: 0  Overflows: 0  Memory Usage: 2kB
                                                      Buffers: shared hit=39
                                                      ->  Index Scan using patents_pkey on patents p_1  (cost=0.28..0.31 rows=1 width=4) (actual time=0.001..0.001 rows=0 loops=13)
                                                            Index Cond: (id = v.patent_id)
                                                            Filter: (tsv @@ '''sensor'''::tsquery)
                                                            Rows Removed by Filter: 1
                                                            Buffers: shared hit=39
                                          ->  Index Only Scan using classifications_code_patent_id_idx on classifications c  (cost=0.28..4.01 rows=1 width=4) (actual time=0.014..0.014 rows=1 loops=21)
                                                Index Cond: ((code ~>=~ 'B60B'::text) AND (code ~<~ 'B60C'::text) AND (patent_id = v.patent_id))
                                                Filter: (code ~~ 'B60B%'::text)
                                                Heap Fetches: 21
                                                Buffers: shared hit=63
                  ->  Index Scan using patents_pkey on patents p  (cost=0.28..161.64 rows=640 width=58) (actual time=0.002..0.052 rows=583 loops=1)
                        Buffers: shared hit=114
    Planning:
      Buffers: shared hit=26
    Planning Time: 0.248 ms
    Execution Time: 0.689 ms

HNSW, hnsw.ef_search = 1000 (the maximum): 8 rows, median 11.10 ms of 15 runs (fastest 8.70, slowest 14.02, measured from Python), HNSW index used: yes

HNSW iterative scan: NOT RUN, this pgvector does not have it (invalid configuration parameter name "hnsw.iterative_scan")

Python search returned 10 patents. Same patents in the same order as exact SQL: True. Largest similarity difference: 1.2e-07
rank of each exact result's best passage among all 32772 vectors: [1, 20, 21, 23, 24, 37, 74, 219, 1130, 2214]
HNSW ef_search 40: 6 rows, 6 of the 10 exact patents found
HNSW ef_search 1000: 8 rows, 8 of the 10 exact patents found
```

</details>

### (b) What was written but could not be run here

Docker is not installed on this machine. So none of the following has been executed.

- **`docker-compose.yml` has never been started.** The image was never pulled. The only check made: the tag `pgvector/pgvector:0.8.7-pg16` is listed on Docker Hub.
- **The default connection string has never reached a real server.** The port mapping to 5433, the password and the health check are untested.
- **The iterative scan step has never succeeded.** The script tries `SET hnsw.iterative_scan = relaxed_order`. pgvector 0.6.2 rejects that setting, so the script printed "NOT RUN". That is the output above. The Docker image has pgvector 0.8.7, which has the setting. There the script should time the statement once more and print its plan. Whether it then returns all 10 patents, and how fast, is unknown.
- **The plans and timings under the Docker image are unknown.** It has a newer PostgreSQL 16 release and a much newer pgvector than the embedded server.

Also not tested anywhere:

- More than one query. Everything above is one query, one classification prefix and one keyword.
- More data than the small dataset. Nothing here measures 10 million patents.

## Shortcuts

- **200 candidate passages is a guess.** The statement takes the 200 nearest surviving passages and then keeps one per patent. A patent with many near passages can crowd out others. Here the 200 passages covered 11 of the 12 surviving patents, so the top ten are exact. With other data the number may need to be larger.
- **The passage text sits on the vector row.** A long passage owns several vectors, so its text is stored several times. At scale it belongs in its own table.
- **The HNSW runs are forced.** The script switches off sequential scans, bitmap scans and sorts so the planner has no cheaper choice. That is why the costs in the second plan are huge numbers. It is a way to look at the index, not a way to run production queries.
- **Keywords are only a filter here.** Part 1 can also rank by keywords and merge that ranking with the vector ranking. This statement does not. It matches the Part 1 call `search(..., mode="semantic", cpc_prefix="B60B", keywords="sensor")`.
- **No error handling, no tests.** The comparison with the Python search at the end of the script is the only check.
