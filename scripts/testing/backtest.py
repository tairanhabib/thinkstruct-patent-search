"""Independent test pass, Stage 4: backtest on questions whose answer is already known from the data.

    python scripts/testing/backtest.py english  --index INDEX_WITH_640_ENGLISH --out scripts/testing/results/backtest_english.json
    python scripts/testing/backtest.py multilingual --index INDEX_WITH_840 --out scripts/testing/results/backtest_multilingual.json

Point --index at a COPY: Test B changes the full text table inside a transaction and rolls it back.

Tests (200 sampled items each, seed 42; recall at 1, recall at 10, mean reciprocal rank, 95% bootstrap interval
from 1,000 resamples):
  A  claim 1 -> own patent      candidates: everything except that patent's own claims
  B  abstract -> own claims     candidates: claims only (so no abstract, own or other)
  C  title -> patent            correct: any patent with exactly that title
  D  dependent claim -> parent  the query claim itself is removed; correct: the parent claim
Every test runs in keyword, semantic and hybrid mode. Nothing here edits src/: ranking uses the project's own
`rank_patents`, `keyword_rank` and `search`, and the fusion below is checked against `search()` query by query.
"""
import argparse
import json
import os
import random
import re
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from src import embed  # noqa: E402
from src.search import KINDS, RRF_K, Index, keyword_rank, rank_patents, search  # noqa: E402

SEED, SAMPLE, RESAMPLES = 42, 200, 1000
MODES = ("keyword", "semantic", "hybrid")
CLAIM = KINDS.index("claim")
EVERYTHING = 100000


# --- metrics --------------------------------------------------------------------------------------

def interval(values):
    values = np.asarray(values, float)
    rng = np.random.default_rng(SEED)
    means = values[rng.integers(0, len(values), (RESAMPLES, len(values)))].mean(axis=1)
    return [round(float(np.percentile(means, 2.5)), 4), round(float(np.percentile(means, 97.5)), 4)]


def metrics(ranks):
    """`ranks`: 1-based rank of the right answer per query, 0 when it was not returned."""
    ranks = np.asarray(ranks, float)
    found = ranks > 0
    out = {"n": int(len(ranks))}
    for name, values in (("recall@1", ranks == 1), ("recall@10", found & (ranks <= 10)),
                         ("mrr", np.where(found, 1.0 / np.maximum(ranks, 1), 0.0))):
        out[name] = round(float(np.mean(values)), 4)
        out[name + "_ci"] = interval(values)
    return out


def gap(ranks, baseline):
    """Paired difference (this minus baseline), with a paired bootstrap interval."""
    ranks, baseline = np.asarray(ranks, float), np.asarray(baseline, float)
    out = {}
    for name, f in (("recall@1", lambda r: (r == 1).astype(float)), ("recall@10", lambda r: ((r > 0) & (r <= 10)).astype(float)),
                    ("mrr", lambda r: np.where(r > 0, 1.0 / np.maximum(r, 1), 0.0))):
        d = f(ranks) - f(baseline)
        out[name] = round(float(d.mean()), 4)
        out[name + "_ci"] = interval(d)
    return out


def position(ranked, target):
    return ranked.index(target) + 1 if target in ranked else 0


def fuse(semantic, keyword):
    """Reciprocal rank fusion exactly as src/search.py does it (semantic list first, then keyword)."""
    fused = {}
    for ranking in (semantic, keyword):
        for rank, patent_id in enumerate(ranking, 1):
            fused[patent_id] = fused.get(patent_id, 0.0) + 1.0 / (RRF_K + rank)
    return sorted(fused, key=fused.get, reverse=True)


def rank_with_mask(index, text, keep, mode, allowed=None, keyword_within_semantic=False):
    """Patent ids, best first, for a custom candidate mask over vector rows. English-only index."""
    semantic, rows = [], []
    if mode != "keyword":
        patents, best, _ = rank_patents(index.vectors, index.vector_patent, embed.encode([text], "query: ")[0], keep, "filter_after")
        semantic, rows = patents.tolist(), best.tolist()
    keyword = []
    if mode != "semantic":
        keyword = [p for p in keyword_rank(index.con, text) if allowed is None or allowed[p]]
        if keyword_within_semantic and semantic:
            inside = set(semantic)
            keyword = [p for p in keyword if p in inside]
    return fuse(semantic, keyword), dict(zip(semantic, rows))


# --- samples ----------------------------------------------------------------------------------------

