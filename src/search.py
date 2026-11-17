"""Search: filter patents in SQL first, score only the passages that survive, then fuse
the keyword ranking and the semantic ranking with reciprocal rank fusion.

    from src.search import Index, search
    index = Index()
    hits = search("wheel hub with integrated pressure sensor", cpc_prefix="B60B", index=index)
"""
import re
import time

import numpy as np

from . import db, embed, translate

KINDS = ("abstract", "claim", "description")
MODES = ("hybrid", "semantic", "keyword")
RRF_K = 60  # the usual constant: it flattens the difference between neighbouring ranks
AUTO_THRESHOLD = 0.15  # share of rows kept below which filter first wins; measured, see benchmarks.md
STOPWORDS = set(
    "a an and are as at be been being by for from has have having in into is it its of on or said such that the "
    "their thereof to was were which with wherein whereby comprising comprises comprise according claim claims "
    "one least first second".split())


class Index:
    """Everything a query needs, loaded once per process."""

    def __init__(self, index_dir=None):
        self.con = db.connect(index_dir)
        self.vectors, self.vector_passage = embed.load_vectors(index_dir)
        size = self.con.execute("SELECT COALESCE(MAX(id), 0) FROM passages").fetchone()[0] + 1
        patent_of, kind_of = np.zeros(size, np.int64), np.zeros(size, np.int8)
        for passage_id, patent_id, kind in self.con.execute("SELECT id, patent_id, kind FROM passages"):
            patent_of[passage_id], kind_of[passage_id] = patent_id, KINDS.index(kind)
        self.vector_patent = patent_of[self.vector_passage]  # owning patent of every vector row
        if np.any(np.diff(self.vector_patent) < 0):  # keep the rows of a patent adjacent, whatever the ingest order
            order = np.argsort(self.vector_patent, kind="stable")
            self.vectors, self.vector_passage = self.vectors[order], self.vector_passage[order]
            self.vector_patent = self.vector_patent[order]
        self.vector_kind = kind_of[self.vector_passage]
        self.patent_ids = {doc: patent_id for doc, patent_id in self.con.execute("SELECT doc_number, id FROM patents")}
        self.table_size = max(self.patent_ids.values(), default=0) + 1


def _terms(text):
    return list(dict.fromkeys(t for t in re.findall(r"\w+", (text or "").lower()) if t not in STOPWORDS and len(t) > 1))


def filter_patents(index, cpc_prefix=None, keywords=None, title=None, date_from=None, date_to=None, language=None,
                   include_unknown=False, restrict_docs=None):
    """Boolean table over patent ids of the patents that pass every filter, or None when there is no filter.

    A patent whose field is missing fails a filter on that field. With `include_unknown`
    it passes instead, because "we do not know" is not the same as "no".
    """
    def unknown(condition):
        return f" OR {condition}" if include_unknown else ""

    where, params = [], []
    if cpc_prefix:
        has_code = "EXISTS (SELECT 1 FROM classifications c WHERE c.patent_id = p.id"
        where.append(f"({has_code} AND c.code GLOB ?){unknown('NOT ' + has_code + ')')})")
        params.append(re.sub(r"[^A-Z0-9]", "", cpc_prefix.upper()) + "*")  # 'b60b 1/04' and 'B60B104' both work
    if keywords and _terms(keywords):
        where.append("(p.id IN (SELECT rowid FROM patents_fts WHERE patents_fts MATCH ?)"
                     f"{unknown('p.title IS NULL OR p.abstract IS NULL')})")
        params.append(" AND ".join(f'"{term}"' for term in _terms(keywords)))  # every keyword must appear
    if title:
        pattern = "%" + re.sub(r"([\\%_])", r"\\\1", title.strip()) + "%"
        where.append(f"(p.title LIKE ? ESCAPE '\\' OR p.title_en LIKE ? ESCAPE '\\'{unknown('p.title IS NULL')})")
        params += [pattern, pattern]
    if date_from:
        where.append(f"(p.filing_week >= ?{unknown('p.filing_week IS NULL')})")
        params.append(date_from)
    if date_to:
        where.append(f"(p.filing_week <= ?{unknown('p.filing_week IS NULL')})")
        params.append(date_to)
    if language:
        where.append(f"(p.language = ?{unknown('p.language IS NULL')})")
        params.append(language.lower())
    if not where and restrict_docs is None:
        return None
    allowed = np.zeros(index.table_size, bool)
    if where:
        ids = [row[0] for row in index.con.execute("SELECT p.id FROM patents p WHERE " + " AND ".join(where), params)]
        allowed[ids] = True
    else:
        allowed[:] = True
    if restrict_docs is not None:  # used by the evaluation to build a candidate set
        inside = np.zeros(index.table_size, bool)
        inside[[index.patent_ids[doc] for doc in restrict_docs if doc in index.patent_ids]] = True
        allowed &= inside
    return allowed


