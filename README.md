# Patent passage search, in any language

Take-home for Thinkstruct. Part 1 is a hybrid search engine over patent passages. Part 2 is a design for 10 million
patents with a small proof of concept. Part 3 is the machine translation enhancement: ingest, search and display
patents that are not in English.

**Video (2 minutes, Parts 2 and 3):** link to be added.

Everything measured here was measured on an Apple M2 Pro laptop (10 cores, 16 GB). The full log of decisions, numbers
and known weaknesses is in [NOTES.md](NOTES.md). The eight decisions that matter most are in [DECISIONS.md](DECISIONS.md).

An independent test pass was run on this project ([TEST_REPORT.md](TEST_REPORT.md), work list in
[TEST_RESULTS_FOR_BUILDER.md](TEST_RESULTS_FOR_BUILDER.md)). Its findings changed the default ranking, the keyword and
classification filters and several numbers below. What changed and what is still open is the last section of
[NOTES.md](NOTES.md). Both reports describe the code as it was before those changes.

## 1. The problem I chose

> Given a description of an invention, or any attribute of a known patent, find the most relevant passages in patent
> applications written in any language, let an examiner narrow the results with filters, and show every result in English.

- **Input:** a sentence or a pasted draft claim in any language, or a document number (optionally one claim of it), or
  filters alone, or any mix.
- **Filters:** classification code prefix, keywords in title or abstract, title, filing week range, original language,
  passage type (claim, abstract, description).
- **Ranking:** by meaning (semantic search over passages) by default. `--mode keyword` ranks by words in title and
  abstract, `--mode hybrid` fuses the two. Section 3 says why semantic is the default.
- **Output:** ranked patents. Each comes with the one passage that matched best (a specific claim or paragraph), its
  score, classification, filing week and language. Anything not in English is shown in English, with the original one
  flag away. A missing field is shown as `Unknown`.
- **Out of scope:** patents outside the dataset, drawings, legal status, translation good enough for legal use.

Why passages and not whole patents: claim mapping needs to point at the claim or paragraph that overlaps, not at a document.

## 2. Quick start

Needs Python 3.11. No web interface, no paid keys, no services to start.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

If a command below fails with `ModuleNotFoundError`, your shell is probably running a different Python: an alias such
as `alias python=/usr/bin/python3` wins over the virtual environment. `which python` should end in `.venv/bin/python`.
If it does not, run `unalias python`, or type `python3` instead of `python` in the commands below.

Put the 64 `patents_ipa*.json` files from the provided archive in `data/small/`:

```bash
mkdir -p data/small
unzip -j path/to/the_small_archive.zip '*.json' -d data/small
```

### Part 1: build the index and search

```bash
python cli.py ingest data/small
python cli.py search "wheel hub with integrated pressure sensor" --cpc B60B --top 5
python cli.py search "tire tread that reduces road noise" --keywords "noise" --from 2024-06-01 --to 2024-12-31 --top 5
python cli.py search --title "pneumatic tire" --cpc B60C11 --top 5
python cli.py similar --doc 20240051333 --claim 1 --top 5
python cli.py show --doc 20240051339
python scripts/benchmark.py
python -m pytest
```

- `ingest` takes 2 to 4 minutes on my laptop. It embeds 32,772 passage vectors, which took between 99 s and 237 s over
  six runs (the slowest on battery in Low Power Mode). The first run downloads the embedding model, 493 MB.
- `search` and `similar` take about 10 seconds to start, almost all of it loading the model. The search itself takes
  about 15 ms.
- `benchmark.py` takes about 3 minutes, needs about 3 GB of free memory and 0.6 GB of temporary disk (it builds an
  index 10 times the size and deletes it), and rewrites `benchmarks.md`. Run it before Part 3, so it measures the
  English index alone.
- The 525 tests need no model and take about 4 seconds.
- An index built by an earlier version of this code is upgraded the first time it is opened (one table is added for the
  keyword filter). It does not have to be rebuilt.
- Dates are ISO dates (`2024-06-01`). A query in Latin letters shorter than 40 letters is treated as English;
  `--query-language de` overrides that. Chinese, Japanese and Korean queries are recognised by their script.
- From Python: `from src.search import Index, search`, then `search("...", cpc_prefix="B60B", index=Index())`.

### Part 3: foreign patents

```bash
python scripts/make_parallel_set.py
python cli.py ingest data/parallel
python scripts/evaluate_multilingual.py
python cli.py search "tyre monitor with an energy harvester that charges the sensor" --top 5
python cli.py search "tyre monitor with an energy harvester that charges the sensor" --top 5 --cross-lingual shared
python cli.py search "pressure sensor that reports tire pressure to the driver" --language de --top 3
python cli.py search "轮辋上带有压力传感器的车轮" --language zh --top 3 --show-original
python cli.py show --doc 20240083200-ZH
```

- `make_parallel_set.py` machine translates 100 of the English patents into German and Chinese (about 16 minutes) and
  writes them to `data/parallel/`. It downloads two translation models, about 600 MB each.
