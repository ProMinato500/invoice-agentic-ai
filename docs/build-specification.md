# RECONCILEAI — COMPLETE PRODUCTION APPLICATION BUILD SPECIFICATION

> **Purpose:** Give this entire document to Codex to implement a real, production-oriented AI-powered purchase-order and invoice reconciliation application. This is a build specification, not a demo or mockup brief.

## ROLE AND EXECUTION MANDATE

Act as a principal AI architect, full-stack engineer, document-intelligence specialist, ML engineer, database architect, DevOps engineer, and QA engineer. **Design, implement, integrate, test, debug, and deliver ReconcileAI as a functioning application.** Do not stop at diagrams, boilerplate, or a static frontend. Process real PDF inputs, persist actual outputs, run real OpenAI calls when configured, and report verified results and limitations.

**Non-negotiable rules:** No mocked production workflows; no hardcoded reconciliation outcomes; no fake progress or fabricated tool calls; no nonfunctional buttons; no synthetic ground-truth leakage into inference; no LLM monetary arithmetic in place of deterministic calculation; no unsupported product-equivalence claims; no forced match when evidence is inadequate; no fabricated PDF evidence; no destructive commands against an existing database; and no claim that a feature works unless it has been tested. Test doubles are permitted only in clearly isolated unit tests.

## 1. PRODUCT OBJECTIVE

Provide a SaaS-style application in which users can upload a PO PDF and invoice PDF, optionally add supporting receipts, amendments, specifications, or multiple invoices, and start a reconciliation. Extract structured data from complex PDFs; match items despite inconsistent wording and layout; reason about product specifications; validate prices, quantities, taxes, currencies, and invoices already billed; detect duplicates and contradictions; investigate uncertainty using bounded AI tool calls; present source-linked findings; allow human correction; recompute affected results; generate PDF/CSV/JSON reports; retain history; and evaluate accuracy using synthetic ground-truth datasets.

Support previously unseen real-world documents, including scanned PDFs, complex layouts, and large tables. Never assume identical columns, sequence, product nomenclature, or page structure.

## 2. LOCKED TECHNOLOGY STACK

**Frontend:** Next.js App Router, React, TypeScript, Tailwind CSS, shadcn/ui, Lucide, TanStack Query, React Hook Form, Zod, PDF.js, Recharts, SSE; Zustand only when useful.

**Backend:** Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL, pgvector, Redis, Celery, structured logging and OpenTelemetry as practical.

**Document intelligence:** Docling primary parser; PyMuPDF for page inspection, rendering, crops, source-coordinate handling; a supported OCR engine/PaddleOCR; OpenAI vision for targeted recovery.

**AI:** official OpenAI SDK, Responses API, schema-constrained Structured Outputs, function calling; LangGraph with durable PostgreSQL checkpoints and human-review interrupts.

**Retrieval:** PostgreSQL native full-text search (not falsely called BM25), pgvector dense retrieval, RapidFuzz, reciprocal-rank fusion (RRF), OpenAI embeddings, dual-augmentation retrieval; optional cross-encoder and feedback-trained LightGBM LambdaMART after sufficient approved labels.

**Validation:** Python Decimal, Pint, OR-Tools, domain-specific constraint validators.

**Quality:** pytest, httpx, Playwright, synthetic PDF generator, ground-truth evaluation, Docker Compose, health and readiness checks.

**No FAISS, Chroma, Qdrant, Pinecone, or additional vector database.** PostgreSQL + pgvector is the locked design. Inspect an existing PostgreSQL instance safely; use a dedicated database or schema and Alembic migrations. Never drop or overwrite existing user data.

## 3. FINAL PROCESSING ARCHITECTURE

