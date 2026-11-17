# Audit of the numbers in `docs/scale_design.md`

Date: 17 November 2026. Reproduce with `python scripts/testing/check_cost_arithmetic.py` (stdlib only, always exits 0). "L" is a line of `docs/scale_design.md` unless a file is named. No repo file was edited. No network was used.

Rule: each figure is recomputed from the document's own inputs and rounded half up to the digits the document prints. MISMATCH means the rounded value differs from the printed one. "Coarse" means it rounds to the printed digits, but the raw difference is above 1% because few digits are printed.

Result: 205 rows. [A] inside the design document: 154 rows, 148 OK, 6 not OK. [X] the same figures quoted in README.md, DECISIONS.md, NOTES.md and poc/README.md: 34 rows, all OK. [R] design inputs against numbers measured in this repo: 17 rows, 11 OK, 6 not OK.

## Arithmetic

### Not OK (12)

| Line | What | Stated | Recomputed | Verdict |
| --- | --- | --- | --- | --- |
| L365 | 16.1 MB / 640 | 25.1 kB | 25.16, prints as 25.2 kB | MISMATCH, rounding (0.22%) |
| L398 | 10,000,000 × 32.8 kB | 327.7 GB | 328.0 GB | MISMATCH, rounding (0.09%). 327.7 needs the unrounded 32.768 kB. Adds 0.3 GB to 340.0, 675.4, 1,327.1 (L398, L399) and 937.7 (L470). No price changes |
| L411 | 338,000,000 / 229 / 3,600 × $1.006 | $412.45 | $412.4551, prints as $412.46 | MISMATCH, 1 cent |
| L436 | 2,778,802 characters / 458 s | 6,062 | 6,067 | MISMATCH, rounding (0.09%). NOTES.md L414 has the same pair. The 101 h and $102 on L438 do not change |
| L211 against L214 | Route for a filter that keeps 1% | "Exact" | 1.74 million vectors survive. The rule on L214 allows exact only below about 1 million | Does not hold |
| L521 against L400 | Disk for re-embedding | about 335 GB extra, 1,000 GB provisioned | 675.4 + 335.5 = 1,010.9 GB | Does not fit |
| L368, L411, L490 [R] | Slowest laptop embedding run | 229 vectors/s | 138.3 (32,772 / 237.0 s, NOTES.md L576) | MISMATCH. At 138.3/s phase 1 is 349.5 h and $351.63, not 211.1 h and $212.33. A4's ratio becomes 3.0 to 7.2 |
| L369 [R] | Parse and load rate | about 100 patents/s | 2.2 on the final run: 640 / (525 s - 237.0 s), NOTES.md L576, L577 | MISMATCH. At 2.2/s: 1,250 process-hours, 6.5 days on 8 processes, $45, not 3.5 h and $6.96 |
| L370, L210 [R] | Unfiltered scan of 983,160 vectors | 70 ms, source named as benchmarks.md | 73.7 ms median, 79.7 ms 95th percentile (benchmarks.md L41) | MISMATCH (5.0%). 12.4 s becomes 13.0 s |
| L211 [R] | Filter first, 1% kept | 2.4 ms | 3.9 ms (benchmarks.md L51) | MISMATCH. The document's pair is from an earlier run (NOTES.md L211) |
| L211 [R] | Filter after, 1% kept | 43.1 ms | 65.9 ms (benchmarks.md L51) | MISMATCH. The ratio there is 17.1, the document says 18 |
| L365 [R] | Raw bytes per patent | 25.1 kB | 24.9 kB (15,939,070 B in 64 files / 640) | MISMATCH, rounding (0.8%). 16.1 MB is the allocated size from `du`, not the content |

### OK (193), grouped by line. Recomputed values in brackets where they add digits.