- `ingest data/parallel` takes about 5 minutes and downloads two more translation models.
- `evaluate_multilingual.py` takes 6 to 9 minutes and rewrites `eval_results.md`.
- The first search returns the same invention three times in its top five, in English (rank 1), German (rank 3) and
  Chinese (rank 5), all shown in English. The second is the same query with the approach that failed (section 7): only
  the English one is found.
- The first search after start loads a translation model per language, which adds a few seconds.
- Optional: `python scripts/compare_models.py` repeats a small version of the test with two larger embedding models.
  It downloads 5.7 GB.

**The real non-English sample.** The task says to request it. It had not arrived when this was built, so Part 3 runs
on the machine translated set above, and section 7 says what that does and does not prove. When the real files arrive,
put them in `data/foreign/` and run `python cli.py ingest data/foreign`. The ingest accepts the field names from the task
sheet as well as the ones in the provided files, detects the language, and needs no code change as far as I can tell
without having seen the files.

### Part 2: proof of concept

```bash
docker compose up -d --wait
pip install -r poc/requirements.txt
python poc/load_and_query.py
docker compose down
```

Without Docker, the same script can start an embedded PostgreSQL:

```bash
pip install -r poc/requirements.txt
python poc/load_and_query.py --pgserver /tmp/patent-poc-pgdata
```

I only ran the second form. Docker is not installed on my machine, so the Docker path is written but untested.
The numbers in [poc/README.md](poc/README.md) were measured with the 640 English patents loaded. Run after Part 3, the
script loads all 840.

## 3. How it works

A picture of the whole project is in [docs/architecture.md](docs/architecture.md).

| Step | What happens | Where |
| --- | --- | --- |
| Normalize | Accept either set of field names, treat empty content as missing, never drop a patent | `src/ingest.py` |
| Claims | Number each claim, drop cancelled ones, note the parent of a dependent claim | `src/ingest.py` |
| Language | Detect once per patent. Chinese, Japanese and Korean by script, the rest statistically | `src/translate.py` |
| Translate at ingest | Title and abstract only, foreign patents only, so English keyword search works | `src/translate.py` |
| Embed | Every passage in its original language, one multilingual model, long passages in windows | `src/embed.py` |
| Store | SQLite (tables, two full text indexes, translation cache) plus one NumPy array of vectors | `src/db.py` |
| Filter | In SQL, before vectors are scored. Classification, keywords, dates and language use indexes; "title contains" reads every title (section 5 says what that costs) | `src/search.py` |
| Translate the query | Into each language that survived the filters. Short, cached | `src/search.py` |
| Semantic ranking | Each passage scored against the query in its own language, best passage per patent | `src/search.py` |
| Calibrate | Each language's scores put on one scale before languages are merged | `src/search.py` |
| Keyword ranking | Only with `--mode keyword` or `--mode hybrid`: BM25 over English title and abstract, words stemmed | `src/search.py` |
| Fuse | Only with `--mode hybrid`: reciprocal rank fusion, the keyword list weighted 0.02 | `src/search.py` |
| Display | Translate what is shown to English, on demand, cached | `cli.py` |

Main choices, each with the reason:

| Choice | Why |
| --- | --- |
| SQLite plus a NumPy array | Nothing to install or start. Exact search over 33,000 vectors takes under 2 ms, so an index structure would add nothing |
| `intfloat/multilingual-e5-small` | One model for about 100 languages, reads 512 tokens (the common alternative reads 128), small enough for a laptop |
| Translate the query, not the documents | Measured: one shared vector space does not work across languages (section 7). The query is short, the corpus is not |
| Compare scores relative to each language's own level | Measured: unrelated Chinese passages score higher against a Chinese query than unrelated English ones against an English query. Merged raw, Chinese patents crowd out English ones (section 7) |
| Translate only title and abstract at ingest | Keywords need English words. Translating all text for 10 million patents would cost about 33 times more ([scale design](docs/scale_design.md)) |
| Semantic ranking by default, keyword fusion as an option | Measured: fusing the keyword ranking in was worse than the better of the two alone on four known-answer tests, at every weight (below) |
| Never drop a patent | Dropping one silently hides prior art |

### Semantic, keyword or both: what was measured

My first version fused a keyword ranking and the semantic ranking with equal votes, and that was the default. The
independent tester built four tests where the right answer is known from the data (200 queries each, the 640 English
patents, `scripts/testing/backtest.py`). Mean reciprocal rank, 1.0 means always first:

| Test | Keyword only | Semantic only | Fused, equal votes (the old default) | Fused, keyword weight 0.02 (`--mode hybrid` now) |
| --- | --- | --- | --- | --- |
| A: claim 1 finds its own patent, its own claims removed | 0.931 | 0.873 | 0.889 | 0.879 |
| B: abstract finds its own claims, the abstract removed from the keyword table | 0.208 | 0.970 | 0.374 | 0.896 |
| C: title finds the patent | 0.760 | 0.963 | 0.917 | 0.963 |
| D: dependent claim finds the patent that holds its parent | 0.701 | 0.887 | 0.844 | 0.889 |

