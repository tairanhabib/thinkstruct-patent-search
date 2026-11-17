# Patent passage search, in any language

Take-home for Thinkstruct. Part 1 is a hybrid search engine over patent passages. Part 2 is a design for 10 million
patents with a small proof of concept. Part 3 is the machine translation enhancement: ingest, search and display
patents that are not in English.

**Video (2 minutes, Parts 2 and 3):** link to be added.

Everything measured here was measured on an Apple M2 Pro laptop (10 cores, 16 GB). The full log of decisions, numbers
and known weaknesses is in [NOTES.md](NOTES.md). The eight decisions that matter most are in [DECISIONS.md](DECISIONS.md).

## 1. The problem I chose

> Given a description of an invention, or any attribute of a known patent, find the most relevant passages in patent
> applications written in any language, let an examiner narrow the results with filters, and show every result in English.

- **Input:** a sentence or a pasted draft claim in any language, or a document number (optionally one claim of it), or
  filters alone, or any mix.
- **Filters:** classification code prefix, keywords in title or abstract, title, filing week range, original language,
  passage type (claim, abstract, description).
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
  four runs (the slowest on battery in Low Power Mode). The first run downloads the embedding model, 493 MB.
- `search` and `similar` take about 10 seconds to start, almost all of it loading the model. The search itself takes
  about 17 ms.
- `benchmark.py` takes about 3 minutes, needs about 3 GB of free memory, and rewrites `benchmarks.md`. Run it before
  Part 3, so it measures the English index alone.
- The tests need no model and take about 1 second.
- Dates are ISO dates (`2024-06-01`). A query in Latin letters shorter than 40 letters is treated as English;
  `--query-language de` overrides that. Chinese, Japanese and Korean queries are recognised by their script.
- From Python: `from src.search import Index, search`, then `search("...", cpc_prefix="B60B", index=Index())`.

### Part 3: foreign patents

```bash
python scripts/make_parallel_set.py
python cli.py ingest data/parallel
python scripts/evaluate_multilingual.py
python cli.py search "pressure sensor that reports tire pressure to the driver" --language de --top 3
python cli.py search "轮辋上带有压力传感器的车轮" --top 3 --show-original
python cli.py search "pressure sensor that reports tire pressure to the driver" --top 5
python cli.py search "pressure sensor that reports tire pressure to the driver" --top 5 --cross-lingual shared
python cli.py show --doc 20240083200-ZH
```

- `make_parallel_set.py` machine translates 100 of the English patents into German and Chinese (about 15 minutes) and
  writes them to `data/parallel/`. It downloads two translation models, about 600 MB each.
- `ingest data/parallel` takes about 5 minutes and downloads two more translation models.
- `evaluate_multilingual.py` takes about 4 minutes and rewrites `eval_results.md`.
- The search with `--cross-lingual shared` uses the approach that failed (section 7). Compare it with the line above
  it: the same query, and the Chinese patent at rank 3 is gone.
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
| Store | SQLite (tables, full text index, translation cache) plus one NumPy array of vectors | `src/db.py` |
| Filter | In SQL, before vectors are scored. Classification, keywords, dates and language use indexes; "title contains" is a scan | `src/search.py` |
| Translate the query | Into each language that survived the filters. Short, cached | `src/search.py` |
| Semantic ranking | Each passage scored against the query in its own language, best passage per patent | `src/search.py` |
| Keyword ranking | BM25 over English title and abstract | `src/search.py` |
| Fuse | Reciprocal rank fusion of the two rankings | `src/search.py` |
| Display | Translate what is shown to English, on demand, cached | `cli.py` |

Main choices, each with the reason:

| Choice | Why |
| --- | --- |
| SQLite plus a NumPy array | Nothing to install or start. Exact search over 33,000 vectors takes under 2 ms, so an index structure would add nothing |
| `intfloat/multilingual-e5-small` | One model for about 100 languages, reads 512 tokens (the common alternative reads 128), small enough for a laptop |
| Translate the query, not the documents | Measured: one shared vector space does not work across languages (section 7). The query is short, the corpus is not |
| Translate only title and abstract at ingest | Keywords need English words. Translating all text for 10 million patents would cost about 33 times more ([scale design](docs/scale_design.md)) |
| Reciprocal rank fusion | Combines a keyword score and a cosine score without having to make them comparable |
| Never drop a patent | Dropping one silently hides prior art |

