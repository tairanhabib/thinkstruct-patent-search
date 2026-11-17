"""Language detection and machine translation, behind two small functions.

Search never depends on translation quality: passages are embedded in their original
language. Translation is used for (1) the title and abstract at ingest, so English
keyword search works, and (2) showing a result in English, on demand, cached.

The engine is a local Helsinki-NLP opus-mt model per language pair. To use a hosted
model instead, replace `translate_texts`.
"""
import hashlib
import re

from langdetect import DetectorFactory, detect_langs

from .embed import CJK, windows

DetectorFactory.seed = 0  # langdetect gives different answers between runs without a seed
MODEL_PATTERN = "Helsinki-NLP/opus-mt-{source}-{target}"

_engines = {}


def detect_language(text):
    """ISO 639-1 code, or None when the text is too short or the detector is unsure."""
    text = (text or "").strip()[:2000]
    letters = sum(ch.isalpha() for ch in text)
    has_cjk = bool(re.search(r"[぀-ヿ一-鿿가-힯]", text))
    if letters < (6 if has_cjk else 20):
        return None  # formulas, part numbers and two word titles are not reliable evidence
    try:
        best = detect_langs(text)[0]
    except Exception:
        return None
    return best.lang.split("-")[0] if best.prob >= 0.7 else None  # zh-cn and zh-tw both become zh


def _engine(source, target):
    """Tokenizer and model for one language pair, or None when no such model exists."""
    name = MODEL_PATTERN.format(source=source, target=target)
    if name not in _engines:
        try:
            from transformers import MarianMTModel, MarianTokenizer
            _engines[name] = (MarianTokenizer.from_pretrained(name), MarianMTModel.from_pretrained(name).eval())
        except Exception as error:  # no model for this pair, or no network on first use
            print(f"no translation model {name}: {type(error).__name__}")
            _engines[name] = None
    return name, _engines[name]


def _sentences(text, source):
    """Pieces short enough for the model input (512 tokens): sentences, then cut at commas if still long."""
    limit = 120 if source in CJK else 400
    pieces = []
    for sentence in re.split(r"(?<=[.!?。！？])\s+|(?<=[。！？])", text):
        pieces.extend(windows(sentence, limit))
    return pieces


def translate_texts(texts, source, target="en", beams=4):
    """Translate a list of texts. Returns None when there is no model for the pair."""
    import torch
    _, engine = _engine(source, target)
    if engine is None:
        return None
    tokenizer, model = engine
    pieces, owner = [], []
    for position, text in enumerate(texts):
        for piece in _sentences(text, source):
            pieces.append(piece)
            owner.append(position)
    order = sorted(range(len(pieces)), key=lambda i: len(pieces[i]))  # similar lengths share a batch
    translated = [""] * len(pieces)
    for start in range(0, len(order), 24):
        chunk = order[start:start + 24]
        batch = tokenizer([pieces[i] for i in chunk], return_tensors="pt", padding=True, truncation=True,
                          max_length=512)
        with torch.no_grad():
            output = model.generate(**batch, num_beams=beams, max_new_tokens=512)
        for i, text in zip(chunk, tokenizer.batch_decode(output, skip_special_tokens=True)):
            translated[i] = text
    joined = [[] for _ in texts]
    for position, text in zip(owner, translated):
        joined[position].append(text)
    return [("" if target in CJK else " ").join(parts) for parts in joined]


def translate_many(texts, source_language, con=None):
    """English versions of `texts`. Cached in the `translations` table when a connection is given.
    Falls back to the original text when no model exists for the language."""
    texts = list(texts)
    if source_language in (None, "en"):
        return texts
    name = MODEL_PATTERN.format(source=source_language, target="en")
    keys = [hashlib.sha1(f"{name}\n{text}".encode("utf-8")).hexdigest() for text in texts]
    known = {}
    if con is not None:
        for key in set(keys):
            row = con.execute("SELECT text_en FROM translations WHERE key = ?", (key,)).fetchone()
            if row:
                known[key] = row[0]
    todo = [i for i, (key, text) in enumerate(zip(keys, texts)) if text and key not in known]
    if todo:
        fresh = translate_texts([texts[i] for i in todo], source_language)
        if fresh is None:
            return texts
        for i, text_en in zip(todo, fresh):
            known[keys[i]] = text_en
            if con is not None:
                con.execute("INSERT OR REPLACE INTO translations VALUES (?,?,?)", (keys[i], name, text_en))
        if con is not None:
            con.commit()
    return [known.get(key, text) for key, text in zip(keys, texts)]


def translate(text, source_language, con=None):
    return translate_many([text], source_language, con)[0] if text else text