The old default's column is the tester's measurement on the code as it was. The other columns are from the code as it
is now (`scripts/testing/results/backtest_english_after_fixes.json`); semantic search on C was 0.958 then and is 0.963
now, because titles in capitals are no longer mistaken for another language.

The fused ranking was behind the better single mode on all four, by 60 points on B. The reason: the keyword ranking
reads only title and abstract, the semantic ranking reads every passage, and both had the same vote. A patent ranked
first by meaning and absent from the keyword list scored below a patent ranked 50th in both.

I gave the keyword list a weight and swept it on tests A and B (`python scripts/tune_keyword_weight.py`, table in
`scripts/testing/results/keyword_weight_sweep.md`). The smaller the weight, the better, and from 0.01 down the keyword
list no longer changed a single result. No weight puts the fused ranking within 2 points of the better single mode on
all four tests. So:

- **Semantic is the default.** It is level with the better mode on B, C and D, and 5.7 points behind keyword search on A.
- **`--mode keyword`** is the better choice when the query repeats a patent's own words, as in A.
- **`--mode hybrid`** stays as an option with the keyword list weighted 0.02: semantic ranking, with keyword matches
  settling near-ties. It is also the mode that can return a patent that has nothing to embed (section 4).

The fresh queries of section 7 do not settle it the same way. On the tester's 30 new English queries, with the top 5
judged for relevance on a scale of 0 to 2, semantic scored 0.83 against 0.72 for the old default on the English index
(difference +0.11, 95% interval -0.03 to +0.27), and 0.75 against 0.76 once the German and Chinese copies are in the
index. On the 10 everyday-language queries among them, on that second index, the old default was better: 0.84 against
0.68 (interval for the difference -0.30 to -0.02). So the known-answer tests favour the switch clearly, the fresh
queries are neutral overall, and one subset points the other way. It is listed as open in section 8.

### The filters, precisely

- `--cpc`: the classification code starts with this prefix.
- `--keywords`: every word must appear in the English title or abstract, as a whole word. "sensor" also passes
  "sensors" and the reverse, and nothing wider: "general" does not pass "generally". Several words are never a
  phrase, quoted or not.
- `--title`: the title contains this text, upper or lower case. It is not an exact match: `--title TIRE` returns every
  title with the word in it.
- `--from`, `--to`: filing week, both ends included. `--language`: the patent's original language.
- `--types`: which passages may be searched and shown as evidence.
- A query, a keyword filter or a classification filter with no letters or digits is refused, and so is `--top 0`.

### What the data really looks like

The provided files differ from the task sheet, and handling that was a real part of the work:

- Field names are `title`, `doc_number`, `abstract`, `detailed_description`, `claims`, `bibtex`, `classification`,
  `filename`. Both naming styles are accepted.
- **119 of 640 patents have an empty description** (a list holding one empty string).
- **3,223 claims have no number and no opening words.** Where a claim was written with nested elements, the source kept
  only the body ("an axle body, having a middle segment ...") and lost "1 . A spoke, comprising:". This happens at any
  position, not only claim 1. In 1,331 of 1,335 places where it can be checked, the count of such claims equals the gap
  in the numbering (`python scripts/inspect_data.py` prints this), so each gets "previous number plus one", and the
  output marks the number as inferred. The patent
  title is put in front of these claims before embedding so they have a subject.
- 167 cancelled claims in five formats are removed.
- Classification is one code such as `B60B104FI`. Group and subgroup cannot be told apart (`1/04` or `10/4`), so the
  filter is a prefix match: `--cpc B60B`, `--cpc "B60B 27"`.
- 21,000 of 42,000 description list items are empty strings, and one paragraph has 25,013 characters.

## 4. Patents with missing fields

**Choice: handle them, never exclude them.** The rule is implemented in `src/ingest.py` and `src/search.py` and proven in
`tests/test_missing_fields.py`.

| Situation | What happens |
| --- | --- |
| A field has no usable content (key absent, null, empty, whitespace, empty list, list of empty strings) | Stored as missing, listed in `patents.missing_fields`, displayed as `Unknown`. The patent is searched through the text it does have |
| A filter is on a field the patent is missing | The patent is left out of that search. `--include-unknown` lets it through, because "not known" is not "no" |
| No such filter is used | The patent is searched like any other |
| No document number | Kept under a labelled placeholder, `NO-NUMBER-<collection>/<file>-<position>` |
| No text at all | Kept, counted in the ingest report and named in the ingest log. It can be shown, and cannot match a query |
| No passage long enough to embed, for example only a title | Kept. Found by `--mode keyword`, `--mode hybrid`, `--title` and `--keywords`. The default semantic search ranks passages, so it cannot return it. No real patent is in this state |
| The user asks for patents similar to a claim the patent does not have | Falls back to the abstract and says so: "Searching with the abstract (claim 999 not found or too short)" |
| A file is not valid JSON, or a record is not a dictionary | Counted and skipped. The rest of the batch continues |
| A foreign patent in a language with no translation model | Kept and searched in its own language. Stored with no English title or abstract, counted in the ingest report, and labelled "not translated" when shown |

