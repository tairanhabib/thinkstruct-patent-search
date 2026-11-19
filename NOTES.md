# Working notes

Running log of every design decision, measured number, shortcut and known weakness.
The README is written from this file. Numbers here were measured on an Apple M2 Pro
(10 cores, 16 GB), Python 3.11.15, unless stated otherwise.

"Ruling" marks a place where I departed from the original plan, with the reason and
what it costs if I am wrong.

## Phase A: data inspection

Command: `python scripts/inspect_data.py data/small`

Measured on the small dataset (64 files in `data/small/`):

| Fact | Value |
| --- | --- |
| Files / patents | 64 files, exactly 10 patents each, 640 patents |
| File dates | `240215` to `250501` |
| Keys (real names) | `title`, `doc_number`, `filename`, `abstract`, `detailed_description` (list), `claims` (list), `bibtex`, `classification` (string) |
| Unique `doc_number` | 640 of 640 |
| Titles shared by more than one patent | 43 |
| File name date equals date inside `filename` | 640 of 640 |
| Classification | one string per patent, 9 to 11 characters, all 640 end in `FI`, no separators |
| Subclass counts | B60C 318, B60B 298, B60D 20, B60F / B60G / B60R / B60J 1 each |
| Claims | 10,578 list items, 7,284 start with a number, 167 cancelled, 7,106 mention "claim N" |
| Description paragraphs | 42,040 list items, 20,819 empty strings, 21,221 real |
| Passage length (characters) | min 2, p10 118, median 351, p90 977, p99 1,859, max 25,013 |
| Passages under 40 characters | 373 |
| Passages over 1,600 characters | 639 |
| Total text | 15.4 million characters |
| Detected language of abstract | English for all 640 |
| Abstracts with non-ASCII characters | 73 (symbols, not foreign language) |

### Where the real data contradicts the plan

1. **Missing fields do exist.** The plan said no patent is missing anything. In fact
   119 of 640 patents have a `detailed_description` that is a list holding one empty
   string. The key is present, the content is not. So "missing" has to mean "no usable
   content", not "key absent". These 119 patents are kept and searched through their
   abstract and claims. Synthetic tests still cover the other fields, which are never
   missing in the real data.

2. **Claims are more damaged than "claim 1 has no number".** 3,294 claim items have no
   number, and only 511 patents have a single unnumbered first claim. 1,831 unnumbered
   items come after a numbered claim, and 49 patents have no numbered claim at all.
   What happened: wherever a claim was written with nested elements, the source lost
   the number and the opening words ("15 . A wheel assembly, comprising:") and kept only
   the body. So an unnumbered item is a whole claim without its preamble, at any
   position.
   - Evidence: of 1,335 runs of unnumbered items that sit before a later numbered claim,
     1,300 (97.4%) have exactly as many items as the gap in the numbering. One item per
     missing claim number.
   - **Ruling:** number an unnumbered claim as "previous claim number + 1" (not "assume 1")
     and flag it `number_inferred`. Cost if wrong: in the 35 runs where the count does not
     match the gap, an inferred number can be off. The flag is shown in the output so a
     reader knows the number was not in the source.
   - **Ruling:** prepend the patent title to every claim that lost its preamble before
     embedding (not only claim 1), because a body such as "the tire has only two belt
     plies" has no subject without it. Cost if wrong: the title pulls these claim vectors
     slightly toward each other within a patent.
   - A dependent claim that lost its preamble also lost its "according to claim N", so
     its parent claim is unknown. Parent claim numbers are stored only where the text
     states them.
   - 2 patents have explicit claim numbers that go backwards. Stored as given.

3. **The classification table stays, but for a different reason.** The data has exactly one
   code per patent, so a separate table is not needed for this dataset. I keep the
   `classifications` table anyway because I have not seen the foreign sample, and it may
   carry several codes per patent. Cost: one extra join in the filter.

### Other things confirmed

- Classification group and subgroup cannot be separated: `B60B104FI` could be `B60B 1/04`
  or `B60B 10/4`. Filtering is by prefix on the raw string, and the 4 character subclass
  is stored separately. The `FI` suffix is kept as part of the raw code.
- `bibtex` only repeats title, number, year and file name. Stored for display, not searched.
- The 6.6 GB `coding_challenge_large_data.zip` belongs to the "efficiency and large data"
  enhancement, which I did not choose. Not unpacked, not used.

## Phase B: ingest, index, embed

Commands: `python cli.py ingest data/small`, `python cli.py stats`

### Decisions

| Decision | Choice | Why |
| --- | --- | --- |
| Storage | SQLite, one file `index/patents.db` | Nothing for the reviewer to install. Real indexes and full text search (FTS5, Porter stemming). |
| Tables | `patents`, `passages`, `classifications`, `patents_fts`, `translations` | See `src/db.py`. |
| Unit of search | Passage: the abstract, each claim, each description paragraph | Claim mapping needs a specific passage as evidence, not a whole document. |
| Vectors | `embeddings.npy` (float32, normalized) plus `vector_passage_ids.npy` | A dot product over one array is the whole semantic search. No vector database needed at this size. |
| Embedding model | `intfloat/multilingual-e5-small`, 384 dimensions, 512 token input | One model for every language, so a German passage and an English query land in the same space. Chosen over `paraphrase-multilingual-MiniLM-L12-v2` because that model reads only 128 tokens and the median passage here is 351 characters with a long tail. |
| Long passages | Cut into windows of at most 1,600 characters (400 for Chinese, Japanese, Korean) at sentence boundaries | 639 passages exceed 1,600 characters, one has 25,013. Without windows the model silently drops the tail. |
| Short passages | Under 40 characters (15 for Chinese, Japanese, Korean): stored, shown, not embedded | They are equation fragments and headings such as `A-B-C (I)`. |
| Claim text for embedding | Title prepended to claims that lost their preamble | See Phase A, ruling 2. |
| Language detection | `langdetect` on the abstract, else first claim, else description, else title | Small pure Python library. Seeded, because it is random by default. |
| Short text guard | Under 20 letters (6 for Chinese, Japanese, Korean) or confidence under 0.7 gives "unknown" | A two word title or a formula is not evidence of a language. |
| Translation at ingest | Title and abstract only, and only for non-English patents | Keyword search needs English words. Two short fields are cheap. Everything else is translated only when shown. |
| Translation engine | Helsinki-NLP `opus-mt-{source}-en`, local, behind `translate.translate_texts` | No paid key, reproducible. One function to replace for a hosted model. |
| Translation cache | Table keyed by a hash of model name and text | **Ruling:** the plan said "key by passage identifier". A text hash survives a rebuild of the index and also covers titles and abstracts. Cost: none known. |
| Dates | `filing_week` from the file name, else from the date inside `filename`, else missing | The two agree for all 640. |
| Re-running ingest | Document numbers already present are skipped | Makes ingest safe to repeat and lets a second collection be added without re-embedding the first. To rebuild, delete `index/`. |
| Bad input | A file that is not JSON, or a record that is not a dictionary, is counted and skipped | One bad record must not stop a batch. |

### Missing field policy (as implemented)

- A patent is **never dropped**, whatever is missing.
- "Missing" means no usable content: key absent, null, empty string, whitespace, empty list, or a list of empty strings.
- A missing field is stored as NULL (or as zero passages) and its name is written to `patents.missing_fields`.
- Display prints `Unknown` for it.
- A filter on a missing field excludes the patent. `--include-unknown` lets it through instead.
  Without a filter on that field, the patent is searched like any other.
- No document number: the patent gets a labelled placeholder `NO-NUMBER-<file>-<position>` so it can still be shown.
- No searchable text at all: stored, counted as `no_searchable_text` in the ingest report, never matches a query.
- No claims: `similar --doc X --claim N` falls back to the abstract and says so.

### Measured

