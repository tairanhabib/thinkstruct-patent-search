#!/usr/bin/env python3
"""Recompute every derived number in docs/scale_design.md from the document's own inputs.

Run from the repo root:  python scripts/testing/check_cost_arithmetic.py      (stdlib only)

Output, one line per figure:
    <file>:L<line> | name | stated in doc | recomputed | OK or MISMATCH (relative difference)

Rule: the recomputed value is rounded (half up) to the precision the document prints.
  MISMATCH    that rounded value differs from the stated one. The raw relative difference
              is shown; "rounding" is added when it is 1% or less.
  OK (coarse) it rounds to the stated digits, but the raw difference is above 1% only
              because the document prints few digits.
  NOT FOUND   the quoted text is not on the quoted line: the document changed, or this
              script mis-quotes it. Every check names the exact text it expects there.
Sums are checked from the document's own printed addends, so one root error is counted once.
Groups: [A] arithmetic inside the design document, [X] the same figures quoted in README.md,
DECISIONS.md, NOTES.md and poc/README.md, [R] design inputs against numbers measured in this repo.
Always exits 0.

Updated by the builder after the corrections of 17 November 2026: the inputs and the expected texts below are the
corrected document's (25.2 kB, 328.0 GB, 138 vectors per second as the slowest laptop run, 6,067 characters per second,
the timings of the regenerated benchmarks.md, monthly totals 3 cents higher). The audit of the document as the tester
found it is in results/scale_design_audit.md.
"""
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATHS = {"D": "docs/scale_design.md", "README": "README.md", "DEC": "DECISIONS.md",
         "NOTES": "NOTES.md", "POC": "poc/README.md"}
TEXT = {k: (ROOT / p).read_text(encoding="utf-8").splitlines() for k, p in PATHS.items()}
rows = []  # (group, where, name, stated, recomputed, verdict)


def rnd(x, nd):
    return float(Decimal(repr(float(x))).quantize(Decimal(1).scaleb(-nd), rounding=ROUND_HALF_UP))


def on_line(f, line, needle):
    return needle in TEXT[f][line - 1]


def chk(line, name, needle, value, nd=None, f="D", group="A"):
    """needle: text as printed on that line; the first number in it is the stated value."""
    where = f"{PATHS[f]}:L{line}"
    lit = re.search(r"\d[\d,]*(?:\.\d+)?", needle).group().rstrip(",")
    stated = float(lit.replace(",", ""))
    if nd is None:
        nd = len(lit.split(".")[1]) if "." in lit else 0
    shown = f"{value:,.{max(nd, 0) + 2}f}"
    if not on_line(f, line, needle):
        verdict = "NOT FOUND on that line"
    else:
        rel = abs(stated - value) / abs(value)
        if rnd(value, nd) != stated:
            verdict = f"MISMATCH ({rel:.3%}{', rounding' if rel <= 0.01 else ''})"
        elif rel > 0.01 + 1e-9:
            verdict = f"OK (coarse, raw difference {rel:.1%})"
        else:
            verdict = "OK"
    rows.append((group, where, name, needle, shown, verdict))


def claim(line, name, needle, holds, detail, f="D", group="A"):
    """A yes/no statement in the document (fits, too small, triples, less than)."""
    verdict = "NOT FOUND on that line" if not on_line(f, line, needle) else ("OK" if holds else "MISMATCH (claim does not hold)")
    rows.append((group, f"{PATHS[f]}:L{line}", name, needle, detail, verdict))