def first_claims(index, collection="small"):
    """{doc_number: (patent id, passage id, text, inferred, title)} for the lowest numbered claim of each patent."""
    out = {}
    for row in index.con.execute(
            "SELECT p.doc_number, p.id, s.id, s.text, s.number_inferred, p.title, s.ord FROM passages s JOIN patents p ON p.id = s.patent_id "
            "WHERE s.kind = 'claim' AND p.collection = ? ORDER BY p.id, s.ord DESC", (collection,)):
        out[row[0]] = tuple(row[1:6])  # the last one seen per patent has the lowest ord
    return out


def sample(items, n=SAMPLE):
    items = sorted(items)
    return random.Random(SEED).sample(items, min(n, len(items)))


def shingles(text, n=5):
    words = re.findall(r"\w+", text.lower())
    return {tuple(words[i:i + n]) for i in range(max(0, len(words) - n + 1))}


# --- Test A -----------------------------------------------------------------------------------------

def test_a(index, docs, mode, exclude="own_claims", variant="raw", own_subclass=False):
    """Ranks of the query patent. `exclude`: own_claims (the plan), all_claims (what eval_results.md does), none
    (a deliberate leak, as a control). `variant`: raw claim text, or 'similar' = with the title in front when the
    claim lost its opening words, which is what `cli.py similar --claim 1` sends."""
    claims = first_claims(index)
    subclass = dict(index.con.execute("SELECT patent_id, subclass FROM classifications"))
    ranks = []
    for doc in docs:
        patent_id, passage_id, text, inferred, title = claims[doc]
        if variant == "similar" and inferred and title:
            text = f"{title}: {text}"
        keep = None
        if exclude == "own_claims":
            keep = ~((index.vector_patent == patent_id) & (index.vector_kind == CLAIM))
        elif exclude == "all_claims":
            keep = index.vector_kind != CLAIM
        if keep is not None:
            assert not keep[index.vector_passage == passage_id].any(), "leak: the query claim is among the candidates"
        allowed = None
        if own_subclass:
            allowed = np.zeros(index.table_size, bool)
            allowed[[p for p, s in subclass.items() if s == subclass.get(patent_id)]] = True
            keep = allowed[index.vector_patent] if keep is None else keep & allowed[index.vector_patent]
        ranked, _ = rank_with_mask(index, text, keep, mode, allowed, keyword_within_semantic=(exclude == "all_claims"))
        ranks.append(position(ranked, patent_id))
    return ranks


def check_harness_against_search(index, docs):
    """The 'all_claims' variant is expressible through search(). Both must give the same ranking for every query."""
    claims, wrong = first_claims(index), 0
    for doc in docs:
        text = claims[doc][2]
        for mode in ("semantic", "hybrid"):
            mine, _ = rank_with_mask(index, text, index.vector_kind != CLAIM, mode, keyword_within_semantic=True)
            theirs = [index.patent_ids[r["doc_number"]] for r in search(
                text, mode=mode, passage_types=["abstract", "description"], top_k=EVERYTHING, translate_results=False, index=index)]
            wrong += mine != theirs
    return wrong


def restatement(index, docs):
    """How much of the query (claim 1) is repeated word for word in the same patent's abstract or description:
    the largest share of the claim's five-word sequences found in one such passage."""
    claims, out = first_claims(index), []
    for doc in docs:
        patent_id, _, text, _, _ = claims[doc]
        query = shingles(text)
        best = 0.0
        for (other,) in index.con.execute("SELECT text FROM passages WHERE patent_id = ? AND kind != 'claim'", (patent_id,)):
            if query:
                best = max(best, len(query & shingles(other)) / len(query))
        out.append(best)
    return np.array(out)


# --- Test B -----------------------------------------------------------------------------------------

def test_b(index, docs, mode, blank_own_abstract):
    """Query: the abstract. Candidates: claims. With `blank_own_abstract` the patent's abstract is also taken out of
    the full text table for the duration of the query (rolled back), because keyword search reads abstracts."""
    ranks = []
    for doc in docs:
        patent_id = index.patent_ids[doc]
        abstract = index.con.execute("SELECT abstract FROM patents WHERE id = ?", (patent_id,)).fetchone()[0]
        if blank_own_abstract:
            index.con.execute("UPDATE patents_fts SET abstract_en = '' WHERE rowid = ?", (patent_id,))
        try:
            results = search(abstract, mode=mode, passage_types=None if mode == "keyword" else ["claim"], top_k=EVERYTHING,
                             translate_results=False, index=index)
        finally:
            index.con.rollback()
        if mode != "keyword":
            assert all(r["passage"]["kind"] == "claim" for r in results if r["similarity"] is not None)
        ranks.append(position([r["doc_number"] for r in results], doc))
    return ranks