def rank_patents(vectors, vector_patent, query_vector, keep=None, strategy="auto"):
    """Best passage per patent, best patent first.

    `keep` is a boolean mask over vector rows (None means every row). Rows of one patent
    must be adjacent in `vector_patent` (Index guarantees it).
    - filter_first copies out the kept rows and scores only those.
    - filter_after scores every row and discards afterwards. The baseline.
    - auto picks filter_first when the filter keeps under AUTO_THRESHOLD of the rows:
      measured, copying out more rows than that costs more than scoring everything in place.
    Returns (patent ids, vector row of each patent's best passage, scores).
    """
    if keep is None:
        rows, scores = None, vectors @ query_vector
    else:
        rows = np.flatnonzero(keep)
        if strategy == "filter_first" or (strategy == "auto" and len(rows) < AUTO_THRESHOLD * len(keep)):
            scores = vectors[rows] @ query_vector
        else:
            scores = (vectors @ query_vector)[rows]
    owners = vector_patent if rows is None else vector_patent[rows]
    if not len(owners):
        return owners, owners, scores
    # One pass per patent instead of sorting every row: the rows of a patent are adjacent.
    starts = np.flatnonzero(np.r_[True, owners[1:] != owners[:-1]])
    best = np.maximum.reduceat(scores, starts)
    sizes = np.diff(np.r_[starts, len(owners)])
    at_best = np.flatnonzero(scores == np.repeat(best, sizes))  # rows that hold their patent's best score
    group = np.searchsorted(starts, at_best, side="right") - 1
    best_row = at_best[np.r_[True, group[1:] != group[:-1]]]  # the first such row of each patent
    order = np.argsort(-best, kind="stable")  # ties keep patent order, so every strategy agrees
    best_row = best_row[order]
    return owners[best_row], best_row if rows is None else rows[best_row], best[order]


def keyword_rank(con, text):
    """Patent ids ordered by BM25 of the query words against English title (weight 2) and abstract."""
    terms = _terms(text)
    if not terms:
        return []
    match = " OR ".join(f'"{term}"' for term in terms)
    # shortcut: every query word goes into one OR query, fine below a million documents;
    # at scale keep only the rarest dozen terms.
    return [row[0] for row in con.execute(
        "SELECT rowid FROM patents_fts WHERE patents_fts MATCH ? ORDER BY bm25(patents_fts, 2.0, 1.0)", (match,))]


def source_vector(index, doc_number, claim_number=None):
    """Query vector taken from a patent already in the index: the named claim, else the
    abstract, else the first claim, else the first description paragraph that has a vector."""
    if doc_number not in index.patent_ids:
        raise ValueError(f"no patent with document number {doc_number!r} in the index")
    patent_id = index.patent_ids[doc_number]
    wanted = ([("claim", claim_number)] if claim_number else []) + [("abstract", None), ("claim", None), ("description", None)]
    for kind, number in wanted:
        sql = "SELECT id, ord FROM passages WHERE patent_id = ? AND kind = ?" + (" AND ord = ?" if number else "") + " ORDER BY ord"
        for passage_id, number_found in index.con.execute(sql, (patent_id, kind) + ((number,) if number else ())):
            rows = np.flatnonzero(index.vector_passage == passage_id)
            if len(rows):
                vector = index.vectors[rows].mean(axis=0)
                label = "abstract" if kind == "abstract" else f"{kind} {number_found}"
                return vector / np.linalg.norm(vector), label
    raise ValueError(f"patent {doc_number} has no embedded text to search with")


