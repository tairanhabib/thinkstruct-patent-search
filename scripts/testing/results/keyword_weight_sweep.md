# Keyword weight sweep (M1)

Output of `python scripts/tune_keyword_weight.py --index COPY_OF_ENGLISH_ONLY_INDEX`, run with the weight still at 1.0.

Mean reciprocal rank, 200 queries per test, 640 patents. Weight in src/search.py now: 1.0.

| Search | A: claim 1 to patent | B: abstract to claims | C: title to patent | D: dependent claim to patent | Worst gap to the better single mode |
| --- | --- | --- | --- | --- | --- |
| keyword only | 0.931 | 0.208 | 0.760 | 0.701 | |
| semantic only | 0.873 | 0.970 | 0.958 | 0.887 | |
| hybrid, keyword weight 1.0 | 0.889 (-0.042) | 0.374 (-0.595) | 0.917 (-0.041) | 0.844 (-0.043) | -0.595 on B (-0.652 to -0.530) |
| hybrid, keyword weight 0.5 | 0.888 (-0.043) | 0.427 (-0.542) | 0.947 (-0.011) | 0.858 (-0.029) | -0.542 on B (-0.601 to -0.478) |
| hybrid, keyword weight 0.2 | 0.890 (-0.040) | 0.518 (-0.451) | 0.962 (+0.004) | 0.885 (-0.003) | -0.451 on B (-0.505 to -0.392) |
| hybrid, keyword weight 0.1 | 0.887 (-0.043) | 0.615 (-0.355) | 0.963 (+0.004) | 0.894 (+0.006) | -0.355 on B (-0.402 to -0.302) |
| hybrid, keyword weight 0.05 | 0.884 (-0.047) | 0.735 (-0.235) | 0.960 (+0.002) | 0.891 (+0.004) | -0.235 on B (-0.275 to -0.195) |
| hybrid, keyword weight 0.02 | 0.878 (-0.052) | 0.896 (-0.074) | 0.958 (+0.000) | 0.889 (+0.002) | -0.074 on B (-0.097 to -0.051) |
| hybrid, keyword weight 0.01 | 0.873 (-0.057) | 0.970 (+0.000) | 0.958 (+0.000) | 0.887 (+0.000) | -0.057 on A (-0.095 to -0.021) |
| hybrid, keyword weight 0.005 | 0.873 (-0.057) | 0.970 (+0.000) | 0.958 (+0.000) | 0.887 (+0.000) | -0.057 on A (-0.095 to -0.021) |
| hybrid, keyword weight 0.002 | 0.873 (-0.057) | 0.970 (+0.000) | 0.958 (+0.000) | 0.887 (+0.000) | -0.057 on A (-0.095 to -0.021) |

In brackets: hybrid minus the better single mode on that test (A: keyword, B: semantic, C: semantic, D: semantic). The last column gives its 95% interval.