1. Upload PDF documents and validate file integrity, file type, size, authorization, and duplicates.
2. Store originals, hashes, metadata and durable job IDs.
3. Classify PO, invoice, receipt, amendment, and specification documents.
4. Extract Docling page layouts, tables, cells, reading order, text, coordinates, with OCR where necessary.
5. Reinspect uncertain source regions using crops and OpenAI vision, preserve competing readings and correction provenance.
6. Normalize headers, supplier identity, line items, units, technical attributes, taxes and monetary fields to canonical typed structures.
7. Persist document versions, evidence, lines, relationships, and embeddings to PostgreSQL.
8. Match exact trusted identifiers, then enrich PO descriptions and expand invoice queries as search aids.
9. Retrieve candidates using PostgreSQL lexical search + pgvector; fuse rankings via RRF and incorporate RapidFuzz/attribute features.
10. Use a feedback-aware candidate ranker; send only ambiguous bounded candidate sets to OpenAI for structured semantic comparison.
11. Evaluate **product correspondence separately from specification compliance** with deterministic domain constraints and targeted AI interpretation.
12. Resolve competing mappings, partial allocations, one-to-many/many-to-one relations, bundles and capacity constraints with OR-Tools where needed.
13. Validate financial rules in Python Decimal, cumulative invoice history and optional goods receipt.
14. Run bounded agentic exception investigation, or abstain and request human review.
15. Perform completeness/evidence audit and persist every decision and discrepancy.
16. Stream real stage/tool events to UI; offer human review and affected-stage recomputation.
17. Produce actual PDF, CSV and JSON reports and persistent run history.

Implement independently testable stages rather than one enormous prompt.

## 4. RESEARCH SOURCES AND HOW TO APPLY THEM

### 4.1 Online Similarity Learning with Feedback for Invoice Line Item Matching (2020)
Paper: https://arxiv.org/abs/2001.00288 ; PDF: https://arxiv.org/pdf/2001.00288

Invoice and PO item descriptions may use short abbreviations, variant word order and measurements, e.g. `TRES 739mL CD KER Smooth` vs `TRES 0.739L CD KER Smth`. Learn correspondence with classification/ranking feedback. Implement candidate-pair feature records (SKU/part number, brand/model, fuzzy, embedding, attributes, units, packaging, context), accepted/rejected/corrected labels, and a separately runnable LightGBM LambdaMART training/evaluation pipeline. Initially use evaluated deterministic ranking; do not claim a learned ranker is deployed until trained and validated.

### 4.2 Dual-Augmentation RAG for Product Reconciliation (2026)
Paper: https://doi.org/10.3390/jrfm19060402

Offline, generate searchable aliases of extracted PO descriptions; online, normalize and expand invoice terminology. Keep originals and verified attributes authoritative. Generated aliases are search aids only and must be labeled with provenance. Index normalized/augmented descriptions, use lexical+dense retrieval, fusion, ranking, targeted OpenAI verification and explicit NO_MATCH. Evaluate candidate Recall@K independently from final approval accuracy.

### 4.3 Structured PDF extraction
Docling: https://github.com/docling-project/docling ; Docs: https://docling-project.github.io/docling/

Preserve table structure, cell-to-header relationships, reading order, page numbers, bounding boxes, layout and provenance. Do not discard the structured representation by flattening everything into Markdown.

### 4.4 PostgreSQL hybrid retrieval
pgvector: https://github.com/pgvector/pgvector ; PostgreSQL text search: https://www.postgresql.org/docs/current/textsearch-intro.html ; hybrid reference: https://github.com/pavangupta352/pghybrid

Use GIN/tsvector lexical indexing, cosine vector matching and reciprocal rank fusion `RRF(d) = SUM[1/(k + rank_i(d))]` with an evaluated k. Native PostgreSQL full-text rank is not BM25. Benchmark HNSW approximate recall against exact vector search before selecting index parameters.

### 4.5 Agent and verification tools
LangGraph: https://github.com/langchain-ai/langgraph ; OpenAI Responses: https://developers.openai.com/api/reference ; Structured Outputs: https://developers.openai.com/api/docs/guides/structured-outputs ; Tool calls: https://developers.openai.com/api/docs/guides/function-calling ; OR-Tools: https://github.com/google/or-tools ; min-cost flow: https://developers.google.com/optimization/flow/mincostflow

Use allowlisted typed tools, checkpoints, interrupts, reproducible rule engines, and deterministic solver outputs. Avoid uncontrolled agent loops.

## 5. REPOSITORY

```text
reconcile-ai/
  frontend/{app,components,features,hooks,lib,types,tests}
  backend/app/{api,core,db,models,schemas,ingestion,extraction,normalization,retrieval,matching,specifications,validation,optimization,agents,tools,workflows,reports,workers}
  backend/{migrations,tests}
  synthetic_data/{generators,templates,catalogs,scenarios,manifests,generated,ground_truth}
  evaluation/{runner,metrics,results}
  docs/{architecture.md,research.md,synthetic-data.md,matching.md,agent-tools.md,api.md,data-model.md,edge-cases.md,testing.md,deployment.md,implementation-status.md}
  scripts/
  docker-compose.yml
  .env.example
  README.md
```

