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
