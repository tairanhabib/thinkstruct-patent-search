# Test results for the builder

An independent test pass was run on commit `8afc1df` (17 November 2026). This file is the work list that came out of
it. The full evidence, with every table and interval, is in [TEST_REPORT.md](TEST_REPORT.md). Nothing under `src/` was
changed by the tester and no fix was applied.

**Verdict: ready with fixes.** Setup, reproducibility and correctness of the core search held up. The items below are
what stands between this and a submission.

## How to read this

- Items are ordered by priority. Each has: what is wrong, how to see it, where in the code, the smallest fix I would
  try, and how to tell it is fixed.
- "Fixed when" names a test that fails today or a number to re-measure. If you think a test's expectation is wrong,
  change the test and say why in the commit. Do not delete it silently.
- After any change to ranking, filters or the schema, regenerate `benchmarks.md` and `eval_results.md` and update the
  numbers quoted in `README.md`, `NOTES.md` and `DECISIONS.md`. Do not edit a reported number by hand.

## How to run the tests

```bash
# 1. Fast tests, no model. Today: 522 tests, 510 pass, 12 fail (the 12 are listed under the items below).
python -m pytest

# 2. Real index, real model. Point it at a COPY of an index (searches write to its translation cache).
#    Today: 83 tests, 79 pass, 4 fail, on both the English index and the one with German and Chinese copies.
cp -R index /path/to/index_copy
PATENT_TEST_INDEX=/path/to/index_copy python -m pytest scripts/testing/test_functional_real.py -q

# 3. Known-answer backtest, Tests A to D in keyword, semantic and hybrid mode. Needs an index holding ONLY the
#    640 English patents, and a copy of it (Test B edits the keyword table inside a transaction it rolls back).
python cli.py --index /path/to/english_only ingest data/small
python scripts/testing/backtest.py english --index /path/to/english_only --out scripts/testing/results/backtest_english.json
python scripts/testing/backtest.py multilingual --index /path/to/index_copy --out scripts/testing/results/backtest_multilingual.json

# 4. Latency, and a real index 10 times the size.
python scripts/testing/perf.py latency --index /path/to/english_only --out scripts/testing/results/perf_1x.json
python scripts/testing/perf.py scale --index /path/to/english_only --dest /path/to/x10 --times 10
python scripts/testing/perf.py latency --index /path/to/x10 --out scripts/testing/results/perf_10x.json

# 5. The cost arithmetic in docs/scale_design.md, recomputed figure by figure.
python scripts/testing/check_cost_arithmetic.py
```

Note: the new files in `tests/` raise the count from 93 to 522. The README says "93 tests" in two places. Until the 12
failures are fixed, `python -m pytest` exits non-zero, which a reviewer following the README will see.

## Do not break these (all verified)

- Every README command for Parts 1 and 3 runs from a fresh clone with an empty model cache. Clone to first result: 183 s.
- The regenerated `eval_results.md` is identical to the committed one in every quality number.
- Filter first, filter after and auto return the same results in the same order (13 filter cases, 50 queries, 2 modes,
  both indexes, plus 175 random-vector cases).
- Results are sorted, free of duplicates and identical between runs and between processes.
- Ingesting twice adds nothing. Adding the 2025 files to an index built from 2024 needs no rebuild and gives the same
  search results as a single-pass build.
- Every missing-field case ingests, stays findable and prints `Unknown` (6 fields removed 4 ways, plus 48 odd values
  such as `0`, `{}` and `[None]`).
- The proof of concept without Docker returns 10, 10, 6 and 8 rows and agrees with the Python search.

## Only a person can do these

| # | What | Check |
| --- | --- | --- |
| H1 | Record the 2 minute video and replace "link to be added" on `README.md` line 7 | `grep -n "link to be added" README.md` prints nothing |
| H2 | Push to a public GitHub repository | `git remote -v` prints a remote |
| H3 | Run the Docker path once, or keep the README's note that it is untested | Docker is not installed on the test machine |
| H4 | Chase the real non-English sample. `data/foreign/` is empty, so nothing was tested on real foreign patents | |

## Major

### M1. Hybrid, the default mode, ranks worse than the better single mode in every known-answer test

| Test | Keyword MRR | Semantic MRR | Hybrid MRR | Hybrid minus the better one |
| --- | --- | --- | --- | --- |
| A: claim 1 finds its own patent | 0.931 | 0.873 | 0.889 | -0.042 (interval -0.070 to -0.018) |
| B: abstract finds its own claims, abstract removed from the keyword index | 0.208 | 0.970 | 0.374 | -0.595 (-0.652 to -0.530) |
| C: title finds the patent | 0.760 | 0.958 | 0.917 | -0.041 (-0.070 to -0.013) |
| D: dependent claim finds the patent holding its parent | 0.701 | 0.887 | 0.844 | -0.043 (-0.082 to -0.007) |

