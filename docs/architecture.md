# Local architecture

The browser talks to same-origin Next.js `/api` rewrites. FastAPI validates uploads, stores original bytes and SHA256 identifiers, and queues persisted Run rows. One local worker owns an OS file lock and claims queued runs transactionally. It runs a LangGraph graph with durable SQLite checkpoints: extraction -> indexing -> matching -> financial/specification validation -> reports -> finish/review interrupt.

SQLite runs in WAL mode with foreign keys and a busy timeout. Original files, structured Docling output, checkpoint state, versioned reports and process logs live under `storage/`. Alembic owns schema creation; destructive downgrades are disabled. Application restart retains data. The worker recovers abandoned PROCESSING records after obtaining its exclusive local lock.

Docling is the primary parser. Canonical table rows prefer Docling cells. PyMuPDF also records original text blocks and native table rectangles and renders documents. Coordinates are stored in PDF points from the top-left; PDF.js transforms them to viewport pixels. No fixed or invented highlight is drawn.

Retrieval scopes candidate lines to the selected PO and organization. Exact identifiers precede FTS5 + RapidFuzz RRF ranking. Similarity is a retrieval feature, not approval. Unique trusted exact matches are validated separately for specifications and money. Ambiguous candidates may invoke structured Azure/OpenAI Responses; returned candidate/evidence IDs are checked against the supplied records. Missing evidence or failures lead to human review.

SQLite BEGIN IMMEDIATE serializes capacity decisions before prior allocations are read. Only fully valid ordinary runs commit billed quantities. Evaluation runs neither consume nor read the normal ledger. Recalculation releases its own allocation and rechecks all validations. Reviewer actions and correction provenance are preserved; original PDF bytes/raw readings remain unchanged.

Workflow event IDs and payloads are persisted before SSE transmission. Reconnects replay durable history. UI timers only poll backend state or reconnect streams; none simulate workflow progression.