Use small cohesive typed modules, migrations and reusable service boundaries.

## 6. BUILD THE SYNTHETIC PDF FACTORY FIRST

Produce actual PDFs and isolated ground truth for each deterministic scenario:

```text
scenario_001/
  purchase_order.pdf
  invoice.pdf
  goods_receipt.pdf             # optional
  specification.pdf            # optional
  manifest.json
  ground_truth.json
  expected_discrepancies.json
  generation_metadata.json
```

All suppliers, addresses, tax IDs and payment details must be fictional. Use seeds to reproduce documents and visual corruption. Do not leak ground-truth IDs into invoice/PO content or any inference API. The scenario library can load only the PDFs into the same upload pipeline as user files; evaluation reads ground truth **after** a run completes.

**PO headers:** buyer/supplier identities and addresses, PO number, revision, dates, currency, payment/delivery terms, shipping and billing locations, category. **PO lines:** line no., supplier/manufacturer SKU, part number, description, model, brand, attributes, quantity, unit/pack, unit price, discount, tax, total, warranty/delivery condition. **Footer:** subtotal, freight, taxes, discounts, grand total and terms.

**Invoices:** invoice number, supplier/buyer, dates, PO reference, currency, line descriptions/codes, billed quantity, unit, price, discounts, taxes, freight, totals, terms. Vary labels and column arrangements.

**Product categories:** IT hardware, industrial equipment/motors, electrical, construction/materials, medical supplies, office, software subscriptions, maintenance/services. Define typed domain attributes: laptop CPU/RAM/storage/warranty, motors power/voltage/speed/IP rating, materials grade/dimensions, subscription license/time period, etc.

**At least 12 layout templates:** clean PO, clean invoice, minimal, dense technical, borderless, landscape, multi-column, multi-page continued tables, service invoice, industrial spec, scanned, mixed-layout. Vary fonts, headers, page breaks, columns and row heights.

**Corruption variants:** rasterization, controlled blur, skew, rotation, low contrast, watermark, stamping, compression, crop, noise and low resolution. Preserve true values and log corruption parameters.

**CLI:** `python -m synthetic_data generate --all --seed 42`; `--scenario specification_mismatch --seed 42`; `--scenario large_document --po-lines 5000 --invoice-lines 3000 --seed 42`.

Each manifest must declare expected correspondence pairs, true unmatched, spec violations, quantity/price/tax differences, expected policy status, and intended recovery path. Generate hundreds of combinations, with focused deterministic test scenarios and randomized stress cases. Keep numerical tests exactly reproducible.

## 7. REQUIRED EDGE-CASE SUITE

For each edge case implement: generator/input PDFs, expected state, discrepancy code, detection, recovery/review behavior and executable assertion.

**PDF/document structure:** native text, full scan, mixed scans, rotated/skewed, low quality OCR (8/3 and O/0), continued tables, repeated/missing headers, merged cells, wrapped/split rows, altered column order, multiple tables, landscape, watermark, handwriting, blank/missing pages, bad reading order, footer-as-row, corrupt/password PDF, multiple invoices bundled in PDF, image-based specifications and footnotes.

**Identity/semantic:** exact SKU, alias SKU, missing SKU, contradictory SKU, manufacturer code differences, abbreviation, reordered words, same product family but wrong model or suffix, brand differences, approved/unapproved substitutions, ambiguous matching, true no-match, extra invoice item, uninvoiced PO item, multiple plausible identical items, bundles, one-to-many/many-to-one, model OCR errors.

**Technical specifications:** 8 vs 16GB RAM, 256 vs 512GB, CPU i5 vs i7, 65W vs 100W, IP54 vs IP65, HP vs kW conversion, 20 vs 25mm, material grades, voltage/temperature range coverage, warranty duration, omitted attributes, conflicting values, footnotes, mandatory certification and standard version, minima/maxima/exact configuration, higher-but-unauthorized variant, conditional requirements, packaging UOM.

**Financial:** exact/over/under tolerance prices, ordered vs billed quantity, valid partial and cumulative overbilling, same invoice changed filename, repeated invoice number across vendors, incorrect extended amounts/totals, inclusive/exclusive or mixed tax, line/document discounts, freight, surcharge, credit/negative/zero-cost lines, currencies and authorized FX basis, decimal separators, rounding, multiple POs, cancelled/revised PO, missing receipt, services/milestones, due/payment terms.