# ---- Inputs, exactly as the document states them (line numbers of docs/scale_design.md) ----
N = 10_000_000                    # L12, L392 patents
SAMPLE = 640                      # L357
VPP1, VPP2 = 17.4, 51.2           # L361, L362 vectors per patent (the doc carries the rounded values, L392)
CH_FULL, CH_TA = 24_000, 736      # L363, L364 characters per patent
RAW_KB, DB_KB = 25.2, 32.8        # L365, L366 kB per patent
DIM, B_HALF_STORED = 384, 776     # L25/L367
LAP_SLOW, LAP_FAST = 138, 330     # L368 vectors/s
PARSE_RATE = 100                  # L369 patents/s per process
SCAN_MS, SCAN_N = 36.3, 983_160     # L370
FOREIGN = 0.30                    # A2 L377
GPU_RATE = 1_000                  # A4 L379 vectors/s
IDX_FACTOR, MEM_FACTOR = 1.5, 1.25  # A5 L380, A6 L381
ROW_HDR = 24                      # A7 L382 bytes per passage row
WEEKLY = 10_000                   # A8 L383
SEARCHES, DAYS, SHOWN, SHOWN_CH = 1_000, 30, 3, 500  # A9 L384
HOURS, WEEKS = 730, 4.33          # A10 L385
P_GPU, P_SEARCH, P_WORKER, P_PARSE = 1.006, 0.0816, 0.1632, 0.29   # L498-L501 $ per hour
P_SELF1, P_SELF2, P_GP3 = 2.016, 6.048, 0.08                       # L502-L504
P_RDS1, P_RDS2, P_RDS_GB, P_S3 = 4.00, 12.00, 0.115, 0.023         # L505-L508
P_AZURE, P_AWS_MT, P_GOOGLE = 10, 15, 20                           # L509-L511 $ per million characters
GIB = 2**30

# ---- Recomputed chain ----
v1, v2 = N * VPP1, N * VPP2
b32, b16 = DIM * 4, DIM * 2
hdr = B_HALF_STORED - b16                      # 8 B header, implied by L367
idx_b = IDX_FACTOR * b16
idx1, idx2 = v1 * idx_b / 1e9, v2 * idx_b / 1e9
mem1, mem2 = idx1 * MEM_FACTOR, idx2 * MEM_FACTOR
tab1, tab2 = v1 * B_HALF_STORED / 1e9, v2 * B_HALF_STORED / 1e9
gpu_h1, gpu_h2 = v1 / GPU_RATE / 3600, (v2 - v1) / GPU_RATE / 3600
gpu_c1, gpu_c2 = gpu_h1 * P_GPU, gpu_h2 * P_GPU
slow_h1, slow_h2 = v1 / LAP_SLOW / 3600, (v2 - v1) / LAP_SLOW / 3600
foreign_n = N * FOREIGN
ta_chars = foreign_n * CH_TA
ta_cost = ta_chars / 1e6 * P_AZURE
full_cost = foreign_n * CH_FULL / 1e6 * P_AZURE
local_h = ta_chars / 448 / 3600                # 448 characters/s, L435
db_month1, db_month2 = P_RDS1 * HOURS, P_RDS2 * HOURS
m_search, m_worker = 2 * P_SEARCH * HOURS, P_WORKER * HOURS
m_embed = 1 * WEEKS * P_GPU
wk_chars = WEEKLY * FOREIGN * CH_TA
m_wk_tr = wk_chars * WEEKS / 1e6 * P_AZURE
m_show = SEARCHES * DAYS * SHOWN * SHOWN_CH / 1e6 * P_AZURE
m_raw = N * RAW_KB / 1e6 * P_S3                # GB times price

# ---- [A] Sections 1 to 4: sizing quoted in the text ----
chk(13, "phase 1 vectors (millions)", "174 million", v1 / 1e6)
chk(13, "phase 1 vectors in table, half precision (GB)", "135 GB", tab1)
chk(14, "phase 2 vectors (millions)", "512 million", v2 / 1e6)
chk(14, "phase 2 vectors in table (GB)", "397 GB", tab2)
chk(128, "32-bit vector stored = 1,536 + 8 B header", "1,544 B", b32 + hdr)
chk(128, "phase 1 index, half precision (GB)", "200 GB", idx1)
chk(128, "phase 1 index, 32-bit = 174M x (1,152 + 768) B (formula not shown in doc)", "334 GB", v1 * (idx_b + b16) / 1e9)
claim(128, "index x 1.25 fits in 256 GiB", "fits in a 256 GiB machine", mem1 <= 256 * GIB / 1e9, f"{mem1:.1f} GB needed, {256 * GIB / 1e9:.1f} GB there")
chk(181, "parse and load, process-hours", "28 process-hours", N / PARSE_RATE / 3600)
chk(181, "same on 8 processes (h)", "3.5 h", N / PARSE_RATE / 3600 / 8)
chk(183, "phase 1 GPU-hours", "48.3 GPU-hours", gpu_h1)
chk(183, "same on 4 GPUs (h)", "12 h", gpu_h1 / 4)
chk(185, "index build scaled linearly from 32,772 vectors in 6.2 s (h)", "9.1 h", v1 / 32_772 * 6.2 / 3600)
chk(210, "exact scan of 174M vectors at 36.3 ms per 983,160 (s)", "6.4 s", v1 / SCAN_N * SCAN_MS / 1000)
chk(211, "32.5 ms / 2.4 ms", "13.5 times", 32.5 / 2.4)
chk(211, "1% of phase 1 vectors (millions)", "1.74 million", 0.01 * v1 / 1e6)
chk(211, "exact scan of 1.74M vectors (s)", "0.06 s", 0.01 * v1 / SCAN_N * SCAN_MS / 1000)
chk(214, "1,000,000 / 17.4 patents", "57,000 patents", 1e6 / VPP1, nd=-3)
chk(214, "1,000,000 / 51.2 patents", "19,500 in phase 2", 1e6 / VPP2, nd=-2)
chk(214, "exact scan of 1,000,000 vectors (ms)", "about 37 ms", 1e6 / SCAN_N * SCAN_MS)
claim(211, "route table agrees with the route rule (L214): 1.74 million survivors are above the threshold and go to the index",
      "sends this one to the approximate index", 0.01 * v1 > 1e6, f"{0.01 * v1 / 1e6:.2f} million vectors survive")
