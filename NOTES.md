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