| What | Value |
| --- | --- |
| Patents ingested | 640 of 640, all detected as English |
| Patents with a missing field | 119 (empty description) |
| Passages stored | 32,272: 640 abstracts, 10,411 claims, 21,221 description paragraphs |
| Cancelled claims dropped | 167 (five different formats, for example `1 .- 15 . (canceled)`) |
| Claims with an inferred number | 3,223 |
| Claims with a stated parent claim | 7,101 |
| Passages too short to embed | 206 (65 claims, 141 description paragraphs) |
| Passages embedded | 32,066, as 32,772 vectors (long passages give several) |
| Vectors longer than 512 tokens (tail cut off by the model) | 6 of 32,772 |
| Embedding time | 99.2 s and 143.2 s on two runs (330 and 229 vectors per second), Apple M2 Pro GPU (MPS) |
| Whole ingest, wall clock | 1 min 46 s and 2 min 29 s on the same two runs |
| Index size on disk | 20 MB database, 50 MB vectors |
| Model download | about 470 MB on first run, cached by Hugging Face afterwards |

The two embedding runs differ by 44% because other work was running on the machine during the slower one. I report both rather than the better one.

### Found while building

- **Cancelled claims come in five formats.** My first pattern only caught `1 - 5 . (canceled)` and left 40 cancelled
  claims in the index as claim text. Found by looking for the word in the stored claims. Fixed, with a test for each format.

### Shortcuts and weaknesses

- A `claims` or `detailed_description` field that arrives as one string is split on line breaks only. Good enough for the
  field shapes seen so far, not a real claim splitter.
- Language is detected once per patent. A patent with an English abstract and foreign claims would be labelled English.
- A window boundary can fall in the middle of a claim element. No overlap between windows.
- `langdetect` is the weakest dependency: it is old and probabilistic. Fine for full abstracts, which is all it sees here.
- "Filing week" follows the task sheet's wording. The files look like the patent office's weekly publication files, so the
  date is more likely the publication week. It is used only as a range filter.

## Phase C: search, hybrid ranking, filters, timing

Commands:

```
python cli.py search "wheel hub with integrated pressure sensor" --cpc B60B --keywords "tire pressure" --top 10
python cli.py similar --doc 20240051333 --claim 1
python cli.py show --doc 20240051339
python scripts/benchmark.py
python -m pytest
```

### Decisions

| Decision | Choice | Why |
| --- | --- | --- |
| Inputs | Text in any language, or a document number (optionally one claim), or filters alone, or any mix | Covers "natural language", "a specific claim", "an entire patent by number" from the task sheet. |
| Output | Ranked patents, each with its single best passage as evidence | An examiner needs to see why a patent matched. |
| Semantic ranking | Dot product of the query vector with every surviving passage vector, then the best passage per patent | Exact search. No approximate index is needed below about a million vectors. |
| Keyword ranking | BM25 over English title (weight 2) and abstract, query words joined with OR, stop words removed | Catches exact part names that embeddings blur. |
| Fusion | Reciprocal rank fusion, constant 60 | Needs no score calibration between BM25 and cosine. A patent ranked first by both scores 2/61. |
| Keyword filter | Every keyword must appear in the English title or abstract, with stemming ("sensors" matches "sensor") | An examiner's keyword filter is a requirement, not a hint. Different from keyword ranking, which is a hint. |
| Title filter | Case insensitive "title contains" | 43 titles are shared, and an exact match would fail on one extra space. A full title is still a specific filter. |
| Classification filter | Prefix match on the code with spaces and slashes removed, so `B60B`, `b60b 27` and `B60B27/00` all work | The data cannot separate group from subgroup, so a prefix is the honest operation. |
| Date filter | `--from` and `--to` on the filing week | |
| Other filters | Original language, passage type | |
| Search by patent | Uses the named claim, else the abstract, else the first claim, else the first description paragraph. The source patent is removed from the results | The fallback is printed. (At this point it reused the stored vector. Phase F changed it to encode the text as a query.) |
| Filter strategy | `auto` by default, with `filter_first` and `filter_after` available as flags | See the ruling below. |

### Rulings

- **Ruling: the default is `auto`, not "always filter first".** The plan assumed filtering first always helps. Measured, it
  only helps when the filter is selective. Filtering first has to copy the surviving rows out of the matrix before scoring
  them, and copying costs more per row than scoring in place. With 100% of rows kept, filter first took 12.8 ms against
  2.7 ms. The crossover is near 15% of rows kept, so `auto` filters first below that and scores everything in place above
  it. Cost if wrong: the 15% threshold was measured on one machine and moves a little with corpus size (at 19% kept,
  filter first won on the real index and lost on the 30 times larger one).
- **Ruling: no full sort.** My first version sorted every passage score to find the best passage per patent. Scoring
  32,772 vectors then took 7.5 ms, most of it sorting. Rows of one patent are adjacent, so one pass per patent
  (`np.maximum.reduceat`) gives the same answer. Scoring dropped to 1.3 to 1.9 ms, and from 355 ms to 70 ms at 983,160
  vectors. Cost: `Index` must keep rows grouped by patent. It checks at load and regroups if needed. Tested.

### Measured (full tables in `benchmarks.md`, last run)

20 fixed queries, 5 runs each, median. Apple M2 Pro.

| What | Value |
| --- | --- |
| Semantic only, whole call | 16.6 ms |
| Hybrid (keyword and semantic fused), whole call | 16.7 ms |
| Keyword only, whole call | 1.1 ms |
| Encoding the query with the model | 13.9 to 14.8 ms, 83% to 89% of a semantic or hybrid call |
| Scoring 32,772 vectors | 1.4 to 1.6 ms |
| Keyword ranking | 0.7 ms |
| Fusing and fetching rows | 0.5 ms |
| Hybrid without the encoding step | 2.8 ms, against 1.9 ms for semantic only |
| Filter keeping 1.0% of vectors, filter and score | filter first 0.44 ms, filter after 2.59 ms (5.8 times) |
| Filter keeping 53% of vectors | filter first 7.42 ms, filter after 2.70 ms (filter first is 2.7 times slower) |
| Same at 983,160 vectors, 1.1% kept, scoring only | filter first 2.4 ms, filter after 43.1 ms (18 times) |
| Same at 983,160 vectors, 53% kept, scoring only | filter first 240 ms, filter after 69 ms |
| Command line start (load index and model) | 9.3 s cold, measured once |

Run to run variation is roughly 20% to 40% on the sub-millisecond rows: the two benchmark runs after the sort was removed gave between 1.30 and 1.91 ms
for the same unfiltered scoring step. The direction of every comparison was the same in both.

### What the numbers say

1. At 640 patents the search itself is not the cost. Encoding the query takes about 14 ms and everything else under 3 ms.
   Hybrid search adds under 1 ms to semantic search.
2. Filtering first helps in proportion to how selective the filter is, and the gain grows with corpus size: 5.8 times on
   the real index and 18 times at a million vectors for a 1% filter.
3. Filtering first hurts when the filter is not selective, because of the row copy. Hence `auto`.
4. The biggest single win was algorithmic, not about filters: removing the full sort made every query about 5 times faster.

### Things I would do, or did, to make it more efficient

Done:
- Vectors normalized once at ingest, so similarity is one matrix product.
- Filters run in SQL on indexed columns before any vector is touched.
- One pass per patent instead of a sort over all passages.
- Adaptive choice between filter first and score in place.
- Query words go to SQLite's full text index, not a scan.
- Translations cached. Result translation happens only for the rows shown.

Would do at scale:
- Cache query vectors. The encoder is 85% of the time today.
- Store vectors as 16 bit floats or 8 bit integers: half or a quarter of the memory, and memory bandwidth is the limit.
- Keep rows partitioned by classification section and language, so a common filter selects a contiguous block and needs
  no copy. That removes the crossover problem above.