The real data only has one kind of missing field (the 119 empty descriptions). So the tests delete or empty each of
7 fields in 6 different ways (42 cases) on synthetic records and check that the patent is still ingested, still found,
and printed with `Unknown`. More tests cover the classification, keyword, title, date and language filters with and
without `--include-unknown`. The independent test pass added its own (`tests/test_independent_*.py`): each of 6 fields
removed in 4 ways, and 48 odd values such as `0`, `{}` and `[None]`. The passage type option is not a field filter: it restricts which passages may be shown as
evidence, so a patent with no description cannot appear when only descriptions are asked for.

## 5. Timing with and without hybrid search

"Hybrid search" in the task is semantic search plus filters, so the question here is what the filters cost and save.
The optional keyword fusion (`--mode hybrid`) is timed too. Full tables: [benchmarks.md](benchmarks.md). 20 fixed
queries, 5 runs each, median, 640 patents, 32,772 vectors.

| | Whole call | Of which encoding the query | Everything else |
| --- | --- | --- | --- |
| Semantic, no filters (default) | 15.4 ms | 13.7 ms | 1.7 ms |
| Semantic and keyword fused (`--mode hybrid`) | 16.3 ms | 13.8 ms | 2.5 ms |
| Keyword only | 1.2 ms | none | 1.0 ms |

Search with filters, filter and scoring steps only. "SQL filter" is the filter query alone and is part of each column
to its right:

| Filter | Vectors kept | SQL filter | Filter first | Filter after | Auto (default) |
| --- | --- | --- | --- | --- | --- |
| none | 100% | | 1.30 ms | | |
| classification `B60C` | 53% | 0.34 ms | 4.83 ms | 1.52 ms | 1.53 ms |
| keyword `rubber` | 11% | 0.12 ms | 1.09 ms | 1.21 ms | 1.03 ms |
| classification `B60D` | 2.9% | 0.05 ms | 0.36 ms | 1.06 ms | 0.30 ms |
| title contains `wheel bearing` | 1.0% | 0.27 ms | 0.54 ms | 1.33 ms | 0.42 ms |

The same on a real index 10 times the size (6,400 patents, 327,720 vectors: every row copied 10 times). This includes
the SQL filter, which the next table does not:

| Filter | Vectors kept | SQL filter | Filter first | Filter after | First against after |
| --- | --- | --- | --- | --- | --- |
| none | 100% | | 12.02 ms | | |
| classification `B60C` | 53% | 4.95 ms | 56.88 ms | 16.94 ms | 0.3 times |
| keyword `rubber` | 11% | 0.92 ms | 10.77 ms | 11.43 ms | 1.1 times |
| classification `B60D` | 2.9% | 0.32 ms | 3.22 ms | 10.45 ms | 3.2 times |
| title contains `wheel bearing` | 1.0% | 6.44 ms | 7.84 ms | 16.22 ms | 2.1 times |

The scoring step alone, on the vectors copied 30 times (983,160 vectors, no SQL):

| Filter | Vectors kept | Filter first | Filter after | First against after |
| --- | --- | --- | --- | --- |
| none | 100% | 36.3 ms | | |
| classification `B60C` | 53% | 152.9 ms | 39.2 ms | 0.3 times |
| keyword `rubber` | 11% | 29.6 ms | 33.1 ms | 1.1 times |
| classification `B60D` | 2.9% | 7.4 ms | 35.2 ms | 4.8 times |
| title contains `wheel bearing` | 1.0% | 2.4 ms | 32.5 ms | 13 times |

What I take from this:

1. **At this size the search is not the cost.** Encoding the query is about 90% of a call (13.7 of 15.4 ms). Fusing
   the keyword ranking in adds under 1 ms.
2. **Filtering first helps in proportion to how selective the filter is, and only if the filter itself is cheap.** On
   the real index a filter that keeps 1% to 3% of the vectors made the filter and scoring steps 2.5 to 2.9 times faster.
   At 10 times the size, with the SQL filter included, it was 2.1 times for the title filter and 3.2 times for the
   classification filter. The two differ because of the filter's own cost. The classification filter is a search on an
   index (0.32 ms). The title filter reads every title: its time grew 24 times with a 10 times larger table (0.27 ms to
   6.44 ms) and became the largest step of that search. The scoring step on its own, at a million vectors, is 13 times
   faster with the 1% filter (2.4 ms against 32.5 ms), but that number leaves the filter's cost out, so it is an upper
   bound and not what a user would see. This is how hybrid search helps performance at scale: a selective filter that
   runs on an index is cheap and removes most of the expensive work. A filter without an index gives much of that back.
3. **Filtering first hurts when the filter is not selective.** It has to copy the surviving rows out of the matrix, and
   copying costs more per row than scoring in place. With 53% kept it was 3 times slower. So the default is `auto`:
   filter first when under 15% of vectors survive, score in place otherwise. My initial plan said "always filter
   first"; the measurement said otherwise.