# --- Test C -----------------------------------------------------------------------------------------

def test_c(index, docs, mode, lower=False):
    ranks = []
    for doc in docs:
        title = index.con.execute("SELECT title FROM patents WHERE doc_number = ?", (doc,)).fetchone()[0]
        results = search(title.lower() if lower else title, mode=mode, top_k=EVERYTHING, translate_results=False, index=index)
        same = [i for i, r in enumerate(results, 1) if (r["title"] or "").strip().lower() == title.strip().lower()]
        ranks.append(same[0] if same else 0)
    return ranks


# --- Test D -----------------------------------------------------------------------------------------

def dependent_claims(index):
    embedded = set(index.vector_passage.tolist())
    out = []
    for row in index.con.execute(
            "SELECT s.id, s.patent_id, s.text, t.id FROM passages s JOIN patents p ON p.id = s.patent_id "
            "JOIN passages t ON t.patent_id = s.patent_id AND t.kind = 'claim' AND t.ord = s.parent_claim "
            "WHERE s.kind = 'claim' AND s.parent_claim IS NOT NULL AND p.collection = 'small' AND t.id != s.id"):
        if row[0] in embedded and row[3] in embedded:
            out.append(tuple(row))
    return out


def ranked_passages(passages, scores):
    order = np.argsort(-scores, kind="stable")
    ordered = passages[order]
    _, first = np.unique(ordered, return_index=True)
    return ordered[np.sort(first)].tolist()


def test_d(index, items):
    """Returns per-query ranks: passage level (parent among all claims; parent among the same patent's claims),
    and patent level per mode (the patent that holds the parent), plus whether the evidence shown is the parent."""
    out = {"passage_all": [], "passage_same_patent": [], "siblings": [],
           **{f"patent_{mode}": [] for mode in MODES}, "evidence_is_parent": []}
    for passage_id, patent_id, text, parent_id in items:
        keep = (index.vector_kind == CLAIM) & (index.vector_passage != passage_id)
        assert not keep[index.vector_passage == passage_id].any(), "leak: the query claim is among the candidates"
        rows = np.flatnonzero(keep)
        scores = index.vectors[rows] @ embed.encode([text], "query: ")[0]
        out["passage_all"].append(position(ranked_passages(index.vector_passage[rows], scores), parent_id))
        same = index.vector_patent[rows] == patent_id
        siblings = ranked_passages(index.vector_passage[rows][same], scores[same])
        out["passage_same_patent"].append(position(siblings, parent_id))
        out["siblings"].append(len(siblings))
        for mode in MODES:
            ranked, best = rank_with_mask(index, text, keep, mode, keyword_within_semantic=True)
            out[f"patent_{mode}"].append(position(ranked, patent_id))
            if mode == "semantic":
                out["evidence_is_parent"].append(int(index.vector_passage[best[patent_id]] == parent_id))
    return out


# --- runs -------------------------------------------------------------------------------------------

def best_single(table):
    return max(("keyword", "semantic"), key=lambda mode: table[mode]["mrr"])