| Lines | What | Stated figures | Verdict |
| --- | --- | --- | --- |
| L13, L14 | Summary sizing | 174 million, 135 GB, 512 million, 397 GB | OK (135.02, 397.31) |
| L128 | Stored vector, index, fit | 1,544 B, about 200 GB, about 334 GB, fits in 256 GiB | OK (200.45, 334.08, 250.6 of 274.9). The 334 formula is not shown: it is 174M × (1,152 + 768) B |
| L181, L183, L185 | Backfill times | 28 process-hours, 3.5 h, 48.3 GPU-hours, 12 h, 9.1 h | OK (27.78, 3.47, 48.33, 12.08, 9.14) |
| L210, L211, L214 | Exact scan scaling | 12.4 s, 18 times, 1.74 million, 0.12 s, 57,000, 19,500, 70 ms | OK (12.389, 17.96, 0.1239 coarse, 57,471, 19,531, 71.2 coarse) |
| L361 to L367 | Measured inputs | 17.4, 51.2, 24,000, 736, 32.8 kB, 1,536 B, 768 B | OK (17.375, 51.206, 736.4, 32.81) |
| L369 | Parse rate | about 100 patents/s | OK, coarse (640 / 6.8 = 94.1, 640 / 5.8 = 110.3) |
| L377 to L385 | Assumptions | 3,000,000, 3.0 to 4.4 times, 1,152 B, 1,888 B, 1,120 B, 730 h, 4.33 weeks | OK (3.03, 4.37, 1,887.8, 4.333) |
| L392 to L397 | Vectors, bytes, index, memory | 174,000,000, 512,000,000, 267.3, 786.4, 135.0, 397.3, 200.4, 589.8, 250.6, 737.3, 274.9, 824.6, 549.8 GB, 512 GiB too small | OK (267.264, 786.432, 135.024, 397.312, 200.448, 589.824, 250.56, 737.28, 274.878, 824.634, 549.756) |
| L398 to L400 | Text and disk | 12.3, 340.0, 675.4, 1,327.1 GB, room to rebuild in 1,000 and 2,000 GB | OK as sums of the printed addends (12.288, peaks 875.8 and 1,916.9 GB) |
| L408 to L415 | One-time compute | 338,000,000, 48.3 h, 93.9 h, $48.62, $94.45, 211.1 h, $212.33, 410.0 h, 100,000 s, 27.8, $6.96, $3,035.00, $96, less than one database day | OK (48.333, 93.889, 48.6233, 94.4522, 211.063, 212.329, 409.995, 27.778) |
| L421 to L427 | Translation | 2,208,000,000, $22,080, $33,120, $44,160, 72,000,000,000, $720,000, 32.6 times | OK (32.609) |
| L435 to L440 | Local translation | 448, 7,035, 1,369 h, $1,377, 101 h, $102, 21,948 h, 79.0 million s, 28 | OK (448.33, 7,034.94, 1,369.05, 1,377.26, 101.18, 101.78, 21,948.31, 79.014, 27.94) |
| L446 to L454 | Monthly lines and totals | $2,920.00, $8,760.00, $115.00, $230.00, $119.14 twice, $4.36, 2,208,000, 9,560,640, $95.61, 45,000,000, $450.00, 251 GB, $5.77, $3,829.02, $9,784.02 | OK (119.136, 4.356, 95.6064, 5.773) |
| L458 to L462 | Notes | $22.08, $23.09, 174,000, 174 s, 12.7 min, 512,000, 37.3 min, $794.02, 15,000,000, $150 | OK (23.086, 12.664, 37.263) |
| L470 to L473 | Alternatives | 937.7 GB, $149.50, $3,863.52, $1,551.68, $3,035.00, $4,575.04, $8,990.00, $1,483.32 | OK |
| L479 to L482 | Totals | $25,170.58, $25,265.03, $3,090.58, about $4,468, about $4,562, $3,829.02, $9,784.02, $3,863.52, $71,118.82 | OK (4,467.58, 4,562.03) |
| L486 to L490, L505, L506, L513 | Sensitivity, price table | $7,360, 334 GB, no longer fits, 850 million, $212.33, $2,920, $8,760, $3,035.00 of $3,829.02 | OK (334.08) |
| L519 to L538 | Challenges, build list | about 200 GB, about 590 GB, triples, $48.62, about 335 GB, 174,000 to 512,000, 0.018%, about 94,000, about 575,000 | OK (335.47, 0.0183 coarse, 93,739, 574,713) |
| README.md L150, L259 to L262 | Quoted | about 33 times, 174 million, about $25,200, $22,080, about $3,800, 76%, 48 GPU hours, about $49, $720,000 | OK (32.61 coarse, 76.26%) |
| DECISIONS.md L18, L19, L43, L44, L67, L145 | Quoted | about 51, 512 million, 17 per patent, $720,000, $22,080, about 740, 3%, about 590 GB, triples | OK (17.375 coarse, 3.07% coarse, 2.96 times) |
| NOTES.md L278 to L293 | Quoted | 174 and 512 million, $25,170.58, $25,265.03, $3,829.02, $9,784.02, $3,863.52, $48.62, 48.3, $94.45, $720,000, 76%, 32.6 times, $3,035 of $3,829 | OK |
| poc/README.md L106 | Quoted | 1.9 kB per vector, close to one terabyte | OK (1.888, 966.7 GB for 32-bit vectors) |
| L184, L185, L193, L361 to L364, L368, L369 [R] | Inputs against the repo | about 60 GB, 6.2 s, 14 ms, 17.4, 51.2, 24,000, 736, 229 to 330, 5.8 to 6.8 s | OK (59.0 coarse, index holds 643 + 10,477 + 21,652 vectors, 23,989 characters, 736.36, 228.9 and 330.4) |