def search(query=None, doc_number=None, claim_number=None, top_k=10, cpc_prefix=None, keywords=None, title=None,
           date_from=None, date_to=None, language=None, passage_types=None, include_unknown=False, mode="hybrid",
           strategy="auto", restrict_docs=None, translate_results=True, index=None, info=None):
    """Ranked patents, each with its best matching passage as evidence.

    Give a `query` in any language, or a `doc_number` (optionally with `claim_number`) to
    find patents like one already indexed, or only filters to list what matches them.
    `info`, when a dict is passed, is filled with timings and counts.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    for kind in passage_types or ():
        if kind not in KINDS:
            raise ValueError(f"passage type must be one of {KINDS}")
    index = index or Index()
    info = {} if info is None else info
    ms, clock = {}, time.perf_counter()

    def lap(name):
        nonlocal clock
        now = time.perf_counter()
        ms[name] = ms.get(name, 0.0) + (now - clock) * 1000
        clock = now

    # 1. what to search with
    query_vector, keyword_text, source_id = None, query, None
    if doc_number:
        query_vector, info["query_source"] = source_vector(index, doc_number, claim_number)
        source_id = index.patent_ids[doc_number]
        row = index.con.execute("SELECT title_en, abstract_en FROM patents WHERE id = ?", (source_id,)).fetchone()
        keyword_text = f"{row[0] or ''} {row[1] or ''}"
    elif query and mode != "keyword":
        query_vector = embed.encode([query], "query: ")[0]
    elif not query:
        keyword_text = keywords  # filters only: order by how well the keywords match
        if not any((cpc_prefix, keywords, title, date_from, date_to, language)):
            raise ValueError("give a query, a document number, or at least one filter")
    lap("encode_query")

    # 2. filter first, in SQL
    allowed = filter_patents(index, cpc_prefix, keywords, title, date_from, date_to, language, include_unknown,
                             restrict_docs)
    if source_id is not None:  # a patent is not its own prior art
        allowed = np.ones(index.table_size, bool) if allowed is None else allowed
        allowed[source_id] = False
    info["patents_passing_filters"] = len(index.patent_ids) if allowed is None else int(allowed.sum())
    lap("filter")

    # 3. semantic ranking over the surviving passages
    semantic, best_row, similarity = [], {}, {}
    if query_vector is not None and mode != "keyword" and len(index.vectors):
        keep = None if allowed is None else allowed[index.vector_patent]
        if passage_types:
            kinds = np.isin(index.vector_kind, [KINDS.index(kind) for kind in passage_types])
            keep = kinds if keep is None else keep & kinds
        info["vectors_kept"] = len(index.vectors) if keep is None else int(keep.sum())
        patents, rows, scores = rank_patents(index.vectors, index.vector_patent, query_vector, keep, strategy)
        semantic = patents.tolist()
        best_row, similarity = dict(zip(semantic, rows.tolist())), dict(zip(semantic, scores.tolist()))
    lap("score")

    # 4. keyword ranking over English title and abstract
    keyword = []
    if mode != "semantic" or query_vector is None:
        keyword = [p for p in keyword_rank(index.con, keyword_text) if allowed is None or allowed[p]]
        if passage_types and semantic:
            keyword = [p for p in keyword if p in best_row]  # evidence must be of a requested type
    lap("keyword")

    # 5. reciprocal rank fusion
    fused = {}
    for ranking in (semantic, keyword):
        for rank, patent_id in enumerate(ranking, 1):
            fused[patent_id] = fused.get(patent_id, 0.0) + 1.0 / (RRF_K + rank)
    if fused:
        ranked = sorted(fused, key=fused.get, reverse=True)[:top_k]
    elif query or doc_number:
        ranked = []
    else:  # filters only and no keywords: newest first
        passing = np.flatnonzero(allowed).tolist() if allowed is not None else []
        ranked = [row[0] for row in index.con.execute(
            f"SELECT id FROM patents WHERE id IN ({','.join(map(str, passing))}) "
            "ORDER BY filing_week DESC, doc_number LIMIT ?", (top_k,))]
    keyword_position = {patent_id: rank for rank, patent_id in enumerate(keyword, 1)}
    lap("fuse")

    # 6. fetch what is shown
    results = []
    for patent_id in ranked:
        patent = index.con.execute("SELECT * FROM patents WHERE id = ?", (patent_id,)).fetchone()
        if patent_id in best_row:
            passage = index.con.execute("SELECT * FROM passages WHERE id = ?",
                                        (int(index.vector_passage[best_row[patent_id]]),)).fetchone()
        else:  # matched on keywords only: the abstract is the evidence, when there is one
            passage = index.con.execute("SELECT * FROM passages WHERE patent_id = ? AND kind = 'abstract'",
                                        (patent_id,)).fetchone()
        results.append({
            "doc_number": patent["doc_number"], "title": patent["title"], "title_en": patent["title_en"],
            "classification": patent["classification"], "language": patent["language"],
            "filing_week": patent["filing_week"], "collection": patent["collection"],
            "missing_fields": [name for name in patent["missing_fields"].split(",") if name],
            "score": fused.get(patent_id), "similarity": similarity.get(patent_id),
            "keyword_rank": keyword_position.get(patent_id),
            "passage": None if passage is None else {
                "kind": passage["kind"], "number": passage["ord"], "number_inferred": bool(passage["number_inferred"]),
                "parent_claim": passage["parent_claim"], "text": passage["text"], "text_en": passage["text"]},
        })
    lap("fetch")

    # 7. English for anything that is not English, on demand and cached
    if translate_results:
        for result in results:
            if result["passage"] and result["language"] not in (None, "en"):
                result["passage"]["text_en"] = translate.translate(result["passage"]["text"], result["language"], index.con)
    lap("translate")
    info["ms"] = {name: round(value, 3) for name, value in ms.items()}
    info["ms"]["total"] = round(sum(ms.values()), 3)
    return results