- **Why:** `src/search.py:342-347`. The keyword list covers only title and abstract but gets the same vote as the
  passage-level list. A patent ranked first by meaning and missing from the keyword list scores 1/61, which is less
  than a patent ranked 50th in both lists (2/110).
- **See it:** command 3 above. Results are in `scripts/testing/results/backtest_english.json`.
- **Smallest fix to try:** give the keyword list a weight below 1 in the fusion and pick the weight on Tests A and B.
  If no weight makes hybrid at least match the better single mode, make `semantic` the default mode and keep hybrid as
  an option. The task's "hybrid search" is the filters, which stay either way.
- **Fixed when:** on a re-run of command 3, "hybrid minus the better single mode" is within 2 points of zero on all
  four tests. Then correct README section 7 ("keyword search alone does as well as hybrid") and DECISIONS 7.

### M2. On fresh queries, Chinese and Japanese are far from comparable, and the built-in evaluation does not show it

Ten new queries, written by the tester in five languages, top 5 judged 0 to 2 for relevance (840 patent index):

| Query language | Mean score of top 5 | Queries with a directly relevant result | Top 10 shared with the English query |
| --- | --- | --- | --- |
| English | 0.94 | 70% | |
| German | 0.86 | 50% | 4.5 of 10 |
| Spanish | 0.80 | 60% | 5.2 of 10 |
| Chinese | 0.54 | 30% | 3.8 of 10 |
| Japanese | 0.36 | 10% | 2.0 of 10 |

- **Why:** the query translation. Language detection was right for all 70 searches. Two of ten Japanese queries were
  translated to "It's a very simple process."; in Chinese, tread "grooves" became a "ditch". The built-in "foreign
  query" test shows Chinese only 5 points behind because its query is a machine translation of the target patent's own
  claim, so it cannot see this.
- **See it:** `scripts/testing/forward_queries.json` (queries), `scripts/testing/results/forward_results_mixed.json`
  (results), `scripts/testing/results/forward_report_mixed.json` (scores).
- **Smallest fix to try:** queries are translated with greedy decoding (`QUERY_BEAMS = 1`, `src/search.py:21`). Try a
  beam width of 4 for queries and re-measure. If that does not close most of the gap, do not chase it: state the
  numbers above in README sections 7 and 8, and say Japanese and Spanish were never part of the built-in evaluation.
- **Fixed when:** the README no longer implies a 5 point gap for Chinese queries, and either the numbers improved or
  the limitation is written down. Re-scoring after a change: `python scripts/testing/forward_test.py run --index COPY
  --tag NAME`, judge the new items in the sheet it writes, then `forward_test.py report --tag NAME`.

### M3. The tool never says it found nothing

- Queries about sourdough bread, aircraft engines, phone cameras, a migraine drug and blockchain each return 10 results
  with similarity 0.81 to 0.86. Real matches score 0.84 to 0.92, so the ranges overlap. All 25 judged results were
  unrelated.
- `python cli.py search "?!...,;:--()"` and `python cli.py search "    "` exit 0 with a ranked list.
- **Where:** `src/search.py:274-285` accepts any non-empty string as a query.
- **Smallest fix:** refuse a query that contains no letters or digits, with the same kind of error as an empty query.
  For off-topic queries, the per-query background sample already exists (`Index.calibration`). Measure how far the top
  result stands above it for the 30 queries in `forward_queries.json` (5 of them are the off-topic ones). If the two
  groups separate, print a one-line warning below that level. If they do not, add the limitation to the README and stop.
- **Fixed when:** `tests/test_independent_search.py::test_query_with_no_words_is_refused_or_returns_nothing` passes
  (5 cases; it accepts a `ValueError` or an empty list).

### M4. The keyword filter passes patents that do not contain the keyword

- On the 640 English patents, `python cli.py search --keywords generator --top 50` passes 27 patents. One contains
  "generator". The other 26 contain "generally", "generated" or "generic". `--keywords general` passes the same 27,
  none of which contains "general". `--keywords bearing` passes one patent that only says "bears". (On the index with
  the German and Chinese copies the first command lists 32.)
- **Where:** `src/db.py:38`, `tokenize='porter unicode61'`. The same stemmed table serves the filter
  (`src/search.py:103`) and the ranking (`src/search.py:190`).
