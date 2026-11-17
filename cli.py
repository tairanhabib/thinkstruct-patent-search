"""Command line entry point. Run `python cli.py --help`."""
import argparse
import json
import textwrap

import time

from src import db, embed, ingest, search as engine, translate

UNKNOWN = "Unknown"


def shown(value):
    return value if value not in (None, "", []) else UNKNOWN


def wrap(text, indent="      ", limit=None):
    if limit and len(text) > limit:
        text = text[:limit].rstrip() + " ..."
    return textwrap.fill(text, width=110, initial_indent=indent, subsequent_indent=indent)


def claim_label(number, inferred, parent=None):
    label = f"claim {number}"
    if inferred:
        label += " (number inferred, opening words missing in the source)"
    if parent:
        label += f" (depends on claim {parent})"
    return label


def format_results(results, show_original=False):
    if not results:
        return "No patent matches."
    lines = []
    for rank, r in enumerate(results, 1):
        foreign = r["language"] not in (None, "en")
        title = shown((r["title_en"] or r["title"]) if foreign else r["title"])
        note = "" if not foreign else f"  [translated from {r['language']}]" if r["title_en"] else f"  [{r['language']}, not translated]"
        lines.append(f"{rank:2d}. {r['doc_number']} | {title}{note}")
        if foreign and show_original and r["title_en"]:
            lines.append(f"      original title: {shown(r['title'])}")
        scores = [f"score {r['score']:.4f}" if r["score"] is not None else "score n/a (filters only)"]
        if r["similarity"] is not None:
            scores.append(f"similarity {r['similarity']:.3f}")
        if r["keyword_rank"]:
            scores.append(f"keyword rank {r['keyword_rank']}")
        lines.append("      " + " | ".join(scores))
        lines.append(f"      classification {shown(r['classification'])} | filing week {shown(r['filing_week'])}"
                     f" | language {shown(r['language'])}"
                     + (f" | missing: {', '.join(r['missing_fields'])}" if r["missing_fields"] else ""))
        passage = r["passage"]
        if passage is None:
            lines.append("      Evidence: no passage, matched on title keywords only")
        else:
            kind = claim_label(passage["number"], passage["number_inferred"], passage["parent_claim"]) \
                if passage["kind"] == "claim" else passage["kind"] + (f" paragraph {passage['number']}" if passage["kind"] == "description" else "")
            lines.append(f"      Evidence, {kind}" + (", machine translated:" if passage["translated"] else ":"))
            lines.append(wrap(passage["text_en"], "        ", 600))
            if passage["translated"] and show_original:
                lines.append("        original:")
                lines.append(wrap(passage["text"], "        ", 600))
        lines.append("")
    return "\n".join(lines)


