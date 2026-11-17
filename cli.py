"""Command line entry point. Run `python cli.py --help`."""
import argparse
import json

from src import db, ingest


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


def main():
    parser = argparse.ArgumentParser(description="Patent passage search")
    parser.add_argument("--index", help="index directory (default: ./index, or $PATENT_INDEX)")
    commands = parser.add_subparsers(dest="command", required=True)

    p = commands.add_parser("ingest", help="load a directory of patent JSON files and embed them")
    p.add_argument("data_dir")
    p.add_argument("--collection", help="label stored with each patent (default: directory name)")
    p.set_defaults(run=cmd_ingest)

    p = commands.add_parser("stats", help="what is in the index")
    p.set_defaults(run=cmd_stats)

    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