4. **The biggest win was not about filters.** My first version sorted every passage score to find the best passage per
   patent. Replacing the sort with one pass per patent made the scoring step about 5 times faster (7.5 ms to under
   2 ms). The whole call went from about 22 ms to about 16 ms, because encoding the query dominates.

These numbers are from the last run. Absolute times at a million vectors were about half those of the run before
(36.3 ms for the unfiltered scan, against 73.7 ms) on the same laptop, on battery with Low Power Mode switched on both
times. I do not know why, so read the ratios, not the milliseconds. I have run the benchmark eight times in all. Every
comparison pointed the same way each time, but the ratios moved too: the 1% filter was between 2.5 and 6 times faster
on the real index, and between 13 and 21 times on the scoring step at a million vectors.

Done to make it efficient: vectors normalized at ingest, filters in SQL before scoring, the classification filter as a
range on an index, one pass instead of a sort, the adaptive strategy, cached translations, the query translated only
into languages that survive the filters.

Would do at scale: a trigram index for "title contains" (the scale design has one), cache query vectors, store vectors
in 16 bits, keep rows partitioned by language and classification section so a common filter is a contiguous block with
no copy, and use an approximate index only when the filtered set is large. The proof of concept shows why that last
rule is needed: forced onto PostgreSQL's approximate index with a filter that 12 patents pass, the query returned 6 of
the 10 right answers (the "filtered approximate search" problem).

## 6. Part 2: the same engine for 10 million patents

[docs/scale_design.md](docs/scale_design.md) is written for an intern to start from: components, tables, three
pipelines, error handling, tracking, cost with every step of the arithmetic, challenges, and an ordered build list.

- **Design:** one PostgreSQL with the pgvector extension holds metadata, full text and vectors, so the hybrid query is
  one SQL statement and nothing can drift apart. A status table doubles as the work queue.
- **Cost, phase 1 (abstract and claims, 174 million vectors):** about $25,200 once, of which $22,080 is translating
  title and abstract for an assumed 30% foreign share with a hosted service, and about $3,800 a month, of which 76% is
  the database machine. Embedding all of it is 48 GPU hours, about $49.
- **Translating all full text up front would cost $720,000.** Translating two short fields and the query does the job.
- **Unverified:** the managed database prices come from third party trackers, not the provider's own page. They carry
  most of the monthly total and are marked as unverified in the document.
- **Proof of concept:** [poc/](poc/README.md) loads the real index into PostgreSQL and runs classification prefix,
  keyword match and vector ordering as one statement. It returns the same 10 patents in the same order as the Python
  search. It also reproduces the main challenge at scale on 640 patents: a selective filter on an approximate index
  silently returns too few results.

## 7. Part 3: machine translation, and why

I picked machine translation because it is the enhancement where a wrong design is cheapest to build and most expensive
to live with. Translate everything to English, and search quality depends on translation quality forever, and the bill
scales with the corpus. I wanted to find out what the minimum translation is.

I got it wrong twice before getting it right, and both mistakes were found by measuring, so they are part of the result.

**The test set.** 100 patents that exist in English, German and Chinese: the English originals, and machine translated
copies. The 100 were drawn at random from the 505 that have a description and a first claim of at least 150 characters.
The query is the first claim in English. Claims are not candidates, so the right answer is the same patent's abstract or
description. The number is mean reciprocal rank, MRR (1.0 means always first). All rows are semantic search, the
default; the tables with keyword and fused search are in [eval_results.md](eval_results.md).

### First design: one shared vector space. It cannot find foreign patents.

Embed every language with one multilingual model, and an English query finds a German passage with no translation. That
was the plan. It is in the code as `--cross-lingual shared`.

| The right patent, among 540 other English patents | English | German | Chinese |
| --- | --- | --- | --- |
| Shared space | 0.930 | 0.007 | 0.003 |

Not one of the 200 foreign targets reached the first ten results.

Why: the model has a language bias. Two unrelated passages in the same language often score higher than a passage and
its own translation. 27.5% of all other English abstracts outscore a patent's own German copy, and 76.5% outscore its
own Chinese copy. It is not truncation (0 to 4 vectors per language are too long). It is only partly the small model:
on a cut-down version of the test, `multilingual-e5-base` reached 0.110 for German and `BAAI/bge-m3`, with 2.7 times the
storage, 0.310.

### Second design: translate the query. It finds them, and then lets them take over.

Translate the query into each language in the index and score each passage against the query in its own language. The
documents are never translated for search. On the same test this looked like success:

| The right patent, among 540 other English patents | English | German | Chinese |
| --- | --- | --- | --- |
| Query translated, raw scores | 0.930 | 0.912 | 0.935 |

I reported that as "comparable". It was not. I found out by using the tool: an English query about wheel hubs came back
with unrelated Chinese patents near the top. The test above only asks "is the right foreign patent found?". It never
asks "do wrong foreign patents get in the way?". Two more tests do:

| Raw scores | Result |
| --- | --- |
| English search, after adding 100 Chinese patents to the corpus | MRR falls from 0.930 to 0.730 |
| 20 short English queries, top 10 each: English, German, Chinese versions of the same 100 patents | 4, 2 and 154 |