- Past about a million vectors, an approximate nearest neighbour index. Approximate indexes lose recall under selective
  filters, so: exact search when the filtered set is small (as measured here, it is fast), approximate search otherwise.
- Cap the keyword query at the rarest dozen terms.

### Found while building

- **Exact score ties are real.** Some patents share identical passages (same applicant, same wording), so two patents can
  tie to the last digit. Filter first and filter after then returned the tied patents in different orders. The
  benchmark's own equality check caught it. Fixed by making tie order deterministic, with a regression test.

### Tests

76 tests at this point (89 by the end), about 1 second, no model download (the embedding model and translator are replaced by small fakes).
`tests/test_missing_fields.py` deletes or empties each of 7 fields in 6 different ways (42 cases) and checks the patent is
still ingested, still found, and shown as `Unknown`. Further tests cover each filter with and without `--include-unknown`.

### Shortcuts and weaknesses

- Search by patent reused vectors that were embedded as passages, slightly off the model's intended use. Changed in
  Phase F: the text is now encoded as a query.
- A non-English query got no help from the keyword side, which only knows English words. Changed in Phase F: the query
  is translated to English first.
- The fusion constant (60) and the title weight (2) are defaults, not tuned.
- Ranking quality on English is not evaluated here beyond the known-item test in Phase F.
- Keyword ranking sends every query word to the full text index. Fine at this size.
- Every command line call loads the model again (about 9 s cold, 0.1 s for commands that need no model).
- Part 2 of the benchmark copies real vectors with noise. It measures arithmetic cost at a million vectors, not retrieval
  quality at that size.

## Phase D: scale design (`docs/scale_design.md`)

Drafted in a separate session from the measured numbers above, then checked line by line. I recomputed the vector
counts, byte sizes, GPU hours, translation totals and both monthly totals by hand. They add up.

Headline numbers (US dollars, prices checked 16 November 2026):

| | Phase 1: abstract and claims, 174 million vectors | Phase 2: full text, 512 million vectors |
| --- | --- | --- |
| One-time, hosted translation of title and abstract | $25,170.58, of which $22,080 is translation | $25,265.03 |
| Monthly | $3,829.05 | $9,784.05, or $3,863.55 if descriptions get no approximate index |
| Embedding all of it on a rented GPU | $48.62 (48.3 GPU hours) | $94.45 more |
| Translating all full text up front instead (rejected) | $720,000 | |

What matters in it:
- Compute is not where the money goes. The database instance is 76% of the phase 1 monthly bill.
- Translating two short fields costs 32.6 times less than translating everything, and search needs neither.
- The route rule: exact search when a filter leaves under about 1 million vectors, approximate index otherwise.
  That rule comes straight from the Phase C measurements and the Phase E finding.

Weak points, stated in the document itself:
- **Unverified prices.** The managed database prices ($4.00 and $12.00 per hour) and its disk price come from third party
  price trackers, not from the provider's own page. They carry $3,035 of the $3,829 monthly total. Marked "No" in the
  price sources table. The GPU, machine, disk, Azure and Amazon translation prices were read from the providers' own
  price files.
- **11 assumptions**, numbered A1 to A11, including a 30% foreign share (nothing to base it on) and an index size of
  1.5 times the vector bytes.
- **The SQL in the document was not run.** Only the proof of concept's statement was.
- Half precision vectors and iterative index scans are designed in but have never been run in this project.

**Ruling:** passages are partitioned by passage type rather than by classification section or language as the plan
suggested, because that makes phase 2 purely additive. Language is the second level to add (see Phase F). Cost if wrong: a filter on classification section does
not skip partitions.

## Phase E: proof of concept (`poc/`, `docker-compose.yml`)

Built in a separate session. Loads the real index into PostgreSQL with pgvector and runs the hybrid query as one SQL
statement: classification prefix, keyword match, vector ordering, best passage per patent.

**What was actually run:** Docker is not installed on this machine, so the Docker path has **not** been run. The script
was run against an embedded PostgreSQL 16.2 with pgvector 0.6.2 from the `pgserver` package (`--pgserver DIR`).

Measured (median of 15 runs, on a busy machine, so read as "about"):

| What | Result |
| --- | --- |
| Load 640 patents and 32,772 vectors with COPY | 8.3 s |
| Build all indexes | 6.2 s |
| Exact statement | 10 rows, 1.15 ms |
| Planner left alone | 10 rows, 1.14 ms, chose not to use the vector index |
| Forced onto the approximate index, default setting | **6 rows instead of 10** |
| Forced onto the approximate index, largest setting | **8 rows instead of 10**, 11.1 ms |
| Agreement with the Python search | same 10 patents, same order, largest score difference 1.2e-07 |
| Vector index size | 59 MB for a 68 MB table |

The useful finding: with a selective filter (12 patents pass), the approximate index silently returns too few results,
because it hands over a capped number of rows and the filter runs afterwards. The missing patents' best passages rank
1,130th and 2,214th among all vectors. This is the "filtered approximate search loses recall" challenge, reproduced on
640 patents.

Not done:
- Docker path not run. The image tag was only checked to exist.
- Iterative index scans (the fix in newer pgvector) not run: the embedded pgvector is too old.
- The statement uses keywords as a filter only. Rank fusion in SQL is sketched in the design document, not run.

## Phase F: machine translation enhancement and evaluation

Commands:

```
python scripts/make_parallel_set.py          # 100 English patents into German and Chinese
python cli.py ingest data/parallel           # same ingest as the English data
python scripts/evaluate_multilingual.py      # writes eval_results.md
python scripts/compare_models.py             # is the gap a property of the small model?
```

I forgot to ask for the real non-English sample. Everything below is measured on a **synthetic** set: 100 English
patents machine translated into German and Chinese. `data/foreign/` is the place for the real sample; it goes through
the same `python cli.py ingest data/foreign` with no code change, as far as I can tell without seeing its format.

### The main finding: the plan's core assumption was wrong

The plan said: embed every language with one multilingual model, text lands in one shared vector space, so an English
query finds a German passage with no translation. I built that, measured it, and it fails.

Test: the first claim of a patent, in English, is the query. Claims are removed from the candidates. The right answer is
the same patent's abstract or description, in English, German or Chinese. "Mixed" means the 100 test patents in one
language plus the 540 other English patents. MRR is mean reciprocal rank.

| Mixed corpus | English target | German target | Chinese target |
| --- | --- | --- | --- |
| Semantic, shared space (the plan) | 0.930 | 0.007 | 0.003 |
| Hybrid, shared space (the plan) | 0.945 | 0.059 | 0.034 |
| Keyword only (translated title and abstract) | 0.964 | 0.906 | 0.719 |
| **Semantic, query translated** | 0.930 | 0.912 | 0.920 |
| **Hybrid, query translated (the default now)** | 0.945 | 0.921 | 0.933 |

Recall at 10 for a German or Chinese target in the mixed corpus was 0.00 with the shared space: not one of 200
foreign targets reached the first page. With query translation it is 0.99.

Diagnosis, in the order the plan asked for (model, truncation, translation noise):

- **Model: language bias. This is the cause.** Two unrelated passages in the same language score higher than a passage
  and its own translation. Measured on abstracts: English against a different English patent averages 0.831 (99th
  percentile 0.900). English against the same patent in German averages 0.851, in Chinese 0.809. So 27.5% of all other
  English abstracts outscore a patent's own German copy, and 76.2% outscore its own Chinese copy. On clean hand-written
  sentences the effect is the same: an exact German translation of the query scored 0.803, an unrelated English sentence
  about trailer hitches 0.778.
- **Is it the small model?** Partly. `scripts/compare_models.py`, abstracts only, mixed corpus, MRR for a German /
  Chinese target: `multilingual-e5-small` 0.017 / 0.008, `multilingual-e5-base` 0.110 / 0.028, `BAAI/bge-m3`
  (1,024 dimensions) 0.310 / 0.099. English stays near 0.91 for all three. A model with 2.7 times the storage gets a
  third of the way there. A bigger model is not the fix.
