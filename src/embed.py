"""Embed passages with one multilingual model, in their original language.

Vectors live in two files next to the database: `embeddings.npy` (float32, normalized)
and `vector_passage_ids.npy` (the passage each row belongs to). A long passage is cut
into several windows, so a passage can own more than one row.
"""
import os
import time

import numpy as np

from . import db

MODEL_NAME = "intfloat/multilingual-e5-small"  # 384 dimensions, 512 token input, about 100 languages
MAX_TOKENS = 512
CJK = {"zh", "ja", "ko"}  # no spaces, and roughly one token per character

_model = None


def limits(language):
    """(shortest passage worth embedding, window size), both in characters."""
    return (15, 400) if language in CJK else (40, 1600)


def windows(text, limit):
    """Cut text into pieces of at most `limit` characters, at a sentence or word boundary where there is one."""
    pieces = []
    while len(text) > limit:
        cut = limit
        for separator in (". ", "。", "; ", "；", ", ", "，", " "):
            at = text.rfind(separator, limit // 2, limit)
            if at != -1:
                cut = at + len(separator)
                break
        pieces.append(text[:cut].strip())
        text = text[cut:]
    if text.strip():
        pieces.append(text.strip())
    return pieces


def model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer  # slow import, only when needed
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def encode(texts, prefix):
    """Normalized float32 vectors. The e5 models expect 'query: ' or 'passage: ' before every text."""
    vectors = model().encode([prefix + text for text in texts], batch_size=64, normalize_embeddings=True,
                             show_progress_bar=len(texts) > 1000)
    return np.asarray(vectors, dtype=np.float32)


def count_truncated(texts, prefix):
    """How many texts are longer than the model input and so lose their tail."""
    tokenizer = model().tokenizer
    total = 0
    for start in range(0, len(texts), 2000):
        batch = tokenizer([prefix + text for text in texts[start:start + 2000]], truncation=False)["input_ids"]
        total += sum(len(ids) > MAX_TOKENS for ids in batch)
    return total


def load_vectors(index_dir=None):
    path = db.index_dir(index_dir)
    try:
        return (np.load(os.path.join(path, "embeddings.npy")),
                np.load(os.path.join(path, "vector_passage_ids.npy")))
    except FileNotFoundError:
        return np.zeros((0, 0), np.float32), np.zeros(0, np.int64)


def embed_pending(con, index_dir=None):
    """Embed every passage that has no vector yet and append to the vector files."""
    vectors, ids = load_vectors(index_dir)
    done = set(ids.tolist())
    texts, owners = [], []
    for row in con.execute("SELECT s.id, s.kind, s.number_inferred, s.text, p.title, p.language "
                           "FROM passages s JOIN patents p ON p.id = s.patent_id ORDER BY s.id"):
        shortest, window = limits(row["language"])
        if row["id"] in done or len(row["text"]) < shortest:
            continue  # equation fragments and headings stay in the database for display only
        text = row["text"]
        if row["kind"] == "claim" and row["number_inferred"] and row["title"]:
            text = f"{row['title']}: {text}"  # a claim that lost its preamble needs a subject
        for piece in windows(text, window):
            texts.append(piece)
            owners.append(row["id"])
    if not texts:
        return {}
    start = time.perf_counter()
    new = encode(texts, "passage: ")
    seconds = time.perf_counter() - start
    truncated = count_truncated(texts, "passage: ")
    path = db.index_dir(index_dir)
    np.save(os.path.join(path, "embeddings.npy"), np.vstack([vectors, new]) if len(vectors) else new)
    np.save(os.path.join(path, "vector_passage_ids.npy"), np.concatenate([ids, np.array(owners, np.int64)]))
    print(f"embedded {len(texts)} windows from {len(set(owners))} passages in {seconds:.1f} s "
          f"({len(texts) / seconds:.0f} windows per second), {truncated} windows longer than {MAX_TOKENS} tokens")
    return {"embedded_windows": len(texts), "embedded_passages": len(set(owners)),
            "embed_seconds": round(seconds, 1), "truncated_windows": truncated}