def format_patent(index, doc_number, show_original=False, full=False):
    """Every field of one patent. Missing fields print as Unknown. Foreign text prints in English."""
    con = index.con
    patent = con.execute("SELECT * FROM patents WHERE doc_number = ?", (doc_number,)).fetchone()
    if patent is None:
        return f"No patent with document number {doc_number!r} in the index."
    language = patent["language"]
    foreign = language not in (None, "en") and translate.available(language)  # foreign, and we can show it in English
    untranslated = language not in (None, "en") and not foreign
    passages = con.execute("SELECT * FROM passages WHERE patent_id = ? ORDER BY kind, ord, id", (patent["id"],)).fetchall()
    claims = [p for p in passages if p["kind"] == "claim"]
    paragraphs = [p for p in passages if p["kind"] == "description"]
    visible = paragraphs if full else paragraphs[:5]
    english = dict(zip((p["id"] for p in claims + visible),
                       translate.translate_many([p["text"] for p in claims + visible], language, con)))

    def both(original, in_english, indent="  "):
        out = [wrap(in_english if foreign else original, indent)]
        if foreign and show_original:
            out.append(wrap("original: " + original, indent + "  "))
        return out

    lines = [
        f"Document number: {patent['doc_number']}",
        f"Title: {shown((patent['title_en'] or patent['title']) if foreign else patent['title'])}",
        *([f"  original: {patent['title']}"] if foreign and show_original and patent["title"] else []),
        f"Language: {shown(language)}" + (" (shown in English, machine translated)" if foreign else "")
        + (" (no English translation available, shown in the original language)" if untranslated else ""),
        f"Classification: {shown(patent['classification'])}",
        f"Filing week: {shown(patent['filing_week'])}",
        f"Source file: {shown(patent['filename'])}",
        f"Collection: {shown(patent['collection'])}",
        f"Citation: {shown(patent['bibtex'])}",
        f"Missing fields: {patent['missing_fields'] or 'none'}",
    ]
    if patent["abstract"]:
        lines += ["Abstract:"] + both(patent["abstract"], patent["abstract_en"] or patent["abstract"])
    else:
        lines.append(f"Abstract: {UNKNOWN}")
    if claims:
        lines.append(f"Claims: {len(claims)}")
        for claim in claims:
            lines.append(f"  {claim_label(claim['ord'], claim['number_inferred'], claim['parent_claim'])}:")
            lines += both(claim["text"], english[claim["id"]], "    ")
    else:
        lines.append(f"Claims: {UNKNOWN}")
    if paragraphs:
        note = "" if full or len(paragraphs) <= 5 else ", showing the first 5 (use --full for all)"
        lines.append(f"Description: {len(paragraphs)} paragraphs{note}")
        for paragraph in visible:
            lines += both(f"[{paragraph['ord']}] " + paragraph["text"], f"[{paragraph['ord']}] " + english[paragraph["id"]])
    else:
        lines.append(f"Description: {UNKNOWN}")
    return "\n".join(lines)


def cmd_ingest(args):
    stats = ingest.ingest_dir(args.data_dir, args.index, args.collection)
    print(json.dumps(stats, indent=2, sort_keys=True))


def cmd_stats(args):
    con = db.connect(args.index)
    for label, sql in (
        ("patents", "SELECT COUNT(*) FROM patents"),
        ("passages", "SELECT COUNT(*) FROM passages"),
        ("by collection and language", "SELECT collection, COALESCE(language, 'Unknown'), COUNT(*) FROM patents GROUP BY 1, 2"),
        ("by passage type", "SELECT kind, COUNT(*) FROM passages GROUP BY 1"),
        ("patents with a missing field", "SELECT missing_fields, COUNT(*) FROM patents WHERE missing_fields != '' GROUP BY 1"),
        ("cached translations", "SELECT COUNT(*) FROM translations"),
    ):
        rows = [tuple(row) for row in con.execute(sql)]
        print(f"{label}: {rows[0][0] if len(rows) == 1 and len(rows[0]) == 1 else rows}")


def cmd_search(args):
    start = time.perf_counter()
    index, info = engine.Index(args.index), {}
    if (getattr(args, "query", None) or getattr(args, "doc", None)) and args.mode != "keyword":
        embed.encode(["warm up"], "query: ")  # load the model outside the timed search
    startup = time.perf_counter() - start
    try:
        results = engine.search(
            query=getattr(args, "query", None), doc_number=getattr(args, "doc", None),
            claim_number=getattr(args, "claim", None), top_k=args.top, cpc_prefix=args.cpc, keywords=args.keywords,
            title=args.title, date_from=args.date_from, date_to=args.date_to, language=args.language,
            passage_types=args.types.split(",") if args.types else None, include_unknown=args.include_unknown,
            mode=args.mode, strategy=args.strategy, cross_lingual=args.cross_lingual, query_lang=args.query_language,
            index=index, info=info)
    except ValueError as error:
        raise SystemExit(f"error: {error}")
    if "query_source" in info:
        print(f"Searching with the {info['query_source']} of {args.doc}.")
    if len(info.get("query_languages", [])) > 1:
        print(f"Query searched in: {', '.join(info['query_languages'])}.")
    print()
    print(format_results(results, args.show_original))
    ms = info["ms"]
    print(f"Startup (load index and model): {startup:.1f} s")
    print(f"{info['patents_passing_filters']} patents passed the filters, {info.get('vectors_kept', 0)} vectors kept. "
          f"{ms['total']:.0f} ms: translate query {ms['translate_query']:.0f}, encode query {ms['encode_query']:.0f}, filter {ms['filter']:.1f}, score {ms['score']:.1f}, "
          f"keyword {ms['keyword']:.1f}, fuse and fetch {ms['fuse'] + ms['fetch']:.1f}, translate {ms['translate']:.0f}")