def english(index):
    assert not index.languages, "the English backtest needs an index with only the 640 English patents"
    report = {"index": {"patents": len(index.patent_ids), "vectors": int(len(index.vectors))}, "seed": SEED}
    claims = first_claims(index)
    eligible = [doc for doc, c in claims.items() if len(c[2]) >= 40]
    docs_a = sample(eligible)
    empty_description = {row[0] for row in index.con.execute(
        "SELECT doc_number FROM patents p WHERE NOT EXISTS (SELECT 1 FROM passages s WHERE s.patent_id = p.id AND s.kind = 'description')")}
    report["test_a_sample"] = {"eligible": len(eligible), "sampled": len(docs_a),
                               "first_claim_inferred": sum(claims[d][3] for d in docs_a),
                               "no_description": sum(d in empty_description for d in docs_a)}
    print("harness check against search() ...", flush=True)
    report["harness_vs_search_mismatches"] = check_harness_against_search(index, docs_a)
    print("  mismatches:", report["harness_vs_search_mismatches"], flush=True)

    a = {}
    for name, options in (("A: own claims removed (the plan)", {}),
                          ("A: all claims removed (as eval_results.md)", {"exclude": "all_claims"}),
                          ("A control: nothing removed (leak on purpose)", {"exclude": "none"}),
                          ("A: own claims removed, title put in front (as `similar --claim 1`)", {"variant": "similar"}),
                          ("A: own claims removed, filter on own subclass", {"own_subclass": True})):
        ranks = {mode: test_a(index, docs_a, mode, **options) for mode in MODES}
        a[name] = {mode: metrics(ranks[mode]) for mode in MODES}
        a[name]["_ranks"] = ranks
        print(name, {mode: (a[name][mode]["recall@1"], a[name][mode]["recall@10"], a[name][mode]["mrr"]) for mode in MODES}, flush=True)
    plain, filtered = a["A: own claims removed (the plan)"]["_ranks"], a["A: own claims removed, filter on own subclass"]["_ranks"]
    report["test_a_filter_effect"] = {mode: {"worse_with_filter": int(sum((f == 0 or f > p) and p > 0 for p, f in zip(plain[mode], filtered[mode]))),
                                             "better_with_filter": int(sum(0 < f < p or (p == 0 and f > 0) for p, f in zip(plain[mode], filtered[mode]))),
                                             "gap": gap(filtered[mode], plain[mode])} for mode in MODES}
    restated = restatement(index, docs_a)
    ranks = np.array(plain["semantic"])
    report["test_a_restatement"] = {
        "share_half_or_more_verbatim": round(float((restated >= 0.5).mean()), 3),
        "share_80pct_or_more_verbatim": round(float((restated >= 0.8).mean()), 3),
        "median_verbatim_share": round(float(np.median(restated)), 3),
        "semantic_restated(>=0.5)": metrics(ranks[restated >= 0.5]) if (restated >= 0.5).sum() else None,
        "semantic_not_restated(<0.5)": metrics(ranks[restated < 0.5]) if (restated < 0.5).sum() else None,
        "hybrid_restated(>=0.5)": metrics(np.array(plain["hybrid"])[restated >= 0.5]),
        "hybrid_not_restated(<0.5)": metrics(np.array(plain["hybrid"])[restated < 0.5]),
        "semantic_no_description": metrics(ranks[[d in empty_description for d in docs_a]]),
        "semantic_has_description": metrics(ranks[[d not in empty_description for d in docs_a]]),
    }
    report["A"] = a

    docs_b = sample([row[0] for row in index.con.execute(
        "SELECT doc_number FROM patents p WHERE abstract IS NOT NULL AND EXISTS (SELECT 1 FROM passages s WHERE s.patent_id = p.id "
        "AND s.kind = 'claim' AND length(s.text) >= 40)")])
    b = {}
    for name, blank in (("B: own abstract removed from candidates and from the keyword index", True),
                        ("B as the system runs it: own abstract still in the keyword index (leaks)", False)):
        ranks = {mode: test_b(index, docs_b, mode, blank) for mode in MODES}
        b[name] = {mode: metrics(ranks[mode]) for mode in MODES}
        b[name]["_ranks"] = ranks
        print(name, {mode: (b[name][mode]["recall@1"], b[name][mode]["recall@10"], b[name][mode]["mrr"]) for mode in MODES}, flush=True)
    report["B"] = b

    docs_c = sample(list(index.patent_ids))
    c = {}
    for name, lower in (("C: title as stored", False), ("C: title in lower case", True)):
        ranks = {mode: test_c(index, docs_c, mode, lower) for mode in MODES}
        c[name] = {mode: metrics(ranks[mode]) for mode in MODES}
        c[name]["_ranks"] = ranks
        print(name, {mode: (c[name][mode]["recall@1"], c[name][mode]["recall@10"], c[name][mode]["mrr"]) for mode in MODES}, flush=True)
    report["C"] = c

    pool = dependent_claims(index)
    items = random.Random(SEED).sample(sorted(pool), min(SAMPLE, len(pool)))
    d = test_d(index, items)
    report["D"] = {
        "eligible": len(pool), "sampled": len(items), "median_sibling_claims": float(np.median(d["siblings"])),
        "D passage level, semantic: parent among all claims of all patents": metrics(d["passage_all"]),
        "D passage level, semantic: parent among the same patent's other claims": metrics(d["passage_same_patent"]),
        "D patent level: the patent holding the parent": {mode: metrics(d[f"patent_{mode}"]) for mode in MODES},
        "evidence shown is the parent claim (semantic)": round(float(np.mean(d["evidence_is_parent"])), 4),
        "_ranks": d,
    }
    print("D", {k: (v["recall@1"], v["recall@10"], v["mrr"]) for k, v in report["D"].items() if isinstance(v, dict) and "mrr" in v}, flush=True)

    # hybrid against the better single mode, paired
    report["hybrid_vs_best_single"] = {}
    for label, table in (("A", a["A: own claims removed (the plan)"]), ("B", b["B: own abstract removed from candidates and from the keyword index"]),
                         ("C", c["C: title as stored"]),
                         ("D", {mode: report["D"]["D patent level: the patent holding the parent"][mode] for mode in MODES}
                          | {"_ranks": {mode: d[f"patent_{mode}"] for mode in MODES}})):
        single = best_single(table)
        report["hybrid_vs_best_single"][label] = {"best_single": single, "gap_hybrid_minus_best_single": gap(table["_ranks"]["hybrid"], table["_ranks"][single])}
    print(json.dumps(report["hybrid_vs_best_single"], indent=1))
    return report