chk(211, "share of phase 1 vectors that is 1 million (%)", "0.6%", 1e6 / v1 * 100)

# ---- [A] 7.1 Inputs ----
chk(361, "11,120 / 640", "17.4 (11,120 / 640)", 11_120 / SAMPLE)
chk(362, "32,772 / 640", "51.2 (32,772 / 640)", 32_772 / SAMPLE)
chk(363, "15.36 million / 640", "24,000 (15.36 million / 640)", 15.36e6 / SAMPLE)
chk(364, "41.8 + 694.6", "736 (41.8 + 694.6)", 41.8 + 694.6)
chk(365, "16.1 MB / 640 (kB)", "25.2 kB (16.1 MB", 16.1e6 / SAMPLE / 1e3)
chk(366, "21.0 MB / 640 (kB)", "32.8 kB (21.0 MB / 640)", 21.0e6 / SAMPLE / 1e3)
chk(367, "384 x 4 B", "1,536 B", b32)
chk(367, "384 x 2 B", "768 B", b16)
chk(369, "640 patents / 6.8 s", "About 100 patents/s", SAMPLE / 6.8, nd=-2)
chk(369, "640 patents / 5.8 s", "About 100 patents/s", SAMPLE / 5.8, nd=-2)
chk(377, "30% of 10 million", "3,000,000 patents", foreign_n)
chk(379, "1,000 / 330", "3.0 to", GPU_RATE / LAP_FAST)
chk(379, "1,000 / 138", "7.2 times", GPU_RATE / LAP_SLOW)
chk(380, "1.5 x 768 B", "1,152 B", idx_b)
chk(380, "59 MiB / 32,772 vectors (B)", "1,888 B", 59 * 2**20 / 32_772)
chk(380, "1,888 - 768 B", "1,120 B", 1_888 - b16)
chk(385, "8,760 h / 12", "730 h", 8760 / 12)
chk(385, "52 weeks / 12", "4.33 weeks", 52 / 12)

