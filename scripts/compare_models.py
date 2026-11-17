"""Is the language gap a property of the small embedding model? Abstracts only, so it runs in a minute or two per model.

Usage: python scripts/compare_models.py [model names ...]

Same test as scripts/evaluate_multilingual.py, cut down: the query is the first claim in
English, the candidates are abstracts only (one vector each), and the right answer is the
abstract of the same patent in English, German or Chinese.
- alone: 100 candidate abstracts, all in the target language.
- mixed: the same 100 plus the abstracts of the 540 other English patents.
Prints mean reciprocal rank and recall at 10.
"""
import os
import sys

import numpy as np
from sentence_transformers import SentenceTransformer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src import db  # noqa: E402

DEFAULT_MODELS = ["intfloat/multilingual-e5-small", "intfloat/multilingual-e5-base", "BAAI/bge-m3"]


def main(models):
    con = db.connect()
    abstracts = dict(con.execute("SELECT doc_number, abstract FROM patents WHERE abstract IS NOT NULL"))
    originals = sorted(doc[:-3] for doc in abstracts if doc.endswith("-DE") and doc[:-3] + "-ZH" in abstracts)
    copies = {doc + suffix for doc in originals for suffix in ("", "-DE", "-ZH")}
    distractors = sorted(doc for doc in abstracts if doc not in copies)
    queries = [con.execute("SELECT s.text FROM passages s JOIN patents p ON p.id = s.patent_id WHERE p.doc_number = ? "
                           "AND s.kind = 'claim' ORDER BY s.ord LIMIT 1", (doc,)).fetchone()[0] for doc in originals]
    print(f"{len(originals)} test patents, {len(distractors)} English distractors\n")
    print("| Model | Dimensions | Target language | Alone: MRR | Alone: recall at 10 | Mixed: MRR | Mixed: recall at 10 |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for name in models:
        model = SentenceTransformer(name)
        e5 = "e5" in name  # the e5 family wants these prefixes, bge-m3 wants none

        def encode(texts, kind):
            return model.encode([(f"{kind}: " if e5 else "") + t for t in texts], batch_size=32, normalize_embeddings=True)

        q, d = encode(queries, "query"), encode([abstracts[doc] for doc in distractors], "passage")
        worst_distractor = (q @ d.T)  # query x distractor scores
        for suffix, language in (("", "English"), ("-DE", "German"), ("-ZH", "Chinese")):
            t = encode([abstracts[doc + suffix] for doc in originals], "passage")
            scores = q @ t.T
            own = np.diag(scores)
            rank_alone = 1 + (scores > own[:, None]).sum(axis=1)
            rank_mixed = rank_alone + (worst_distractor > own[:, None]).sum(axis=1)
            print(f"| `{name}` | {q.shape[1]} | {language} | {np.mean(1 / rank_alone):.3f} | {np.mean(rank_alone <= 10):.2f} "
                  f"| {np.mean(1 / rank_mixed):.3f} | {np.mean(rank_mixed <= 10):.2f} |", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:] or DEFAULT_MODELS)
