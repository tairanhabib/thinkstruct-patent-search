# The eight decisions that matter

Each one says what I chose, what I rejected, and why, in plain language. Numbers are from [NOTES.md](NOTES.md),
[benchmarks.md](benchmarks.md) and [eval_results.md](eval_results.md).

Decisions 6 and 7 changed after an independent test pass ([TEST_REPORT.md](TEST_REPORT.md)). Decision 7 was reversed
by it. The numbers in 2 and 4 are those of the new default.

"MRR" below is mean reciprocal rank: the average of 1/rank of the right patent. 1.0 means it is always first, and a
search that always puts it second scores 0.5.

## 1. Search passages, not whole patents

**Chose:** every claim, the abstract, and every description paragraph is its own searchable unit. A result is a patent
plus the one passage that matched best.

**Rejected:** one vector per patent (for example the abstract, or an average of everything).

**Why:** the job is claim mapping. An examiner needs to see *which* claim or paragraph overlaps, not just that a
document is related. One vector per patent would also blur a 60 paragraph description into a single point. The price is
about 51 vectors per patent instead of 1, which is the main cost driver at 10 million patents (512 million vectors), so
the scale design embeds abstract and claims first (17 per patent) and descriptions second.

## 2. Translate the query into each language, and compare scores relative to each language's own level

**Chose:** passages are embedded in their original language. At search time the short query is translated into each
language in the index, and each passage is scored against the query in its own language. Before languages are merged,
every score is expressed as how far it stands above its own language's background for that query.

**Rejected, first:** the plan I started with. One multilingual model, one shared vector space, no translation for
search at all. I built it and measured it. In a corpus that mixes languages it fails completely: for an English query the
right German patent had an MRR of 0.007 and the right Chinese one 0.003, against 0.930 for English. Not one of 200
foreign targets reached the first ten results. The model often scores two
unrelated English passages as more alike than a passage and its own translation: for 27.5% of other English abstracts
against a patent's German copy, and 76.5% against its Chinese copy. Bigger models reduced this and none removed it (the
best of three reached 0.310).

**Rejected, second:** translating the query and merging the raw scores. I shipped this and called it comparable,
because the test I had (is the right foreign patent found?) said German 0.912 and Chinese 0.935 against 0.930. Then I
used the tool and saw unrelated Chinese patents at the top of an English search. Each language has its own score level:
an unrelated Chinese passage scores about 0.85 against a Chinese query, an unrelated English one about 0.79 against the
English query. Merged raw, adding 100 Chinese patents cut English search from 0.930 to 0.730, and Chinese copies took
154 of 200 top-ten places on short queries.

**Rejected, third:** translating every document to English and searching in English. It works, but search quality then
depends on translation quality forever, and the translation bill grows with the corpus: $720,000 at hosted prices for
10 million patents, against $22,080 for title and abstract.

**Why:** a query is a sentence. A corpus is hundreds of gigabytes. Translating the short side lets foreign patents be found
and leaves the documents untouched. Comparing scores relative to each language's level keeps one language from winning
by default: adding foreign patents now costs English search almost nothing (0.930 before, 0.930 and 0.920 after). The
cost is one translation per language for a new query (about 1.3 seconds for a full claim, measured on the slow side,
then cached), a small extra calculation per query, and a new dependency on translating the query well.

**Where it stands:** German is 2 to 4 points behind English in every test of mine. Chinese is not there yet: a Chinese
patent among English ones is ranked first 70% of the time against 89% (MRR 0.792 against 0.930). On short queries the
correction is not even: German versions of the same patents come back twice as often as English ones.

**Where the dependency bites:** the independent tester wrote fresh queries in five languages. German and Spanish
queries did as well as English ones. Chinese reached half and Japanese a third of the relevance, because the
translation of the query fails ("It's a very simple process." for two of ten Japanese queries). I then compared this
decision against embedding the original query with no translation, against fusing both, and against a wider
translation search. None was measurably better on 40 queries, so the decision stands and the gap is written down.

**What I am not sure of:** these numbers come from machine translated test patents, made by the same models that
translate the query, so they flatter the method. And the calibration assumes each language's patents cover the same mix
of topics, which is true of my test set by construction and may not be true of a real one.

## 3. Translate three small things, and only those

**Chose:** (a) title and abstract of a foreign patent, once, at ingest; (b) the query; (c) whatever is displayed, at the
moment it is displayed, cached.

**Rejected:** translating full text at ingest. Also rejected: translating nothing at ingest.

**Why:** keyword search cannot cross languages, and Chinese has no spaces between words, so keywords need English text.
Title and abstract are about 740 characters per patent, 3% of the text. That alone gave keyword search an MRR of 0.906
on German patents, and it was the only thing that worked while the shared space was failing. Display translation
touches only the handful of passages a person actually reads. And translation quality is poor enough that it should not
be trusted with more: the title "SPOKE" came back as "Speaker", and a rubber recipe in "parts" came back in "hours".

## 4. Measure "comparable" from both sides, on a mixed corpus, with an interval

**Chose:** build the same 100 patents in English, German and Chinese. Search with the first claim in English, remove
claims from the candidates, and count where the same patent's abstract or description ranks. Then ask two different
questions. Is a foreign patent found among English ones? And does adding foreign patents make English search worse?
Report gaps with a 95% interval. Also run it backwards (foreign query, English patents), and count which languages short
queries return.

**Rejected:** testing each language on its own, reading a few results and calling them good, and, the mistake I
actually made, asking only the first of those two questions.