**Operational/security:** OpenAI timeout/rate limit/refusal/invalid output/truncated output, malformed/hallucinated tool ID, no candidate, ties, worker restart, browser reconnect, duplicate job, cancellation, stale updates, file storage/db outage, absent API key, prompt injection inside a PDF, cross-tenant retrieval attempt, correction after matching, PO revisions, concurrency race and retry exhaustion. Use controlled fault injection in tests, never hidden simulated success in production.

## 8. PDF INGESTION, EXTRACTION AND EVIDENCE

Validate MIME and PDF signature, sizes, integrity, access, SHA256, duplicate status, PDF permissions/password, page count and classification. Store originals securely with durable IDs. Create actual queued tasks rather than performing large extraction within the HTTP request.

Docling must extract sections, text, reading order, tables, rows, cells, page coordinates, footers/headers. Preserve raw output and normalize into typed canonical records. Verify line count, table continuity, missing required fields, row/cell consistency, parse ambiguity, `quantity * unit_price` vs printed amount and total consistency. Use arithmetic as a warning signal only, not as proof of an OCR correction.

Recovery tool: locate source region, render/crop PyMuPDF, invoke OCR or OpenAI vision with a bounded typed response, validate independent evidence, version corrections, rerun affected checks, or escalate. Always preserve raw reading, alternative reading, source bbox, method, verification status and changed actor/time. Distinguish absent, empty, unreadable, N/A, inferred and verified.

Example source record:

```json
{"document_id":"DOC-1001","page":3,"bbox":[80,110,410,145],"raw_text":"16GB DDR5","normalized_value":"16 GB","extraction_method":"DOCLING","status":"EXTRACTED"}
```

Do not invent evidence coordinates. Convert extracted PDF coordinate systems correctly when highlighting with PDF.js.

## 9. POSTGRESQL DATA MODEL

Use Alembic-managed tables: organizations, users, suppliers, documents, document_versions, document_pages, document_elements, document_tables/cells, purchase_orders/revisions/lines, invoices/lines, goods_receipts/lines, product_attributes, evidence_references, product_search_records, embeddings, reconciliation_runs, workflow_events, agent_tool_calls, match_candidates, line_matches, quantity_allocations, validation_results, discrepancies, review_events, matching_feedback, policies, synthetic_scenarios, evaluation_runs.

Use UUIDs where appropriate, foreign keys, tenant scoping, indexes, created/updated timestamps, versioned review/extraction/policies, immutable provenance and transactional updates. Use Decimal-compatible database numeric types for money. Protect cumulative quantity allocations with transaction isolation/locking so concurrent jobs cannot double allocate.

Create extension `vector` only with appropriate authorization. Embed verified attributes and descriptions alongside separately labeled generated aliases. Store model, dimensions, embedding version and indexing date; implement re-embedding/migration. GIN full-text indexes and HNSW for sufficiently large datasets; evaluate exact vs approximate recall and filter by authorized PO/supplier before retrieval.

## 10. RESEARCH-INFORMED MATCHING ENGINE

For each invoice line:

1. Normalize identifiers, brand/model, description, UOM and typed technical attributes without erasing meaningfully distinct versions.
2. Match trusted exact PO-line links, manufacturer IDs, SKU/GTIN, known approved aliases.
3. For unresolved cases perform dual-sided query augmentation and PostgreSQL full-text + pgvector retrieval, include RapidFuzz, combine rankings with RRF.
4. Generate feature vectors: SKU/part match, brand/model, lexical/vector/fuzzy, attributes, unit/pack, PO reference and supplier scope.
5. Rank and adaptively expand top-K; offer a real NO_MATCH choice.
6. Send only relevant bounded candidate groups with source evidence to OpenAI Structured Outputs; validate returned IDs against actual records and cross-check evidence.
7. Produce separate correspondence and specification decisions: `SAME_PRODUCT`, `SAME_FAMILY`, `DIFFERENT`, `UNCERTAIN`, `NO_MATCH`; spec `PASS`, `FAIL`, `UNKNOWN`, `NOT_APPLICABLE`.
8. Globally resolve competing edges, split/bundle mappings and quantity capacities with OR-Tools as needed. Retain unallocated invoice quantity as a discrepancy; do not force an assignment.
9. Validate amounts, prior allocations and optional receipts using deterministic services.
10. Record reviewer feedback and feature snapshots. Include a separate LightGBM training/evaluation entry point, activated only when labels exist and model quality is verified.