The totals are sums of the printed, rounded lines. Summing unrounded lines gives $794.01, $3,829.01 and $9,784.01 (1 cent lower).

## Assumptions without a source

| Line | Assumption | Flagged in the document? | Check against this repo |
| --- | --- | --- | --- |
| L505 to L507 | Managed database $4.00/h, $12.00/h, disk $0.115 per GB-month | Yes ("No", "Treat as an assumption") | Not verifiable offline. Carries $3,035 of $3,829.02 (79.3%) in phase 1 and $8,990 of $9,784.02 (91.9%) in phase 2 |
| L498 to L504, L508 to L511 | Machine, disk, storage and translation prices | 9 rows "Yes", storage "Partly", Google "No" | Not verifiable offline. Ratios are consistent: $0.1632 = 2 × $0.0816, $6.048 = 3 × $2.016 |
| L377 (A2) | 30% non-English | Yes. NOTES.md L296: nothing to base it on | Cannot check: `data/small` is all English. Drives $22,080 of $25,170.58 (87.7%). 10 points = $7,360 |
| L378 (A3) | Foreign title plus abstract = 736 characters | Yes ("Too high" for Chinese, Japanese, Korean) | Machine-made copies in the index: German 47.2 + 761.9 = 809, Chinese 11.6 + 185.4 = 197. Holds for German (+10%), 3.7 times too high for Chinese |
| L376 (A1) | 10 million patents look like 640 US ones in one class | Yes (L488) | Sample ratios reproduce: (643 + 10,477) / 640 = 17.375, 32,772 / 640 = 51.2. Before windowing: (640 + 10,411) / 640 = 17.3 and 32,272 / 640 = 50.4 passages. Representativeness cannot be checked |
| L363, L364 | 24,000 and 736 characters per patent | Measured | 15,326,275 passage characters / 640 = 23,947 (23,989 with titles). 471,270 / 640 = 736.4. Both hold. NOTES.md L31 (15.4 million) and DECISIONS.md L67 (about 740) agree |
| L368, L379 (A4) | Laptop 229 to 330 vectors/s. Rented GPU 1,000/s | A4 yes. The range is presented as measured | Five recorded runs span 138 to 330 (NOTES.md L131, L576). 1,000/s is not measured. Cost effect: $48.62 to about $352 |
| L369 | 100 patents/s parse and load | Presented as measured | Two wall-clock subtractions. The final run gives 2.2. SQLite on a laptop, not PostgreSQL |
| L380 (A5) | Index 1,152 B per vector at half precision | Yes ("Half precision itself was not run") | 32-bit only: 59 MiB / 32,772 = 1,888 B, holds. Its own support gives 1,120 B. The 256 GiB fit breaks above 1,264 B per vector (9.7% above 1,152) |
| L381 (A6) | Memory = index × 1.25 | Listed, no reason given | Cannot check. Leaves 24.3 GB of 274.9 GB for everything else |
| L382 (A7) | PostgreSQL text = 32.8 kB per patent + 24 B per row | Yes | `index/patents.db` is now 28,286,976 B for 840 patents (33.7 kB each, with 200 translated copies and the cache), so 21.0 MB cannot be re-measured. Proof of concept table minus vectors: (68 MiB - 32,772 × 1,544 B) / 640 = 32.3 kB. Roughly holds |
| L383 (A8), L384 (A9) | 10,000 new patents per week. 1,000 searches per day, 3 foreign results, 500 characters, no cache | Listed, no source | Cannot check. $23.09 per week. $450 per month (11.8%), linear in search volume |
| L386 (A11) | Database runs one month before launch | Listed | $3,035 one-time. L185 and L186 name 2 to 4 days of work |
| L184 | About 60 GB of dead rows | No formula given | Index: abstract and claim text is 3,507,354 / 640 = 5,480 characters per patent. 54.8 + 4.2 = 59.0 GB. Holds |
| L185 | Index build 1 to 3 days | Yes ("Assumption", "Not measured") | Only 6.2 s for 32,772 vectors, all indexes plus ANALYZE |
| L210, L214 | Exact scan runs "on one core". Threshold of about 1 million vectors carried from NumPy to PostgreSQL | L210 no. L214 yes ("not measured yet") | benchmarks.md L3 says 10 cores, thread count not recorded. NumPy only: 71 to 75 ms per million |
| L438 | Rented GPU translates no faster than the laptop: 448 and 6,062 characters/s | Stated | Match NOTES.md L414, L421. Final run: 446 and 5,558 (NOTES.md L586, L587) |
| L349, L462, L463 | 2 s at the 95th percentile is acceptable. 100-character queries, 5 languages. Under $50 for load balancer, network, monitoring | Yes | Cannot check |
| L412, L450, L487, L488 | 24 h parse budget. 1 GPU-hour per week. Next instance size "roughly doubles" the line. Chemistry descriptions are much longer | No | The arithmetic needs 3.5 h and 174 s. No 512 GiB price in the table. One class in the sample |

