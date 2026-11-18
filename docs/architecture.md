# Architecture

One picture of the whole project. Solid arrows are data moving. Dotted arrows are "measures" or "is a model of". Inside the search box, dotted arrows are steps taken only with `--mode keyword` or `--mode hybrid`: the default search is semantic.

```mermaid
flowchart TD
    subgraph IN["Input data (JSON files, never committed)"]
        small["data/small<br/>640 English patents"]
        parallel["data/parallel<br/>100 patents in German and Chinese<br/>(machine translated copies)"]
        foreign["data/foreign<br/>real non-English sample<br/>(not received yet)"]
    end

    mk["scripts/make_parallel_set.py<br/>opus-mt English to German, Chinese"]
    small --> mk --> parallel

    subgraph ING["Ingest: python cli.py ingest DIR"]
        norm["normalize fields<br/>record what is missing, drop nothing"]
        claims["split and number claims<br/>drop cancelled claims"]
        lang["detect language"]
        tr1["translate title and abstract<br/>to English (foreign patents only)"]
        emb["embed every passage<br/>in its original language<br/>multilingual-e5-small"]
        norm --> claims --> lang --> tr1 --> emb
    end
    small --> norm
    parallel --> norm
    foreign -.-> norm

    subgraph IDX["Index directory: index/"]
        db[("patents.db (SQLite)<br/>patents, passages, classifications<br/>two full text indexes on English title and abstract<br/>(stemmed for ranking, whole words for the keyword filter)<br/>translation cache")]
        vec[("embeddings.npy<br/>one normalized vector per passage window")]
    end
    tr1 --> db
    emb --> vec

    subgraph SRCH["Search: python cli.py search / similar / show"]
        q["query text in any language<br/>or document number and claim<br/>or filters only"]
        filt["1. filters in SQL<br/>classification prefix, keywords, title,<br/>dates, language, passage type"]
        tq["2. translate the query<br/>into each language that survived<br/>(short, cached)"]
        sem["3. score each passage against the query<br/>in its own language, on one scale<br/>best passage per patent"]
        kw["4. keyword ranking (BM25)<br/>English title and abstract<br/>only with --mode keyword or hybrid"]
        rrf["5. reciprocal rank fusion<br/>only with --mode hybrid,<br/>keyword list weighted 0.02"]
        show["6. show in English<br/>translate displayed passages on demand, cache"]
        q --> filt --> tq --> sem --> show
        sem -.-> rrf -.-> show
        tq -.-> kw -.-> rrf
    end
    db --> filt
    db --> kw
    vec --> sem
    show <--> db
    tq <--> db

    subgraph MEAS["Measurement"]
        bench["scripts/benchmark.py<br/>benchmarks.md"]
        evalm["scripts/evaluate_multilingual.py<br/>scripts/compare_models.py<br/>eval_results.md"]
        tests["tests/ and scripts/testing/<br/>missing fields, filters, claims,<br/>and the independent test pass"]
    end
    bench -.-> SRCH
    evalm -.-> SRCH
    tests -.-> ING
    tests -.-> SRCH

    subgraph P2["Part 2: the same design at 10 million patents"]
        design["docs/scale_design.md"]
        poc["poc/ and docker-compose.yml<br/>PostgreSQL with pgvector<br/>hybrid query as one SQL statement"]
    end
    IDX -.-> poc
    design -.-> poc
```

## Where each piece lives

| Piece | File |
| --- | --- |
| Schema | `src/db.py` |
| Field normalization, claim parsing, missing field handling | `src/ingest.py` |
| Embedding model, windows, vector files | `src/embed.py` |
| Language detection, translation, cache | `src/translate.py` |
| Filters, query translation, semantic ranking (default), optional keyword ranking and fusion | `src/search.py` |
| Command line and display | `cli.py` |
| Timing | `scripts/benchmark.py` |
| Synthetic German and Chinese set | `scripts/make_parallel_set.py` |
| English against foreign comparison | `scripts/evaluate_multilingual.py`, `scripts/compare_models.py` |
| Scale design and its proof of concept | `docs/scale_design.md`, `poc/` |