### What the data really looks like

The provided files differ from the task sheet, and handling that was a real part of the work:

- Field names are `title`, `doc_number`, `abstract`, `detailed_description`, `claims`, `bibtex`, `classification`,
  `filename`. Both naming styles are accepted.
- **119 of 640 patents have an empty description** (a list holding one empty string).
- **3,223 claims have no number and no opening words.** Where a claim was written with nested elements, the source kept
  only the body ("an axle body, having a middle segment ...") and lost "1 . A spoke, comprising:". This happens at any
  position, not only claim 1. In 1,300 of 1,335 places where it can be checked, the count of such claims equals the gap
  in the numbering, so each gets "previous number plus one", and the output marks the number as inferred. The patent
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
| No text at all | Kept and counted in the ingest report. It can be shown, and cannot match a query |
| No claims, and the user asks for patents similar to claim 1 | Falls back to the abstract and says so |
| A file is not valid JSON, or a record is not a dictionary | Counted and skipped. The rest of the batch continues |
| A foreign patent in a language with no translation model | Kept and searched in its own language. Stored with no English title or abstract, counted in the ingest report, and labelled "not translated" when shown |

The real data only has one kind of missing field (the 119 empty descriptions). So the tests delete or empty each of
7 fields in 6 different ways (42 cases) on synthetic records and check that the patent is still ingested, still found,
and printed with `Unknown`. More tests cover the classification, keyword, title, date and language filters with and
without `--include-unknown`. The passage type option is not a field filter: it restricts which passages may be shown as
evidence, so a patent with no description cannot appear when only descriptions are asked for.

## 5. Timing with and without hybrid search

Full tables: [benchmarks.md](benchmarks.md). 20 fixed queries, 5 runs each, median, 640 patents, 32,772 vectors.

| | Whole call | Of which encoding the query | Everything else |
| --- | --- | --- | --- |
| Semantic only (hybrid off) | 16.3 ms | 14.1 ms | 2.3 ms |
| Hybrid (keyword and semantic, fused) | 16.7 ms | 13.7 ms | 2.8 ms |
| Keyword only | 1.2 ms | none | 1.0 ms |

Hybrid search with filters, filter and scoring steps only:

| Filter | Vectors kept | Filter first | Filter after | Auto (default) |
| --- | --- | --- | --- | --- |
| none | 100% | 1.57 ms | | |
| classification `B60C` | 53% | 6.64 ms | 2.40 ms | 1.71 ms |
| keyword `rubber` | 11% | 0.89 ms | 1.78 ms | 0.87 ms |
| classification `B60D` | 2.9% | 0.43 ms | 1.58 ms | 0.43 ms |
| title contains `wheel bearing` | 1.0% | 0.41 ms | 2.14 ms | 0.40 ms |

The same scoring step on the vectors copied 30 times (983,160 vectors):

| Filter | Vectors kept | Filter first | Filter after |
| --- | --- | --- | --- |
| none | 100% | 67.7 ms | |
| classification `B60C` | 53% | 234.5 ms | 67.1 ms |
| keyword `rubber` | 11% | 52.6 ms | 60.6 ms |
| classification `B60D` | 2.9% | 11.5 ms | 62.5 ms |
| title contains `wheel bearing` | 1.0% | 3.0 ms | 61.2 ms |

What I take from this:

1. **At this size the search is not the cost.** Encoding the query is about 85% of a call (14 of 16.7 ms). Hybrid
   adds about half a millisecond to semantic search.
2. **Filtering first helps in proportion to how selective the filter is.** A filter that keeps 1% of the vectors made
   the filter and scoring steps 5 times faster on the real index (0.41 ms against 2.14 ms). On the scoring step alone
   at a million vectors the same filter was 20 times faster (3.0 ms against 61.2 ms). This is how hybrid search helps
   performance at scale: a selective filter on an index is cheap, and it removes most of the expensive work. The
   advantage grows with the corpus only for very selective filters. For a filter that keeps 11% it was 2.0 times on
   the real index and 1.2 times at a million vectors.
3. **Filtering first hurts when the filter is not selective.** It has to copy the surviving rows out of the matrix, and
   copying costs more per row than scoring in place. With 53% kept it was 2.8 times slower. So the default is `auto`:
   filter first when under 15% of vectors survive, score in place otherwise. My initial plan said "always filter
   first"; the measurement said otherwise.
