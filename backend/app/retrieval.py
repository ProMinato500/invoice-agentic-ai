import json

from rapidfuzz import fuzz
from sqlalchemy import select, text

from backend.app.ai import embed
from backend.app.core.config import settings
from backend.app.models import Line, SearchRecord
from backend.app.normalization import identifier


def rrf(rankings, k=60):
    scores = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, 1):
            scores[item] = scores.get(item, 0) + 1 / (k + rank)
    return sorted(scores, key=lambda x: scores[x], reverse=True)


def expand_description(value):
    # Deterministic dual-sided aliases are retrieval aids, never authoritative attributes.
    import re

    aliases = [
        (r"\bpcs?\b", "pieces"),
        (r"\bea\b", "each"),
        (r"\bsmth\b", "smooth"),
        (r"\bcd\b", "conditioner"),
        (r"\bltr?\b", "litre"),
    ]
    text_value = value.lower()
    for pattern, replacement in aliases:
        text_value = re.sub(pattern, replacement, text_value)
    return text_value


def index_po(db, document_id, org, emit):
    lines = list(
        db.scalars(select(Line).where(Line.document_id == document_id, Line.organization_id == org))
    )
    records = {
        r.line_id: r
        for r in db.scalars(
            select(SearchRecord).where(
                SearchRecord.document_id == document_id,
                SearchRecord.organization_id == org,
            )
        )
    }
    for line in lines:
        if line.id not in records:
            record = SearchRecord(
                organization_id=org,
                line_id=line.id,
                document_id=document_id,
                search_text=line.description
                + " "
                + line.sku
                + " "
                + json.dumps(line.attributes)
                + " "
                + expand_description(line.description),
                aliases=[
                    {
                        "text": expand_description(line.description),
                        "method": "DETERMINISTIC_QUERY_NORMALIZATION",
                        "authoritative": False,
                    }
                ]
                if settings.enable_dual_augmentation
                else [],
            )
            db.add(record)
            records[line.id] = record
    for line in lines:
        record = records[line.id]
        current_text = (
            line.description
            + " "
            + line.sku
            + " "
            + json.dumps(line.attributes)
            + " "
            + expand_description(line.description)
        )
        if record.search_text != current_text:
            record.search_text = current_text
            record.aliases = (
                [
                    {
                        "text": expand_description(line.description),
                        "method": "DETERMINISTIC_QUERY_NORMALIZATION",
                        "authoritative": False,
                    }
                ]
                if settings.enable_dual_augmentation
                else []
            )
            record.embedding = None
            record.embedding_model = None
        if record.embedding_model and record.embedding_model != settings.openai_embedding_model:
            record.embedding = None
            record.embedding_model = None
    db.commit()
    if settings.enable_embeddings:
        missing = [r for r in records.values() if r.embedding is None]
        for offset in range(0, len(missing), 64):
            batch = missing[offset : offset + 64]
            vectors = embed([r.search_text for r in batch])
            for record, vector in zip(batch, vectors):
                record.embedding = vector
                record.embedding_model = settings.openai_embedding_model
            db.commit()
            emit(
                "COMPLETED",
                "Embedded verified PO descriptions",
                {"count": len(batch), "model": settings.openai_embedding_model},
            )
    if db.bind.dialect.name == "sqlite":
        db.execute(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS product_fts USING fts5(line_id UNINDEXED, document_id UNINDEXED, organization_id UNINDEXED, search_text)"
            )
        )
        db.execute(
            text("DELETE FROM product_fts WHERE document_id=:doc AND organization_id=:org"),
            {"doc": document_id, "org": org},
        )
        for record in records.values():
            db.execute(
                text(
                    "INSERT INTO product_fts (line_id,document_id,organization_id,search_text) VALUES (:line,:doc,:org,:content)"
                ),
                {
                    "line": record.line_id,
                    "doc": document_id,
                    "org": org,
                    "content": record.search_text,
                },
            )
        db.commit()
    if db.bind.dialect.name == "postgresql":
        # Native full-text is ts_rank, not BM25. Embeddings remain provenance-bearing JSON
        # and are cast to pgvector in this safely scoped exact-search query.
        db.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_product_lexical ON product_search_records USING gin (to_tsvector('simple',search_text))"
            )
        )
        db.commit()