- **Truncation: no.** 0 to 5 vectors per language exceed the model input.
- **Translation noise: real but secondary.** With no English distractors ("alone", 100 candidates in one language) the
  shared space still only reached 0.409 (German) and 0.210 (Chinese) against 0.982.

### Rulings

- **Ruling: search each language with the query translated into that language.** `search()` detects the query language,
  translates the query to English if needed, then from English into each language that still has patents after the
  filters, and scores every passage against the query in its own language. Passages are still embedded in their original
  language and never translated for search, so the cost argument of the plan holds: only the short query is translated.
  The plan's approach is kept as `--cross-lingual shared` so the comparison stays reproducible.
  Cost if wrong: search now depends on translating a short query well, and adds one translation and one encoding per
  language to an uncached query.
- **Ruling: search by patent now encodes the claim or abstract text as a query** instead of reusing its stored vector, so
  it goes through the same translation path. Cost: `similar` needs the model loaded.
- **Ruling: Chinese, Japanese and Korean are detected by script, not statistics.** The statistical detector labelled only
  79 of 100 Chinese abstracts as Chinese (10 Korean, 11 unknown). Those 21 were then translated with the wrong model or
  not at all. Counting characters by script gets 100 of 100. Tested.
- **Ruling: greedy decoding for queries and for building the test set**, beam width 4 for what a person reads (title,
  abstract, displayed passages). Measured on the laptop GPU for English to German: 3,577 characters per second greedy,
  705 with beam width 4.
- **Ruling: the query is translated only into languages that survive the filters.** `--language en` costs nothing extra.

### Measured

Building the test set (`make_parallel_set.py`):

| What | Value |
| --- | --- |
| Patents | 100, chosen at random (seed 0) from 505 that have a description and a first claim of at least 150 characters |
| Characters translated | 2,778,802 per language |
| Time | German 395 s (7,035 characters per second), Chinese 458 s (6,062), whole script 14 min 15 s |

Ingesting it (`cli.py ingest data/parallel`):

| What | Value |
| --- | --- |
| Patents | 200 (100 German, 100 Chinese), all detected correctly after the script rule |
| Title and abstract translated to English | 100,829 characters in 224.9 s: 448 characters per second (one patent at a time, beam width 4) |
| Vectors | 11,870 from 11,389 passages in 47.2 s. 5 exceed the model input |
| Whole ingest | 4 min 37 s |
| Index after both ingests | 840 patents, 43,739 passages, 44,642 vectors |

Evaluation (`eval_results.md`, full tables there). Gap is MRR minus the English MRR, with a 95% paired bootstrap interval:

| Setting, hybrid, query translated | English | German (gap, interval) | Chinese (gap, interval) |
| --- | --- | --- | --- |
| Alone (100 candidates) | 0.990 | 0.972 (-0.018, -0.038 to -0.003) | 0.966 (-0.024, -0.047 to -0.005) |
| Mixed (640 candidates) | 0.945 | 0.921 (-0.023, -0.059 to +0.009) | 0.933 (-0.012, -0.053 to +0.028) |

The other direction, a foreign query against the 640 original English patents. This is the fairest test here: the
query is translated to English by a different model than the one that made the copies, and has to match text a person wrote.

| Query language | Semantic, shared | Semantic, query translated | Hybrid, query translated |
| --- | --- | --- | --- |
| English | 0.930 | 0.930 | 0.945 |
| German | 0.591 | 0.900 | 0.917 |
| Chinese | 0.051 | 0.770 | 0.862 |

Query language was detected correctly for 100 of 100 German and 100 of 100 Chinese claims.

Cost of query translation (laptop on battery in Low Power Mode, so read these as slow-side numbers):

| What | Value |
| --- | --- |
| Claim-length query (median 667 characters) into 2 languages, not cached | median 1,340 ms, slowest 8,760 ms (includes loading the models) |
| Same, cached | 0.05 ms |
| Bulk query translation | 249,808 characters in 47 s (5,330 characters per second) |

### So, does it "perform comparably"?

**Superseded.** The answer below was too generous. See "Found by using it" near the end of this file: merging raw
scores across languages favoured Chinese, and the test in this section could not see it.

- English query, foreign patents, mixed corpus: yes on this test set. The German and Chinese intervals both include zero
  and the gap is 1 to 2 points of MRR.
- Foreign query, English patents: German yes (0.917 against 0.945). **Chinese no: 0.862 against 0.945**, and 0.770
  against 0.930 without keywords. Two machine translations in a row (English to Chinese to make the patent, Chinese to
  English for the query) lose too much.

### What this evaluation does not show (read before trusting the table)

- **The test set is machine translated, not real.** Real German and Chinese patents are written by people, use the
  proper legal vocabulary, and are messier.
- **The good German and Chinese rows are an upper bound.** The copies were made by the same opus-mt models that then
  translate the query. Query and document share that model's wording more than they would with real patents. The
  foreign query table does not have this flaw, which is why I call it the fairest.
- **Same patent matching is a stand-in for relevance.** A patent's description often repeats its claim nearly word for
  word, which makes the English baseline easy. This measures "can it find the same invention", not "does it rank prior
  art well".
- 100 queries. The intervals are about plus or minus 4 points of MRR.
- One technical field (vehicle wheels and tires), two foreign languages.
- Scores from different languages are merged without calibration. No offset showed up here, on machine translated text.

### Translation quality, seen while building

Search no longer depends on translating documents, only display does. That matters, because the translations are rough:

- The title `SPOKE` became `Sprecher` (German: speaker) and `发声` (Chinese: to make a sound), shown back in English as
  "Speaker" and "Make a sound." The model read "spoke" as the past tense of "speak".
- All capital titles came out as garbage at first (`SPOKE` became `GESAMT`, and a run of `SPOK SPKO SPOK`). 93 of 100
  titles changed once capitals were lower-cased before translation. Fixed and tested.
- The Chinese model translated "claim" as `索赔` (a claim for compensation) instead of `权利要求`. So the parent of a
  dependent claim was found for 1,215 of 1,712 claims in English and German, and for 0 of 1,712 in the machine made
  Chinese. Real Chinese claims use `权利要求`, which the parser handles (tested), so this is a property of the test set.
- Displayed results read like "70 to 92 hours of a solution polymerised styrene butadiene rubber" for "parts per hundred".
  Good enough to decide whether to read the original. Not good enough for legal use.

### Shortcuts and weaknesses

- Translation at ingest runs one patent at a time (448 characters per second). Batching across patents would be several
  times faster: the same models did 6,000 to 7,000 in bulk.
- A non-English query goes to other languages through English, so it is translated twice.
- A language with no opus-mt model falls back to the English query vector for its passages, which is the shared space
  that was just shown not to work. It prints a warning.
- Query language detection is deliberately cautious (40 letters, 90% confidence) and treats short queries as English.
  `--query-language` overrides it.
- The first search after start loads a translation model per language (seconds).
- Timings in this phase after the first evaluation were taken on battery in Low Power Mode.

## Independent review, and what it changed

After Phase F I had the code and the README reviewed by a fresh reader with no part in writing them, with one
instruction: find bugs, and find claims the evidence does not support. It found both. All fixes below have a test that
failed first.

Bugs fixed:

| Finding | Effect before the fix | Fix |
| --- | --- | --- |
| A keyword filter made only of common words (`--keywords first`) was dropped | The search ran unfiltered and said nothing | The filter now uses every word. Only keyword *ranking* ignores common words |
| Dates were compared as raw text | `--from 2024-6-1` or `06/01/2024` silently gave wrong results | Dates must parse as ISO dates, otherwise an error |
| `--types` was silently ignored in keyword only and filters only searches | The abstract was shown as evidence whatever was asked | Refused with an error where it cannot apply |
| Placeholder document numbers could collide | Two numberless records in files of the same name in different folders: the second was skipped | The placeholder includes the collection and the folder |
| A translation model that failed to load was treated as "translated" | Foreign text was stored as the English title, and keyword search on it was silently broken | Stored as "no English version", counted in the ingest report, labelled when shown |
| Search by patent counted itself | "840 patents passed the filters" where 839 did | Counted correctly |
| The evaluation's "not cached" timing | True only on the first run against an index | Measured straight on the models, never through the cache |