4. **The biggest win was not about filters.** My first version sorted every passage score to find the best passage per
   patent. Replacing the sort with one pass per patent made the scoring step about 5 times faster (7.5 ms to under
   2 ms). The whole call went from about 22 ms to about 16 ms, because encoding the query dominates.

These numbers are from the final run, which was on battery in Low Power Mode. Earlier runs on the same machine were
within about 25% of them.

Done to make it efficient: vectors normalized at ingest, filters in SQL before scoring, one pass instead of a sort, the
adaptive strategy, cached translations, the query translated only into languages that survive the filters.

Would do at scale: cache query vectors, store vectors in 16 bits, keep rows partitioned by language and classification
section so a common filter is a contiguous block with no copy, and use an approximate index only when the filtered set is
large. The proof of concept shows why that last rule is needed: forced onto PostgreSQL's approximate index with a filter
that 12 patents pass, the query returned 6 of the 10 right answers (the "filtered approximate search" problem).

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

### What I built first, and what the measurement said

The plan was: embed every language with one multilingual model, and an English query finds a German passage with no
translation at all. That design is in the code as `--cross-lingual shared`. It does not work.

Test: take 100 patents that exist in English, German and Chinese. Search with the first claim in English. Claims are
not candidates, so the right answer is the same patent's abstract or description. "Mixed" puts the 100 test patents in
one language among the 540 other English patents. The number is mean reciprocal rank (1.0 means always first).

| Mixed corpus, 640 candidates | English target | German target | Chinese target |
| --- | --- | --- | --- |
| Semantic, one shared space (the plan) | 0.930 | 0.007 | 0.003 |
| Hybrid, one shared space (the plan) | 0.945 | 0.059 | 0.034 |
| Keyword only, on translated title and abstract | 0.964 | 0.906 | 0.719 |
| Semantic, query translated | 0.930 | 0.912 | 0.920 |
| **Hybrid, query translated (the default)** | **0.945** | **0.921** | **0.933** |

With semantic search on the shared space, not one of the 200 foreign targets reached the first ten results. With
keywords fused in, 19 did.

Two notes on reading the table. The 100 test patents were drawn at random from the 505 that have a description and a
first claim of at least 150 characters. And for English, keyword search alone does as well as hybrid on this test (0.964
against 0.945), because a patent's abstract repeats the words of its claim. The fusion is not tuned.

**Why.** The model has a language bias. Two unrelated passages in the same language score higher than a passage and its
own translation: 27.5% of all other English abstracts outscore a patent's own German copy, and 76.2% outscore its own
Chinese copy. It is not truncation (0 to 5 vectors per language are too long). It is only partly the small model:
on a cut-down version of the test, `multilingual-e5-base` reached 0.110 for German and `BAAI/bge-m3`, with 2.7 times the
storage, 0.310.

### The fix

Translate the **query** into each language in the index, and score each passage against the query in its own language.
Passages are still embedded in their original language and never translated for search. Only three things are ever
translated: title and abstract at ingest (for keywords), the query (short, cached), and whatever is displayed.

"Comparably", measured as the gap in mean reciprocal rank to English with a 95% bootstrap interval:

| Hybrid, query translated | English | German | Chinese |
| --- | --- | --- | --- |
| Mixed corpus | 0.945 | 0.921 (gap -0.023, interval -0.059 to +0.009) | 0.933 (gap -0.012, interval -0.053 to +0.028) |
| Foreign query against the 640 English patents | 0.945 | 0.917 (gap -0.028, interval -0.056 to -0.006) | 0.862 (gap -0.082, interval -0.138 to -0.030) |

So: for an English query over a mixed corpus the gap is 1 to 2 points and the interval includes zero. For a German
query against English patents it is 3 points and the interval just excludes zero. **For a Chinese query it does not
hold: 8 points.** Tested alone, with no English patents in the way, German and Chinese are each about 2 points below
English, also just outside zero. So "comparable" here means within about 3 points, except for Chinese queries.

Translating a claim-length query into two languages took a median of 1.2 seconds with the models already loaded, and
under 0.1 ms once cached (measured on battery in Low Power Mode, so on the slow side).

### What this does not prove