## Internal consistency

1. L211 against L214: the route table sends a 1% filter (1.74 million vectors, 0.12 s) to exact search. The rule allows exact only below about 1 million.
2. L210 against L211: 70 ms to score 983,160 vectors, yet "filter after", which scores the same vectors, is 43.1 ms. The two rows mix runs. benchmarks.md has 73.7 and 65.9.
3. L370 names benchmarks.md for 70 ms. That file says 73.7 (L41). The 2.4 / 43.1 / 18 times of L211 are in NOTES.md L211 only. benchmarks.md L51 and README.md L229 say 3.9 / 65.9 / 17 times. NOTES.md L583 adds 2.3 / 43.1 and 3.0 / 61.2.
4. L368, L411, L490 call 229 vectors/s the slower laptop run. NOTES.md L576 records 138 per second. L369 (100 patents/s) against NOTES.md L576, L577 (2.2 by the same subtraction).
5. L521 against L400: re-embedding needs 1,010.9 GB, 1,000 GB is provisioned. An index rebuild peaks at 875.8 GB (87.6%) and 1,916.9 GB (95.8%), above the 80% disk alert on L348.
6. L194 caps the survivor count at 60,000 patents. That is 1.04 million vectors in phase 1 and 3.07 million in phase 2, three times the L214 threshold.
7. L6 says assumptions are A1 to A11. Unnumbered inputs also feed the arithmetic: L185, L349, L412, L438, L450, L462, L463, L470 (1,300 GB), L505 to L508.
8. L128: the 334 GB for a 32-bit index is 174M × 1,920 B. A5's stated rule (1.5 × vector bytes) gives 400.9 GB. The measured 1,888 B gives 328.5 GB.
9. L513 says the three managed database rows carry $3,035.00. Only two of them are in phase 1. The third is the phase 2 instance.
10. L262 searches each language with `language = ...`. `passages` (L84 to L95) has no language column, and L218 says to drop `allowed` when there are no filters.
11. Other documents: all 34 quoted figures match the design document. README.md L260 "76% is the database machine" is the instance alone. With disk it is 79.3% (L513). NOTES.md L274 says the numbers add up: four rounding slips remain.