Not changed, by decision:
- **Ruling: `--types description` does not return patents that have no description, even with `--include-unknown`.**
  The passage type option restricts what may be shown as evidence. Returning a patent with other evidence would break
  what was asked. The README now says this option is not a field filter. Cost if wrong: a user who wants "description
  matches, plus anything whose description is unknown" has to run two searches.

Claims corrected in the README and DECISIONS (the measurements were right, the sentences were too strong):
- "Not one of 200 foreign targets reached the first ten" is true for semantic search on the shared space. With keywords
  fused in, 19 of 200 did.
- "Filtering first helps more as the corpus grows" holds for very selective filters (under about 3% kept). For a filter
  keeping 11% the advantage shrank at a million vectors, and at 19% it reversed.
- "Removing the sort made every query 5 times faster" was the scoring step (7.5 ms to 1.4 ms). The whole call went from
  about 22 ms to about 16 ms, because encoding the query dominates.
- "The model scores unrelated English passages above a translation" is true for 27.5% of pairs (German) and 76.2%
  (Chinese), not on average for German.
- The foreign query test is the least flattering one, but it is still a round trip of the patent's own claim.
- Counts refreshed after the cancelled claim fix: 3,223 inferred claim numbers (not 3,225), 206 passages too short to
  embed (not 246).
- On this test, keyword only search is as good as or better than hybrid for English (0.964 against 0.945). The
  description and abstract of a patent repeat the words of its claim, which suits keywords. Hybrid is not tuned.

## Final check from scratch

What I did: `git clone` of this repository into an empty directory, a new virtual environment from
`requirements.txt`, the data taken from the original archive with the README's `unzip` command, then every command in
the README, in README order, copied literally. The committed `benchmarks.md` and `eval_results.md` are the files this
run wrote.

What happened:

1. First attempt, on the code before the review fixes: Part 1 ran clean. I stopped it during Part 3 because the review
   had come back and I was about to change code.
2. Second attempt, on the fixed code: everything ran until `scripts/evaluate_multilingual.py`, which **failed**. One
   of my review fixes (refusing passage types in keyword only search) broke a call inside the evaluation. No unit test
   covered the script. Fixed, and a test now runs every evaluation method on a small index.
3. Resumed from the evaluation step in the same clone, after emptying the translation cache there so the evaluation
   started cold. Ran to the end, exit code 0.

So the README commands have all run on the final code, but not in one unbroken pass: steps up to the German and Chinese
ingest ran on the commit before the last fix (which touched only the evaluation script and a test), and the rest ran
on the final commit.

Deviations from the README text:
- The proof of concept's data folder was in my scratch directory, not `/tmp/patent-poc-pgdata`.
- The embedding and translation models were already in the Hugging Face cache, so download time is not included in
  any time below. Sizes on disk: embedding model 493 MB, four translation models about 600 MB each (2.45 GB).
- The laptop was on battery in Low Power Mode. The power state during Phases B and C was not recorded.

Not covered by this check: the Docker path, a machine with no cached models, a machine without a GPU, another
operating system.

Numbers from this run, next to the earlier ones:

| What | Final run | Earlier runs |
| --- | --- | --- |
| Embedding 32,772 vectors | 237.0 s (138 per second). The laptop was partly idle during this step, so read it as a worst case | 99.2 s, 101.5 s, 123.5 s, 143.2 s |
| Whole `ingest data/small` | 8 min 45 s | 1 min 46 s to 2 min 29 s |
| Command line start | 7.7 s typical, 56.6 s once right after the slow ingest | 9.3 s |
| Benchmark script | 2 min 46 s | 2 min 42 s |
| Semantic / hybrid / keyword, whole call | 16.3 / 16.7 / 1.2 ms | 16.6 / 16.7 / 1.1 ms |
| Scoring 32,772 vectors, no filter | 1.57 to 1.83 ms | 1.30 to 1.99 ms |
| 1% filter, filter and score, first against after | 0.41 against 2.14 ms (5.3 times) | 0.44 against 2.59 ms (5.8 times) |
| Same at 983,160 vectors, scoring only | 3.0 against 61.2 ms (20.5 times) | 2.3 against 43.1 ms (18.6 times) |
| 53% filter, first against after | 6.64 against 2.40 ms | 7.42 against 2.70 ms |
| Tests | 90 passed in 1.2 s | |
| Building the German and Chinese set | 398 s and 500 s (6,989 and 5,558 characters per second), 15 min 0 s in all | 395 s and 458 s, 14 min 15 s |
| `ingest data/parallel` | 4 min 48 s: 100,823 characters translated in 225.9 s (446 per second), 11,870 vectors in 50.0 s | 4 min 37 s, 448 per second, 47.2 s |
| Evaluation script | 3 min 59 s | |
| Evaluation tables | identical to Phase F in every MRR to three decimals | |
| Query translation, claim-length, 2 languages, models loaded | median 1,218 ms, slowest 2,114 ms. Cache hit 0.06 ms | median 1,340 ms (measured differently, see the review section) |
| Bulk query translation | 265,822 characters in 48 s (5,511 per second) | |
| Foreign query table, new intervals | German hybrid gap -0.028 (-0.056 to -0.006). Chinese hybrid gap -0.082 (-0.138 to -0.030) | |
| Proof of concept, re-run by me with 840 patents loaded | exact 10 rows in 1.31 ms, approximate index 6 rows, largest setting 8 rows in 12.4 ms, same 10 patents as the Python search | 640 patents: 1.15 ms, 6 rows, 8 rows in 11.1 ms |

One more thing the check showed. With the German and Chinese copies in the index, the same English query run both ways:
the default returns a Chinese patent at rank 3 (shown in English), and `--cross-lingual shared` returns five English
patents and no foreign one. That pair of commands is the shortest demonstration of the main finding.

## Left on this machine

- Model files in the Hugging Face cache (`~/.cache/huggingface`): the models above, plus `multilingual-e5-base`
  (1.1 GB) and `BAAI/bge-m3` (4.6 GB) from `compare_models.py`, and `opus-mt-ko-en` (0.6 GB), downloaded by mistake when
  the first language detector called some Chinese abstracts Korean.
- `psycopg` and `pgserver` installed into `.venv` for the proof of concept.

## Found by using it: scores from different languages are not on one scale

After everything above was committed and checked, the first real query typed into the tool
(`"wheel hub with integrated pressure sensor" --cpc B60B`) came back with two Chinese patents in the top five, both
irrelevant, both displayed as a word repeated dozens of times. Two separate defects.

### Defect 1: translating the query was not enough. Raw scores cannot be merged.

Each language has its own score level. Mean similarity between a query and a fixed random sample of 2,000 passages of
the same language, nearly all unrelated to the query:

| Queries | English | German | Chinese |
| --- | --- | --- | --- |
| 20 short queries | 0.793 | 0.799 | 0.847 |
| 100 claim-length queries | 0.809 | 0.825 | 0.869 |

So a Chinese passage starts about 0.05 ahead of an English one before relevance counts for anything. My evaluation in
Phase F asked one question, "is the right foreign patent found among English ones?", and a method that scores foreign
patents too high passes that question. It never asked the opposite one.

Two tests added to `scripts/evaluate_multilingual.py`, and what they show for the version I had shipped (raw scores):