# ---- [A] 7.2 Vectors, bytes, memory, disk ----
chk(392, "10M x 17.4", "174,000,000", v1)
chk(392, "10M x 51.2", "512,000,000", v2)
chk(393, "phase 1 x 1,536 B (GB)", "267.3 GB", v1 * b32 / 1e9)
chk(393, "phase 2 x 1,536 B (GB)", "786.4 GB", v2 * b32 / 1e9)
chk(394, "phase 1 x 776 B (GB)", "135.0 GB", tab1)
chk(394, "phase 2 x 776 B (GB)", "397.3 GB", tab2)
chk(395, "phase 1 x 1,152 B (GB)", "200.4 GB", idx1)
chk(395, "phase 2 x 1,152 B (GB)", "589.8 GB", idx2)
chk(396, "phase 1 index x 1.25 (GB)", "250.6 GB", mem1)
chk(396, "phase 2 index x 1.25 (GB)", "737.3 GB", mem2)
chk(397, "256 GiB in GB", "274.9 GB", 256 * GIB / 1e9)
chk(397, "768 GiB in GB", "824.6 GB", 768 * GIB / 1e9)
chk(397, "512 GiB in GB", "549.8 GB", 512 * GIB / 1e9)
claim(397, "512 GiB too small, 768 GiB enough for phase 2", "is too small", 512 * GIB / 1e9 < mem2 <= 768 * GIB / 1e9, f"{mem2:.1f} GB needed")
chk(398, "10,000,000 x 32.8 kB (GB)", "328.0 GB", N * DB_KB / 1e6)
chk(398, "512,000,000 x 24 B (GB)", "12.3 GB", v2 * ROW_HDR / 1e9)
chk(398, "328.0 + 12.3 (printed addends)", "340.3 GB", 328.0 + 12.3)
chk(399, "phase 1 disk: 340.3 + 135.0 + 200.4 (printed addends)", "675.7 GB", 340.3 + 135.0 + 200.4)
chk(399, "phase 2 disk: 340.3 + 397.3 + 589.8 (printed addends)", "1,327.4 GB", 340.3 + 397.3 + 589.8)
claim(400, "phase 1: room to rebuild the index beside the old one in 1,000 GB", "1,000 GB", 675.7 + idx1 <= 1000, f"{675.7 + idx1:.1f} GB at the peak")
claim(400, "phase 2: same in 2,000 GB", "2,000 GB", 1327.1 + idx2 <= 2000, f"{1327.1 + idx2:.1f} GB at the peak")

# ---- [A] 7.3 One-time compute ----
chk(408, "512M - 174M", "338,000,000", v2 - v1)
chk(409, "phase 1 GPU hours at 1,000/s", "48.3 h", gpu_h1)
chk(409, "phase 2 extra GPU hours", "93.9 h", gpu_h2)
chk(410, "phase 1 GPU cost", "$48.62", gpu_c1)
chk(410, "phase 2 extra GPU cost", "$94.45", gpu_c2)
chk(411, "phase 1 hours at 138/s", "350.2 h", slow_h1)
chk(411, "phase 1 cost at 138/s", "$352.34", slow_h1 * P_GPU)
chk(411, "phase 2 extra hours at 138/s", "680.4 h", slow_h2)
chk(411, "phase 2 extra cost at 138/s", "$684.44", slow_h2 * P_GPU)
chk(412, "10M / 100 per s", "100,000 s", N / PARSE_RATE)
chk(412, "same in process-hours", "27.8 process-hours", N / PARSE_RATE / 3600)
chk(412, "24 h x $0.29", "$6.96", 24 * P_PARSE)
chk(413, "730 h x $4.00 + 1,000 GB x $0.115", "$3,035.00", HOURS * P_RDS1 + 1000 * P_RDS_GB)
chk(415, "$4.00 x 24 h", "= $96", P_RDS1 * 24)
claim(415, "phase 1 embedding costs less than one database day", "costs less than one day", gpu_c1 < P_RDS1 * 24, f"${gpu_c1:.2f} against ${P_RDS1 * 24:.2f}")

# ---- [A] 7.4 One-time translation ----
chk(421, "3,000,000 x 736 characters", "2,208,000,000", ta_chars)
chk(421, "x $10 per million", "$22,080", ta_cost)
chk(422, "x $15 per million", "$33,120", ta_chars / 1e6 * P_AWS_MT)
chk(423, "x $20 per million", "$44,160", ta_chars / 1e6 * P_GOOGLE)
chk(424, "3,000,000 x 24,000 characters", "72,000,000,000", foreign_n * CH_FULL)
chk(424, "x $10 per million", "$720,000", full_cost)
chk(427, "$720,000 / $22,080", "32.6 times", full_cost / ta_cost)
chk(435, "100,829 characters / 224.9 s", "| 448 |", 100_829 / 224.9)
chk(436, "2,778,802 characters / 395 s", "7,035 (German)", 2_778_802 / 395)
chk(436, "2,778,802 characters / 458 s", "6,067 (Chinese)", 2_778_802 / 458)
chk(438, "2,208,000,000 / 448 / 3,600 GPU-hours", "1,369 GPU-hours", local_h)
chk(438, "x $1.006", "$1,377", local_h * P_GPU)
chk(438, "2,208,000,000 / 6,067 / 3,600 GPU-hours", "101 GPU-hours", ta_chars / 6_067 / 3600)
chk(438, "x $1.006", "$102", ta_chars / 6_062 / 3600 * P_GPU)
chk(440, "$22,080 / $1.006 GPU-hours", "21,948 GPU-hours", ta_cost / P_GPU)
chk(440, "same in million seconds", "79.0 million seconds", ta_cost / P_GPU * 3600 / 1e6)
chk(440, "break-even characters per second", "= 28)", ta_chars / (ta_cost / P_GPU * 3600))

