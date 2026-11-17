# Test report: Thinkstruct patent search take-home

Independent test pass on commit `8afc1df`, run on 17 November 2026 by a test agent that did not write the code.
Nothing under `src/` was changed and no reported number was edited. All new test code is in `tests/test_independent_*.py`
and `scripts/testing/`. Raw results are in `scripts/testing/results/`.

Machine: Apple M2 Pro, 10 cores, 16 GB, on mains power with Low Power Mode on. Python 3.11.15. Every number below was
measured in this session. Sampling uses seed 42. Intervals are 95% bootstrap intervals from 1,000 resamples.

## 1. Verdict

**Ready with fixes.** The engineering holds up: from a fresh clone, a new virtual environment and an empty model cache,
every README command for Parts 1 and 3 ran without a single undocumented step, the first search result arrived 183
seconds after `git clone`, and the regenerated evaluation tables are identical to the committed ones in every quality
number. The proof of concept ran and reproduced its results. The README is unusually honest about what it does not
prove. What needs fixing before a reviewer sees it: the video link is still a placeholder and the repository has no
remote; the default hybrid mode is worse than keyword-only or semantic-only search on all four known-answer tests I ran;
on fresh queries Chinese and Japanese are far from "comparable" (the built-in evaluation understates this because its
foreign queries are round trips of the patent's own claim); the tool returns ten confident results for a query about
sourdough bread or a query made of punctuation; and two statements in the README about filters do not match what the
code does.

## 2. Blocking issues

**Breaks a clean setup: none.** All 12 Part 1 commands, all 8 Part 3 commands and the proof of concept without Docker
exited 0 (`scripts/testing/stage1_clean_clone.sh`, log in section 3.1).

**Missing deliverables (these block submission, not the code):**

| # | Issue | Command to reproduce |
| --- | --- | --- |
| B1 | The README's video link is a placeholder. The task requires a 2 minute recording the reviewer can open. | `grep -n "link to be added" README.md` prints line 7 |
| B2 | The repository has no remote, so there is no public GitHub link to submit and I could not check one. | `git remote -v` prints nothing |

**Statements in the README that the code or the measurements contradict:**

| # | README says | What happens | Command to reproduce |
| --- | --- | --- | --- |
| B3 | Section 3: "Classification, keywords, dates and language use indexes" | The classification filter scans every patent and probes the classification table once per patent. The index on the code column is never used. | `sqlite3 index/patents.db "EXPLAIN QUERY PLAN SELECT p.id FROM patents p WHERE EXISTS (SELECT 1 FROM classifications c WHERE c.patent_id = p.id AND c.code GLOB 'B60B*');"` prints `SCAN p` |
| B4 | Section 2, Part 3: `search "轮辋上带有压力传感器的车轮" --top 3 --show-original` is given as the example of showing the original text | The three results are all English patents, so the flag prints no original text at all | `python cli.py search "轮辋上带有压力传感器的车轮" --top 3 --show-original \| grep -c original` prints 0 |
| B5 | Section 5, point 2: filtering first is how "hybrid search helps performance at scale", 17 times faster at a million vectors | That figure times the scoring step only. On a real index 10 times the size, with the SQL filter included, the advantage of the 1% title filter fell from 5.5 times to 3.6 times, because the title scan grew 23 times | `python scripts/testing/perf.py scale --index index --dest /path/x10 --times 10` then `python scripts/testing/perf.py latency --index /path/x10` (use an English-only index) |

## 3. Results tables

### 3.1 Clean start (Stage 1)

Fresh `git clone`, new virtual environment, empty Hugging Face cache, README commands copied literally. The pip download
cache was warm, so the 34 seconds for `pip install` does not include downloading 1.2 GB of packages.

| Step | Exit | Seconds | Peak memory | Note |
| --- | --- | --- | --- | --- |
| `git clone`, `venv`, `pip install`, `unzip` | 0 | 36.1 | 364 MB | 64 files unpacked, no stray files |
| `cli.py ingest data/small` | 0 | 137.4 | 1,459 MB | 640 patents, 32,772 vectors in 131.1 s (250 per second). Includes the 470 MB model download |
| First `search` | 0 | 9.6 | 1,114 MB | **183 s from clone to first result** |
| Other four Part 1 commands | 0 | 0.2 to 8.6 | 1,103 MB | filters-only and `show` need no model: 0.2 s |
| `scripts/benchmark.py` | 0 | 169.8 | 3,542 MB | rewrote `benchmarks.md` |
| `python -m pytest` | 0 | 1.9 | 125 MB | 93 passed |
| `scripts/make_parallel_set.py` | 0 | 1,146 | 1,082 MB | machine shared with my other tests from here on, so these are upper bounds |
| `cli.py ingest data/parallel` | 0 | 340 | 1,019 MB | 200 patents, 100,183 characters translated |
| `scripts/evaluate_multilingual.py` | 0 | 537 | 1,134 MB | tables identical to the committed file except three timing lines |
| Five Part 3 `search` and `show` commands | 0 | 8.3 to 15.2 | 1,928 MB | |
| `docker compose up -d --wait` | 127 | | | Docker is not installed. Not run |
| `poc/load_and_query.py --pgserver` | 0 | 33.5 | 1,230 MB | data folder under my scratch directory instead of `/tmp` |

Whole README: about 41 minutes. Downloads into the empty cache: embedding model 470 MB, four translation models 571,
571, 598 and 598 MB. Data location instructions are correct. Repository check: no data files, no binaries and no secrets
in the tree or in history; `.gitignore` present; the six direct requirements are pinned with `==` (torch and
transformers come in unpinned as dependencies; model revisions are not pinned).

### 3.2 Unit and functional tests (Stages 2 and 3)

| Suite | Tests | Passed | Failed | Not run |
| --- | --- | --- | --- | --- |
| Existing `tests/` (the author's) | 93 | 93 | 0 | 0 |
| New, no model needed: `tests/test_independent_ingest.py` (75), `_missing_fields.py` (140), `_search.py` (214) | 429 | 417 | 12 | 0 |
| New, real index and real models, 640 English patents: `scripts/testing/test_functional_real.py` | 83 | 79 | 4 | 0 |
| The same on the index with German and Chinese copies (840 patents) | 83 | 79 | 4 | 0 |

The 12 plus 4 failures are seven distinct defects, listed in section 5 (m1 to m6 and M4). What passed, item by item:

| Test plan item | Result |
| --- | --- |
| Empty paragraphs dropped; cancelled claims dropped (12 spellings); claim numbers parsed; unnumbered first claim is claim 1 | Pass |
| Dependent claims linked to the right parent (7 phrasings); a claim is never its own parent | Pass |
| Paragraph over 20,000 characters split, stored text intact, every word in exactly one window | Pass |
| Fragments under 40 characters stored and shown, not embedded (39 out, 40 in) | Pass |
| Subclass is the first four characters; prefix filter on the raw code (11 cases) | Pass |
| Filing week from the file name; agrees with the date inside `filename` for all 640 | Pass. When the two disagree the file name wins and nothing is flagged |
| Document numbers unique; same file twice adds nothing; interrupted embedding is finished by the next run | Pass |
| Real data: 640 patents, 64 files, passages 640 abstracts, 10,411 claims, 21,221 paragraphs | Pass, equal to `NOTES.md` |
| Six fields removed four ways each: ingests, still found through every remaining field, prints `Unknown`, never `None` or a blank line | Pass (72 cases, plus 48 with odd values such as `0`, `{}`, `[None]`) |
| Filter on a missing field excludes by default, includes with the option | Pass |
| Patent with no searchable text: kept and counted | Pass. Fail on "logged reason": the log does not name the patent |
| Every README input type works | Pass |
| Search by document number never returns that patent (40 patents, 3 modes, with and without a claim) | Pass |
| Classification, keyword, date filters return exactly the matching set; filters combined give the intersection | Pass. Dates are inclusive at both ends, as documented |
| Title filter returns every patent sharing a title (all 43 shared titles) | Pass. It is "contains", not exact: `--title TIRE` returns every title containing the word |
| Multi-word keyword filter | Pass as documented (every word, any order). It is not a phrase match, and quoting changes nothing |
| Filter first and filter after give the same results in the same order | **Pass.** 13 filter cases, 50 queries, 2 modes, full ranking and evidence compared, on both indexes. Also 175 random-vector cases |
| Ordered by score, no duplicates, same query twice identical (also across processes), `top_k` respected | Pass |
| Hybrid list contains items from both lists; score equals reciprocal rank fusion recomputed by hand | Pass |
| Bad input (21 cases through the command line) | No crash and no traceback in any case. Three give a wrong or missing message, see m1, m2, m3 |

### 3.3 Backtest (Stage 4)

640 English patents, 200 sampled items per test. Each cell is the value with its 95% interval.

| Test | Mode | Recall at 1 | Recall at 10 | MRR |
| --- | --- | --- | --- | --- |
| **A.** Claim 1 finds its own patent. That patent's claims are not candidates | keyword | 0.900 [0.855, 0.940] | 0.975 [0.950, 0.995] | 0.931 [0.898, 0.958] |
| | semantic | 0.815 [0.760, 0.870] | 0.970 [0.945, 0.990] | 0.873 [0.835, 0.911] |
| | hybrid | 0.825 [0.770, 0.875] | 0.975 [0.950, 0.995] | 0.889 [0.853, 0.922] |
| **B.** Abstract finds its own claims. Candidates are claims; the abstract is also taken out of the keyword index | keyword | 0.135 [0.085, 0.185] | 0.345 [0.280, 0.415] | 0.208 [0.161, 0.258] |
| | semantic | 0.950 [0.920, 0.980] | 0.995 [0.985, 1.000] | 0.970 [0.949, 0.987] |
| | hybrid | 0.295 [0.235, 0.360] | 0.515 [0.445, 0.585] | 0.374 [0.318, 0.434] |
| **C.** Title finds a patent with exactly that title | keyword | 0.695 [0.625, 0.760] | 0.965 [0.935, 0.990] | 0.760 [0.705, 0.812] |
| | semantic | 0.930 [0.890, 0.960] | 1.000 [1.000, 1.000] | 0.958 [0.934, 0.978] |
| | hybrid | 0.860 [0.810, 0.900] | 0.990 [0.975, 1.000] | 0.917 [0.887, 0.944] |
| **D.** Dependent claim finds its parent claim, among all claims of all patents (the query claim removed) | semantic | 0.050 [0.020, 0.080] | 0.280 [0.215, 0.340] | 0.115 [0.084, 0.147] |
| D, among the same patent's other claims only (median 19 of them) | semantic | 0.060 [0.030, 0.095] | 0.585 [0.515, 0.655] | 0.188 [0.156, 0.219] |
| D, patent level: the patent that holds the parent | keyword | 0.605 [0.535, 0.670] | 0.885 [0.840, 0.925] | 0.701 [0.644, 0.751] |
| | semantic | 0.815 [0.755, 0.865] | 0.990 [0.975, 1.000] | 0.887 [0.849, 0.919] |
| | hybrid | 0.775 [0.715, 0.825] | 0.960 [0.930, 0.985] | 0.844 [0.799, 0.881] |

Test D has no keyword or hybrid row at passage level because the keyword index holds only titles and abstracts. Also,
`cli.py similar` removes the whole source patent from its results, so the tool itself can never return a parent claim.

**Hybrid against the better single mode (paired difference in MRR): worse in all four tests.**

| Test | Better single mode | Hybrid minus that mode | Interval |
| --- | --- | --- | --- |
| A | keyword | -0.042 | -0.070 to -0.018 |
| B | semantic | -0.595 | -0.652 to -0.530 |
| C | semantic | -0.041 | -0.070 to -0.013 |
| D (patent level) | semantic | -0.043 | -0.082 to -0.007 |

**Variants of Test A**

| Variant | Keyword MRR | Semantic MRR | Hybrid MRR |
| --- | --- | --- | --- |
| Own claims removed (the plan; the rows above) | 0.931 | 0.873 | 0.889 |
| All claims of all patents removed (what `eval_results.md` does) | 0.931 | 0.923 | 0.936 |
| Control: nothing removed, a leak on purpose | 0.931 | 0.986 (recall at 1: 0.975) | 0.963 |
| Title put in front of the claim (what `similar --claim 1` sends) | 0.972 | 0.877 | 0.913 |
| With a filter on the patent's own subclass | 0.935 | 0.877 | 0.895 |

The subclass filter never made a rank worse (0 of 200 queries in every mode; 6 or 7 got better), so filters do not cost
recall when the answer passes the filter.

**Leakage checks**

- **Is the query excluded from the candidates?** Yes, in every test. The script asserts it for every query, and the
  control row shows what a leak looks like (semantic recall at 1 of 0.975 against 0.815).
- **Is my ranking the system's ranking?** Yes. My fusion code and `search()` gave the same full ranking for all 400
  query and mode pairs checked (0 mismatches).
- **Was claim 1 embedded with the title?** Yes for 186 of the 200 sampled first claims (they lost their opening words in
  the source). Those vectors are claims, so they are not candidates in Test A and do not help it. The title does help
  when it is in the query: both versions are in the table above.
- **Test B leaks unless the keyword index is touched.** Run as the system stands, the abstract finds its own row in the
  keyword index: keyword recall at 1 is 0.965 and hybrid MRR is 0.973. With that row blanked for the query, keyword
  falls to 0.135 and hybrid to 0.374. Only the second version is a fair test.
- **Does the built-in evaluation leak?** No: `eval_results.md` removes every claim from the candidates, so the query
  text cannot find itself. Its English numbers reproduce exactly. But it is lenient in three ways, and the README states
  only the first:
  1. A description often repeats its claim. In my sample 42.5% of the claims have at least half of their five-word
     sequences word for word in one passage of the same patent (19% have at least 80%). Semantic MRR is 0.965 on those
     and 0.806 on the rest.
  2. Removing all claims removes the hardest wrong answers. With only the patent's own claims removed, semantic MRR on
     the same 200 queries is 0.873 instead of 0.923.
  3. The 100 test patents are drawn only from the 505 that have a description. The 119 without one are harder: semantic
     MRR 0.788 against 0.896 in my sample.

### 3.4 Multilingual backtest (Stage 4)

The 100 patents that exist in English, German and Chinese. The query is the English first claim, identical for all
three targets. Claims are not candidates. Default mode (hybrid, query translated, calibrated). Gaps are in percentage
points against English, paired.

| Setting | Language | Recall at 1 | Recall at 10 | MRR | Gap in recall at 1 | Gap in recall at 10 | Gap in MRR |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Alone: 100 candidates in that language | English | 0.98 [0.95, 1.00] | 1.00 | 0.990 [0.975, 1.000] | | | |
| | German | 0.95 [0.90, 0.99] | 1.00 | 0.972 [0.944, 0.995] | -3.0 [-7.0, 0.0] | 0.0 | -1.8 [-3.8, 0.0] |
| | Chinese | 0.94 [0.89, 0.98] | 1.00 | 0.966 [0.936, 0.990] | -4.0 [-8.0, -1.0] | 0.0 | -2.4 [-4.8, -0.5] |
| Mixed: those 100 plus 540 other English patents | English | 0.90 [0.84, 0.96] | 1.00 | 0.945 [0.907, 0.976] | | | |
| | German | 0.86 [0.79, 0.93] | 0.99 [0.97, 1.00] | 0.908 [0.860, 0.953] | -4.0 [-9.0, +2.0] | -1.0 [-3.0, 0.0] | -3.7 [-7.1, -0.2] |
| | Chinese | 0.71 [0.62, 0.80] | 0.96 [0.92, 0.99] | 0.801 [0.732, 0.864] | -19.0 [-27.0, -12.0] | -4.0 [-8.0, -1.0] | -14.3 [-19.8, -9.3] |

| Mixed setting, other modes (MRR) | English | German (gap) | Chinese (gap) |
| --- | --- | --- | --- |
| Keyword only | 0.964 | 0.906 (-5.7 [-9.6, -2.6]) | 0.722 (-24.1 [-31.1, -17.7]) |
| Semantic only | 0.930 | 0.890 (-4.0 [-8.3, +0.3]) | 0.792 (-13.9 [-19.5, -8.8]) |
| Semantic, shared space (the rejected first design, as a control) | 0.930 | 0.007 | 0.003 |

Adding 100 foreign patents to the English corpus does not hurt English search: hybrid MRR changes by +0.1 points
[-0.8, +1.2] with German and +0.5 [0.0, +1.5] with Chinese.

These are my own script's numbers (`scripts/testing/backtest.py`). They equal `eval_results.md` to three decimals in
every cell. The table the clean clone regenerated from a freshly translated set is also identical.

**Is "comparable" supported?** Threshold fixed before running: the gap in recall at 10 and in MRR is at most 5 points,
and the lower end of the MRR interval is no worse than -10 points.

- German: yes, in both settings (worst case -3.7, interval down to -7.1).
- Chinese: yes alone, **no** among English patents (-14.3, interval -19.8 to -9.3).
- The README says exactly this ("German: close", "Chinese: not yet"). It does not claim comparable performance for
  Chinese, so its claim is supported on this test. Section 3.5 shows the test itself is too kind.

**Circularity.** Confirmed and stated in the README: `opus-mt-en-de` and `opus-mt-en-zh` produced the foreign patents and
also translate the query, so query and document share one model's wording. The English shown to the user comes from
`opus-mt-de-en` and `opus-mt-zh-en`, different models of the same family. Rebuilding the set gives the same text
(greedy decoding is deterministic), so the evaluation has one sample of translation noise, not two.

### 3.5 Forward test (Stage 5)

**Fresh queries.** 30 queries written before any search was run (`scripts/testing/forward_queries.json`), ten of them
also in German, Spanish, Chinese and Japanese: 70 searches, hybrid mode, on the 840 patent index. The top 5 of each
were judged 0 (unrelated), 1 (same area) or 2 (directly relevant) from the displayed title and passage: 365 distinct
items. Judging was done by three blind instances of the test agent that saw neither rank nor language. I checked 26 of
their scores by hand and agreed on 23; the three differences were one point each.

| The same 10 queries, by query language | Mean score at 5 (of 2) | Queries with a result scored 2 | Difference from English | Top 10 shared with the English query |
| --- | --- | --- | --- | --- |
| English | 0.94 | 70% | | |
| German | 0.86 | 50% | -0.08 [-0.24, +0.06] | 4.5 of 10 |
| Spanish | 0.80 | 60% | -0.14 [-0.32, -0.02] | 5.2 of 10 |
| Chinese | 0.54 | 30% | -0.40 [-0.66, -0.16] | 3.8 of 10 |
| Japanese | 0.36 | 10% | -0.58 [-0.92, -0.20] | 2.0 of 10 |

All 70 queries had their language detected correctly. The loss is in translating the query. What the system searched
with: two of ten Japanese queries became "It's a very simple process." and one became "The tire is a little bit like a
nail."; in Chinese, tread "grooves" became a "ditch" and "makes less humming noise" became "the smaller tires that
buzz". German and Spanish read well.

| 30 English queries, by kind | Mean score at 5 | Queries with a result scored 2 | Top similarity, lowest to highest |
| --- | --- | --- | --- |
| 10 general | 0.94 | 70% | 0.852 to 0.924 |
| 5 vague | 1.24 | 60% | 0.839 to 0.879 |
| 5 very specific | 1.28 | 80% | 0.855 to 0.920 |
| 5 with spelling mistakes | 0.68 | 40% | 0.842 to 0.868 |
| 5 that should match nothing | 0.00 | 0% | 0.810 to 0.858 |
| All 30 | 0.85 | 53% | |
| The 25 that should match something | 1.02 | 64% | |

**Queries that should match nothing** (aircraft engine, sourdough bread, phone camera, migraine drug, blockchain): each
returned 10 results. All 25 judged results are unrelated. Their similarity (0.81 to 0.86) overlaps real matches (0.84 to
0.92): "sourdough bread recipe" scored 0.858, higher than the top result of two of the ten general queries. There is
no score threshold and no warning.

**Other observations.** On the 840 patent index, 0.93 of every 10 result slots went to a second or third language copy
of an invention already listed. Across these 70 first-time searches a call took a median of 1.3 s, 13 s at the 95th
percentile and 58.7 s at worst (loading translation models, translating the query and the results shown).

**Time split.** Index built from the 46 files before 2025, then the 18 files of 2025 ingested through `cli.py ingest`.

| Check | Result |
| --- | --- |
| Incremental ingest without a rebuild | Yes. 180 patents added in 44.6 s; 10,195 new vectors appended; the 22,577 old vectors unchanged byte for byte |
| Duplicates | None: 640 patents, 640 distinct numbers, each passage embedded once. Ingesting the whole folder again: 640 "already indexed", 0.3 s |
| New patents searchable immediately | Yes: a 2025 patent was absent before, found by title and usable as a query right after |
| Same as an index built in one pass | Same passages; 0 of 150 top 10 lists differ; largest similarity difference 1.8e-07 |

| Test A, all eligible patents | Before 2025 (456) | 2025 (178) | Difference in MRR |
| --- | --- | --- | --- |
| Keyword: recall at 1, at 10, MRR | 0.919, 0.974, 0.942 [0.923, 0.960] | 0.899, 0.966, 0.929 [0.894, 0.959] | -0.013 [-0.053, +0.024] |
| Semantic | 0.822, 0.969, 0.881 [0.854, 0.905] | 0.843, 0.966, 0.892 [0.853, 0.929] | +0.011 [-0.037, +0.056] |
| Hybrid | 0.860, 0.980, 0.910 [0.888, 0.930] | 0.843, 0.978, 0.895 [0.853, 0.933] | -0.015 [-0.058, +0.028] |

No drop on the newer patents: nothing was fitted to the older data.

**Real foreign data.** `data/foreign/` is empty. The forward test on real foreign patents was not possible. All
multilingual evidence in this report and in the repository comes from machine-translated English patents.

### 3.6 Translation and display (Stage 6)

| Check | Result |
| --- | --- |
| Non-English results shown in English | 150 results from German-only and Chinese-only searches: every passage translated and in English, none stuck repeating, every title in English, all labelled `[translated from de]` or `[translated from zh]`, original text printed with `--show-original` for all 150. All 200 foreign patents have a stored English title and abstract |
| Abstract in the result list | Not shown. A result prints the title and one evidence passage (the abstract in 8 of 150). `cli.py show` prints the abstract and claims in English |
| Language detection, 20 passages each | English 20 of 20, German 20 of 20, Chinese 20 of 20 |
| Detection of my 10 queries in each of 5 languages | 50 of 50 under the passage rule and under the stricter query rule |
| Short, numeric and formula-only text | 15 of 15 formulas, numbers and empty strings give "unknown". Of 40 short English fragments, 1 was called Danish ("Deformation Mode: Tensile") |
| English taken for a foreign language | Abstracts 0 of 640. First claims 0 of 640. 2,000 passages: 1 (a formula). **Titles: 155 of 640 under the passage rule, 41 of 640 under the query rule** (upper case titles; 0 when lower-cased) |
| Translation cache, 10 Chinese passages | First request median 1,145 ms (703 to 9,114). Second request median 0.076 ms. Same text both times |
| Round trip, 10 passages, read by me | Through German: readable, numbers kept in 10 of 10. "rim" became "edge", "tread pattern" became "profile pattern", "bead" became "beaded", "lateral groove" became "side rod", "at most 10 mm to 12 mm" became "not more than 10 mm but not more than 12 mm". Through Chinese: numbers changed in 4 of 10 (a stray "281." and "272." appeared), "spoke" became "speech" and "interviews", "rim" became "circle", "sipe" became "mouth", "groove" became "sink", "carcass" became "body". "hub" survived both |
| Numbers survive, English to German (test set, 4,491 passages with a number) | All numbers identical in 92.0% |
| Numbers survive, German to English (as displayed, 100 passages) | 100 of 100 |
| Numbers survive, English to Chinese (test set) | 59.7% |
| Numbers survive, Chinese to English (as displayed, 100 passages) | **38 of 100.** Of 94 passages with a reference numeral of two or more digits, one was lost in 51 |
| Units | "phr" (parts per hundred rubber) became "Stunden" (hours) in German, as the README says |

### 3.7 Performance (Stage 7)

Latency over 50 queries (the 20 benchmark queries and my 30), each run twice, model warm, result translation off.
Milliseconds, median / 95th percentile. Machine quiet for these runs.

| 640 patents, 32,772 vectors | Whole call | Without encoding the query | Filter and score steps |
| --- | --- | --- | --- |
| No filter, semantic | 16.8 / 23.0 | 2.5 / 3.5 | 1.90 |
| No filter, keyword | 2.3 / 4.4 | 1.0 / 1.8 | |
| No filter, hybrid | 17.4 / 21.3 | 2.8 / 3.8 | 1.64 |
| Broad filter (53% of vectors kept): filter first / filter after | 23.3 / 29.5 and 17.8 / 22.2 | 7.8 and 3.4 | 6.63 and 2.27 |
| Medium filter (11% kept): filter first / filter after | 15.0 / 18.4 and 16.9 / 22.8 | 1.8 and 2.8 | 0.89 and 1.74 |
| Narrow filter (1% kept): filter first / filter after | 13.9 / 16.4 and 17.6 / 22.8 | 1.2 and 3.2 | 0.41 and 2.24 |

| Other measurements | Value |
| --- | --- |
| Cold start, three fresh processes | Index loads in 0.06 to 0.11 s. First query 6.8 to 7.2 s (loading the model). Second query 180 to 190 ms. Later queries 15 to 22 ms |
| Peak memory | Ingest 1,459 MB. A search 1,103 to 1,187 MB (1,928 MB once translation models load). Benchmark script 3,542 MB. Memory on the laptop's graphics processor is not in these figures |
| Disk | English index: database 21.0 MB, vectors 50.3 MB. With the 200 copies: 27 MB and 65 MB |
| Ingest | 137 s for 640 patents; embedding 250 vectors per second |

**Scaling probe.** A real index 10 times the size (6,400 patents, 327,720 vectors, built by `perf.py scale`), same 50
queries.

| Step, median ms | 640 patents | 6,400 patents | Growth |
| --- | --- | --- | --- |
| Scoring all vectors | 1.90 | 23.45 | 12.4 times |
| Keyword ranking | 0.67 | 5.63 | 8.4 times |
| SQL filter, classification prefix | 0.34 | 2.81 | 8.2 times |
| SQL filter, keyword | 0.09 | 2.00 | 23 times |
| SQL filter, title contains | 0.26 | 5.95 | 23 times |
| Whole hybrid call, no filter | 17.4 | 47.9 | 2.8 times |
| Narrow filter, filter and score: first / after | 0.41 / 2.24 (5.5 times apart) | 7.78 / 28.33 (3.6 times apart) | |

Scoring grows a little faster than linearly between these two sizes and then levels: 58 ms per million vectors at
32,772, 72 at 327,720, and 69 to 75 in the benchmark's 983,160. `docs/scale_design.md` assumes 70 ms per 983,160 and
linear growth beyond, which this supports for the scoring step. The two filters that scan (title, keyword membership)
grow faster than linearly and at 10 times the size the title filter costs three times as much as scoring what it kept.

**Measured against `benchmarks.md`.** The clean clone's rerun of the author's script, compared cell by cell
(`results/benchmark_clean_clone_vs_claimed.json`): 136 cells, 21 differ by more than 30%.

| Row | Claimed | Measured | Difference |
| --- | --- | --- | --- |
| Semantic, whole call | 15.9 / 20.8 | 16.3 / 22.2 | +3% / +7% |
| Hybrid, whole call | 17.0 / 22.2 | 17.8 / 22.6 | +5% / +2% |
| Keyword, whole call | 1.2 / 4.2 | 1.2 / 4.2 | 0% |
| Encode query | 14.0 to 14.4 | 13.9 to 14.3 | -1% |
| Score vectors, no filter | 1.42 to 1.44 | 2.27 to 2.31 | **+58% to +63%** |
| Filter after, real index, 6 of 10 filters | 1.35 to 1.67 | 1.88 to 2.28 | **+37% to +46%** |
| Filter first, 53% kept | 7.66 | 6.75 | -12% |
| 1% filter, first / after | 0.40 / 1.64 (4.1 times) | 0.41 / 2.28 (5.6 times) | +2% / **+39%** |
| At 983,160 vectors, no filter | 73.7 | 68.2 | -7% |
| At 983,160 vectors, 1% filter, first / after | 3.9 / 65.9 (17 times) | 2.9 / 60.6 (21 times) | -26% / -8% |

17 of the 21 flagged cells are steps of under 4 ms on the real index, all slower than claimed, in a range where the
README itself reports 20% to 40% variation between runs. The other 4 are at 983,160 vectors: one 95th percentile slower
(+72%) and three small filter-first cells faster (-31% to -44%). No complete call (encoding included) moved by more than
7%, and every filter first against filter after comparison points the same way as claimed. Slower than claimed and outside 30%, but
measured while the machine ran other tests: `evaluate_multilingual.py` 9.0 minutes against "about 6", and uncached query
translation 1,674 ms against 1,224 ms.

## 4. Claims audit

| Claim | Stated value | Where | Verdict | Measured |
| --- | --- | --- | --- | --- |
| Ingest time | 2 to 4 minutes; 32,772 vectors in 99 to 237 s | README 2 | Reproduced | 137 s; 131 s for the vectors |
| Embedding model download | 493 MB | README 2 | Reproduced | 470 MB |
| Start-up of `search` | about 10 s | README 2 | Reproduced | 8.5 to 9.6 s |
| Search itself | about 17 ms | README 2, 5 | Reproduced | 17.4 ms median, hybrid, warm. The one query a command line call runs shows 26 to 51 ms |
| Benchmark script | about 3 minutes, about 3 GB | README 2 | Reproduced | 170 s, 3.5 GB |
| Tests | 93, no model, about 1 s | README 2, Files | Reproduced | 93 passed in 1.3 s |
| Latin query under 40 letters treated as English | | README 2 | Reproduced | in code and in tests |
| Building the German and Chinese set | about 16 minutes, two models of about 600 MB | README 2 | Reproduced | 19.1 minutes on a shared machine; 571 and 598 MB |
| `ingest data/parallel` | about 5 minutes | README 2 | Reproduced | 5.7 minutes, shared machine |
| `evaluate_multilingual.py` | about 6 minutes | README 2 | Not reproduced | 9.0 minutes, shared machine |
| First Part 3 search returns one invention in three languages at ranks 1 to 3 | | README 2, 7 | Reproduced | English, Chinese, German, all shown in English |
| The same with `--cross-lingual shared` finds only the English one | | README 2, 7 | Reproduced | |
| 119 of 640 empty descriptions; 3,223 claims without a number; 167 cancelled in five formats; 25,013 character paragraph; 43 shared titles | | README 3 | Reproduced | all exact; "21,000 of 42,000 empty items" is 20,819 of 42,040 |
| Inferred numbers equal the numbering gap in 1,300 of 1,335 places | | README 3 | Not reproduced exactly | my recount: 1,308 of 1,312. No script in the repository prints this figure |
| Classification, keywords, dates and language use indexes | | README 3 | **Not reproduced** for classification | query plan is a scan of all patents (B3) |
| Exact search over 33,000 vectors under 2 ms | | README 3 | Partly | 1.6 to 2.3 ms across my runs |
| 42 missing-field cases (7 fields, 6 ways) | | README 4 | Reproduced | and 120 more of mine pass |
| Timing table | see 3.7 | README 5, `benchmarks.md` | Reproduced for whole calls | 21 of 136 cells over 30%, all sub-steps |
| Encoding is about 85% of a call | 14 of 17 ms | README 5 | Reproduced | 83% |
| Hybrid adds under 1 ms to semantic | | README 5, DECISIONS 7 | Reproduced | 0.3 to 0.8 ms |
| 1% filter: 4 times faster; 17 times at a million vectors | | README 5 | Reproduced for the scoring step | 5.5 times; 21 times. With the SQL filter included at 10 times the size: 3.6 times (B5) |
| 53% kept: filter first 4 times slower | | README 5 | Direction reproduced | 2.8 to 2.9 times slower |
| All three strategies return the same results | | `benchmarks.md` | Reproduced | section 3.2 |
| Removing the sort made scoring 5 times faster | 7.5 ms to under 2 ms | README 5 | Not testable | the old code is not in the repository |
| Every MRR, recall and interval in the Part 3 tables | 0.930, 0.007, 0.003, 0.945, 0.908, 0.801, 0.730 and the rest | README 7, `eval_results.md` | Reproduced | regenerated file identical; my own script agrees to three decimals |
| Language bias 27.5% and 76.5%; score levels 0.793 and 0.847 | | README 7 | Reproduced | identical |
| Larger models: e5-base 0.110, bge-m3 0.310 for a German target | | README 7 | Reproduced | 0.110 and 0.310 (Chinese 0.025 and 0.099) |
| Translating a claim-length query: 1.2 s, under 0.1 ms cached | | README 7 | Partly | 1.67 s on a shared machine; 0.09 ms |
| Ingest translation speed | 448 characters per second | README 8 | Partly | 357 on a shared machine |
| Every result prints in English with the language labelled; `--show-original` adds the original | | README 7 | Reproduced | 150 of 150 |
| "As a query language [Chinese] is 5 points behind" | | README 7 | Reproduced on the built-in test, **not supported on fresh queries** | section 3.5: mean relevance 0.54 against 0.94 |
| Proof of concept: 10 rows; same 10 patents in the same order as Python; approximate index returns 6, then 8 | | README 6, `poc/README.md` | Reproduced | 10, 10, 6, 8; largest score difference 1.2e-07; exact 1.22 ms |
| Proof of concept through Docker | | README 2 | Not run | Docker not installed. The README says the author did not run it either |
| Cost: $25,170.58 once, $3,829.02 a month, 76% database, $720,000 for full translation, 174 and 512 million vectors, 590 GB | | README 6, `docs/scale_design.md` | Arithmetic reproduced | 205 figures recomputed by `scripts/testing/check_cost_arithmetic.py`; every total holds |
| Prices behind the cost | | `docs/scale_design.md` | Not testable | no way to check prices here; the document marks the database prices as unverified |

**Cost arithmetic, line by line.** Four rounding slips that change no total: line 365 (25.1 kB should be 25.2), line 398
(327.7 GB should be 328.0), line 411 ($412.45 should be $412.46), line 436 (6,062 should be 6,067). Inputs that disagree
with the repository's own numbers: line 368 calls 229 vectors per second the slower laptop run, while `NOTES.md` records
138; lines 210 and 370 quote 70 ms per 983,160 vectors "from benchmarks.md", which says 73.7; line 211 quotes 2.4 ms,
43.1 ms and 18 times, where the committed file says 3.9, 65.9 and 17.1. Internal inconsistencies: line 211 routes a
filter that leaves 1.74 million vectors to exact search while line 214 sets the limit at about 1 million; line 521 needs
1,010.9 GB for a re-embedding where 1,000 GB is provisioned (line 400); line 262 filters on a `language` column the
`passages` table (lines 84 to 95) does not have. Assumptions stated without a source that carry most of the money: the
30% foreign share ($22,080 of the $25,170 one-time cost), the managed database prices (79% of the monthly bill with its
disk), and the half-precision index size, which has never been run. Full list: `scripts/testing/results/scale_design_audit.md`.

**README coverage of what the challenge requires.**

| Required | Present |
| --- | --- |
| Problem statement | Yes, section 1 |
| How the code addresses it | Yes, section 3 |
| Which enhancement and why | Yes, section 7 |
| How to run Parts 1 and 3, reproducibly | Yes, section 2. Verified from a clean clone |
| Missing field policy | Yes, section 4 |
| Timing with and without hybrid search, with commentary | Yes, section 5 |
| Part 2 design: components, pipelines, cost, errors, tracking, challenges | Yes, all present in `docs/scale_design.md` |
| Part 2 proof of concept | Yes, runs without Docker |
| Video | **No.** Placeholder |
| Non-English sample requested | The README says it was requested and had not arrived |

**`DECISIONS.md` against the code.** All eight decisions are implemented as written: passages as the unit; query
translated per language with scores calibrated on a 2,000 passage sample; only title, abstract, query and displayed text
translated; no patent dropped; filter first below 15% of vectors; reciprocal rank fusion with constant 60 over BM25 on
English title and abstract; SQLite and one array. I found no documented decision the code does not implement.

## 5. Findings

No fix was applied.

### Blocking

| # | Finding | Evidence | Suggested fix |
| --- | --- | --- | --- |
| B1 | Video link missing | README line 7: "link to be added" | Record and link it |
| B2 | No public repository to hand in | `git remote -v` is empty | Push and put the link in the submission |

### Major

| # | Finding | Evidence | Suggested fix |
| --- | --- | --- | --- |
| M1 | **Hybrid, the default mode, is worse than the better single mode in every known-answer test**, and collapses when the right patent's title and abstract lack the query's words | Section 3.3: -4 points of MRR in A, C and D, all intervals below zero. Test B: 0.374 against 0.970 for semantic. Cause: the keyword list covers only title and abstract but gets the same vote as the passage-level list; a patent ranked first by meaning and absent from the keyword list scores 1/61, less than a patent ranked 50th in both | Until tuned, default to semantic, or weight the lists, or only let keywords reorder the semantic top results. Add Tests A and B to the evaluation so the fusion can be tuned against something |
| M2 | **On fresh queries, Chinese and Japanese are not comparable**, and the built-in evaluation hides it | Section 3.5: mean relevance 0.54 (Chinese) and 0.36 (Japanese) against 0.94; a directly relevant result for 30% and 10% of queries against 70%. The built-in "Chinese query" test shows only -5 points because its query is a machine translation of the target patent's own claim. Japanese and Spanish are not evaluated in the repository at all | State it. Translate queries with beam search or a stronger model; add independently written foreign queries to the evaluation |
| M3 | **No signal that a search found nothing** | Section 3.5: off-topic queries return 10 results with similarity 0.81 to 0.86, inside the range of real matches. A query of only punctuation or only spaces also returns a ranked list (`cli.py search "?!...,;:--()"` exits 0 with results) | Reject a query with no words. Use the per-query background sample the code already computes to print a warning when the best result is not clearly above it |
| M4 | **The keyword filter matches words the user did not type** | `--keywords generator` passes 27 patents; 1 contains "generator". The other 26 contain "generally", "generated" or "generic" (Porter stemming). `--keywords general` passes the same 27 with 0 containing "general" | Use an unstemmed index for the filter and keep stemming for ranking |
| M5 | **Two filters scan every patent, and the headline speed-up excludes the filter's own cost** | B3 and B5. Title filter step 0.26 ms at 640 patents, 5.95 ms at 6,400 | Rewrite the classification filter as a range lookup on `classifications.code`; index titles; rerun part 2 of the benchmark on a real enlarged index |
| M6 | **Chinese text shown in English loses numbers and claim terms** | Section 3.6: numbers intact in 38 of 100 displayed Chinese passages (German: 100 of 100); "spoke" shown as "speech", "sipe" as "mouth". Measured on machine-made Chinese, so real patents may differ | Copy numerals through translation (mask and restore), and say in the README how often they change |
| M7 | The built-in English baseline is easier than it looks | Section 3.3, leakage checks: 0.923 with all claims removed against 0.873 with only the patent's own; 0.965 on restated claims against 0.806; patents without a description left out | Report the stricter variant beside the current one |

### Minor

| # | Finding | Evidence | Suggested fix |
| --- | --- | --- | --- |
| m1 | A claim number that does not exist is answered with the abstract, without saying the claim is missing | `python cli.py similar --doc 20240051333 --claim 999` prints "Searching with the abstract of 20240051333." and results | Error, or say "claim 999 not found, using the abstract" |
| m2 | `--top -1` returns everything but the last result | 639 results on the English index | Refuse values below 1 |
| m3 | A keyword filter with no usable word is ignored | `--keywords "!!! ???"` returns all 640 | Error |
| m4 | English titles in capitals are taken for another language | 41 of 640 as a query (German 37, Vietnamese 3, Somali 1): the query is run through a translator ("TREAD" became "thread") and a 554 MB Vietnamese model was downloaded during my tests. Ranking barely moved (1 of 37 worse). At ingest, 155 of 640 titles would be labelled foreign, which matters only for a patent with no other text | Lower-case before detecting; never download a model for a language the index does not hold |
| m5 | A null inside a classification list becomes the code `NONE` | `tests/test_independent_ingest.py::test_a_null_inside_a_classification_list_does_not_become_a_code` | Skip non-strings |
| m6 | A patent with no searchable text is counted but not named | ingest prints only `no_searchable_text: 1` | Print the document number |
| m7 | Similarity does not find a dependent claim's parent | Test D: parent is the top match 5% of the time, and the evidence shown is the parent in 6% | Not a defect of search. The stored `parent_claim` link is the right source; say so if claim mapping inside a patent is in scope |
| m8 | Semantic title lookup depends on letter case | Test C: recall at 1 0.93 with the stored capitals, 0.81 in lower case | Lower-case titles before embedding them |
| m9 | Title filter is "contains" only; keywords cannot be a phrase | section 3.2 | Add an exact option, or document it |
| m10 | The README example for `--show-original` shows no original | B4 | Add `--language zh` to that example |
| m11 | The same invention can fill several result slots | 0.93 of 10 slots on the 840 patent index | Group by family when real data has families |
| m12 | 25 dependent claims point at a parent that was cancelled and is not stored; 91 patents have no claim numbered 1 | counts on the real index | Display only |
| m13 | Transitive dependencies and model revisions are not pinned | `requirements.txt` pins 6 packages; torch 2.15.0 and transformers 5.23.0 arrive unpinned | Add a lock file and a model revision |
| m14 | Small slips in `docs/scale_design.md` | section 4 | Correct the four roundings and the three stale benchmark quotes |

## 6. Limitations the README should state but does not

- Hybrid search is worse than keyword-only or semantic-only on every known-answer test here, not merely "as good as".
  The README says so only for one English test.
- The tool always returns a full list. Nothing tells a user that the best result is noise.
- Japanese and Spanish queries work mechanically but were never evaluated; on my ten queries Japanese is the weakest by
  far. The Chinese query result in the README comes from a round trip and does not predict fresh queries.
- The keyword filter stems words and can pass patents that do not contain the keyword.
- The classification and title filters read every patent. The 17 times figure is for the scoring step only.
- Chinese display changes numbers and reference numerals in most passages.
- The English baseline excludes all claims from the candidates and leaves out the 119 patents without a description.
- A foreign-language copy of the same invention is listed as a separate result.
- A search needs about 1.1 GB of memory, 1.9 GB once translation models are loaded.
- Results a year from now may differ: torch, transformers and the model files are not pinned.

## 7. Not run

| Check | Why |
| --- | --- |
| Proof of concept through Docker (`docker compose up -d --wait`) | Docker is not installed on this machine (exit 127). The embedded PostgreSQL path was run instead |
| Forward test on real foreign patents (Stage 5, part 3) | `data/foreign/` is empty |
| `pip install` with an empty pip cache | The pip cache was warm; download time for 1.2 GB of packages is not in the 183 s |
| Part 3 timings on an idle machine | Those three steps ran while other test jobs used the machine. Their times are upper bounds |
| `scripts/compare_models.py` inside the clean clone | It would download 5.7 GB. Run instead on the working copy with the models already on disk; it reproduced |
| "Removing the sort made scoring 5 times faster" | The earlier code is not in the repository |
| Every price in `docs/scale_design.md` | No offline source; the document marks the largest ones unverified |
| The video | It does not exist yet |
| A machine without a graphics processor, another operating system | Only this laptop was available |
| A second relevance judge per item | Each of the 365 items was judged once; I re-judged 26 |