| Test | Raw scores | Calibrated |
| --- | --- | --- |
| English search, 100 Chinese patents added, semantic (MRR, was 0.930) | 0.730 | 0.920 |
| Same, hybrid (was 0.945) | 0.908 | 0.950 |
| English search, 100 German patents added, hybrid | 0.953 | 0.945 |
| 20 short queries, top 10 each: English / German / Chinese versions of the test patents, semantic | 4 / 2 / 154 | 19 / 40 / 18 |
| Same, hybrid | 16 / 8 / 65 | 24 / 20 / 9 |

- **Ruling: scores are compared relative to each language's own level.** For each query, the sample of each language is
  scored against that language's version of the query. A passage's score becomes (score - sample mean) / sample
  spread, and patents are merged on that. The similarity shown to the user is still the plain one. The raw merge stays
  available as `--cross-lingual uncalibrated` so the comparison can be re-run.
  Cost if wrong: it assumes most sampled passages are unrelated to the query and that languages cover the same mix of
  topics. True here by construction. Not guaranteed on real data.
- I tried three other ways first. Subtracting the mean only: English 0.940, German 0.827, Chinese 0.415 on the "is it
  found" test, and it over-corrects. Scaling between the background and the query's similarity to itself: 0.812 and
  0.741. Scaling to the top 1% of the background: 0.815 and 0.805. Mean and spread was the best balance of the two
  questions (0.890 and 0.804 here, and no harm to English).
- A language with fewer than 200 embedded passages borrows English's level. Shortcut, marked in the code.

### What "comparable" looks like now (final run, hybrid, calibrated, the default)

| Test | English | German | Chinese |
| --- | --- | --- | --- |
| Right patent, alone in its language | 0.990 | 0.972 (-0.018, -0.038 to -0.003) | 0.966 (-0.024, -0.046 to -0.005) |
| Right patent among 540 other English patents | 0.945 | 0.908 (-0.037, -0.073 to -0.002) | 0.801 (-0.143, -0.200 to -0.091) |
| Recall at 1 / at 10 in that test | 0.90 / 1.00 | 0.86 / 0.99 | 0.71 / 0.96 |
| English search after adding that language | 0.945 | 0.945 (+0.001) | 0.950 (+0.005) |
| Query in that language, English patents | 0.945 | 0.917 (-0.028, -0.056 to -0.006) | 0.895 (-0.050, -0.095 to -0.009) |

German is 2 to 4 points behind everywhere. Chinese is clearly behind when it has to compete with English patents.
The Phase F figure of 0.933 for Chinese was inflated by the offset this section describes. The honest figure is 0.801.

Why I believe the calibrated numbers more: they agree with the one test that never depended on merging languages. In the
foreign query test all candidates are English, and there German was 3 points behind and Chinese 5 to 11.

### Defect 2: the translation model gets stuck, and my test set was full of it

The English to Chinese model sometimes repeats one word until it hits the length limit. 284 of 5,733 Chinese test
passages (5%) contained such a run, so did some German ones. The display then translated the run faithfully
("wheel wheel wheel wheel ..."). The cause was in my own test set builder, not in search.

- **Ruling: a translation that repeats the same few letters six or more times in a row is translated again** with
  repeated three word sequences forbidden. Tested on the two passages from the bad output: both come out readable.
  Applied everywhere translation is used (building the test set, ingest, queries, display).
- After rebuilding the test set: 0 of 5,734 German and 0 of 5,733 Chinese passages are stuck.
- Cleaning the test set changed some numbers. The Chinese query test rose from 0.862 to 0.895 (hybrid) and from 0.770
  to 0.824 (semantic), because Chinese claims used as queries are no longer garbled. The shared space numbers alone in
  one language rose a little (German 0.409 to 0.459, Chinese 0.210 to 0.227).

### Third check from scratch

Fresh clone, new virtual environment, every README command in order, this time in one unbroken pass, exit code 0.
On battery in Low Power Mode.

| What | Value |
| --- | --- |
| Embedding 32,772 vectors | 129.4 s. Whole `ingest data/small` 2 min 16 s |
| Benchmark | 2 min 54 s. Semantic 15.9 ms, hybrid 17.0 ms, keyword 1.2 ms |
| 1% filter, first against after | 0.40 against 1.64 ms (4.1 times). At 983,160 vectors 3.9 against 65.9 ms (17 times) |
| Tests | 93 passed in 1.2 s (525 since the independent test pass, see the last section) |
| Building the German and Chinese set, with retries | 403 s and 552 s (6,902 and 5,034 characters per second), 15 min 56 s in all |
| `ingest data/parallel` | 5 min 31 s: 100,183 characters translated in 223.1 s (449 per second), 11,827 vectors in 44.5 s |
| Evaluation | 5 min 40 s |
| Query translation, claim-length, 2 languages | median 1,224 ms, slowest 3,056 ms. Cache hit 0.05 ms. Bulk 5,814 characters per second |
| Proof of concept, 840 patents | exact 10 rows in 1.31 ms, approximate index 6 rows, largest setting 8 rows, same 10 patents as the Python search |
| Model comparison, re-run on the rebuilt set (German / Chinese target, mixed, abstracts only) | e5-small 0.017 / 0.008, e5-base 0.110 / 0.025, bge-m3 0.310 / 0.099 |

The benchmark has now been run five times since the sort was removed. The direction of every comparison was the same
each time. The size of the advantage moved: a 1% filter was 3.2, 5.8, 5.7, 5.3 and 4.1 times faster on the real index,
and 18.6, 18.6, 20.2, 20.5 and 17.1 times at a million vectors.

### What I take from this

The evaluation was honest about being synthetic and still wrong about the conclusion, because it measured one side of
the question. I did not find that by reviewing the numbers or by the independent review. I found it by typing a query.
The test that would have caught it is now in the evaluation, and both README demonstrations were re-chosen: the old
pair (a Chinese patent appearing at rank 3) was itself an example of the bias.

## Independent test pass, and what it changed (17 November 2026)

An independent tester ran a full test pass on commit `de3fe99` and changed nothing under `src/`. The report is
`TEST_REPORT.md`, the work list `TEST_RESULTS_FOR_BUILDER.md`, the scripts and results are in `scripts/testing/`, and
three test files went into `tests/` (429 tests, 12 of them failing when they arrived). Verdict: ready with fixes.
This section is what I did with each item, in the order worked, one commit per step. Earlier sections of this file
describe the project as it was before; where a number below disagrees with one above, the one below is current.

### M4. The keyword filter passed patents that do not contain the keyword

- Found: `--keywords generator` passed 27 patents, one of which contains the word. The filter and the ranking shared one
  stemmed full text table, and the stemmer files generator, general, generally and generic under one stem.
- **Ruling:** a second full text table without stemming (`patents_words`), read only by the filter. The filter matches
  the word, or its plain plural or singular ("sensor" passes "sensors"), and nothing wider. Ranking keeps the stemmed
  table. Cost if wrong: a user who expects "bearing" to pass "bears" no longer gets that from the filter.
- **Ruling:** an index built before this change is filled the first time it is opened. The tester suggested a rebuild
  and a README note. Filling it costs four lines and removes the chance that an old index silently passes nothing.
- Measured on the 840 patent index: `generator` now passes 3 patents (the same invention in three languages), all
  containing the word. `general` passes none.
- Test renamed from `..._uses_word_stems` to `..._matches_whole_words`, with the new behaviour in it.

### M1. Hybrid, the default, was worse than the better single mode on all four known-answer tests