## Latency and scaling assumptions

- L193: encoding the query takes "about 14 ms per version on the laptop". L461: on a CPU it "is not measured".
- L210: "174,000,000 / 983,160 × 70 ms = 12.4 s per query on one core. Too slow". Route: approximate index.
- L211: a 1% filter leaves 1.74 million vectors, "about 0.12 s at the laptop rate". Route: exact. L212: above about 15% kept, filtering first was slower than scoring everything. Route: approximate index, filter checked during the scan.
- L214: "exact search when the filter leaves fewer than about 1 million vectors, the approximate index otherwise". That is about 57,000 patents in phase 1 and 19,500 in phase 2. "The laptop scored that many in about 70 ms." PostgreSQL "will be slower per vector than NumPy. That rate is not measured yet". L216: exact route with 12 patents (469 vectors) took "about 1 ms". poc/README.md L97: 1.15 to 1.60 ms.
- L222, L233, L242: `hnsw.ef_search = 500`, 500 nearest passages, 200 keyword rows. No time is stated for the approximate route. L349: the only target. Alert when the 95th percentile is above 2 s for 15 minutes ("assumption: 2 s is acceptable").
- L462: query translation speed on a 2 virtual CPU machine "is not measured". NOTES.md L590: 1,218 ms median and 2,114 ms slowest for a claim-length query into 2 languages on the laptop GPU. Uncached, that alone is near the 2 s alert.
- L519: if the index is not in memory "a query takes seconds". L185: index build scaled "in a straight line" is 9.1 h, "expect more", assumed 1 to 3 days.
- Linear growth of exact scan time: yes, claimed. L210 and L211 scale 70 ms per 983,160 vectors in a straight line to 174 million and to 1.74 million. For the probe: the implied rate is 71.2 ms per million vectors. benchmarks.md gives 75.0 (median) and 81.1 (95th percentile). The repo's own two sizes are not linear: 1.44 ms at 32,772 vectors (44 ms per million, benchmarks.md L13) against 73.7 ms at 983,160 (75 ms per million), 1.7 times more per vector. Both are 32-bit vectors in memory, not half precision rows in PostgreSQL.

## Challenge coverage

| Asked for | Present? | Evidence |
| --- | --- | --- |
| System components | Yes | Section 2: table of 8 components with hardware (L19 to L28) and a diagram (L32 to L47) |
| Major pipelines | Yes | 4.1 weekly, 8 stages (L150 to L159). 4.2 backfill, 7 steps (L178 to L186). 4.3 query path (L192 to L196) |
| Breakdown of expected cost | Yes | Section 7 (L353 to L513): inputs, sizing, one-time, monthly, totals, sensitivity, price sources |
| Error handling | Yes | Section 5 (L279 to L315): 10 failure cases, bounded retries, dead letter list, replay statement |
| Contents and status tracking | Yes | `source_files` and `document_status` (L104 to L118), model version columns, a counts view, 8 dashboard panels, 9 alerts (L317 to L351) |
| Major challenges at scale | Yes | Section 8 (L515 to L527): 9 challenges, each with what breaks and a mitigation |
| An intern could start | Yes, with caveats | Full table definitions (L53 to L124) and an ordered 8-step build list (L529 to L538). Stated caveats: the fused statement was never run (L130, L218), half precision and iterative scans are untested (L128). Unstated: consistency item 10 |

Not checked: any price (offline). The task sheet PDF could not be opened here (no PDF reader), so this checklist is the one in the audit brief.
