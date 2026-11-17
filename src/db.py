"""SQLite schema and connection. The index is one directory: patents.db plus the vector files."""
import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS patents (
    id INTEGER PRIMARY KEY,
    doc_number TEXT UNIQUE NOT NULL,
    collection TEXT,               -- which ingest directory it came from
    title TEXT, title_en TEXT,     -- NULL means missing; *_en is the English version used for keywords
    abstract TEXT, abstract_en TEXT,
    classification TEXT,           -- raw codes joined with ', ' for display
    bibtex TEXT,
    filename TEXT,
    filing_week TEXT,              -- ISO date taken from the file name
    language TEXT,                 -- detected; NULL means could not tell
    missing_fields TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS classifications (
    patent_id INTEGER NOT NULL,
    code TEXT NOT NULL,            -- upper case, letters and digits only, for prefix lookups
    subclass TEXT NOT NULL         -- first four characters
);
CREATE INDEX IF NOT EXISTS idx_classifications_code ON classifications(code);
CREATE INDEX IF NOT EXISTS idx_classifications_patent ON classifications(patent_id);
CREATE TABLE IF NOT EXISTS passages (
    id INTEGER PRIMARY KEY,
    patent_id INTEGER NOT NULL,
    kind TEXT NOT NULL,            -- claim | abstract | description
    ord INTEGER NOT NULL,          -- claim number, or paragraph position
    number_inferred INTEGER NOT NULL DEFAULT 0,  -- claim number was not in the source
    parent_claim INTEGER,          -- for dependent claims, where the text says so
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_passages_patent ON passages(patent_id);
CREATE VIRTUAL TABLE IF NOT EXISTS patents_fts USING fts5(title_en, abstract_en, tokenize='porter unicode61');
-- cache; `text_en` holds the translation (into English, or into the model's target for translated queries)
CREATE TABLE IF NOT EXISTS translations (key TEXT PRIMARY KEY, model TEXT NOT NULL, text_en TEXT NOT NULL);
"""


def index_dir(path=None):
    return path or os.environ.get("PATENT_INDEX", "index")


def connect(path=None):
    path = index_dir(path)
    os.makedirs(path, exist_ok=True)
    con = sqlite3.connect(os.path.join(path, "patents.db"))
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con