Why: each language has its own score level. An unrelated Chinese passage scores 0.847 on average against a Chinese
query. An unrelated English passage scores 0.793 against the English query. Merged as they are, Chinese patents win on
that offset alone. The good Chinese number in the table above was partly that same offset.

### Third design, the default: translate the query, and compare scores relative to each language's own level.

For each query, a fixed sample of 2,000 passages per language is scored first. Every score is then expressed as how far
it stands above its own language's sample, in units of that sample's spread, and languages are merged on that scale.

| Query translated, calibrated (default) | English | German | Chinese |
| --- | --- | --- | --- |
| The right patent, alone in its language (100 candidates) | 0.982 | 0.964 | 0.945 |
| The right patent, among 540 other English patents | 0.930 | 0.890 | 0.792 |
| English search after adding 100 patents in that language | 0.930 | 0.930 | 0.920 |
| A query in that language, against the 640 English patents | 0.930 | 0.900 | 0.824 |
| 20 short queries: versions of the test patents in the top 10 | 19 | 40 | 18 |

### So, is it comparable?

- **Adding foreign patents costs English search almost nothing.** 0.930 before, 0.930 with the German patents added
  and 0.920 with the Chinese ones (interval for that change -0.025 to 0.000).
- **German: close on this test.** 2 to 4 points of MRR behind English in every row, with intervals that reach zero
  (for example -0.040, 95% interval -0.084 to +0.001).
- **Chinese: not yet.** Searched on its own it is 4 points behind. A Chinese patent among English ones is found
  first 70% of the time against 89% for English (MRR 0.792 against 0.930, interval for the gap -0.193 to -0.089),
  though it is still in the top ten 96% of the time. As a query language it is 11 points behind here (0.824 against
  0.930), and much further behind on fresh queries (next subsection).
- **Short queries do not treat the languages alike.** The same 100 patents exist once per language, and their German
  versions come back twice as often as their English ones (40 against 19, Chinese 18). The calibration removes the
  large Chinese advantage of the raw scores (154) and leaves a smaller German one. The keyword vote of the old default
  hid part of this (24, 20 and 9).

Translating a claim-length query into two languages took a median of 1.3 seconds with the models already loaded, and
under 0.1 ms once cached (measured on battery with Low Power Mode on, so probably on the slow side).

### Fresh queries in five languages: where it is not comparable

The test above searches with a patent's own first claim. The independent tester wrote 10 new queries in everyday words
("a spare wheel that takes less room in the trunk"), each also in German, Spanish, Chinese and Japanese, and had the
top 5 results judged for relevance: 0 unrelated, 1 same area, 2 directly relevant. On the index with all 840 patents,
with the default search:

| Query language | Mean relevance of the top 5 (0 to 2) | Queries of 10 with a directly relevant result | Top 10 shared with the English query |
| --- | --- | --- | --- |
| English | 0.68 | 4 | |
| German | 0.76 | 4 | 5.3 of 10 |
| Spanish | 0.70 | 4 | 5.1 of 10 |
| Chinese | 0.34 | 1 | 3.7 of 10 |
| Japanese | 0.24 | 0 | 1.9 of 10 |

- **German and Spanish queries do as well as English ones. Chinese is at half and Japanese at a third.** Spanish and
  Japanese are not in my own evaluation at all.
- **My own "query in that language" row above cannot see this.** Its query is a machine translation of the target
  patent's own claim, which a translation model handles far better than a sentence an inventor would type.
- **The loss is in translating the query.** The language was detected correctly for all 70 searches. But two of the
  ten Japanese queries were translated to "It's a very simple process.", and in Chinese tread "grooves" became a
  "ditch".

The tester's finding came with a suggestion, so I compared three ways of handling a query that is not in English, and
a wider translation search (beam width 4), on the 40 foreign-language queries against the English patents
(`scripts/testing/forward_variants.py`):

| Way | German | Spanish | Chinese | Japanese | All 40 | Directly relevant result | Difference to the current way (95% interval) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Translate to English, then search (current) | 0.74 | 0.66 | 0.38 | 0.22 | 0.50 | 6 of 40 | |
| The same, beam width 4 | 0.76 | 0.66 | 0.46 | 0.26 | 0.54 | 9 of 40 | +0.04 (-0.01 to +0.10) |
| Embed the original query, no translation | 0.34 | 0.56 | 0.04 | 0.58 | 0.38 | 7 of 40 | -0.12 (-0.26 to +0.03) |
| Both rankings fused | 0.66 | 0.66 | 0.40 | 0.48 | 0.55 | 9 of 40 | +0.05 (-0.03 to +0.13) |

Embedding the original query is the only thing that helps Japanese, because it sidesteps the failed translation, and
it is useless for Chinese. Fusing splits the difference. Neither of the two higher scores can be told apart from the
current way on 40 queries, beam width 4 doubled the time to translate these queries (240 ms against 112 ms) and left
"It's a very simple process." in place, so I kept the default and wrote the gap down. What would close it is a better
translation model for Chinese and Japanese queries, not a different way of combining what these models produce.

