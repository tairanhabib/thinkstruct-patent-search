# The eight decisions that matter

Each one says what I chose, what I rejected, and why, in plain language. Numbers are from [NOTES.md](NOTES.md),
[benchmarks.md](benchmarks.md) and [eval_results.md](eval_results.md).

"MRR" below is mean reciprocal rank: 1.0 means the right patent is always first, 0.5 means it is second on average.

## 1. Search passages, not whole patents

**Chose:** every claim, the abstract, and every description paragraph is its own searchable unit. A result is a patent
plus the one passage that matched best.

**Rejected:** one vector per patent (for example the abstract, or an average of everything).

**Why:** the job is claim mapping. An examiner needs to see *which* claim or paragraph overlaps, not just that a
document is related. One vector per patent would also blur a 60 paragraph description into a single point. The price is
about 51 vectors per patent instead of 1, which is the main cost driver at 10 million patents (512 million vectors), so
the scale design embeds abstract and claims first (17 per patent) and descriptions second.

## 2. Translate the query into each language, not the documents, and not nothing

**Chose:** passages are embedded in their original language. At search time the short query is translated into each
language in the index, and each passage is scored against the query in its own language.

**Rejected, first:** the plan I started with. One multilingual model, one shared vector space, no translation for
search at all. I built it and measured it. In a corpus that mixes languages it fails completely: for an English query the
right German patent had an MRR of 0.007 and the right Chinese one 0.003, against 0.930 for English. Not one of 200
foreign targets reached the first ten results. The model scores two unrelated English passages as more alike than a
passage and its own translation. Bigger models reduced this and none removed it (the best of three reached 0.310).

**Rejected, second:** translating every document to English and searching in English. It works, but search quality then
depends on translation quality forever, and the translation bill grows with the corpus: $720,000 at hosted prices for
10 million patents, against $22,080 for title and abstract.

**Why:** a query is a sentence. A corpus is terabytes. Translating the short side fixed the gap (hybrid MRR 0.921 German,
0.933 Chinese, 0.945 English) and keeps the documents untouched. The cost is one translation per language for a new query
(about 1.3 seconds for a full claim, measured on the slow side, then cached) and a new dependency on translating the
query well.

**What I am not sure of:** those numbers come from machine translated test patents, made by the same models that
translate the query. They are an upper bound until the real foreign sample is tested.

## 3. Translate three small things, and only those

**Chose:** (a) title and abstract of a foreign patent, once, at ingest; (b) the query; (c) whatever is displayed, at the
moment it is displayed, cached.

**Rejected:** translating full text at ingest. Also rejected: translating nothing at ingest.

**Why:** keyword search cannot cross languages, and Chinese has no spaces between words, so keywords need English text.
Title and abstract are about 740 characters per patent, 3% of the text. That alone gave keyword search an MRR of 0.906
on German patents, and it was the only thing that worked while the shared space was failing. Display translation
touches only the handful of passages a person actually reads. And translation quality is poor enough that it should not
be trusted with more: the title "SPOKE" came back as "Speaker", and a rubber recipe in "parts" came back in "hours".

## 4. Measure "comparable" on a mixed corpus, with an interval

**Chose:** build the same 100 patents in English, German and Chinese. Search with the first claim in English, remove
claims from the candidates, and count where the same patent's abstract or description ranks. Do it with the foreign
patents mixed among 540 other English patents. Report the gap to English with a 95% interval, and also run the test
backwards (foreign query, English patents).

**Rejected:** testing each language on its own, or reading a few results and calling them good.

**Why:** a real corpus is mixed, and the mixed test is where the first design fell apart. On its own, German looked
merely worse (0.409). Mixed, it was invisible (0.007). Looking at a few results would have missed it entirely, because
every result returned was a plausible English patent. The backwards test matters because it is the only one where the
documents are original human text, and it is the one that shows Chinese still falling short (0.862 against 0.945).

**What it does not measure:** real foreign patents, real relevance (finding the same patent is a stand-in), or more than
one technical field.

## 5. Keep every patent, whatever is missing

**Chose:** never drop a patent. A field with no content is stored as missing and shown as "Unknown". A filter on a
missing field leaves the patent out of *that* search only, and `--include-unknown` lets it through.

**Rejected:** excluding patents with missing fields, which the task allowed.

**Why:** 119 of the 640 patents have an empty description. Excluding them would silently remove 19% of the prior art, and
a search tool that hides prior art without saying so is worse than one with gaps it shows. The filter rule follows from
the same idea: "we do not know its classification" is not the same as "it is not in B60B", so the user decides.
The same reasoning covers damaged claims: 3,225 claims lost their number and opening words in the source. They are
kept, numbered as "previous claim plus one" (right in 1,300 of 1,335 places where it can be checked), and labelled as
inferred.

## 6. Filter first only when the filter is selective

**Chose:** apply filters in SQL before touching vectors when they keep under about 15% of the vectors, and otherwise
score everything in place and discard afterwards. The switch is automatic.

**Rejected:** always filtering first (my plan), and always filtering afterwards (the naive way).

**Why:** I measured both. With a filter that keeps 1% of vectors, filtering first was 6 times faster on the real index
and 19 times faster at a million vectors. With a filter that keeps 53%, filtering first was 2.7 times *slower*, because
it has to copy the surviving rows out before scoring them and a copy costs more than the arithmetic. This is also the
answer to "how can hybrid search help performance": a selective filter on an index is nearly free and removes most of
the expensive work, and the benefit grows with the corpus.

## 7. Combine keyword and meaning by rank, not by score

**Chose:** two rankings, one from keywords (BM25 on English title and abstract) and one from embeddings, merged by
reciprocal rank fusion: each patent gets 1/(60 + rank) from each list.

**Rejected:** adding the two scores with weights. Also rejected: meaning only.

**Why:** a keyword score and a cosine similarity are on different scales, and any weights would have to be tuned on
relevance data I do not have. Ranks need no tuning. Keywords also earn their place: they catch exact part names that
embeddings blur, and for a Chinese query they lifted the result from 0.770 to 0.862. Hybrid adds under 1 ms to a query.

## 8. One plain database now, one PostgreSQL later, no vector database

**Chose:** SQLite plus one NumPy array for Part 1. For 10 million patents, one PostgreSQL with the pgvector extension
holding metadata, full text and vectors together.

**Rejected:** a dedicated vector database beside a relational one.

**Why:** at 640 patents, exact search over all 32,772 vectors takes 1.4 ms, so any index structure is overhead, and
the reviewer installs nothing. At scale, keeping everything in one database makes the hybrid query a single SQL
statement, gives one thing to back up, and means text, keywords and vectors can never disagree about which patents
exist. The proof of concept shows the statement working and returning the same ten patents as the Python search. It
also shows the price: forced onto the approximate index with a selective filter, it returned 6 of 10 right answers. So
the design uses exact search when a filter leaves few vectors and the approximate index otherwise. The honest weak
spot is memory: the index for full text is about 590 GB, which triples the database bill.