def by_documents(index, docs, mode, variant_all_claims=True, exclude_from=None):
    """Test A through search(): query = first claim of each doc, claims are not candidates."""
    claims = first_claims(index)
    return [claims[doc][2] for doc in docs]


def multilingual(index):
    """Test A on the parallel set: identical English queries against the English, German and Chinese copies."""
    copies = {}
    for doc in index.patent_ids:
        base, _, suffix = doc.rpartition("-")
        if suffix in ("DE", "ZH") and base in index.patent_ids:
            copies.setdefault(suffix.lower(), {})[base] = doc
    originals = sorted(set.intersection(*(set(c) for c in copies.values())))
    copies["en"] = {doc: doc for doc in originals}
    everything = {copy for group in copies.values() for copy in group.values()}
    distractors = [doc for doc in index.patent_ids if doc not in everything]
    claims = first_claims(index)
    queries = [claims[doc][2] for doc in originals]
    report = {"patents": len(originals), "distractors": len(distractors), "seed": SEED, "tables": {}}

    def run(targets, candidates, mode, ignore=None, cross_lingual="translate_query"):
        ranks = []
        for i, (query, target) in enumerate(zip(queries, targets)):
            results = search(query, mode=mode, cross_lingual=cross_lingual, restrict_docs=candidates, top_k=EVERYTHING,
                             passage_types=None if mode == "keyword" else ["abstract", "description"],
                             translate_results=False, index=index)
            assert all(r["passage"] is None or r["passage"]["kind"] != "claim" for r in results), "leak: a claim was a candidate"
            ranked = [r["doc_number"] for r in results if ignore is None or r["doc_number"] != ignore[i]]
            ranks.append(position(ranked, target))
        return ranks

    for setting in ("alone", "mixed"):
        for mode in MODES:
            base = None
            for language in ("en", "de", "zh"):
                group = list(copies[language].values())
                ranks = run([copies[language][doc] for doc in originals], group + (distractors if setting == "mixed" else []), mode)
                entry = metrics(ranks)
                if base is None:
                    base = ranks
                else:
                    entry["gap_to_english"] = gap(ranks, base)
                report["tables"][f"{setting}|{mode}|{language}"] = entry
                print(setting, mode, language, entry["recall@1"], entry["recall@10"], entry["mrr"], entry.get("gap_to_english", {}).get("mrr"), flush=True)
    # does adding a foreign language hurt English search? (the other half of "comparable")
    english_pool = originals + distractors
    for mode in ("semantic", "hybrid"):
        base = run(originals, english_pool, mode)
        report["tables"][f"english_target|{mode}|none added"] = metrics(base)
        for language in ("de", "zh"):
            ranks = run(originals, english_pool + list(copies[language].values()), mode, ignore=[copies[language][d] for d in originals])
            entry = metrics(ranks)
            entry["change"] = gap(ranks, base)
            report["tables"][f"english_target|{mode}|{language} added"] = entry
            print("english target", mode, language, entry["mrr"], entry["change"]["mrr"], flush=True)
    # the old default, as a control that the test can still see the failure the README describes
    for language in ("de", "zh"):
        ranks = run([copies[language][doc] for doc in originals], list(copies[language].values()) + distractors, "semantic", cross_lingual="shared")
        report["tables"][f"mixed|semantic shared space|{language}"] = metrics(ranks)
    return report


def strip(report):
    if isinstance(report, dict):
        return {k: strip(v) for k, v in report.items()}
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("what", choices=("english", "multilingual"))
    parser.add_argument("--index", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    index = Index(args.index)
    result = english(index) if args.what == "english" else multilingual(index)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=1, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o))
    print("wrote", args.out)