# ---- [A] 7.5 Monthly ----
chk(446, "$4.00 x 730 h", "$2,920.00", db_month1)
chk(446, "$12.00 x 730 h", "$8,760.00", db_month2)
chk(447, "1,000 GB x $0.115", "$115.00", 1000 * P_RDS_GB)
chk(447, "2,000 GB x $0.115", "$230.00", 2000 * P_RDS_GB)
chk(448, "2 x $0.0816 x 730 h", "$119.14", m_search)
chk(449, "$0.1632 x 730 h", "$119.14", m_worker)
chk(450, "1 GPU-hour x 4.33 x $1.006", "$4.36", m_embed)
chk(451, "10,000 x 30% x 736", "2,208,000 characters", wk_chars)
chk(451, "x 4.33", "9,560,640", wk_chars * WEEKS)
chk(451, "x $10 per million", "$95.61", m_wk_tr)
chk(452, "1,000 x 30 x 3 x 500", "45,000,000", SEARCHES * DAYS * SHOWN * SHOWN_CH)
chk(452, "x $10 per million", "$450.00", m_show)
chk(453, "10M x 25.2 kB (GB)", "252 GB", N * RAW_KB / 1e6)
chk(453, "x $0.023", "$5.80", m_raw)
six = round(m_search, 2) + round(m_worker, 2) + round(m_embed, 2) + round(m_wk_tr, 2) + round(m_show, 2) + round(m_raw, 2)
total1 = db_month1 + 1000 * P_RDS_GB + six
total2 = db_month2 + 2000 * P_RDS_GB + six
chk(454, "phase 1 monthly total (sum of the 8 lines)", "$3,829.05", total1)
chk(454, "phase 2 monthly total", "$9,784.05", total2)
chk(458, "2,208,000 characters x $10 per million", "$22.08", wk_chars / 1e6 * P_AZURE)
chk(458, "$1.006 + $22.08 per week", "$23.09", P_GPU + wk_chars / 1e6 * P_AZURE)
chk(459, "10,000 x 17.4", "174,000 vectors", WEEKLY * VPP1)
chk(459, "174,000 / 1,000 per s", "(174 s", WEEKLY * VPP1 / GPU_RATE)
chk(459, "174,000 / 138 per s (minutes)", "21.0 minutes", WEEKLY * VPP1 / LAP_SLOW / 60)
chk(459, "10,000 x 51.2", "512,000 vectors", WEEKLY * VPP2)
chk(459, "512,000 / 138 per s (minutes)", "61.8 minutes", WEEKLY * VPP2 / LAP_SLOW / 60)
chk(460, "six lines below database storage", "$794.05", six)
chk(462, "1,000 x 30 x 100 x 5 characters", "15,000,000 characters", 1000 * 30 * 100 * 5)
chk(462, "x $10 per million", "$150 per month", 15e6 / 1e6 * P_AZURE)
chk(470, "340.3 + 397.3 + 200.4 (printed addends)", "938.0 GB", 340.3 + 397.3 + 200.4)
chk(470, "1,300 GB x $0.115", "$149.50", 1300 * P_RDS_GB)
chk(470, "$2,920.00 + $149.50 + $794.05", "$3,863.55", db_month1 + 1300 * P_RDS_GB + six)
chk(471, "$2.016 x 730 + 1,000 GB x $0.08", "$1,551.68", P_SELF1 * HOURS + 1000 * P_GP3)
chk(471, "managed phase 1: $2,920 + $115", "$3,035.00", db_month1 + 1000 * P_RDS_GB)
chk(471, "$6.048 x 730 + 2,000 GB x $0.08", "$4,575.04", P_SELF2 * HOURS + 2000 * P_GP3)
chk(471, "managed phase 2: $8,760 + $230", "$8,990.00", db_month2 + 2000 * P_RDS_GB)
chk(473, "$3,035.00 - $1,551.68", "$1,483.32", db_month1 + 1000 * P_RDS_GB - (P_SELF1 * HOURS + 1000 * P_GP3))