def cmd_show(args):
    print(format_patent(engine.Index(args.index), args.doc, args.show_original, args.full))


def main():
    parser = argparse.ArgumentParser(description="Patent passage search")
    parser.add_argument("--index", help="index directory (default: ./index, or $PATENT_INDEX)")
    commands = parser.add_subparsers(dest="command", required=True)

    filters = argparse.ArgumentParser(add_help=False)
    filters.add_argument("--cpc", help="classification code prefix, for example B60B or 'B60B 27'")
    filters.add_argument("--keywords", help="words that must all appear in the English title or abstract")
    filters.add_argument("--title", help="text the title must contain, case insensitive")
    filters.add_argument("--from", dest="date_from", metavar="YYYY-MM-DD", help="earliest filing week")
    filters.add_argument("--to", dest="date_to", metavar="YYYY-MM-DD", help="latest filing week")
    filters.add_argument("--language", help="original language, for example en, de, zh")
    filters.add_argument("--types", help="passage types to search, comma separated: claim,abstract,description")
    filters.add_argument("--include-unknown", action="store_true",
                         help="let patents through a filter when the filtered field is missing")
    filters.add_argument("--mode", choices=engine.MODES, default="semantic",
                         help="semantic: best passage by meaning (default). keyword: words in title and abstract. "
                              "hybrid: semantic, with the keyword ranking settling near-ties")
    filters.add_argument("--strategy", choices=("auto", "filter_first", "filter_after"), default="auto",
                         help="auto filters first when the filter is selective, see benchmarks.md")
    filters.add_argument("--cross-lingual", choices=engine.CROSS_LINGUAL, default="translate_query",
                         help="translate_query: search each language with the query in that language, scores put on "
                              "one scale (default). uncalibrated: the same without the common scale. "
                              "shared: one query vector for all languages")
    filters.add_argument("--query-language", help="language of the query when detection gets it wrong, for example de")
    filters.add_argument("--top", type=int, default=10)
    filters.add_argument("--show-original", action="store_true", help="also print foreign text untranslated")

    p = commands.add_parser("ingest", help="load a directory of patent JSON files and embed them")
    p.add_argument("data_dir")
    p.add_argument("--collection", help="label stored with each patent (default: directory name)")
    p.set_defaults(run=cmd_ingest)

    p = commands.add_parser("stats", help="what is in the index")
    p.set_defaults(run=cmd_stats)

    p = commands.add_parser("search", parents=[filters], help="search by text in any language, by filters, or both")
    p.add_argument("query", nargs="?")
    p.set_defaults(run=cmd_search)

    p = commands.add_parser("similar", parents=[filters], help="find patents like one already in the index")
    p.add_argument("--doc", required=True, help="document number")
    p.add_argument("--claim", type=int, help="search with this claim instead of the abstract")
    p.set_defaults(run=cmd_search)

    p = commands.add_parser("show", help="print every field of one patent")
    p.add_argument("--doc", required=True)
    p.add_argument("--show-original", action="store_true")
    p.add_argument("--full", action="store_true", help="print the whole description")
    p.set_defaults(run=cmd_show)

    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