How these were judged: three blind judges scored the 465 results the tester had not seen, with the tester's rubric.
A hidden sample of the tester's own items came back one point stricter in 7 of 45 cases, so the same judges then
re-scored all 365 of the tester's items too (328 identical, 37 one point apart). Every number in this subsection uses
that one set of judgments, so the rows compare with each other. They do not compare with the tester's report, where the
same English, German, Spanish, Chinese and Japanese searches under the old default were scored 0.94, 0.86, 0.80, 0.54
and 0.36 by the tester's judges (0.84, 0.78, 0.74, 0.46 and 0.30 by these).

### What this does not prove

- **The test patents are machine translated, not real.** Real foreign patents are written by people and are messier.
- **The German and Chinese numbers flatter the method.** The copies were made by the same translation models that then
  translate the query, so the wording matches more than it would with real patents. The "query in that language" row is
  less affected: the query goes through a different model and has to match text a person wrote. It is still a round
  trip of that patent's own claim.
- **Finding the same patent is a stand-in for relevance.** A description often repeats its claim nearly word for word.
  For English, keyword search alone beats the default on this test (0.964 against 0.930), as it does on the tester's
  test A in section 3, because the query repeats the patent's own words.
- **The English baseline is easier than it reads** (measured by the independent tester on 200 queries). This test
  removes every claim from the candidates. With only the query patent's own claims removed, semantic search scores
  0.873, not 0.923. 42.5% of first claims have at least half of their five-word sequences word for word in one passage
  of the same patent: semantic search scores 0.965 on those and 0.806 on the rest. And the 100 test patents were drawn
  only from the 505 that have a description. Patents without one score 0.788 against 0.896.
- **The calibration assumes most sampled passages are unrelated to the query.** That holds here, where the foreign
  patents are a random sample of the English ones. It would not hold if one language's patents were all in one field.
- 100 queries, one technical field, two languages.

### Display in English

Every result prints in English with the original language labelled. `--show-original` adds the original text. Here the
same invention is found in three languages:

```text
$ python cli.py search "tyre monitor with an energy harvester that charges the sensor" --top 5
Query searched in: de, en, zh.

 1. 20240083200 | TYRE MONITOR
      score 0.0164 | similarity 0.941
      classification B60C2304FI | filing week 2024-03-14 | language en
      Evidence, claim 2 (depends on claim 1):
        A tyre monitor as claimed in claim 1 , in which the energy harvester unit is also arranged to convert
        a second type of energy experienced by the harvester unit in use into electrical energy to energise
        the sensor device.

 2. 20250108669 | PCB IMPEDANCE TUNING TO ACHIEVE WIDEBAND AND HIGH ACCEPTANCE OF COIL ANTENNA LENGTH VARIATION
      ...
 3. 20240083200-DE | Tyre monitoring  [translated from de]
      score 0.0159 | similarity 0.910
      classification B60C2304FI | filing week 2024-03-14 | language de
      Evidence, abstract, machine translated:
        A tyre monitor shall be exposed, including a sensor device configured to operate within a closed space
        formed by the wheel and the tyre, and an energy harvester unit. ...

 4. 20250108667 | TIRE WITH SEALANT AND TIRE PUNCTURE SENSOR SYSTEM
      ...
 5. 20240083200-ZH | Tyre monitor  [translated from zh]
      score 0.0154 | similarity 0.929
      classification B60C2304FI | filing week 2024-03-14 | language zh
      Evidence, claim 1 (number inferred, opening words missing in the source), machine translated:
        A sensor device, which is configured to detect the operational parameters of a tyre installed on a
        wheel, is configured to operate in closed space formed by wheels and tyres, and an energy collector
        arranges for the conversion of the first type of energy used by the harvester unit into electrical
        energy to reinforce the sensor device.
```

The Chinese copy has a higher similarity than results 2 to 4 and still ranks below them: that is the calibration,
which measures each score against its own language's level. With `--cross-lingual shared`, the same query returns
results 1, 2 and 4 and two more English patents. Results 3 and 5 are gone. Each language version of an invention
takes its own place in the list; grouping them needs patent family data, which the files do not have.

The translations are rough, and that is the point of keeping them out of search. The title `SPOKE` became `Sprecher` in
German and comes back as "Speaker". The Chinese model wrote "claim" as a claim for compensation. A rubber recipe in
"parts" is displayed as "hours". The translation models also sometimes get stuck repeating one word; 5% of the first
Chinese test passages were damaged that way until a retry was added. Good enough to decide whether to read the
original, not good enough for legal use.

The independent tester measured how rough (`scripts/testing/translation_checks.py`, on the machine-made copies, so
real patents may differ). Shown in English, every number in the passage survived in 100 of 100 German passages and in
38 of 100 Chinese ones. Of 94 Chinese passages that cite a reference numeral of two or more digits, 51 lost at least
one. Translated to Chinese and back, "spoke" returned as "speech" and "interviews", "sipe" as "mouth" and "rim" as
"circle". A reference numeral is how a claim points at a drawing, so for Chinese the English display is a hint at
what the passage is about and nothing more. `--show-original` prints the text itself.

