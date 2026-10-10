# Persisted data

Alembic version 0001 creates documents, document_elements, document_lines, product_search_records, reconciliation_runs, workflow_events, line_matches, discrepancies, review_events, quantity_allocations and evaluation_runs. IDs are UUIDs; records carry organization ownership and creation timestamps. Money/quantities use SQLAlchemy Numeric values and Python Decimal.

Original documents are hash-addressed logically with a unique organization/hash/role constraint; repeated uploads reuse the document record. Evidence stores document/page/top-left PDF rectangle/raw text/method. Canonical corrections store normalized values and audited before/after snapshots. Docling's structured raw JSON is retained separately from canonical fields.

Reports are versioned under `storage/reports/<run UUID>/<result version>/`. Review events retain previous matching state and annotations. LangGraph stores small ID/outcome checkpoint state in `storage/checkpoints.db`. FTS5 is a local lexical index derived from authorized product_search_records; it can be rebuilt without changing originals.

The complete SaaS organization/user/supplier/revision/receipt/policy relational model from the original brief is not deployed in this single-user local version.