- **Smallest fix:** a second full text table without `porter`, used only by the filter. Keep stemming for ranking.
  This changes the schema, so an existing `index/` must be rebuilt; say so in the README.
- **Fixed when:** `scripts/testing/test_functional_real.py::test_keyword_filter_every_result_has_the_keyword_in_title_or_abstract`
  passes for all five keywords, and `--keywords generator` returns only patents containing the word or its plural.
  Then decide whether README section 3 and `tests/test_search.py::test_keyword_filter_needs_every_keyword_and_uses_word_stems`
  should still promise that "sensors" matches "sensor".

### M5. Two filters scan every patent, and the headline speed-up leaves the filter's own cost out

- `README.md:134` says classification, keywords, dates and language use indexes. The classification filter does not:

  ```bash
  sqlite3 index/patents.db "EXPLAIN QUERY PLAN SELECT p.id FROM patents p WHERE EXISTS (SELECT 1 FROM classifications c WHERE c.patent_id = p.id AND c.code GLOB 'B60B*');"
  ```

  prints `SCAN p`. The index on `classifications.code` is never used.
- `README.md:229` quotes "17 times faster" at a million vectors. That figure times the scoring step only. On a real
  index 10 times the size, with the SQL filter included, the 1% title filter went from 5.5 times faster than filter
  after (0.41 ms against 2.24 ms) to 3.6 times (7.78 ms against 28.33 ms). The title scan grew 23 times (0.26 ms to
  5.95 ms) and became the largest step.
- **Where:** `src/search.py:97-100` (classification), `src/search.py:106-109` (title).
- **Smallest fix:** select the passing patents from the classification table by a range on the code, for example
  `p.id IN (SELECT patent_id FROM classifications WHERE code >= ? AND code < ?)` with the prefix and the prefix with
  its last character raised by one, and confirm with `EXPLAIN QUERY PLAN` that `idx_classifications_code` is used. The
  title filter can stay a scan if the README says what it costs. Either way, put the end-to-end numbers at the larger
  size beside the scoring-only ones (commands under 4 above).
- **Fixed when:** the query plan shows a search on the code index, all tests under 2 above still pass, and README
  section 5, point 2 no longer presents a scoring-only number as the benefit at scale.

### M6. Chinese shown in English loses numbers and claim terms

- Numbers intact after display translation: German 100 of 100 passages, Chinese 38 of 100. Of 94 Chinese passages with
  a reference numeral of two or more digits, one was lost in 51. In round trips, "spoke" came back as "speech" and
  "interviews", "sipe" as "mouth", "rim" as "circle", and a stray "281." appeared at the start of a claim.
- Measured on machine-made Chinese, so real patents may differ.
- **Smallest fix:** state these figures in README section 7 next to "the translations are rough". Optional: replace
  each number with a placeholder before translating and put it back after.
- **See it:** `python scripts/testing/translation_checks.py --index COPY --out scripts/testing/results/translation.json`

### M7. The built-in English baseline is easier than it reads

- With every claim removed from the candidates (what `evaluate_multilingual.py` does), semantic MRR on my 200 queries
  is 0.923. With only the query patent's own claims removed, it is 0.873.
- 42.5% of the first claims have at least half of their five-word sequences word for word in one passage of the same
  patent. Semantic MRR is 0.965 on those and 0.806 on the rest.
- The 100 test patents come only from the 505 that have a description. Patents without one score 0.788 against 0.896.
- This is not a leak: the query text is never a candidate. **Smallest fix:** add these three sentences to "What this
  does not prove" in README section 7. Optional: report the stricter variant beside the current one.

## Minor