# ---- [A] 7.6 Totals, 7.7 Sensitivity, 7.8 ----
once_compute = round(gpu_c1, 2) + 24 * P_PARSE + HOURS * P_RDS1 + 1000 * P_RDS_GB
once1 = once_compute + ta_cost
chk(479, "phase 1 one-time: $48.62 + $6.96 + $3,035.00 + $22,080.00", "$25,170.58", once1)
chk(479, "phase 2 one-time: plus $94.45", "$25,265.03", once1 + round(gpu_c2, 2))
chk(480, "$48.62 + $6.96 + $3,035.00", "$3,090.58", once_compute)
chk(480, "$3,090.58 + $1,377 local translation", "$4,468", once_compute + 1377)
chk(480, "plus $94.45", "$4,562", once_compute + 1377 + round(gpu_c2, 2))
chk(481, "phase 1 monthly, repeated", "$3,829.05", total1)
chk(481, "phase 2 monthly, repeated", "$9,784.05", total2)
chk(481, "phase 2 without description index, repeated", "$3,863.55", db_month1 + 1300 * P_RDS_GB + six)
chk(482, "first year: $25,170.58 + 12 x $3,829.05", "$71,119.18", once1 + 12 * total1)
chk(486, "1,000,000 x 736 x $10 per million", "$7,360", 1e6 * CH_TA / 1e6 * P_AZURE)
chk(487, "174,000,000 x 1,536 B x 1.25 (GB)", "= 334 GB", v1 * 2.0 * b16 * MEM_FACTOR / 1e9)
claim(487, "334 GB does not fit in 256 GiB", "no longer fits in 256 GiB", v1 * 2.0 * b16 * MEM_FACTOR / 1e9 > 256 * GIB / 1e9, "334.1 GB against 274.9 GB")
chk(488, "174M + 2 x 338M vectors (millions)", "850 million", (v1 + 2 * (v2 - v1)) / 1e6)
chk(490, "phase 1 embedding at 138/s", "$352.34", slow_h1 * P_GPU)
chk(505, "$4.00 x 730 h", "$2,920 per month", db_month1)
chk(506, "$12.00 x 730 h", "$8,760 per month", db_month2)
chk(513, "RDS instance + disk, phase 1 monthly", "$3,035.00 of the $3,829.05", db_month1 + 1000 * P_RDS_GB)

# ---- [A] Sections 8 and 9 ----
chk(519, "phase 1 index (GB)", "about 200 GB", idx1)
chk(519, "phase 2 index (GB)", "about 590 GB", idx2, nd=-1)
claim(519, "$12.00 / $4.00 per hour = 3.0", "triples the instance price", P_RDS2 / P_RDS1 == 3, f"{P_RDS2 / P_RDS1:.2f} times")
chk(521, "phase 1 re-embedding compute", "$48.62", gpu_c1)
chk(521, "second vector column + second index: 135.0 + 200.4 GB", "335 GB", tab1 + idx1)
chk(521, "disk during re-embedding: 675.7 + 335.4 (GB)", "1,011 GB", 675.7 + tab1 + idx1)
claim(521, "the document now says this does not fit in the 1,000 GB provisioned", "more than the 1,000 GB", 675.7 + tab1 + idx1 > 1000, f"{675.7 + tab1 + idx1:.1f} GB needed")
chk(521, "300 GB x $0.115", "$34.50", 300 * P_RDS_GB)
chk(524, "weekly vectors, phase 1", "174,000 to", WEEKLY * VPP1)
chk(524, "weekly vectors, phase 2", "to 512,000", WEEKLY * VPP2)
chk(525, "6 / 32,772 (%)", "0.018%", 6 / 32_772 * 100)
chk(525, "512M x 6 / 32,772", "94,000 vectors", v2 * 6 / 32_772, nd=-3)
chk(538, "10,000,000 vectors / 17.4", "575,000 patents", 1e7 / VPP1, nd=-3)

