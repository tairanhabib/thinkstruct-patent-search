"""Phase A: describe the raw data so the schema follows the data, not the brief.

Usage: python scripts/inspect_data.py data/small
"""
import collections
import glob
import json
import os
import re
import statistics
import sys

from langdetect import DetectorFactory, detect

DetectorFactory.seed = 0  # langdetect is random without a seed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def is_missing(value):
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return not any(str(v).strip() for v in value)
    return False


def pct(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * q))]


def main(data_dir):
    files = sorted(glob.glob(os.path.join(data_dir, "*.json")))
    patents, per_file = [], []
    for path in files:
        with open(path, encoding="utf-8") as fh:
            rows = json.load(fh)
        per_file.append(len(rows))
        for row in rows:
            row["_file"] = os.path.basename(path)
            patents.append(row)

    print(f"files: {len(files)}  patents: {len(patents)}  "
          f"patents per file: min {min(per_file)} max {max(per_file)}")
    print(f"file dates: {files[0][-11:-5]} .. {files[-1][-11:-5]}")

    keys = collections.Counter(k for p in patents for k in p if k != "_file")
    print("\nkeys (count of patents having the key | missing or empty | value types):")
    for key, count in keys.items():
        missing = sum(is_missing(p.get(key)) for p in patents)
        types = collections.Counter(type(p.get(key)).__name__ for p in patents)
        print(f"  {key:22s} {count:4d} | missing {missing:3d} | {dict(types)}")

    docs = [p.get("doc_number") for p in patents]
    titles = collections.Counter(p.get("title") for p in patents)
    print(f"\nunique doc_number: {len(set(docs))} of {len(docs)}")
    print(f"titles shared by more than one patent: {sum(c > 1 for c in titles.values())}")

    # dates: file name week versus the date inside the `filename` field
    agree = 0
    for p in patents:
        week = "20" + re.search(r"(\d{6})\.json$", p["_file"]).group(1)
        inner = re.search(r"-(\d{8})\.", p.get("filename") or "")
        agree += bool(inner and inner.group(1) == week)
    print(f"file name date == date inside `filename`: {agree} of {len(patents)}")

    # classification
    codes = [p.get("classification") for p in patents if not is_missing(p.get("classification"))]
    print(f"\nclassification: type {collections.Counter(type(c).__name__ for c in codes)}, "
          f"length {min(map(len, codes))}..{max(map(len, codes))}, "
          f"ends with FI: {sum(c.endswith('FI') for c in codes)}, "
          f"contains separator [ ,;/]: {sum(bool(re.search(r'[ ,;/]', c)) for c in codes)}")
    print("  subclass (first 4 chars):", collections.Counter(c[:4] for c in codes).most_common())
    print("  examples:", codes[:5])

    # claims
    claims = [c for p in patents for c in (p.get("claims") or [])]
    numbered = sum(bool(re.match(r"\s*\d+\s*\.", c)) for c in claims)
    cancelled = sum(bool(re.search(r"\(cancel+ed\)", c, re.I)) for c in claims)
    first_numbered = sum(bool(re.match(r"\s*\d+\s*\.", (p.get("claims") or [""])[0])) for p in patents)
    dependent = sum(bool(re.search(r"\bclaims?\s+\d+", c)) for c in claims)
    print(f"\nclaims: {len(claims)} total, {numbered} start with a number, "
          f"{cancelled} cancelled, {dependent} mention 'claim N' (dependent)")
    print(f"  patents whose first claim starts with a number: {first_numbered} of {len(patents)}")
    print(f"  claims per patent: median {statistics.median(len(p.get('claims') or []) for p in patents)}")
    print("  first claim examples:")
    for p in patents[:3]:
        print("   ", repr(p["claims"][0][:110]))
    print("  second claim example:", repr(patents[0]["claims"][1][:110]))
    print("  cancelled example:", repr(next(c for c in claims if re.search(r"\(cancel+ed\)", c, re.I))[:80]))

    # Is "previous number plus one" the right number for a claim that lost its number? Wherever unnumbered
    # items sit between two numbered claims, their count can be compared with the gap in the numbering.
    from src.ingest import CANCELLED, CLAIM_NUMBER
    runs = matching = 0
    for p in patents:
        previous, run = 0, 0
        for item in (c for c in (p.get("claims") or []) if isinstance(c, str) and c.strip()):
            number = CLAIM_NUMBER.match(item)
            if CANCELLED.fullmatch(item):  # "1 - 5 . (canceled)" uses up its numbers
                stated = re.findall(r"\d+", item)
                first, last = (int(stated[0]), int(stated[-1])) if stated else (previous + run + 1,) * 2
            elif number:
                first = int(number.group(1))
                last = int(number.group(2) or number.group(1))
            else:
                run += 1
                continue
            if run:
                runs += 1
                matching += first - previous - 1 == run
            previous, run = last, 0
    print(f"  runs of unnumbered claims followed by a numbered claim: {runs}; "
          f"as many items as the gap in the numbering: {matching} ({matching / runs:.1%})")

    # description paragraphs
    paras = [d for p in patents for d in (p.get("detailed_description") or [])]
    empty = sum(not d.strip() for d in paras)
    real = [d for d in paras if d.strip()]
    print(f"\ndescription paragraphs: {len(paras)} total, {empty} empty, {len(real)} non-empty")

    passages = real + [c for c in claims if c.strip()] + [p["abstract"] for p in patents if not is_missing(p.get("abstract"))]
    lengths = [len(t) for t in passages]
    print(f"\npassage length in characters over {len(passages)} non-empty passages:")
    print(f"  min {min(lengths)}  p10 {pct(lengths, .10)}  median {pct(lengths, .50)}  "
          f"p90 {pct(lengths, .90)}  p99 {pct(lengths, .99)}  max {max(lengths)}")
    for limit in (40, 1000, 1600, 2000):
        print(f"  under {limit} chars: {sum(n < limit for n in lengths)}")
    print(f"  total characters: {sum(lengths):,}")
    print("  short examples:", [t for t in real if len(t) < 40][:6])

    # language
    langs = collections.Counter()
    for p in patents:
        text = p.get("abstract") or (p.get("claims") or [""])[0]
        try:
            langs[detect(text)] += 1
        except Exception:
            langs["undetected"] += 1
    non_ascii = sum(any(ord(ch) > 127 for ch in (p.get("abstract") or "")) for p in patents)
    print(f"\ndetected language of abstract: {dict(langs)}")
    print(f"abstracts containing non-ASCII characters: {non_ascii}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/small")