| # | What happens | Where | Fixed when |
| --- | --- | --- | --- |
| m1 | `similar --doc X --claim 999` searches with the abstract and prints only "Searching with the abstract of X", never that claim 999 does not exist | `src/search.py:201-209`, `cli.py:159` | `tests/test_independent_search.py::test_claim_number_that_does_not_exist_is_reported` passes (an error naming the number, or a `query_source` that says the claim was not found). The command-line test in `test_functional_real.py` looks for "claim 999 not found", "claim 999 does not exist", "no claim 999" or "has no claim" |
| m2 | `--top -1` returns everything but the last result (639 on the English index) | `src/search.py:347` | `test_top_k_of_zero_or_less_returns_nothing_or_is_refused[-1]` passes |
| m3 | A keyword filter with no usable word (`--keywords "!!! ???"`) is ignored and the search runs unfiltered | `src/search.py:101-102` | `test_keyword_filter_with_no_usable_word_is_not_silently_dropped` passes (3 cases) |
| m4 | English titles in capitals are taken for another language when typed as a query: 41 of 640 (German 37, Vietnamese 3, Somali 1). The query goes through a translator ("TREAD" became "thread") and a 554 MB Vietnamese model was downloaded. Ranking barely moved (1 of 37 worse). At ingest, where the title is the last fallback, 155 of 640 titles would be labelled foreign | `src/search.py:213-216`, `src/translate.py` `detect_language` | Lower-case before detecting (0 of 640 misdetected in lower case). Do not load a model for a language the index does not hold |
| m5 | A null inside a classification list is stored as the code `NONE` | `src/ingest.py:105` | `tests/test_independent_ingest.py::test_a_null_inside_a_classification_list_does_not_become_a_code` passes |
| m6 | A patent with no searchable text is counted but the log does not say which one | `src/ingest.py:183-184` | `tests/test_independent_missing_fields.py::test_ingest_names_the_patent_that_has_no_searchable_text` passes (the document number appears in the output) |
| m7 | Semantic title lookup depends on letter case: recall at 1 is 0.93 with the stored capitals and 0.81 with the same title in lower case | `src/embed.py:92` puts the title in front of claims as stored | Optional. Lower-case the title before embedding, then rebuild and re-measure Test C |
| m8 | The README's example for `--show-original` (line 82) returns three English patents, so no original text is printed | `README.md:82` | Add `--language zh` to that example |
| m9 | The title filter is "contains" only (`--title TIRE` returns every title with the word), and a multi-word keyword is never a phrase, quoted or not | `src/search.py:101-109` | Document it, or add an exact option |
| m10 | The same invention in another language takes its own result slot (0.93 of 10 slots on the 840 patent index) | | Note it as a limitation until real patent families exist |
| m11 | `torch`, `transformers` and the model files are not pinned | `requirements.txt` | Optional: a lock file and a model revision |

Not a defect, but worth one sentence in the README: similarity search does not find a dependent claim's parent (the
parent is the top match 5% of the time). The stored `parent_claim` link is the right source for that.

## Document corrections

| File and line | Now | Should be |
| --- | --- | --- |
| `README.md:7` | "link to be added" | the video link (H1) |
| `README.md:134` | classification "use indexes" | true only after M5 |
| `README.md:229` | "17 times faster" presented as the benefit at scale | scoring step only; add the end-to-end figure (M5) |
| `README.md:342` | Chinese "as a query language it is 5 points behind" | add the fresh-query result (M2) |
| `README.md:358` | keyword "does as well as hybrid" on one test | hybrid is behind the better single mode on all four tests (M1) |
| `README.md` section 2 | "`evaluate_multilingual.py` takes about 6 minutes" | it took 9.0 minutes here, on a machine running other jobs |
| `README.md` section 3 | "1,300 of 1,335 places" | my recount gives 1,308 of 1,312, and no script in the repository prints this figure |
| `docs/scale_design.md:365` | 25.1 kB | 25.2 kB |
| `docs/scale_design.md:398` | 327.7 GB | 328.0 GB |
| `docs/scale_design.md:411` | $412.45 | $412.46 |
| `docs/scale_design.md:436` | 6,062 characters per second | 6,067 |
| `docs/scale_design.md:368` | "slower laptop run" 229 vectors per second | `NOTES.md` records 138 as the slowest |
| `docs/scale_design.md:210`, `:370` | 70 ms per 983,160 vectors "from benchmarks.md" | the committed file says 73.7 |
| `docs/scale_design.md:211` | 2.4 ms, 43.1 ms, 18 times | the committed file says 3.9, 65.9, 17.1 |
| `docs/scale_design.md:211` and `:214` | a filter leaving 1.74 million vectors is routed to exact search | the rule two lines later says exact only below about 1 million |
| `docs/scale_design.md:521` and `:400` | re-embedding needs 1,010.9 GB | 1,000 GB is provisioned |
| `docs/scale_design.md:262` | filters on a `language` column of `passages` | the table defined at lines 84 to 95 has no such column |

The four rounding slips change no total: every dollar total in the cost breakdown reproduces. Full list in
`scripts/testing/results/scale_design_audit.md`.

## Claims that reproduced (no action)

Ingest time, model sizes, start-up time, the 17 ms search, the timing table's whole-call rows (within 7%), all data
facts (119 empty descriptions, 3,223 unnumbered claims, 167 cancelled claims, 43 shared titles), every MRR and recall
in the Part 3 tables, the language bias figures, the larger-model comparison (0.110 and 0.310), the first two Part 3
demonstrations, the proof of concept, and all eight entries in `DECISIONS.md` against the code.
