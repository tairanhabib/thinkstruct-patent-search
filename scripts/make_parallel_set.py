"""Build a synthetic foreign language test set by machine translating English patents.

Usage: python scripts/make_parallel_set.py [--n 100] [--languages de zh] [--source data/small] [--out data/parallel]

Why: the real non-English sample has not arrived. Translating a sample of the English
patents gives the same inventions in three languages, so "does search work as well on
foreign patents" becomes a measurement. The output has the same shape as the source
files and goes through the normal ingest: `python cli.py ingest data/parallel`.

The copies get the document number of the original plus `-DE` or `-ZH`.
Safe to stop and run again: finished files are skipped.
"""
import argparse
import glob
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.ingest import CANCELLED, CLAIM_NUMBER  # noqa: E402
from src.translate import translate_texts  # noqa: E402

MIN_CHARS = 40  # shorter pieces are formulas and headings: copied, not translated (they are never embedded)


def choose(source, n, seed=0):
    """A fixed random sample of patents that can serve as test queries: they need a
    description to be found by, and a first claim long enough to search with."""
    eligible = []
    for path in sorted(glob.glob(os.path.join(source, "*.json"))):
        with open(path, encoding="utf-8") as handle:
            for patent in json.load(handle):
                first_claim = next((c for c in patent.get("claims") or [] if not CANCELLED.fullmatch(c)), "")
                if any(p.strip() for p in patent.get("detailed_description") or []) and len(first_claim) >= 150:
                    eligible.append((os.path.basename(path), patent))
    chosen = random.Random(seed).sample(eligible, min(n, len(eligible)))
    by_file = {}
    for file_name, patent in chosen:
        by_file.setdefault(file_name, []).append(patent)
    return by_file, len(eligible)


def translate_patents(patents, language, beams):
    """Copies of the patents with every text field translated. Structure is kept item for item."""
    texts, slots = [], []  # slots: where each translated text goes back, with a prefix to restore

    def want(text, target, key, prefix=""):
        if len(text.strip()) >= MIN_CHARS:
            texts.append(text.strip())
            slots.append((target, key, prefix))

    copies = []
    for patent in patents:
        copy = dict(patent, doc_number=f"{patent['doc_number']}-{language.upper()}",
                    claims=list(patent["claims"]), detailed_description=list(patent["detailed_description"]))
        copies.append(copy)
        texts.append(patent["title"])  # titles are always translated, however short
        slots.append((copy, "title", ""))
        want(patent["abstract"], copy, "abstract")
        for i, claim in enumerate(patent["claims"]):
            match = None if CANCELLED.fullmatch(claim) else CLAIM_NUMBER.match(claim)
            if match:  # keep "12 . " as it is and translate only the body
                want(match.group(3), copy["claims"], i, claim[:match.start(3)])
            elif not CANCELLED.fullmatch(claim):
                want(claim, copy["claims"], i)
        for i, paragraph in enumerate(patent["detailed_description"]):
            want(paragraph, copy["detailed_description"], i)
    translated = translate_texts(texts, "en", language, beams=beams)
    if translated is None:
        raise SystemExit(f"no translation model for English to {language!r}: check the language code and the network")
    for (target, key, prefix), text in zip(slots, translated):
        target[key] = prefix + text
    return copies, sum(map(len, texts))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--languages", nargs="+", default=["de", "zh"])
    parser.add_argument("--source", default="data/small")
    parser.add_argument("--out", default="data/parallel")
    parser.add_argument("--beams", type=int, default=1, help="beam width; 1 is greedy and fastest")
    args = parser.parse_args()

    by_file, eligible = choose(args.source, args.n)
    chosen = sum(map(len, by_file.values()))
    print(f"{chosen} patents chosen at random (seed 0) from {eligible} eligible, in {len(by_file)} files")
    for language in args.languages:
        start, characters, done = time.perf_counter(), 0, 0
        os.makedirs(os.path.join(args.out, language), exist_ok=True)
        for file_name, patents in sorted(by_file.items()):
            target = os.path.join(args.out, language, file_name)
            done += len(patents)
            if os.path.exists(target):
                continue
            copies, count = translate_patents(patents, language, args.beams)
            characters += count
            with open(target + ".part", "w", encoding="utf-8") as handle:
                json.dump(copies, handle, ensure_ascii=False, indent=1)
            os.replace(target + ".part", target)  # a file either exists whole or not at all
            elapsed = time.perf_counter() - start
            print(f"  {language}: {done}/{chosen} patents, {characters:,} characters in {elapsed:.0f} s", flush=True)
        elapsed = time.perf_counter() - start
        if characters:
            print(f"{language}: translated {characters:,} characters in {elapsed:.0f} s ({characters / elapsed:.0f} characters per second)")
        else:
            print(f"{language}: nothing to do, all files already exist")


if __name__ == "__main__":
    main()
