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
   `classifications` table anyway because the foreign sample has not arrived and may
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
| Claims with an inferred number | 3,225 |
| Claims with a stated parent claim | 7,101 |
| Passages too short to embed | 246 (105 claims, 141 description paragraphs) |
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
| Search by patent | Uses the stored vector of the named claim, else the abstract, else the first claim, else the first description paragraph. The source patent is removed from the results | No model call needed. The fallback is printed. |
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

Run to run variation is roughly 20% on the sub-millisecond rows: the three benchmark runs I made gave 1.30, 1.43 and 1.91 ms
for the same unfiltered scoring step. The direction of every comparison was the same in all three.

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

76 tests, about 1 second, no model download (the embedding model and translator are replaced by small fakes).
`tests/test_missing_fields.py` deletes or empties each of 7 fields in 6 different ways (42 cases) and checks the patent is
still ingested, still found, and shown as `Unknown`. Further tests cover each filter with and without `--include-unknown`.

### Shortcuts and weaknesses

- Search by patent reuses vectors that were embedded as passages. The model was trained with separate "query" and
  "passage" prefixes, so this is slightly off the intended use. Not measured.
- A non-English query gets no help from the keyword side, which only knows English words. Hybrid search then leans on the
  semantic ranking alone.
- The fusion constant (60) and the title weight (2) are defaults, not tuned.
- Ranking quality on English is not evaluated here beyond the known-item test in Phase F.
- Keyword ranking sends every query word to the full text index. Fine at this size.
- Every command line call loads the model again (about 9 s cold, 0.1 s for commands that need no model).
- Part 2 of the benchmark copies real vectors with noise. It measures arithmetic cost at a million vectors, not retrieval
  quality at that size.