Never call a high similarity score an approval. Record model version, evidence and actual tool calls.

## 11. SPECIFICATION AND FINANCIAL VALIDATORS

Implement explicit spec constraints: EQ, NEQ, GT/GTE, LT/LTE, IN_RANGE, SUPERSET_RANGE, MEMBER_OF, MANDATORY_FEATURE, CERTIFIED_TO, CONDITIONAL and APPROVED_EQUIVALENT. Use Pint when dimensions and conversion basis agree. Special handling is mandatory for IP codes, material grades, certifications, part revisions, product variants, warranty and operating envelopes. If equivalence lacks evidence, return UNKNOWN/REVIEW_REQUIRED.

Financial validation: supplier and PO/revision, invoice identity, currency/authorized FX basis, unit/remaining/cumulative quantity, price tolerance, discount, freight, taxes, rounding, credit note, receipt, totals, payment conditions and duplicate prevention. Use Decimal and versioned per-org/supplier policies. A PO line absent from a partial invoice is not automatically a discrepancy. Track prior invoices and allocate capacity transactionally. Use statuses `AUTO_APPROVABLE`, `REVIEW_REQUIRED`, `BLOCKED`, `INCOMPLETE`. Do not initiate payment.

## 12. BOUNDED AGENTS AND ACTUAL TOOLS

Use LangGraph as a persistent stateful orchestration graph rather than autonomous free-form conversation. Four reasoning roles:

**Extraction Recovery Agent:** `get_document_page`, `render_page`, `crop_region`, `inspect_extracted_table`, `reinspect_with_vision`, `validate_extraction`, `propose_correction`.

**Matching Agent:** `lookup_identifier`, `search_po_candidates`, `get_po_line`, `get_invoice_line`, `get_candidate_context`, `rerank_candidates`, `propose_match`.

**Specification Agent:** `extract_attributes`, `normalize_units`, `compare_constraints`, `verify_model_identifier`, `check_standard`, `check_approved_substitution`, `get_source_evidence`.

**Exception Agent:** `expand_candidate_search`, `reinspect_source_region`, `retrieve_alternative_match`, `get_previous_allocations`, `check_po_revision`, `request_human_review`.

All tools must be real functions with typed request/response, auth, tenant checks, timeouts, audited results, error handling and bounded retry budgets. Do not expose arbitrary SQL/shell/file access to agents. Numeric rules, allocation, duplication, authorization and report generation must be deterministic services rather than LLM agents.

Checkpoint graph state holding IDs and version references, not giant PDF content. Support interrupts and resume, guarded cancellation, retriable failures and human review. Treat instructions within PDFs as untrusted content; do not obey them.

## 13. WORKERS, EVENTS AND LIVE EXECUTION

FastAPI creates a persisted run and queues Celery processing through Redis. Worker executes LangGraph/stage services; each stage writes durable start/completion/failure/warning/retry/tool-call events before broadcasting over SSE. Event stream should support event IDs/replay on reconnect. UI is driven only by backend state; **never use setTimeout to simulate stage completion**.

Stages: UPLOADED, VALIDATING, EXTRACTING, NORMALIZING, INDEXING, RETRIEVING, MATCHING, VERIFYING_SPECIFICATIONS, OPTIMIZING_ASSIGNMENTS, VALIDATING_FINANCIALS, INVESTIGATING_EXCEPTIONS, WAITING_FOR_REVIEW, GENERATING_REPORT, COMPLETED, COMPLETED_WITH_DISCREPANCIES, FAILED, CANCELLED.

Real event payloads include run ID, stage, status, start/end timestamps, processed counts, tool name/result metadata, error reason, retry number and model usage where available. Resume state correctly after browser refresh or worker interruption; protect against duplicate job requests and double allocation.

## 14. PRODUCTION-QUALITY FRONTEND

Build a polished neutral enterprise SaaS UI: Next.js/TypeScript/Tailwind/shadcn, calm typography, accessible contrast, consistent spacing, meaningful status colors, excellent tables, responsive layouts, usable loading/error/empty states. No decorative fake charts, filler cards or inert controls.