- Found (tester's `backtest.py`, 200 queries per test, MRR): hybrid was behind the better of keyword-only and
  semantic-only by 4, 60, 4 and 4 points. Cause: the keyword list reads only title and abstract and had the same vote
  as the passage-level list.
- Done: a weight for the keyword list in the fusion (`KEYWORD_WEIGHT`), swept on tests A and B with
  `scripts/tune_keyword_weight.py` (table in `scripts/testing/results/keyword_weight_sweep.md`):

| Keyword weight | A: claim 1 to patent | B: abstract to claims | C: title to patent | D: dependent claim to patent |
| --- | --- | --- | --- | --- |
| keyword only | 0.931 | 0.208 | 0.760 | 0.701 |
| semantic only | 0.873 | 0.970 | 0.958 | 0.887 |
| 1.0 (what shipped) | 0.889 | 0.374 | 0.917 | 0.844 |
| 0.5 | 0.888 | 0.427 | 0.947 | 0.858 |
| 0.2 | 0.890 | 0.518 | 0.962 | 0.885 |
| 0.1 | 0.887 | 0.615 | 0.963 | 0.894 |
| 0.05 | 0.884 | 0.735 | 0.960 | 0.891 |
| 0.02 | 0.878 | 0.896 | 0.958 | 0.889 |
| 0.01 and below | 0.873 | 0.970 | 0.958 | 0.887 |

- The sweep ran before the m4 fix. On the final code (`results/backtest_english_after_fixes.json`, run in the fresh
  clone) A, B and D are unchanged and C is 0.963 for semantic and for hybrid, because titles in capitals are no longer
  taken for another language and sent through a translator. Hybrid minus the better single mode, final: A -0.052
  (interval -0.089 to -0.017), B -0.074 (-0.097 to -0.051), C 0.000, D +0.002.
- What it says: the smaller the weight, the better on B, and nothing gained on A (hybrid never exceeds 0.892 there,
  against 0.931 for keywords alone). From 0.01 down the fused ranking is the semantic ranking. No weight is within
  2 points of the better single mode on all four tests.
- **Ruling (the rule was given to me: if no weight gets within 2 points, semantic becomes the default):** semantic is
  the default mode in `search()` and on the command line. Hybrid stays as an option at 0.02, the largest weight that
  stays near the best worst case and still changes results (21 of 50 test queries get a different top ten than semantic).
  Cost if wrong: see "fresh queries" below, where the old default looks better on one subset.
- Consequence I had not planned for: a patent with no passage long enough to embed (a title only) cannot be returned by
  the default search, because semantic search ranks passages. Keyword and hybrid mode and the filters still find it. No
  real patent is in that state (0 of 840). A test now states this behaviour.
- Consequence for Part 3: the default's numbers are the semantic rows of `eval_results.md`, a little lower than the
  hybrid rows I reported before (English 0.930, was 0.945), and the short-query balance is worse (German versions 40,
  English 19, Chinese 18, where the old default had 20, 24 and 9).
- Tests that encoded the equal vote were changed, each with a comment saying why: the fused score, the fused top 3,
  the reciprocal rank formula, and "something from both lists reaches the top ten", which is now "hybrid is the
  semantic list with keyword matches moved up a little".

### M3. The tool never says it found nothing

- Done: a query with no letters or digits is refused, like an empty one.
- Measured (`scripts/testing/offtopic_check.py`, 30 queries, 5 of them off topic): how far the best result stands
  above the per-query background sample that calibration already scores. Off-topic queries: 4.0 to 5.2 spreads. Real
  queries: 2.9 to 6.2. 22 of the 25 real queries are at or below the highest off-topic one. Plain similarity separates
  better (off-topic 0.826 to 0.848, real 0.839 to 0.924) and still overlaps, on 5 examples.
- **Ruling:** no warning. A threshold set on five examples with overlapping ranges would be a guess. Written up as a
  limitation.

### M5. Two filters scanned every patent, and the headline speed-up left the filter's cost out

- Done: the classification filter is a range on the code index. `EXPLAIN QUERY PLAN` before: `SCAN p`. After:
  `SEARCH p USING INTEGER PRIMARY KEY` with `SEARCH classifications USING INDEX idx_classifications_code (code>? AND code<?)`.
  A test reads the plan of the statement the search really runs.
- Done: `benchmarks.md` has a third part, the whole search on a real index 10 times the size (built with the tester's
  `perf.py scale`), and every filter row shows the time of its SQL filter alone.
- Measured at 10 times the size: the 1% title filter is 2.1 times faster than filtering afterwards (7.84 ms against
  16.22 ms), not 13. Its SQL scan takes 6.44 ms of that, 24 times its time on the real index. The 2.9% classification
  filter, now on an index, is 3.2 times faster (3.22 ms against 10.45 ms) with 0.32 ms of SQL.
- Not done: the title filter is still a scan. The README says what it costs. The scale design uses a trigram index.

### Minors

| Item | What changed |
| --- | --- |
| m1 | `similar --claim 999` says "abstract (claim 999 not found or too short)" where it used to fall back silently |
| m2 | `--top 0` or less is refused. `-1` used to return everything but the last result |
| m3 | A keyword filter with no letters or digits is refused. So is such a classification filter |
| m4 | Text in capitals is lower-cased before language detection: of the 640 English titles typed as queries, 41 were taken for German, Vietnamese or Somali, now none. At ingest a title is only used when there is no other text, and must then pass the stricter test used for queries: 15 of 640 were still labelled foreign with the usual one, none with the stricter one |
| m5 | A null inside a classification list is no longer stored as the code `NONE` |
| m6 | The ingest log names each patent that has no searchable text |
| m8 | The README's `--show-original` example now has `--language zh`, so it prints original text |

- **Ruling, against the tester on one point of m4:** "do not load a model for a language the index does not hold" is
  not done. A German or Japanese query against an English index needs exactly that model, and the tester's own forward
  test depends on it. With capitals handled, the case that triggered the download is gone.
- The claim-number check quoted in the README was not reproducible ("1,300 of 1,335"; the tester counted 1,308 of
  1,312). `scripts/inspect_data.py` now prints it with a stated definition: 1,335 runs of unnumbered claims followed by
  a numbered claim, 1,331 of them as long as the gap in the numbering. My earlier count did not treat a cancelled
  range as using up its numbers. Both recounts find 4 mismatches.

### M2. Chinese and Japanese queries on fresh queries

- Found: on 10 new everyday-language queries in five languages, Chinese and Japanese queries reach about half and a
  third of the relevance of English ones. My own evaluation shows a small gap because its query is a machine
  translation of the target's own claim.
- Compared, as asked, three ways of handling a foreign query and beam width 4, on the 40 foreign-language queries
  against the English patents (`scripts/testing/forward_variants.py`, mean relevance of the top 5 on a 0 to 2 scale):

| Way | German | Spanish | Chinese | Japanese | All 40 | Queries with a result scored 2 | Difference to current (95% interval) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Translate, greedy (current) | 0.74 | 0.66 | 0.38 | 0.22 | 0.500 | 6 | |
| Translate, beam width 4 | 0.76 | 0.66 | 0.46 | 0.26 | 0.535 | 9 | +0.035 (-0.010 to +0.095) |
| Original query embedded, no translation | 0.34 | 0.56 | 0.04 | 0.58 | 0.380 | 7 | -0.120 (-0.255 to +0.030) |
| Both fused | 0.66 | 0.66 | 0.40 | 0.48 | 0.550 | 9 | +0.050 (-0.025 to +0.130) |

- **Ruling:** the default stays. Neither higher score is distinguishable from the current one on 40 queries. Beam
  width 4 doubled the translation time of these short queries (median 240 ms against 112 ms; 3 to 5 times on a full
  claim, measured in Phase F) and did not fix the failures it was meant to fix: "It's a very simple process." is still
  what two Japanese queries become, and one became "It's a tire. It's a tire. It's a tire.". The fused version gains
  only where translation fails outright (Japanese) and leans on the direct embedding, which scored 0.04 for Chinese
  here and 0.051 MRR in my own test. Cost if wrong: about 0.04 of mean relevance on foreign queries.
- Judging. Three blind judges (separate model instances that saw query, title and passage, not rank, language or
  variant) scored the 465 result items the tester's judges had not seen. I hid 45 of the tester's items among them: 38
  came back with the same score and 7 one point lower. So before and after would not have been comparable, and the same
  judges re-scored all 365 of the tester's items: 328 identical, 37 one point apart (28 of those from 1 down to 0),
  none two apart, mean 0.567 against the tester's 0.647. Every number in this section and in the README's fresh-query
  subsection uses that one set (`scripts/testing/results/forward_judgments_builder.json`).
- Before and after on the 840 patent index, same judges (mean relevance, queries of 10 with a result scored 2):

| Query language | Old default (fused, equal votes) | New default (semantic) |
| --- | --- | --- |
| English | 0.84, 6 | 0.68, 4 |
| German | 0.78, 4 | 0.76, 4 |
| Spanish | 0.74, 5 | 0.70, 4 |
| Chinese | 0.46, 2 | 0.34, 1 |
| Japanese | 0.30, 0 | 0.24, 0 |

- **What this says about M1, and I did not expect it.** The switch to semantic is not confirmed by the fresh queries.
  All 30 English queries: 0.720 to 0.833 on the English index (+0.113, interval -0.033 to +0.267), 0.760 to 0.747 on the
  840 patent index (-0.013, -0.153 to +0.127). The 10 general English queries on the 840 patent index: 0.84 to 0.68
  (-0.16, interval -0.30 to -0.02). The 40 foreign queries there: 0.570 to 0.510 (-0.06, -0.14 to +0.03). Part of the
  English loss on that index is German copies: 9 of the 50 top-five results are German versions with a mean score of
  0.22, against 5 before. Semantic gains on misspelled queries (0.40 to 0.84 on the English index), where keywords cannot
  match at all. I kept the rule I was given and list the default as open.

### Documented, not fixed (M6, M7, m7, m9, m10, m11)

All in the README: section 7 for the loss of numbers in Chinese display (38 of 100 passages keep every number) and for
the three reasons the English baseline is easier than it reads; section 8 for letter case in semantic search, the
"contains" title filter and keywords that are never a phrase, one result slot per language version of an invention
(0.64 of 10 on the 840 patent index with the new default, 0.93 before), and unpinned `torch`, `transformers` and model
files.

### Document corrections

Every row of the tester's table is applied. In `docs/scale_design.md`: 25.2 kB, 328.0 GB (and the sums that use it:
340.3, 675.7, 1,327.4 and 938.0 GB), the slowest laptop embedding run is 138 vectors per second, not 229 (worst case
$352.34 for phase 1, was $212.33), 6,067 characters per second, the benchmark figures are the ones in the committed
`benchmarks.md`, the 1% filter row no longer contradicts the one million rule, re-embedding is said not to fit in
1,000 GB (grow the disk to 1,300 GB first), and the per-language step filters on `patents.language`. Changing 25.1 to
25.2 kB moves the raw file store from 251 to 252 GB and every monthly total by 3 cents ($3,829.05 and $9,784.05). The
SQL sketch there weights the keyword list 0.02, as Part 1 now does. The tester's `check_cost_arithmetic.py` was updated
to the corrected document and passes on all its rows.