def candidates(db, invoice, po_lines, org, po_id, k=5):
    exact = [p for p in po_lines if invoice.sku and identifier(invoice.sku) == identifier(p.sku)]
    scores = {
        p.id: fuzz.WRatio(invoice.description.lower(), p.description.lower()) / 100
        for p in po_lines
    }
    fuzzy = sorted(po_lines, key=lambda p: scores[p.id], reverse=True)
    rankings = [[p.id for p in fuzzy[: max(k, 20)]]]
    if db.bind.dialect.name == "sqlite":
        import re

        terms = re.findall(r"[a-zA-Z0-9]+", expand_description(invoice.description))[:30]
        query = " OR ".join(chr(34) + term + chr(34) for term in terms)
        if query:
            lexical = (
                db.execute(
                    text(
                        "SELECT line_id FROM product_fts WHERE product_fts MATCH :q AND organization_id=:org AND document_id=:doc ORDER BY rank LIMIT :limit"
                    ),
                    {"q": query, "org": org, "doc": po_id, "limit": max(k, 20)},
                )
                .scalars()
                .all()
            )
            rankings.append(lexical)
        if settings.enable_embeddings:
            import numpy as np

            vector = np.asarray(embed([invoice.description])[0])
            ranked = []
            for record in db.scalars(
                select(SearchRecord).where(
                    SearchRecord.organization_id == org,
                    SearchRecord.document_id == po_id,
                )
            ):
                if record.embedding:
                    candidate = np.asarray(record.embedding)
                    if candidate.shape == vector.shape:
                        denom = np.linalg.norm(vector) * np.linalg.norm(candidate)
                        ranked.append(
                            (
                                float(np.dot(vector, candidate) / denom) if denom else 0,
                                record.line_id,
                            )
                        )
            rankings.append([rid for score, rid in sorted(ranked, reverse=True)[: max(k, 20)]])
    if db.bind.dialect.name == "postgresql":
        lexical = (
            db.execute(
                text(
                    "SELECT line_id FROM product_search_records WHERE organization_id=:org AND document_id=:doc ORDER BY ts_rank(to_tsvector('simple',search_text),plainto_tsquery('simple',:query)) DESC LIMIT :limit"
                ),
                {
                    "org": org,
                    "doc": po_id,
                    "query": invoice.description,
                    "limit": max(k, 20),
                },
            )
            .scalars()
            .all()
        )
        rankings.append(lexical)
        if settings.enable_embeddings:
            vector = embed([invoice.description])[0]
            dense = (
                db.execute(
                    text(
                        "SELECT line_id FROM product_search_records WHERE organization_id=:org AND document_id=:doc AND embedding IS NOT NULL ORDER BY (embedding::text)::vector <=> CAST(:vec AS vector) LIMIT :limit"
                    ),
                    {
                        "org": org,
                        "doc": po_id,
                        "vec": json.dumps(vector),
                        "limit": max(k, 20),
                    },
                )
                .scalars()
                .all()
            )
            rankings.append(dense)
    selected = [p.id for p in exact] + rrf(rankings)
    unique = list(dict.fromkeys(selected))[:k]
    lookup = {p.id: p for p in po_lines}
    return [
        {
            "po_line_id": pid,
            "description": lookup[pid].description,
            "sku": lookup[pid].sku,
            "score": scores[pid],
            "exact_identifier": lookup[pid] in exact,
            "attributes": lookup[pid].attributes,
            "evidence": lookup[pid].evidence,
        }
        for pid in unique
    ]