# ---- [X] The same figures quoted in other documents ----
X = dict(group="X")
chk(161, "$720,000 / $22,080", "about 33 times", full_cost / ta_cost, f="README", **X)
chk(345, "phase 1 vectors (millions)", "174 million", v1 / 1e6, f="README", **X)
chk(345, "phase 1 one-time", "$25,200", once1, nd=-2, f="README", **X)
chk(345, "title and abstract translation", "$22,080", ta_cost, f="README", **X)
chk(346, "phase 1 monthly", "$3,800", total1, nd=-2, f="README", **X)
chk(346, "database instance share of phase 1 monthly (%)", "76%", db_month1 / total1 * 100, f="README", **X)
chk(347, "phase 1 GPU hours", "48 GPU hours", gpu_h1, f="README", **X)
chk(347, "phase 1 GPU cost", "$49", gpu_c1, f="README", **X)
chk(348, "full text translation", "$720,000", full_cost, f="README", **X)
chk(21, "vectors per patent, full text", "about 51 vectors", 32_772 / SAMPLE, f="DEC", **X)
chk(21, "phase 2 vectors (millions)", "512 million", v2 / 1e6, f="DEC", **X)
chk(22, "vectors per patent, abstract and claims", "17 per patent", 11_120 / SAMPLE, f="DEC", **X)
chk(46, "full text translation", "$720,000", full_cost, f="DEC", **X)
chk(47, "title and abstract translation", "$22,080", ta_cost, f="DEC", **X)
chk(77, "title plus abstract characters", "about 740 characters", 41.8 + 694.6, nd=-1, f="DEC", **X)
chk(77, "736 / 24,000 (%)", "3% of the text", CH_TA / CH_FULL * 100, f="DEC", **X)
chk(180, "phase 2 index (GB)", "about 590 GB", idx2, nd=-1, f="DEC", **X)
claim(180, "$8,990 / $3,035 per month", "triples the database bill", 2.9 <= (db_month2 + 230) / (db_month1 + 115) <= 3.1, f"{(db_month2 + 230) / (db_month1 + 115):.2f} times", f="DEC", **X)
chk(278, "phase 1 vectors (millions)", "174 million", v1 / 1e6, f="NOTES", **X)
chk(278, "phase 2 vectors (millions)", "512 million", v2 / 1e6, f="NOTES", **X)
chk(280, "phase 1 one-time", "$25,170.58", once1, f="NOTES", **X)
chk(280, "phase 2 one-time", "$25,265.03", once1 + round(gpu_c2, 2), f="NOTES", **X)
chk(281, "phase 1 monthly", "$3,829.05", total1, f="NOTES", **X)
chk(281, "phase 2 monthly", "$9,784.05", total2, f="NOTES", **X)
chk(281, "phase 2 without description index", "$3,863.55", db_month1 + 1300 * P_RDS_GB + six, f="NOTES", **X)
chk(282, "phase 1 GPU cost", "$48.62", gpu_c1, f="NOTES", **X)
chk(282, "phase 1 GPU hours", "48.3 GPU hours", gpu_h1, f="NOTES", **X)
chk(282, "phase 2 extra GPU cost", "$94.45", gpu_c2, f="NOTES", **X)
chk(283, "full text translation", "$720,000", full_cost, f="NOTES", **X)
chk(286, "database instance share of phase 1 monthly (%)", "76%", db_month1 / total1 * 100, f="NOTES", **X)
chk(287, "$720,000 / $22,080", "32.6 times", full_cost / ta_cost, f="NOTES", **X)
chk(293, "RDS instance + disk, phase 1 monthly", "$3,035 of the $3,829", db_month1 + 1000 * P_RDS_GB, f="NOTES", **X)
chk(106, "59 MiB / 32,772 vectors (kB)", "1.9 kilobytes", 59 * 2**20 / 32_772 / 1e3, f="POC", **X)
claim(106, "512M x 1,888 B, 32-bit index", "close to one terabyte", 0.9 <= v2 * 1_888 / 1e12 <= 1.1, f"{v2 * 1_888 / 1e9:.1f} GB", f="POC", **X)