### Final numbers after these changes (regenerated, not edited)

| What | Value |
| --- | --- |
| Tests | 525 (96 mine, 429 from the tester), about 4 s |
| `ingest data/small` | 133.2 s, of which embedding 127.6 s (257 vectors per second) |
| Search, 640 patents: semantic (default) / hybrid / keyword | 15.4 / 16.3 / 1.2 ms, of which encoding the query 13.7 ms |
| 1% title filter, first against after, real index | 0.54 against 1.33 ms (2.5 times), SQL filter 0.27 ms |
| The same on a real index 10 times the size | 7.84 against 16.22 ms (2.1 times), SQL filter 6.44 ms |
| 2.9% classification filter, 10 times the size | 3.22 against 10.45 ms (3.2 times), SQL filter 0.32 ms |
| Scoring step alone at 983,160 vectors, 1% filter | 2.4 against 32.5 ms (13 times). Unfiltered scan 36.3 ms (73.7 ms in the run before, same laptop, on battery with Low Power Mode on both times; I do not know why) |
| `ingest data/parallel` | 289 s: 100,183 characters translated in 221.5 s, 11,827 vectors in 57.4 s |
| Evaluation | 337 s |
| Default (semantic, query translated, calibrated): right patent alone in its language, English / German / Chinese | 0.982 / 0.964 / 0.945 |
| The same among 540 other English patents | 0.930 / 0.890 / 0.792 |
| English search after adding that language's 100 patents | 0.930 / 0.930 / 0.920 |
| A query in that language against the 640 English patents | 0.930 / 0.900 / 0.824 |
| 20 short queries, versions in the top ten | 19 / 40 / 18 |
| Query translation, claim-length, 2 languages | median 1,278 ms, slowest 3,242 ms, cache hit 0.07 ms |

### Still open

1. Which ranking should be the default (M1 against the fresh queries). Needs relevance judged by people on more queries.
2. Chinese and Japanese queries. Needs a better translation model for the query.
3. No "nothing found" signal.
4. German copies over-represented on short queries with the semantic default (40 against 19 English).
5. Everything that needs a person: the video, the public repository, the Docker path, the real foreign sample.

### Fourth check from scratch (after the independent test pass)

Fresh clone of commit `98a30da` (the last one that changes code), new virtual environment, every README command in
order in one pass, then the tester's own checks on the indexes the clone had just built. Exit code 0, 52 minutes, on
battery with Low Power Mode on. The commits after `98a30da` change documents, the regenerated tables and the tester's
arithmetic checker only.

| What | Result |
| --- | --- |
| `ingest data/small` | 2 min 44 s |
| The four Part 1 searches, `show` | ran, results as the README describes |
| `benchmark.py`, with the new 10 times part | 2 min 54 s |
| `python -m pytest` | 525 passed in 4.1 s |
| Tester's real-index tests, English index | 83 passed |
| Tester's backtest, English index | A 0.931 / 0.873 / 0.879, B 0.208 / 0.970 / 0.896, C 0.760 / 0.963 / 0.963, D 0.701 / 0.887 / 0.889 (keyword / semantic / hybrid). Its own fusion agrees with `search()` on every query |
| `make_parallel_set.py` | 17 min 37 s |
| `ingest data/parallel` | 4 min 43 s |
| `evaluate_multilingual.py` | 5 min 34 s. Every quality number identical to the committed `eval_results.md` |
| The four Part 3 searches | same invention at ranks 1, 3 and 5; with `--cross-lingual shared` only the English one; `--language zh --show-original` prints the Chinese text |
| Tester's real-index tests, mixed index | 83 passed |
| Tester's backtest, mixed index | default 0.930 / 0.890 / 0.792 for an English, German, Chinese target among English patents, the same as `eval_results.md` |
| Proof of concept, embedded PostgreSQL | exact 10 rows, approximate index 6, largest setting 8, same 10 patents in the same order as the Python search |

Not run in this check: the Docker path (Docker is not installed here), `compare_models.py` (optional, 5.7 GB of
models), and the tester's `perf.py` and `translation_checks.py` (their figures in the README are the tester's own).

## History rewritten once (17 November 2026)

After the repository went public, the script for the video was taken out of it, including out of every earlier
commit, because it is working material and not part of the submission. That changed the hash of 17 of the 26 commits.
Nothing else in any commit changed: same files, same authors, same dates, same messages.

| Named before | Same commit now | Where it is named |
| --- | --- | --- |
| `8afc1df` | `de3fe99` | The commit the independent tester ran on: this file, `TEST_REPORT.md`, `TEST_RESULTS_FOR_BUILDER.md`, `scripts/testing/forward_compare.py` |
| `da3d6ef` | `98a30da` | The commit of the fourth check from scratch: this file |

The hash is the only thing changed in the tester's two reports. No command reads the removed file, so the checks
recorded above hold for the new commits.
