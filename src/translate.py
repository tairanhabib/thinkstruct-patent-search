"""Language detection and machine translation, behind two small functions.

Passages are embedded in their original language and are never translated for search.
Translation is used for (1) the title and abstract at ingest, so English keyword search
works, (2) the query, which is short, into each language the index holds, and
(3) showing a result in English, on demand. All cached.

The engine is a local Helsinki-NLP opus-mt model per language pair. To use a hosted
model instead, replace `translate_texts`.
"""
import hashlib
import re
import time

from langdetect import DetectorFactory, detect_langs

from .embed import CJK, windows

DetectorFactory.seed = 0  # langdetect gives different answers between runs without a seed
MODEL_PATTERN = "Helsinki-NLP/opus-mt-{source}-{target}"

_engines = {}
usage = {"seconds": 0.0, "characters": 0}  # what translation has cost in this process


def detect_language(text, min_letters=20, min_probability=0.7):
    """ISO 639-1 code, or None when the text is too short or the detector is unsure."""
    text = (text or "").strip()[:2000]
    letters = sum(ch.isalpha() for ch in text)
    kana = len(re.findall(r"[\u3040-\u30ff]", text))
    hangul = len(re.findall(r"[\uac00-\ud7af]", text))
    han = len(re.findall(r"[\u4e00-\u9fff]", text))
    if kana + hangul + han >= 6 and kana + hangul + han > 0.3 * letters:
        # East Asian text is decided by its script, which is certain. The statistical detector
        # called 21 of 100 Chinese abstracts Korean or unknown.
        return "ja" if kana > 0.05 * (kana + han) else "ko" if hangul > han else "zh"
    if letters < min_letters:
        return None  # formulas, part numbers and two word titles are not reliable evidence
    try:
        best = detect_langs(text)[0]
    except Exception:
        return None
    return best.lang.split("-")[0] if best.prob >= min_probability else None


def _engine(source, target):
    """Tokenizer, model and device for one language pair, or None when no such model exists."""
    name = MODEL_PATTERN.format(source=source, target=target)
    if name not in _engines:
        try:
            import torch
            from transformers import MarianMTModel, MarianTokenizer
            device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
            _engines[name] = (MarianTokenizer.from_pretrained(name),
                              MarianMTModel.from_pretrained(name).eval().to(device), device)
        except Exception as error:  # no model for this pair, or no network on first use
            print(f"no translation model {name}: {type(error).__name__}")
            _engines[name] = None
    return name, _engines[name]


def _sentences(text, source):
    """Pieces short enough for the model input (512 tokens): sentences, then cut at commas if still long."""
    limit = 120 if source in CJK else 400
    pieces = []
    for sentence in re.split(r"(?<=[.!?。！？])\s+|(?<=[。！？])", text):
        if sentence.isupper():
            sentence = sentence.capitalize()  # these models garble capitals: the title "SPOKE" came out as "GESAMT"
        pieces.extend(windows(sentence, limit))
    return pieces


def translate_texts(texts, source, target="en", beams=4):
    """Translate a list of texts. Returns None when there is no model for the pair."""
    import torch
    _, engine = _engine(source, target)
    if engine is None:
        return None
    tokenizer, model, device = engine
    pieces, owner = [], []
    for position, text in enumerate(texts):
        for piece in _sentences(text, source):
            pieces.append(piece)
            owner.append(position)
    order = sorted(range(len(pieces)), key=lambda i: len(pieces[i]))  # similar lengths share a batch
    translated = [""] * len(pieces)
    for start in range(0, len(order), 64):
        chunk = order[start:start + 64]
        batch = tokenizer([pieces[i] for i in chunk], return_tensors="pt", padding=True, truncation=True,
                          max_length=512).to(device)
        with torch.no_grad():
            # Output capped at twice the input length: stops the runaway repetition these models sometimes produce.
            output = model.generate(**batch, num_beams=beams, max_length=2 * batch["input_ids"].shape[1] + 10)
        for i, text in zip(chunk, tokenizer.batch_decode(output, skip_special_tokens=True)):
            translated[i] = text
    joined = [[] for _ in texts]
    for position, text in zip(owner, translated):
        joined[position].append(text)
    return [("" if target in CJK else " ").join(parts) for parts in joined]


def translate_many(texts, source_language, con=None, target="en", beams=4):
    """`texts` in the target language (English unless stated). Cached in the `translations`
    table when a connection is given. Falls back to the original text when no model exists
    for the language pair."""
    texts = list(texts)
    if source_language in (None, target):
        return texts
    name = MODEL_PATTERN.format(source=source_language, target=target)
    keys = [hashlib.sha1(f"{name}\n{beams}\n{text}".encode("utf-8")).hexdigest() for text in texts]
    known = {}
    if con is not None:
        for key in set(keys):
            row = con.execute("SELECT text_en FROM translations WHERE key = ?", (key,)).fetchone()
            if row:
                known[key] = row[0]
    todo = [i for i, (key, text) in enumerate(zip(keys, texts)) if text and key not in known]
    if todo:
        start = time.perf_counter()
        fresh = translate_texts([texts[i] for i in todo], source_language, target, beams)
        if fresh is None:
            return texts
        usage["seconds"] += time.perf_counter() - start
        usage["characters"] += sum(len(texts[i]) for i in todo)
        for i, translated in zip(todo, fresh):
            known[keys[i]] = translated
            if con is not None:
                con.execute("INSERT OR REPLACE INTO translations VALUES (?,?,?)", (keys[i], name, translated))
        if con is not None:
            con.commit()
    return [known.get(key, text) for key, text in zip(keys, texts)]


def translate(text, source_language, con=None, target="en", beams=4):
    return translate_many([text], source_language, con, target, beams)[0] if text else text