# ---- [R] Design inputs against numbers measured in this repo ----
R = dict(group="R")
chk(368, "32,772 vectors / 99.2 s (NOTES.md L131)", "to 330", 32_772 / 99.2, **R)
chk(368, "slowest recorded run: 32,772 / 237.0 s (NOTES.md L576)", "138 to", 32_772 / 237.0, **R)
chk(369, "regeneration run of 17 November: 133.22 s - 127.6 s (NOTES.md, last section)", "5.6 to", 133.22 - 127.6, **R)
chk(369, "1 min 46 s - 99.2 s (NOTES.md L131-L132)", "to 6.8 s", 106 - 99.2, **R)
chk(369, "the slow run the document now names: 640 / (8 min 45 s - 237.0 s) (NOTES.md L576-L577)", "2 patents/s", SAMPLE / (525 - 237.0), **R)
chk(370, "unfiltered scan of 983,160 vectors, median ms (benchmarks.md, part 2)", "36.3 ms per 983,160", 36.3, **R)
chk(211, "filter first at 1.0% kept, ms (benchmarks.md, part 2)", "2.4 ms", 2.4, **R)
chk(211, "filter after at 1.0% kept, ms (benchmarks.md, part 2)", "32.5 ms", 32.5, **R)
chk(193, "query encoding, ms (benchmarks.md L13)", "about 14 ms", 14.0, **R)
chk(185, "index build time, s (poc/README.md L85)", "6.2 s", 6.2, **R)
# Counted read-only on 2026-11-17 for the 640 patents of collection 'small' in index/patents.db and
# index/vector_passage_ids.npy. Vectors: abstract 643, claim 10,477, description 21,652.
# Characters: titles 26,732, abstracts 444,538, claims 3,062,816, descriptions 11,818,921.
# data/small: 64 files, 15,939,070 bytes of content.
chk(361, "vectors in the index: (643 abstract + 10,477 claim) / 640", "17.4 (11,120 / 640)", (643 + 10_477) / SAMPLE, **R)
chk(362, "vectors in the index: (643 + 10,477 + 21,652) / 640", "51.2 (32,772 / 640)", (643 + 10_477 + 21_652) / SAMPLE, **R)
chk(363, "characters in the index: (titles + all passages) / 640", "24,000 (15.36 million / 640)",
    (26_732 + 444_538 + 3_062_816 + 11_818_921) / SAMPLE, nd=-3, **R)
chk(364, "characters in the index: (titles + abstracts) / 640", "736 (41.8 + 694.6)", (26_732 + 444_538) / SAMPLE, **R)
chk(365, "content bytes of data/small / 640 (kB)", "24.9 kB", 15_939_070 / SAMPLE / 1e3, **R)
chk(184, "dead rows: 10M x abstract and claim characters per patent + 174M x 24 B (GB), no formula in doc", "about 60 GB",
    (N * (444_538 + 3_062_816) / SAMPLE + v1 * ROW_HDR) / 1e9, nd=-1, **R)

# ---- Output ----
if __name__ == "__main__":
    titles = {"A": "[A] Arithmetic inside docs/scale_design.md",
              "X": "[X] Figures quoted in README.md, DECISIONS.md, NOTES.md, poc/README.md",
              "R": "[R] Design inputs against numbers measured in this repo"}
    print("where | name | stated in doc | recomputed | verdict")
    for g, title in titles.items():
        print(f"\n{title}")
        for group, where, name, stated, shown, verdict in rows:
            if group == g:
                print(f"{where} | {name} | {stated} | {shown} | {verdict}")
    bad = [r for r in rows if not r[5].startswith("OK")]
    print(f"\nNot OK ({len(bad)}):")
    for group, where, name, stated, shown, verdict in bad:
        print(f"  [{group}] {where} | {name} | stated {stated} | recomputed {shown} | {verdict}")
    print("\nSummary")
    for g in titles:
        sub = [r for r in rows if r[0] == g]
        print(f"  [{g}] checked {len(sub)}, OK {sum(r[5].startswith('OK') for r in sub)}, "
              f"MISMATCH {sum(r[5].startswith('MISMATCH') for r in sub)}, "
              f"NOT FOUND {sum(r[5].startswith('NOT FOUND') for r in sub)}")
    print(f"  total checked {len(rows)}, OK {len(rows) - len(bad)}, not OK {len(bad)}")