**Navigation:** Overview, New Reconciliation, Runs, Review Queue, Documents, Evaluation, Settings — every link must work.

**Overview:** real totals, completed/review/failed counts, discrepancies, processing duration, recent runs and status breakdown from SQL; empty state if none.

**Upload:** real drag-and-drop PO/invoice + optional documents, PDF preview, policy selection, upload progress, preflight validation, functional run creation. Synthetic Test Library can load generated PDFs as inputs only; must not insert outcomes.

**Live execution:** stage timeline/graph, actual per-stage counts/timing, retries, agent tools, warnings, failures and review status. Expand stage to see actual backend event and concise decision rationale; never expose fabricated private reasoning.

**Results:** large paginated/sortable/filterable grid with invoice description, mapped PO line, identity status, spec status, quantity status, price status, discrepancy, evidence and actions; searchable with server pagination for thousands of rows.

**Evidence viewer:** real side-by-side PDF.js PO and invoice renderers, zoom/page controls, source bbox highlights, jump to selected evidence, raw and normalized values. Do not approximate with fake highlights.

**Human review:** accept/reject mapping, select alternate PO item, mark unmatched, correct extraction, approve documented substitution, annotate and recompute dependent validations; every action creates audited DB changes and feedback records.

**History:** persisted search/sort/filter, click previous runs, open reports and stage traces after restart.

**Evaluation:** only actual benchmark extraction accuracy, candidate Recall@K, line F1, spec/financial detection, false approvals, OCR recovery, token usage, cost and runtime. Label synthetic benchmark separately and show an empty state if unexecuted.

## 15. API CONTRACT

```text
POST /api/documents/upload
GET  /api/documents
GET  /api/documents/{id}
GET  /api/documents/{id}/pages
GET  /api/documents/{id}/elements
POST /api/reconciliations
GET  /api/reconciliations
GET  /api/reconciliations/{id}
GET  /api/reconciliations/{id}/events
GET  /api/reconciliations/{id}/stream
GET  /api/reconciliations/{id}/matches
GET  /api/reconciliations/{id}/discrepancies
GET  /api/reconciliations/{id}/report
POST /api/reconciliations/{id}/retry
POST /api/reconciliations/{id}/cancel
POST /api/reconciliations/{id}/recalculate
POST /api/matches/{id}/review
POST /api/elements/{id}/correct
POST /api/discrepancies/{id}/investigate
GET  /api/dashboard/summary
GET  /api/dashboard/activity
GET  /api/synthetic/scenarios
POST /api/synthetic/scenarios/{id}/load
POST /api/evaluations
GET  /api/evaluations
GET  /api/evaluations/{id}
GET  /health
GET  /ready
```

Typed Pydantic request/response, OpenAPI docs, appropriate HTTP errors, pagination, authorization and tenant scoping. Do not leave endpoints as placeholders.

## 16. REPORTING

Every finished run must provide persisted JSON, discrepancy CSV and a downloadable PDF report containing document identities, run ID, outcome, counts, matched/unmatched lines, spec conflicts, price/quantity/tax issues, duplicates, uncertainty, source evidence references, policy versions, reviewer actions and concise grounded explanations. Never fabricate report data or downloads.

## 17. SECURITY AND RELIABILITY

Implement real file signature validation, size limits, PDF processing isolation where possible, secure storage, auth and tenant permissions, server-side secrets, prompt-injection isolation, allowlisted tools, logs, audit trail, idempotency, retries/backoff, database transactions and quantity locks, job timeouts/cancellation, error visibility, retention configuration and restart recovery. Do not access another tenant's candidate records or permit document-borne instructions to override system logic.

## 18. EVALUATION AND TESTING

**Unit tests:** currency/numeric parsing, SKU normalization, synonym/unit conversions, constraints, price/quantity/tax rules, allocations, duplicates, retrieval fusion and no-match.

**Extraction integration:** run actual synthetic PDFs through Docling and verify header/row/cell values, counts, table continuity, OCR fallback and source bboxes.

**Matching:** exact and semantic Recall@1/@3/@5, precision/recall/F1, hard negative model variants, no-match recall, spec mismatch detection, false approvals, cumulative allocation.

