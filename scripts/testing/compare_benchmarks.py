"""Compare two benchmarks.md files cell by cell and flag differences over 30 percent.
Usage: python scripts/testing/compare_benchmarks.py CLAIMED.md MEASURED.md [--out file.json]"""
import json
import re
import sys


def cells(path):
    out, section = {}, ""
    for line in open(path, encoding="utf-8"):
        if line.startswith("#"):
            section = line.strip("# \n")[:28]
        if line.startswith("|") and not line.startswith("| ---"):
            parts = [p.strip() for p in line.strip().strip("|").split("|")]
            if parts[0] in ("Mode", "Filter"):
                header = parts
                continue
            for name, value in zip(header[1:], parts[1:]):
                if name in ("Patents passing", "Vectors kept", "First against after"):
                    continue
                for i, number in enumerate(re.findall(r"\d+\.?\d*", value)):
                    out[f"{section} | {parts[0]} | {name}{' p95' if i else ''}"] = float(number)
    return out


claimed, measured = cells(sys.argv[1]), cells(sys.argv[2])
rows = []
for key in claimed:
    if key in measured and claimed[key] > 0:
        rows.append((key, claimed[key], measured[key], measured[key] / claimed[key] - 1))
flagged = [r for r in rows if abs(r[3]) > 0.30]
print(f"{len(rows)} cells compared, {len(flagged)} differ by more than 30%")
for key, c, m, d in rows:
    print(f"{'FLAG ' if abs(d) > 0.30 else '     '}{key:95s} claimed {c:8.2f}  measured {m:8.2f}  {d:+.0%}")
if "--out" in sys.argv:
    json.dump({"cells": len(rows), "flagged": len(flagged), "rows": rows}, open(sys.argv[sys.argv.index("--out") + 1], "w"), indent=1)