- **The test patents are machine translated, not real.** Real foreign patents are written by people and are messier.
- **The good German and Chinese numbers in the mixed table are an upper bound.** The copies were made by the same
  translation models that then translate the query, so the wording matches more than it would with real patents. The
  "foreign query" row is less affected: the query goes through a different model and has to match text a person wrote.
  It is still a round trip of that patent's own claim. It is the least flattering row, and it is the one where Chinese
  falls short.
- **Finding the same patent is a stand-in for relevance.** A description often repeats its claim nearly word for word.
- 100 queries, one technical field, two languages.

### Display in English

Every result prints in English with the original language labelled. `--show-original` adds the original text.

```text
$ python cli.py search "轮辋上带有压力传感器的车轮" --top 3 --show-original
Query searched in: de, en, zh.

 1. 20240140145 | MODULAR TIRE PRESSURE MONITORING SYSTEM (TPMS) SENSOR WITH EASILY REMOVABLE AND REPLACEABLE BATTERY
      score 0.0315 | similarity 0.910 | keyword rank 4
      classification B60C2304FI | filing week 2024-05-02 | language en
      Evidence, description paragraph 110:
        In some aspects, the techniques described herein relate to a pressure monitoring system where the
        pressure sensor (1420) detects an air pressure in a tire attached to the tire rim.

 2. 20240083200-ZH | Tyre monitor  [translated from zh]
      original title: 轮胎监测器
      score 0.0308 | similarity 0.909 | keyword rank 6
      classification B60C2304FI | filing week 2024-03-14 | language zh
      Evidence, claim 12, machine translated:
        The tyre monitor, described in claim 1, includes a pressure sensor to measure the inner pressure of
        the tyre.
        original:
        索赔1中所称轮胎监测仪,其中传感器包括测量轮胎内压的压力传感器。
```

The translations are rough, and that is the point of keeping them out of search. The title `SPOKE` became `Sprecher` in
German and comes back as "Speaker". The Chinese model wrote "claim" as a claim for compensation. A rubber recipe in
"parts" is displayed as "hours". Good enough to decide whether to read the original, not good enough for legal use.

## 8. Limitations

- Part 3 is evaluated on machine translated patents. The real sample is still needed.
- A Chinese query against English patents is measurably worse than an English one.
- Ranking quality in English is only tested by the find-the-same-patent test. There are no relevance judgements.
- A language with no translation model falls back to the shared space, which is the thing shown not to work. A network
  failure while loading a model looks the same as "no model"; the ingest report counts such patents, and fixing it means
  rebuilding the index.
- Language is detected once per patent. A patent with an English abstract and foreign claims would be labelled English.
- Translation at ingest runs one patent at a time and is slow (448 characters per second into English at beam width 4).
  Bulk translation in the other direction with greedy decoding ran at 6,000 to 7,000; about a factor of 5 of that is the
  beam width, the rest is batching.
- Every command line call loads the model again (about 10 seconds). A long-running service would not.
- The inferred claim numbers can be wrong in the 35 places where the count does not match the numbering gap.
- The scale design's SQL was not run, apart from the one statement in the proof of concept. The Docker path was not run.
- The fusion constant and the title weight are defaults, not tuned.

## 9. Next steps

1. Run the evaluation on the real non-English sample, using patent families (the same invention filed in two languages)
   as the test, so both sides are written by people.
2. Fix the Chinese query path: a better translation model for the query, or search with both the translated query and
   the original and keep the better score.
3. Batch translation at ingest, and cut windows by token count instead of character count.
4. Step 1 of the scale design: run the proof of concept on a current pgvector, with half precision vectors and the fused
   statement.

## Files

| Path | What |
| --- | --- |
| `cli.py` | Command line: `ingest`, `search`, `similar`, `show`, `stats` |
| `src/` | `db.py`, `ingest.py`, `embed.py`, `translate.py`, `search.py` |
| `scripts/` | `inspect_data.py`, `benchmark.py`, `make_parallel_set.py`, `evaluate_multilingual.py`, `compare_models.py` |
| `tests/` | 90 tests, no model needed |
| `benchmarks.md`, `eval_results.md` | Generated tables |
| `docs/scale_design.md`, `docs/architecture.md` | Part 2 design, project diagram |
| `poc/`, `docker-compose.yml` | Part 2 proof of concept |
| `NOTES.md`, `DECISIONS.md` | Every decision and number; the eight that matter |
| `VIDEO_SCRIPT.md` | Talk-through of Parts 2 and 3 |