## 8. Limitations

Still open after the independent test pass:

- **Which ranking should be the default is not settled.** The known-answer tests say semantic, clearly. The 30 fresh
  queries are neutral overall, and on the 10 everyday-language ones, with the German and Chinese copies in the index,
  the old fused default was better (section 3). Reverting is one word in `src/search.py` and `cli.py`.
- **The tool never says it found nothing.** A query about sourdough bread returns ten tire patents with similarity 0.81
  to 0.86, and real matches score 0.84 to 0.92. I tested whether the per-query background sample could flag such
  queries (`scripts/testing/offtopic_check.py`). It cannot: the best result of an off-topic query stands 4.0 to 5.2
  spreads above the background, inside the 2.9 to 6.2 of real queries. Plain similarity comes closer and still
  overlaps, on five examples. So there is no warning.
- **Chinese and Japanese queries are far behind** on fresh queries: half and a third of the relevance of English ones
  (section 7). The cause is the translation of the query, and three other ways of handling it were no better.
- **Chinese is behind as a document language too**: a Chinese patent among English ones is ranked first 70% of the
  time, against 89%.
- **Short queries favour German copies** two to one over their English originals (section 7). Scores are compared
  across languages by a per-query estimate of each language's score level. It is a statistical correction, tested on
  one corpus where the languages have the same mix of topics.
- **Chinese shown in English loses numbers and claim terms** (section 7): every number survived in 38 of 100 passages.
- Part 3 is evaluated on machine translated patents. The real sample is still needed.
- Ranking quality in English rests on known-answer tests and on 30 queries judged by language models. No person has
  judged relevance.
- Semantic search depends on letter case. A title typed in capitals, as stored, finds its patent first 94% of the
  time. The same title in lower case, 81% (tester's test C).
- Searching with a dependent claim does not find its parent claim: among all claims, the parent is the best match 5%
  of the time (tester's test D). The stored link is the right source for that, and the output prints it ("depends on
  claim 1").
- The same invention in another language takes its own result slot: 0.64 of 10 slots on the 840 patent index.
- The title filter is "contains" only, and several keywords are never a phrase (section 3).
- A patent with no passage long enough to embed cannot be returned by the default search (section 4).
- `requirements.txt` pins the packages it names, not `torch`, `transformers` or the model files. A later install can
  get different versions and slightly different numbers.
- A language with no translation model falls back to the shared space, which is the thing shown not to work. A network
  failure while loading a model looks the same as "no model"; the ingest report counts such patents, and fixing it means
  rebuilding the index.
- Language is detected once per patent. A patent with an English abstract and foreign claims would be labelled English.
- Translation at ingest runs one patent at a time and is slow (448 characters per second into English at beam width 4).
  Bulk translation in the other direction with greedy decoding ran at 6,000 to 7,000; about a factor of 5 of that is the
  beam width, the rest is batching.
- Every command line call loads the model again (about 10 seconds). A long-running service would not.
- The inferred claim numbers can be wrong in the 4 places where the count does not match the numbering gap.
- The scale design's SQL was not run, apart from the one statement in the proof of concept. The Docker path was not run.
- The keyword weight was tuned on two tests. The fusion constant and the title weight of the keyword ranking are defaults.

## 9. Next steps

1. Run the evaluation on the real non-English sample, using patent families (the same invention filed in two languages)
   as the test, so both sides are written by people.
2. Close the Chinese and Japanese gap: a better translation model for the query, and a calibration fitted on real
   pairs of the same invention in two languages instead of estimated per query. The same fit should remove the German
   advantage on short queries.
3. Decide the default ranking with relevance judged by people, on more than 30 queries.
4. Batch translation at ingest, and cut windows by token count instead of character count.
5. Step 1 of the scale design: run the proof of concept on a current pgvector, with half precision vectors and the fused
   statement.

## Files

| Path | What |
| --- | --- |
| `cli.py` | Command line: `ingest`, `search`, `similar`, `show`, `stats` |
| `src/` | `db.py`, `ingest.py`, `embed.py`, `translate.py`, `search.py` |
| `scripts/` | `inspect_data.py`, `benchmark.py`, `tune_keyword_weight.py`, `make_parallel_set.py`, `evaluate_multilingual.py`, `compare_models.py` |
| `tests/` | 525 tests, no model needed. 96 are mine, the rest came from the independent test pass |
| `scripts/testing/` | The independent tester's scripts and results: tests on a real index, known-answer backtest, fresh-query test, performance, cost arithmetic |
| `TEST_REPORT.md`, `TEST_RESULTS_FOR_BUILDER.md` | The independent test report and its work list, as received |
| `benchmarks.md`, `eval_results.md` | Generated tables |
| `docs/scale_design.md`, `docs/architecture.md` | Part 2 design, project diagram |
| `poc/`, `docker-compose.yml` | Part 2 proof of concept |
| `NOTES.md`, `DECISIONS.md` | Every decision and number; the eight that matter |
| `VIDEO_SCRIPT.md` | Talk-through of Parts 2 and 3 |