**Agents:** actual tool dispatch/schema validation, hallucinated ID rejection, failure/retry caps, missing evidence, review escalation, prompt injection, OpenAI refusal/timeout/rate-limit handling. Unit tests may mock network dependencies; separately run live OpenAI integration tests if configured and report which tests were real.

**Browser end-to-end Playwright:** upload actual PDFs, start process, observe backend SSE, view results, inspect source highlights, download report, refresh/reopen, correct a match and verify persistent/recomputed state.

**Load benchmarks:** 10, 100, 500, 1000 and 5000 PO lines; record actual extraction/retrieval/LLM/solver times, total duration, peak memory, token/cost, candidate recall and correctness. Do not invent benchmarks.

Quality gates: backend starts, frontend builds, PostgreSQL/pgvector connection works, Alembic migrates, PDFs generate, real end-to-end pipeline succeeds for happy path, mismatched spec, valid partial, extra item, scanned/OCR, persistent SSE history, reviewer correction and real reports. Clearly disclose incomplete or blocked features; do not label production-ready merely because app starts.

## 19. CONFIGURATION AND DEPLOYMENT

Provide Docker Compose services for Next.js, FastAPI, worker, Redis, storage, and optionally a local pgvector-enabled PostgreSQL only when no external instance is configured. Existing PostgreSQL should be selectable by `DATABASE_URL`; never modify unrelated databases. Create `.env.example`:

```env
DATABASE_URL=
REDIS_URL=
OPENAI_API_KEY=
OPENAI_MODEL=
OPENAI_VISION_MODEL=
OPENAI_EMBEDDING_MODEL=
OPENAI_EMBEDDING_DIMENSIONS=
STORAGE_BACKEND=local
STORAGE_PATH=./storage
MAX_UPLOAD_MB=50
MAX_AGENT_TOOL_CALLS=12
ENABLE_VISION_FALLBACK=true
ENABLE_DUAL_AUGMENTATION=true
ENABLE_HUMAN_REVIEW=true
DEFAULT_PRICE_TOLERANCE_PERCENT=2
DEFAULT_QUANTITY_OVERAGE_PERCENT=0
```

Verify current OpenAI model/API capabilities and supported dimension/index combinations from official docs. Do not hardcode unavailable models. If key is missing, show explicit configuration-required state; never fake successful inference. Add startup readiness validation and exact commands to launch locally.

## 20. IMPLEMENTATION ORDER AND STATUS

Maintain `docs/implementation-status.md` with done/in-progress/blockers, actual test commands/results, incomplete features and next steps. Implement in coherent vertical slices:

1. Foundation: Next.js/FastAPI/PostgreSQL/pgvector/Redis/Celery/Docker/migrations.
2. Deterministic synthetic PDF factory, manifests and ground truth.
3. Real upload, Docling extraction, canonical fields and source evidence.
4. Basic exact/hybrid retrieval with PostgreSQL and pgvector.
5. OpenAI candidate verification and technical constraints.
6. Deterministic financial validation and OR-Tools allocation.
7. LangGraph tools/checkpoints/recovery/human review.
8. Polished frontend upload/live execution/results/evidence/review/history/evaluation.
9. Real reporting, integration/E2E tests, load evaluation, security and documentation.

Prioritize a first working vertical slice `PDF upload -> extraction -> matching -> validation -> persisted results` before widening scope. Do not add excessive agents at the expense of correctness.

## 21. FINAL DEFINITION OF DONE

A new user must be able to start the application, upload unseen PO/invoice PDFs, have them truly parsed by Docling, store canonical line items, find candidates via PostgreSQL+pgvector, invoke real OpenAI semantic verification where necessary, validate specifications and financials, detect partial/missing/extra/duplicate items, see real stage execution and actual tool calls, inspect original PDF source evidence, correct a match and recompute results, download genuine PDF/CSV/JSON reports, refresh to reopen history, and run synthetic evaluation with genuine accuracy/runtime results.

Document actual verified tests, remaining limitations, credential-dependent checks, database/pgvector/OpenAI/LangGraph health and exact startup commands. **Never claim a feature is complete without verification.**

## FINAL EXECUTION INSTRUCTION

**Inspect the current workspace, make the repository changes and build ReconcileAI now.** Do not stop after outlining a plan. Write modular typed production-oriented code, persist data safely, run actual processes and tests, fix failures, and accurately track progress. The finished output must be a genuine working AI-powered PO/invoice reconciliation application—not a simulated UI, static artifact, or loose scripts.