**Why:** a real corpus is mixed, and each failure only showed up in the test built to catch it. On its own, German
under the shared space looked merely worse (0.459). Mixed, it was invisible (0.007). Then the raw-score version passed
the "is it found" test with 0.935 for Chinese and failed the "does it hurt" test badly (English fell from 0.930 to 0.730),
because any method that scores foreign patents too high passes the first test. A test that can be passed by cheating
needs a second test that the cheat fails. I found the second problem by using the tool, not by measuring, and that is
the lesson I would take from this project.

**What it does not measure:** real foreign patents, real relevance (finding the same patent is a stand-in), or more than
one technical field. The independent tester found a third thing it does not measure, the same way I found the second:
by asking a question the test could not fail. My "query in another language" test uses a translated copy of the
target's own claim as the query, and shows Chinese 11 points behind. With queries a person would type, Chinese is at
half. The lesson repeats: the test set was built by the system's own translation models, so it cannot see where they
fail.

## 5. Keep every patent, whatever is missing

**Chose:** never drop a patent. A field with no content is stored as missing and shown as "Unknown". A filter on a
missing field leaves the patent out of *that* search only, and `--include-unknown` lets it through.

**Rejected:** excluding patents with missing fields, which the task allowed.

**Why:** 119 of the 640 patents have an empty description. Excluding them would silently remove 19% of the prior art, and
a search tool that hides prior art without saying so is worse than one with gaps it shows. The filter rule follows from
the same idea: "we do not know its classification" is not the same as "it is not in B60B", so the user decides.
The same reasoning covers damaged claims: 3,223 claims lost their number and opening words in the source. They are
kept, numbered as "previous claim plus one" (right in 1,331 of 1,335 places where it can be checked), and labelled as
inferred.

## 6. Filter first only when the filter is selective

**Chose:** apply filters in SQL before touching vectors when they keep under about 15% of the vectors, and otherwise
score everything in place and discard afterwards. The switch is automatic.

**Rejected:** always filtering first (my plan), and always filtering afterwards (the naive way).

**Why:** I measured both, eight times. With a filter that keeps 1% of vectors, filtering first was 2.5 to 6 times
faster on the real index and 13 to 21 times faster on the scoring step at a million vectors. With a filter that keeps
53%, filtering first was 3 to 4 times *slower*, because it has to copy the surviving rows out before scoring them and a
copy costs more than the arithmetic. This is also the answer to "how can hybrid search help performance": a selective
filter on an index is nearly free and removes most of the expensive work. For middling filters (10% to 20% kept) the
benefit shrinks or reverses, which is why the switch is automatic.

**What the independent test pass added:** the 13 to 21 times is the scoring step only. With the filter's own cost
included, on a real index 10 times the size, the same 1% filter was 2.1 times faster, because "title contains" reads
every title and that scan grew 24 times. The classification filter also read every patent. It is now a range on an
index, and at that size it is 3.2 times faster than filtering afterwards for a filter that keeps 2.9%. So the benefit
depends on the filter being cheap, not only selective.

## 7. Rank by meaning alone. Fusing keywords in is an option, not the default

**Chose first, and it was wrong:** two rankings, one from keywords (BM25 on English title and abstract) and one from
embeddings, merged by reciprocal rank fusion with equal votes. I chose ranks over scores because a keyword score and a
cosine similarity are on different scales, and ranks need no tuning. I never tested whether the fusion beat its parts.

**What the independent tester measured:** four tests where the right answer is known from the data, 200 queries each.
The fused ranking was behind the better of its two parts on every one: by 4 points on three of them, and by 60 on the
test where an abstract has to find its own claims. The keyword list reads only title and abstract, the semantic list
reads every passage, and both had the same vote, so a patent ranked first by meaning and missing from the keyword list
lost to a patent ranked 50th in both.

**Chose now:** semantic ranking is the default. The fusion has a weight for the keyword list, I swept it on two of the
four tests, and the answer was "as small as possible": no weight made the fused ranking as good as the better part on
all four. Fusion stays as `--mode hybrid` with the keyword list at 0.02, where it settles near-ties. Keyword search
alone stays as `--mode keyword`, and it is the best of the three when the query repeats a patent's own words.

**Rejected:** keeping the equal-vote fusion as the default. Also rejected: a weight in between, which is worse than
semantic on one test and no better than it on the others.

**What I am not sure of:** the same tester's 30 fresh queries, judged for relevance, do not confirm the switch. They
are neutral overall, and on the 10 everyday-language queries, with the German and Chinese copies in the index, the old
fusion was better (0.84 against 0.68 on a scale of 0 to 2). Known-answer tests reward exact matches of long texts.
Fresh queries are short and vague. I followed the tests that have 800 queries over the one that has 30, and I list the
default as open.

## 8. One plain database now, one PostgreSQL later, no vector database

**Chose:** SQLite plus one NumPy array for Part 1. For 10 million patents, one PostgreSQL with the pgvector extension
holding metadata, full text and vectors together.

**Rejected:** a dedicated vector database beside a relational one.

**Why:** at 640 patents, exact search over all 32,772 vectors takes under 2 ms, so any index structure is overhead, and
the reviewer installs nothing. At scale, keeping everything in one database makes the hybrid query a single SQL
statement, gives one thing to back up, and means text, keywords and vectors can never disagree about which patents
exist. The proof of concept shows the statement working and returning the same ten patents as the Python search. It
also shows the price: forced onto the approximate index with a selective filter, it returned 6 of 10 right answers. So
the design uses exact search when a filter leaves few vectors and the approximate index otherwise. The honest weak
spot is memory: the index for full text is about 590 GB, which triples the database bill.
